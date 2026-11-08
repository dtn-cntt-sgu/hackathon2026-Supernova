"""Bounded explicit camera inference; source fetching never calls a model."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.schemas.contracts import CameraEvidence, EvidenceEligibility, RiskLevel

logger = logging.getLogger(__name__)
ROUTING_USES = {"ROUTING_EVIDENCE_PERMITTED"}


def fresh(value: Any) -> bool:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return False
    return (isinstance(value, datetime) and value.tzinfo is not None
            and 0 <= (datetime.now(timezone.utc) - value).total_seconds()
            <= settings.ROUTE_AI_MAX_FRAME_AGE_SECONDS)


def belongs_to_step(camera: CameraEvidence, edges: list[dict]) -> bool:
    return bool(
        getattr(camera, "permitted_use", None) in ROUTING_USES
        and camera.coordinate_source_url and camera.view_verification_source_url
        and camera.line_of_sight_verified and camera.observed_osm_way_id is not None
        and camera.observed_edge_index is not None
        and any(edge.get("route_match_verified") is True
                and edge["osm_way_id"] == camera.observed_osm_way_id
                and edge.get("edge_index") == camera.observed_edge_index for edge in edges)
    )


def model_version() -> str:
    """Manifest includes verified weight hashes and both model versions."""
    manifest = Path("data/models/model_manifest.json")
    content = manifest.read_bytes() if manifest.is_file() else b"MODEL_UNAVAILABLE"
    return hashlib.sha256(content + settings.VEHICLE_MODEL_PATH.encode() + b"original-only-v2").hexdigest()


class RouteCameraAI:
    def __init__(self) -> None:
        self._pipeline = None
        self._pipeline_version = None
        self._pipeline_lock = threading.Lock()
        self._executor = None
        self._slots = None
        self._inflight: dict[str, asyncio.Task] = {}
        self._cache: OrderedDict[str, tuple[float, CameraEvidence]] = OrderedDict()
        self._closed = False

    def reopen(self) -> None:
        """Lifespan startup may follow a prior orderly shutdown in the same process."""
        self._closed = False

    async def close(self) -> None:
        self._closed = True
        if self._inflight:
            await asyncio.gather(*list(self._inflight.values()), return_exceptions=True)
        if self._executor is not None:
            await asyncio.to_thread(self._executor.shutdown, wait=True)
            self._executor = None

    def _analyze(self, path: str, metadata: dict, version: str) -> CameraEvidence:
        # Read/validate before any model construction; immutable paths bind the result.
        from backend.app.services.image_validator import validate_camera_image_bytes
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != metadata["content_sha256"]:
            raise ValueError("SNAPSHOT_HASH_MISMATCH")
        if not validate_camera_image_bytes(raw).is_valid:
            raise ValueError("INVALID_SNAPSHOT")
        with self._pipeline_lock:
            if self._pipeline is None or self._pipeline_version != version:
                from backend.app.services.vision import CameraVisionPipeline
                self._pipeline = CameraVisionPipeline(vehicle_model_path=settings.VEHICLE_MODEL_PATH,
                                                      fallback_to_heuristic=False)
                self._pipeline_version = version
            pipeline = self._pipeline
        storage_dir = str(Path(path).parent) if metadata.get("permitted_use") == "VIEW_ONLY" else "storage/cams"
        result = pipeline.analyze_camera_image(path, metadata, storage_dir=storage_dir)
        if result.inference_input_sha256 != metadata["content_sha256"]:
            raise ValueError("INFERENCE_HASH_MISMATCH")
        return result.model_copy(update={"frame_sha256": metadata["content_sha256"],
                                         "route_ai_model_version": version,
                                         "retrieved_at": metadata["retrieved_at"],
                                         "fetched_at": metadata["retrieved_at"]})

    def _cached(self, key: str, metadata: dict, view_only: bool = False) -> CameraEvidence | None:
        item = self._cache.get(key)
        if (item and item[0] > time.monotonic() and item[1].snapshot_id == metadata["snapshot_id"]
                and item[1].inference_input_sha256 == metadata["content_sha256"]
                and (view_only or fresh(item[1].captured_at)) and fresh(item[1].retrieved_at) and fresh(item[1].updated_at)):
            self._cache.move_to_end(key)
            return item[1]
        self._cache.pop(key, None)
        return None

    async def _run(self, key: str, path: str, metadata: dict, version: str, redis: Any, view_only: bool = False) -> CameraEvidence | None:
        token = None
        deadline = time.monotonic() + settings.ROUTE_AI_TIMEOUT_SECONDS
        # The caller's request-scoped client may close while a timed-out model finishes.
        if redis is not None:
            from backend.app.db.session import get_redis_client
            redis = get_redis_client()
        try:
            if redis is not None:
                try:
                    cached = await redis.get(key)
                    if cached:
                        result = CameraEvidence.model_validate_json(cached)
                        if (result.inference_input_sha256 == metadata["content_sha256"]
                                and result.snapshot_id == metadata["snapshot_id"]
                                and result.route_ai_model_version == version
                                and (view_only or fresh(result.captured_at)) and fresh(result.retrieved_at)
                                and fresh(result.updated_at)):
                            return result
                    # Across processes, a waiting route reuses the owner's completed result.
                    import uuid
                    token = uuid.uuid4().hex
                    if not await redis.set(key + ":lease", token, nx=True, ex=120):
                        token = None
                        while time.monotonic() < deadline:
                            await asyncio.sleep(0.1)
                            cached = await redis.get(key)
                            if cached:
                                result = CameraEvidence.model_validate_json(cached)
                                return result if (result.inference_input_sha256 == metadata["content_sha256"]
                                                  and result.snapshot_id == metadata["snapshot_id"]
                                                  and result.route_ai_model_version == version
                                                  and (view_only or fresh(result.captured_at)) and fresh(result.retrieved_at) and fresh(result.updated_at)) else None
                            if not await redis.get(key + ":lease"):
                                return None
                        return None
                except Exception as exc:
                    logger.debug("Route AI cache unavailable: %s", exc)
                    # Local singleflight still prevents duplication within this process.
            if self._executor is None:
                limit = max(1, settings.ROUTE_AI_MAX_CONCURRENCY)
                self._executor = ThreadPoolExecutor(max_workers=limit, thread_name_prefix="route-camera-ai")
                self._slots = asyncio.Semaphore(limit)
            # Keep the permit until the thread finishes, even if the route times out.
            await asyncio.wait_for(self._slots.acquire(), timeout=max(0.01, deadline - time.monotonic()))
            try:
                if (not view_only and not fresh(metadata["captured_at"])) or not fresh(metadata["retrieved_at"]):
                    return None
                result = await asyncio.get_running_loop().run_in_executor(
                    self._executor, self._analyze, path, metadata, version)
            finally:
                self._slots.release()
            if (not view_only and not fresh(result.captured_at)) or not fresh(result.retrieved_at):
                return None
            result = result.model_copy(update={"route_ai_model_version": version})
            if view_only:
                result = result.model_copy(update={"evidence_eligibility": EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING,
                                                   "risk_level": RiskLevel.UNKNOWN, "permitted_use": "VIEW_ONLY"})
            self._cache[key] = (time.monotonic() + settings.ROUTE_AI_CACHE_TTL_SECONDS, result)
            while len(self._cache) > 256:
                self._cache.popitem(last=False)
            if redis is not None:
                try:
                    await redis.set(key, result.model_dump_json(), ex=settings.ROUTE_AI_CACHE_TTL_SECONDS)
                except Exception:
                    pass
            return result
        except Exception as exc:
            logger.warning("Route camera analysis unavailable: %s", exc)
            return None
        finally:
            if token is not None:
                try:
                    await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, key + ":lease", token)
                except Exception:
                    pass
            self._inflight.pop(key, None)
            if redis is not None:
                try:
                    await redis.aclose()
                except Exception:
                    pass

    async def analyze(self, path: str, metadata: dict, redis: Any, *, view_only: bool = False) -> CameraEvidence | None:
        if self._closed or (view_only and not settings.CAMERA_VIEW_AI_ENABLED) or (not view_only and metadata.get("permitted_use") == "VIEW_ONLY"):
            return None
        if view_only:
            metadata = {**metadata, "permitted_use": "VIEW_ONLY", "line_of_sight_verified": False,
                        "observed_osm_way_id": None, "observed_edge_index": None}
        version = model_version()
        scope = "view_ai" if view_only else "route_ai"
        key = f"camera:{scope}:{metadata['cam_id']}:{metadata['content_sha256']}:{version}"
        cached = self._cached(key, metadata, view_only)
        if cached is not None:
            return cached
        task = self._inflight.get(key)
        if task is None:
            # Bound waiting tasks as well as executing native model calls.
            if len(self._inflight) >= max(1, settings.ROUTE_AI_MAX_CONCURRENCY) * 2:
                return None
            task = asyncio.create_task(self._run(key, path, metadata, version, redis, view_only))
            self._inflight[key] = task
        result = await asyncio.shield(task)
        return result if (result is not None and result.snapshot_id == metadata["snapshot_id"]
                          and result.inference_input_sha256 == metadata["content_sha256"]
                          and result.route_ai_model_version == version) else None


route_camera_ai = RouteCameraAI()
_snapshot_locks: OrderedDict[str, tuple[asyncio.Lock, int]] = OrderedDict()


async def _locked_snapshot(camera: CameraEvidence, session: Any, redis: Any) -> dict | None:
    entry = _snapshot_locks.get(camera.cam_id)
    if entry is None:
        if len(_snapshot_locks) >= 256:
            removable = next((key for key, (_, users) in _snapshot_locks.items() if users == 0), None)
            if removable is None:
                return None
            _snapshot_locks.pop(removable)
        entry = (asyncio.Lock(), 0)
    lock, users = entry
    _snapshot_locks[camera.cam_id] = (lock, users + 1)
    _snapshot_locks.move_to_end(camera.cam_id)
    try:
        async with lock:
            return await _snapshot(camera, session, redis)
    finally:
        _snapshot_locks[camera.cam_id] = (lock, _snapshot_locks[camera.cam_id][1] - 1)


def sufficient_existing_evidence(camera: CameraEvidence, snapshot: dict) -> bool:
    """Reuse trustworthy current-model evidence only for this exact frame."""
    if (camera.evidence_eligibility != EvidenceEligibility.ROUTING_ELIGIBLE
            or not fresh(camera.updated_at) or not fresh(camera.captured_at)
            or not fresh(camera.retrieved_at) or camera.snapshot_id != snapshot["snapshot_id"]
            or camera.inference_input_sha256 != snapshot["content_sha256"]):
        return False
    if camera.route_ai_model_version != model_version():
        return False
    try:
        manifest = json.loads(Path("data/models/model_manifest.json").read_text())
        vehicle = manifest["models"]["vehicle_detector"]
        return bool(camera.vehicle_model_sha256 == vehicle["sha256"]
                    and camera.model_version == vehicle["version"])
    except (OSError, ValueError, KeyError):
        return False


async def _snapshot(camera: CameraEvidence, session: Any, redis: Any) -> dict | None:
    query = text("""SELECT snapshot_id, content_sha256, file_path, source_captured_at, fetched_at
                    FROM camera_snapshots WHERE camera_id = :cam_id AND is_latest = TRUE
                    ORDER BY created_at DESC LIMIT 1""")
    result = await session.execute(query, {"cam_id": camera.cam_id}) if isinstance(session, AsyncSession) else session.execute(query, {"cam_id": camera.cam_id})
    row = result.fetchone()
    if row and fresh(row.source_captured_at) and fresh(row.fetched_at):
        return {"snapshot_id": row.snapshot_id, "content_sha256": row.content_sha256,
                "image_path": row.file_path, "captured_at": row.source_captured_at,
                "retrieved_at": row.fetched_at}
    if row and fresh(row.fetched_at):
        # A recently retrieved frame with unknown/old capture time cannot be repaired
        # by repeatedly requesting the provider during concurrent route searches.
        return None
    # Fetch only this selected route camera; retain the scraper's provider/backoff gates.
    from backend.app.services.scraper import scrape_camera_image, portal_circuit_breaker
    if not portal_circuit_breaker.can_request():
        return None
    backoff_query = text("SELECT next_retry_at FROM camera_ingestion_state WHERE cam_id = :cam_id")
    result = await session.execute(backoff_query, {"cam_id": camera.cam_id}) if isinstance(session, AsyncSession) else session.execute(backoff_query, {"cam_id": camera.cam_id})
    backoff = result.fetchone()
    if backoff and backoff.next_retry_at and backoff.next_retry_at > datetime.now(timezone.utc):
        return None
    async with httpx.AsyncClient(verify=True, follow_redirects=False,
                                 timeout=settings.CAMERA_FETCH_TIMEOUT_SEC) as client:
        fetched = await scrape_camera_image(client, camera.model_dump(), allow_view_only=False, redis=redis)
    from backend.app.services.camera_scheduler import camera_scheduler
    await camera_scheduler.record_result(session=session, res=fetched, redis=redis)
    if not fetched.is_valid_image or not fresh(fetched.captured_at) or not fresh(fetched.retrieved_at):
        return None
    path = Path("storage/snapshots") / camera.cam_id / f"{fetched.snapshot_id}.jpg"
    return {"snapshot_id": fetched.snapshot_id, "content_sha256": fetched.content_sha256,
            "image_path": str(path), "captured_at": fetched.captured_at,
            "retrieved_at": fetched.retrieved_at}


async def enrich_route_cameras(cameras: dict, edges: dict, session: Any, redis: Any, *,
                               weather_tide: Any = None, traffic_news: Any = None,
                               step_context: dict | None = None) -> dict:
    """Called only between an actual OSRM route lookup and its risk ranking."""
    # Expired, old-model or permission-revoked evidence cannot influence a new search.
    current_version = model_version()
    cameras = {step: [c if (getattr(c, "permitted_use", None) in ROUTING_USES
                           and settings.CAMERA_ROUTING_EVIDENCE_PERMITTED
                           and belongs_to_step(c, edges.get(step, []))
                           and c.route_ai_model_version == current_version
                           and fresh(c.captured_at) and fresh(c.retrieved_at) and fresh(c.updated_at))
                      else c.model_copy(update={"evidence_eligibility": EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING})
                      for c in items] for step, items in cameras.items()}
    if not (settings.CAMERA_AI_MODE == "route_only" and settings.ROUTE_CAMERA_AI_ENABLED
            and settings.CAMERA_INGESTION_PERMITTED and settings.CAMERA_ROUTING_EVIDENCE_PERMITTED):
        return cameras
    selected: dict[str, CameraEvidence] = {}
    for step, items in cameras.items():
        context = (step_context or {}).get(step)
        sufficient = False
        if context is not None:
            # Existing independent evidence of closure/critical hazard is enough to
            # penalize this step; extra camera work cannot make it safe.
            from backend.app.services.risk_engine import calculate_segment_risk
            for edge in edges.get(step, []):
                if edge.get("route_match_verified") is not True:
                    continue
                try:
                    risk = calculate_segment_risk(
                        segment={**edge, "length_meters": edge.get("length_meters", context.get("distance")),
                                 "geojson_path": edge.get("geometry", context.get("geometry")),
                                 "street_name": context.get("name")},
                        camera_evidences=[], weather_tide=weather_tide,
                        traffic_news=traffic_news or [],
                    )
                    if risk.risk_level == RiskLevel.CRITICAL or risk.is_closed:
                        sufficient = True
                        break
                except (ValueError, TypeError):
                    continue
        if sufficient:
            continue
        for camera in items:
            if belongs_to_step(camera, edges.get(step, [])):
                selected.setdefault(camera.cam_id, camera)
    selected = dict(list(selected.items())[:max(0, settings.ROUTE_AI_MAX_CAMERAS)])
    if not selected:
        return cameras
    replacements = {}
    invalidated = set()

    async def work() -> None:
        pending = []
        try:
            # Session operations stay sequential; AsyncSession cannot service concurrent queries.
            for camera in selected.values():
                try:
                    invalidated.add(camera.cam_id)
                    snapshot = await _locked_snapshot(camera, session, redis)
                    if snapshot is None or not snapshot["snapshot_id"] or not snapshot["content_sha256"]:
                        continue
                    if sufficient_existing_evidence(camera, snapshot):
                        invalidated.discard(camera.cam_id)
                        continue
                    metadata = {**camera.model_dump(), **snapshot}
                    pending.append((camera.cam_id, metadata, asyncio.create_task(route_camera_ai.analyze(snapshot["image_path"], metadata, redis))))
                except Exception as exc:
                    logger.debug("Route snapshot unavailable for %s: %s", camera.cam_id, exc)
            for cam_id, metadata, task in pending:
                result = await task
                if result is not None:
                    replacements[cam_id] = result
        finally:
            for _, _, task in pending:
                if not task.done():
                    task.cancel()

    try:
        await asyncio.wait_for(work(), timeout=max(0.01, settings.ROUTE_AI_TIMEOUT_SECONDS))
    except asyncio.TimeoutError:
        logger.info("Route camera AI time budget exhausted; retaining available evidence")
    # Database spatial provenance remains authoritative, including on cached AI results.
    spatial_fields = ("permitted_use", "coordinate_source_url", "view_verification_source_url", "observed_osm_way_id",
                      "observed_edge_index", "line_of_sight_verified", "spatial_match_status")
    return {step: [replacements[c.cam_id].model_copy(update={field: getattr(c, field) for field in spatial_fields})
                   if c.cam_id in replacements and belongs_to_step(c, edges.get(step, []))
                   else c.model_copy(update={"evidence_eligibility": EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING})
                   if c.cam_id in invalidated else c
                   for c in items] for step, items in cameras.items()}
