"""
Modular Traffic Camera Source Adapter Architecture for SafePath AI.

Pipeline Architecture:
Camera Source
  -> Camera Adapter (Protocol / Base Interface)
  -> Data Validation (JPEG/PNG magic bytes, dimensions, corruption check)
  -> Image Acquisition & SHA-256 Freeze Detection
  -> Timestamp Validation (LIVE / RECENT / STALE / SIMULATED / UNAVAILABLE)
  -> Computer Vision Pipeline (VGG16-SSD + Flood Segmenter)
  -> Traffic Density Analysis (Multi-factor PCU + ROI Occupancy)
  -> Database / Redis Cache
  -> Frontend API

Zero-Mock Compliance:
- Never fabricates camera URLs or synthetic traffic feeds.
- Strictly separates LIVE, RECENT, STALE, SIMULATED, and UNAVAILABLE states.
- Detects frozen camera feeds via SHA-256 frame hash tracking.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import cv2
import httpx
import numpy as np

from backend.app.core.config import settings
from backend.app.schemas.contracts import (
    CameraEvidence,
    DataSourceStatus,
    TrafficDensityLevel,
)

logger = logging.getLogger(__name__)

# Freshness thresholds (seconds)
DEFAULT_LIVE_TTL_SECONDS: int = 300       # <= 5 minutes: LIVE
DEFAULT_RECENT_TTL_SECONDS: int = 1800    # <= 30 minutes: RECENT; > 30 minutes: STALE


@dataclass
class CameraFramePayload:
    """Validated camera frame acquisition result from a CameraSourceAdapter."""

    camera_id: str
    source: str
    location: Dict[str, Any]
    data_status: DataSourceStatus
    captured_at: Optional[datetime] = None
    retrieved_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    image_path: Optional[str] = None
    frame_sha256: Optional[str] = None
    is_frozen_frame: bool = False
    is_simulated: bool = False
    validation_passed: bool = False
    status_reason: str = "UNINITIALIZED"
    width: int = 0
    height: int = 0
    vehicle_counts: Dict[str, int] = field(default_factory=dict)
    total_vehicles: int = 0
    traffic_density_score: Optional[float] = None
    traffic_density_level: TrafficDensityLevel = TrafficDensityLevel.UNKNOWN
    confidence: float = 0.0

    def to_audit_record(self) -> Dict[str, Any]:
        """Returns standardized camera frame record for API / telemetry."""
        return {
            "camera_id": self.camera_id,
            "location": self.location,
            "source": self.source,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "retrieved_at": self.retrieved_at.isoformat() if self.retrieved_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "data_status": (
                self.data_status.value
                if hasattr(self.data_status, "value")
                else str(self.data_status)
            ),
            "status_reason": self.status_reason,
            "validation_passed": self.validation_passed,
            "frame_sha256": self.frame_sha256,
            "is_frozen_frame": self.is_frozen_frame,
            "vehicle_counts": dict(self.vehicle_counts),
            "total_vehicles": int(self.total_vehicles),
            "traffic_density": {
                "score": self.traffic_density_score,
                "level": (
                    self.traffic_density_level.value
                    if hasattr(self.traffic_density_level, "value")
                    else str(self.traffic_density_level)
                ),
            },
            "confidence": round(float(self.confidence), 3),
        }


def classify_camera_data_status(
    *,
    has_valid_image: bool,
    is_simulated: bool = False,
    captured_at: Optional[datetime] = None,
    retrieved_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    is_frozen_frame: bool = False,
    live_ttl_seconds: Optional[int] = None,
    recent_ttl_seconds: int = DEFAULT_RECENT_TTL_SECONDS,
) -> Tuple[DataSourceStatus, str]:
    """
    Strictly classifies camera data status into:
    - LIVE: Real verified camera snapshot within active live window (`<= live_ttl_seconds`).
    - RECENT: Real camera snapshot retrieved/captured within recent window (`<= recent_ttl_seconds`)
              or recently retrieved when watermark capture timestamp is absent.
    - STALE: Real camera snapshot older than `recent_ttl_seconds` or frozen frame across polling cycles.
    - SIMULATED: Synthetic / test / simulated frame (never reported as LIVE or RECENT).
    - UNAVAILABLE: Missing, corrupt, or unreachable camera image.
    """
    if not has_valid_image:
        return DataSourceStatus.UNAVAILABLE, "NO_VALID_IMAGE"

    if is_simulated:
        return DataSourceStatus.SIMULATED, "SIMULATED_SOURCE_EXPLICIT"

    if is_frozen_frame:
        return DataSourceStatus.STALE, "FROZEN_DUPLICATE_FRAME_DETECTED"

    if now is None:
        now = datetime.now(timezone.utc)

    effective_live_ttl = int(
        live_ttl_seconds
        if live_ttl_seconds is not None
        else getattr(settings, "CAMERA_IMAGE_TTL_SECONDS", DEFAULT_LIVE_TTL_SECONDS)
    )
    effective_recent_ttl = max(effective_live_ttl, int(recent_ttl_seconds))

    cap_age: Optional[float] = None
    if isinstance(captured_at, datetime):
        cap_dt = captured_at if captured_at.tzinfo else captured_at.replace(tzinfo=timezone.utc)
        cap_age = max(0.0, (now - cap_dt).total_seconds())

    ret_age: Optional[float] = None
    if isinstance(retrieved_at, datetime):
        ret_dt = retrieved_at if retrieved_at.tzinfo else retrieved_at.replace(tzinfo=timezone.utc)
        ret_age = max(0.0, (now - ret_dt).total_seconds())

    # 1. Both capture and retrieval timestamps exist and are within live TTL -> LIVE
    if cap_age is not None and ret_age is not None:
        if cap_age <= effective_live_ttl and ret_age <= effective_live_ttl:
            return DataSourceStatus.LIVE, "VERIFIED_LIVE_CAPTURE_AND_RETRIEVAL"
        if cap_age <= effective_recent_ttl and ret_age <= effective_recent_ttl:
            return DataSourceStatus.RECENT, "RECENT_VERIFIED_CAPTURE"
        return DataSourceStatus.STALE, f"CAPTURE_OR_RETRIEVAL_EXPIRED_{int(max(cap_age, ret_age))}S"

    # 2. Only capture timestamp available
    if cap_age is not None:
        if cap_age <= effective_live_ttl:
            return DataSourceStatus.LIVE, "VERIFIED_LIVE_CAPTURE"
        if cap_age <= effective_recent_ttl:
            return DataSourceStatus.RECENT, "RECENT_CAPTURE_TIMESTAMP"
        return DataSourceStatus.STALE, f"CAPTURE_TIMESTAMP_STALE_{int(cap_age)}S"

    # 3. Only retrieval timestamp available (no verified watermark capture time)
    # Zero-Mock: Without a verified capture timestamp, we classify fresh retrieval as RECENT (or LIVE if configured),
    # never over-claiming unverified old cache as LIVE.
    if ret_age is not None:
        if ret_age <= effective_live_ttl:
            return DataSourceStatus.RECENT, "RECENTLY_RETRIEVED_UNVERIFIED_CAPTURE_TIME"
        if ret_age <= effective_recent_ttl:
            return DataSourceStatus.RECENT, f"RECENT_RETRIEVAL_{int(ret_age)}S"
        return DataSourceStatus.STALE, f"RETRIEVAL_TIMESTAMP_STALE_{int(ret_age)}S"

    return DataSourceStatus.STALE, "MISSING_CAPTURE_AND_RETRIEVAL_TIMESTAMPS"


def validate_image_bytes_and_file(image_path: str) -> Tuple[bool, str, int, int, Optional[str]]:
    """
    Validates that a local image file exists, has non-trivial size, valid image headers,
    decodes cleanly with OpenCV, and computes its SHA-256 digest.
    Returns: (is_valid, reason, width, height, sha256_hex)
    """
    if not image_path or not os.path.exists(image_path):
        return False, "IMAGE_FILE_NOT_FOUND", 0, 0, None

    try:
        file_size = os.path.getsize(image_path)
        if file_size < 512:
            return False, f"IMAGE_FILE_TOO_SMALL_{file_size}B", 0, 0, None

        with open(image_path, "rb") as f:
            raw_bytes = f.read()

        sha256_hex = hashlib.sha256(raw_bytes).hexdigest()

        arr = np.frombuffer(raw_bytes, dtype=np.uint8)
        decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if decoded is None or decoded.size == 0:
            return False, "OPENCV_DECODE_FAILED", 0, 0, sha256_hex

        h, w = decoded.shape[:2]
        if h < 64 or w < 64:
            return False, f"IMAGE_DIMENSIONS_TOO_SMALL_{w}x{h}", w, h, sha256_hex

        return True, "VALID_IMAGE_FRAME", w, h, sha256_hex
    except Exception as exc:
        return False, f"VALIDATION_ERROR:{type(exc).__name__}", 0, 0, None


class CameraSourceAdapter(ABC):
    """
    Abstract Adapter interface for any traffic camera source
    (e.g., HCMC VDMS Snapshot API, GTHT Public Portal, RTSP/HLS Gateway, Local Cache).
    """

    source_name: str = "ABSTRACT_CAMERA_SOURCE"

    @abstractmethod
    async def acquire_frame(
        self,
        cam_meta: Dict[str, Any],
        storage_dir: str = "storage/cams",
    ) -> CameraFramePayload:
        """Acquires and validates a single frame for the given camera metadata."""
        raise NotImplementedError


class HcmcVdmsCameraAdapter(CameraSourceAdapter):
    """
    Adapter for HCMC Public Traffic Camera Snapshots (VDMS / GTHT compatible endpoints)
    with local storage fallback and SHA-256 frozen-stream detection.

    Strictly honors Zero-Mock constraints:
    - Does not fabricate camera URLs if `snapshot_url` is not configured.
    - Does not bypass authentication.
    - Tracks SHA-256 hashes across consecutive polls to detect frozen upstream cameras.
    """

    source_name: str = "HCMC_VDMS_PUBLIC_ADAPTER"

    def __init__(self, timeout_seconds: float = 8.0):
        self.timeout_seconds = timeout_seconds
        # Map of camera_id -> (last_sha256, first_seen_timestamp, repeat_count)
        self._frame_hash_history: Dict[str, Tuple[str, datetime, int]] = {}

    def _check_frozen_frame(self, camera_id: str, sha256_hex: Optional[str], now: datetime) -> bool:
        """Detects if an upstream camera has been returning the exact same byte-identical image."""
        if not sha256_hex:
            return False
        prev = self._frame_hash_history.get(camera_id)
        if prev is None:
            self._frame_hash_history[camera_id] = (sha256_hex, now, 1)
            return False

        prev_hash, first_seen, count = prev
        if prev_hash == sha256_hex:
            new_count = count + 1
            self._frame_hash_history[camera_id] = (sha256_hex, first_seen, new_count)
            elapsed = (now - first_seen).total_seconds()
            # If identical image returned >= 3 times and over live TTL, mark frozen
            if new_count >= 3 and elapsed > getattr(settings, "CAMERA_IMAGE_TTL_SECONDS", DEFAULT_LIVE_TTL_SECONDS):
                return True
            return False

        self._frame_hash_history[camera_id] = (sha256_hex, now, 1)
        return False

    async def acquire_frame(
        self,
        cam_meta: Dict[str, Any],
        storage_dir: str = "storage/cams",
    ) -> CameraFramePayload:
        now = datetime.now(timezone.utc)
        cam_id = str(cam_meta.get("cam_id") or "")
        location = {
            "lat": float(cam_meta.get("lat") or 0.0),
            "lng": float(cam_meta.get("lng") or 0.0),
            "name": cam_meta.get("name") or f"Camera {cam_id}",
            "district": cam_meta.get("district"),
            "osm_way_id": cam_meta.get("observed_osm_way_id") or cam_meta.get("nearest_osm_way_id"),
        }
        is_simulated = bool(cam_meta.get("is_simulated", False))
        snapshot_url = cam_meta.get("snapshot_url") or cam_meta.get("live_snapshot_url")
        image_path = os.path.join(storage_dir, f"{cam_id}.jpg")

        captured_at = cam_meta.get("captured_at")
        if isinstance(captured_at, str):
            try:
                captured_at = datetime.fromisoformat(captured_at)
            except ValueError:
                captured_at = None

        retrieved_at: Optional[datetime] = None
        source_tag = self.source_name

        # 1. If an explicit, real public snapshot URL is configured, attempt live HTTP acquisition
        if snapshot_url and isinstance(snapshot_url, str) and snapshot_url.startswith(("http://", "https://")):
            try:
                os.makedirs(storage_dir, exist_ok=True)
                async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
                    resp = await client.get(snapshot_url)
                    content_type = resp.headers.get("content-type", "").lower()
                    if resp.status_code == 200 and len(resp.content) >= 512 and (
                        "image" in content_type or resp.content[:2] == b"\xff\xd8" or resp.content[:4] == b"\x89PNG"
                    ):
                        with open(image_path, "wb") as f:
                            f.write(resp.content)
                        retrieved_at = now
                        source_tag = "HCMC_LIVE_HTTP_SNAPSHOT"
            except Exception as exc:
                logger.debug("Live snapshot fetch failed for camera %s: %s", cam_id, exc)

        # 2. Check local cached snapshot on disk
        if os.path.exists(image_path):
            if retrieved_at is None:
                mtime = os.path.getmtime(image_path)
                retrieved_at = datetime.fromtimestamp(mtime, timezone.utc) if mtime > 0 else None
                if source_tag == self.source_name:
                    source_tag = "HCMC_CACHED_CAMERA_SNAPSHOT"

            valid, reason, w, h, sha256_hex = validate_image_bytes_and_file(image_path)
            if not valid:
                return CameraFramePayload(
                    camera_id=cam_id,
                    source=source_tag,
                    location=location,
                    data_status=DataSourceStatus.UNAVAILABLE,
                    captured_at=captured_at,
                    retrieved_at=retrieved_at,
                    processed_at=now,
                    image_path=image_path,
                    frame_sha256=sha256_hex,
                    is_simulated=is_simulated,
                    validation_passed=False,
                    status_reason=reason,
                    width=w,
                    height=h,
                )

            is_frozen = self._check_frozen_frame(cam_id, sha256_hex, now)
            status, status_reason = classify_camera_data_status(
                has_valid_image=True,
                is_simulated=is_simulated,
                captured_at=captured_at,
                retrieved_at=retrieved_at,
                now=now,
                is_frozen_frame=is_frozen,
            )
            return CameraFramePayload(
                camera_id=cam_id,
                source="SIMULATED_TEST_CAMERA" if is_simulated else source_tag,
                location=location,
                data_status=status,
                captured_at=captured_at,
                retrieved_at=retrieved_at,
                processed_at=now,
                image_path=image_path,
                frame_sha256=sha256_hex,
                is_frozen_frame=is_frozen,
                is_simulated=is_simulated,
                validation_passed=True,
                status_reason=status_reason,
                width=w,
                height=h,
            )

        # 3. No image available
        return CameraFramePayload(
            camera_id=cam_id,
            source=source_tag,
            location=location,
            data_status=DataSourceStatus.UNAVAILABLE,
            captured_at=captured_at,
            retrieved_at=None,
            processed_at=now,
            image_path=None,
            frame_sha256=None,
            is_simulated=is_simulated,
            validation_passed=False,
            status_reason="CAMERA_SNAPSHOT_UNAVAILABLE",
        )


class CameraAdapterRegistry:
    """
    Registry managing camera source adapters and orchestrating end-to-end
    acquisition + validation + CV pipeline enrichment.
    """

    def __init__(self, default_adapter: Optional[CameraSourceAdapter] = None):
        self._adapters: Dict[str, CameraSourceAdapter] = {}
        self._default_adapter = default_adapter or HcmcVdmsCameraAdapter()
        self.register_adapter("default", self._default_adapter)
        self.register_adapter("hcmc_vdms", self._default_adapter)

    def register_adapter(self, key: str, adapter: CameraSourceAdapter) -> None:
        self._adapters[key.lower()] = adapter

    def get_adapter(self, key: str = "default") -> CameraSourceAdapter:
        return self._adapters.get(key.lower(), self._default_adapter)

    async def acquire_and_enrich_evidence(
        self,
        cam_meta: Dict[str, Any],
        vision_pipeline: Any,
        storage_dir: str = "storage/cams",
        adapter_key: str = "default",
    ) -> Tuple[CameraFramePayload, Optional[CameraEvidence]]:
        """
        Executes full Camera Adapter pipeline:
        Camera Source -> Adapter -> Data Validation -> Timestamp Validation -> CV Pipeline -> Enriched Evidence
        """
        adapter = self.get_adapter(adapter_key)
        frame_payload = await adapter.acquire_frame(cam_meta, storage_dir=storage_dir)

        if not frame_payload.validation_passed or not frame_payload.image_path:
            return frame_payload, None

        evidence: CameraEvidence = vision_pipeline.analyze_camera_image(
            image_path=frame_payload.image_path,
            cam_meta=cam_meta,
            storage_dir=storage_dir,
        )
        # Synchronize adapter data_status if simulated or RECENT
        evidence.source_status = frame_payload.data_status

        if evidence.vehicle_counts:
            frame_payload.vehicle_counts = dict(evidence.vehicle_counts)
        if evidence.total_vehicles is not None:
            frame_payload.total_vehicles = int(evidence.total_vehicles)
        elif evidence.vehicle_count is not None:
            frame_payload.total_vehicles = int(evidence.vehicle_count)

        frame_payload.traffic_density_score = evidence.traffic_density_score
        frame_payload.traffic_density_level = evidence.traffic_density_level
        frame_payload.confidence = float(evidence.analysis_confidence or 0.0)
        frame_payload.processed_at = evidence.analyzed_at

        return frame_payload, evidence


default_camera_registry = CameraAdapterRegistry()

