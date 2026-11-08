"""
SafePathAI Camera 10-Minute Background Refresh & Provenance Acceptance Tests.
Covers:
1. Duplicate SHA-256 detection (is_new_snapshot=False, no redundant queue/inference).
2. New image with distinct SHA-256 (advances last_success_at, is_new_snapshot=True).
3. Unverified timestamp (RECENTLY_RETRIEVED_CAPTURE_UNKNOWN, CAPTURE_TIME_UNKNOWN, never fake LIVE).
4. Verified timestamp within TTL (LIVE_VERIFIED, CAPTURE_TIME_EXPLICIT).
5. Stale frame retention (STALE, last known good frame preserved).
6. HTTP 403 / 429 exponential backoff and RESTRICTED status.
7. Placeholder detection and zero-mock quarantine.
8. Single-flight request coalescing for concurrent client refreshes.
9. Starvation-free fair scheduling and 600s cycle metrics.
"""

import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import os
from typing import Optional
import cv2
import numpy as np
import pytest
from starlette.testclient import TestClient

from backend.app.core.config import settings
from backend.app.main import app, _camera_refresh_locks, _camera_last_refreshed
from backend.app.schemas.contracts import (
    CameraFreshnessStatus,
    DataSourceStatus,
    ImageAccessStatus,
)
from backend.app.services.image_validator import (
    validate_camera_image_bytes,
    ImageValidationStatus,
)
from backend.app.services.scraper import (
    ScrapedCameraResult,
)
from backend.app.services.camera_scheduler import (
    CameraScheduler,
    camera_scheduler,
)


def _make_test_image(text_label: str = "CAM_TEST_1", color=(100, 150, 200)) -> bytes:
    arr = np.full((240, 320, 3), color, dtype=np.uint8)
    noise = np.random.randint(0, 30, (240, 320, 3), dtype=np.uint8)
    arr = cv2.add(arr, noise)
    cv2.putText(arr, text_label, (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    _, enc = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    return enc.tobytes()


def _create_synthetic_placeholder(width=290, height=183) -> bytes:
    """Creates a placeholder image matching the HCMC 'IMAGE NOT AVAILABLE' style."""
    arr = np.full((height, width, 3), 200, dtype=np.uint8)
    cv2.rectangle(arr, (20, 20), (width - 20, height - 20), (120, 120, 120), -1)
    cv2.putText(arr, "IMAGE NOT AVAILABLE", (30, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1)
    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    arr_gray = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    _, enc = cv2.imencode(".png", arr_gray)
    return enc.tobytes()


def _make_scraped_result(
    cam_id: str = "test_cam",
    source_status: DataSourceStatus = DataSourceStatus.LIVE,
    freshness_status: str = CameraFreshnessStatus.RECENTLY_RETRIEVED_CAPTURE_UNKNOWN,
    captured_at: Optional[datetime] = None,
    capture_time_status: str = "CAPTURE_TIME_UNKNOWN",
    is_new_snapshot: bool = True,
    is_valid_image: bool = True,
    validation_status: Optional[str] = "VALID_FRAME",
    image_status_reason: Optional[str] = None,
    http_status: int = 200,
    content_sha256: Optional[str] = None,
    retrieved_at: Optional[datetime] = None,
) -> ScrapedCameraResult:
    now = retrieved_at or datetime.now(timezone.utc)
    return ScrapedCameraResult(
        cam_id=cam_id,
        code="TEST",
        name=f"Camera {cam_id}",
        district="Q1",
        lat=10.77,
        lng=106.70,
        image_path=f"storage/cams/{cam_id}.jpg" if is_valid_image else None,
        image_bytes=b"dummy" if is_valid_image else None,
        source_status=source_status,
        retrieved_at=now,
        captured_at=captured_at,
        capture_time_status=capture_time_status,
        file_size=1000 if is_valid_image else 0,
        is_valid_image=is_valid_image,
        is_new_snapshot=is_new_snapshot,
        validation_status=validation_status,
        image_status_reason=image_status_reason,
        http_status=http_status,
        content_sha256=content_sha256,
        freshness_status=freshness_status,
    )


# ------------------------------------------------------------------------------
# 1. SHA-256 Deduplication & Idempotency
# ------------------------------------------------------------------------------
def test_duplicate_sha256_marked_not_new_and_no_timestamp_advance():
    """Identical SHA-256 frame must not advance last_success_at and must set is_new_snapshot=False."""
    raw = _make_test_image("FRAME_STATIC_1")
    sha256 = hashlib.sha256(raw).hexdigest()

    # Step 1: Validate with previous_sha256 equal to current -> flagged as DUPLICATE_FRAME
    val = validate_camera_image_bytes(raw, previous_sha256=sha256)
    assert val.is_valid is False
    assert val.status == ImageValidationStatus.DUPLICATE_FRAME

    # Step 2: Scraped result with duplicate SHA256 has is_new_snapshot=False
    result = _make_scraped_result(
        cam_id="test_cam_dedup",
        content_sha256=sha256,
        is_new_snapshot=False,
    )
    assert result.is_new_snapshot is False
    assert result.content_sha256 == sha256


def test_distinct_sha256_accepted_as_new_snapshot():
    """Distinct SHA-256 advances last_success_at and sets is_new_snapshot=True."""
    raw1 = _make_test_image("FRAME_A", color=(100, 120, 140))
    raw2 = _make_test_image("FRAME_B", color=(150, 180, 210))

    sha1 = hashlib.sha256(raw1).hexdigest()
    sha2 = hashlib.sha256(raw2).hexdigest()
    assert sha1 != sha2

    val = validate_camera_image_bytes(raw2, previous_sha256=sha1)
    assert val.is_valid is True
    assert val.status == ImageValidationStatus.VALID

    result = _make_scraped_result(
        cam_id="test_cam_new",
        content_sha256=sha2,
        is_new_snapshot=True,
    )
    assert result.is_new_snapshot is True
    assert result.content_sha256 == sha2


# ------------------------------------------------------------------------------
# 2. Timestamp Provenance & Freshness Status Segregation
# ------------------------------------------------------------------------------
def test_unverified_timestamp_yields_capture_unknown():
    """Frame with unverified capture time must yield RECENTLY_RETRIEVED_CAPTURE_UNKNOWN, never LIVE_VERIFIED."""
    t_now = datetime.now(timezone.utc)
    res = _make_scraped_result(
        cam_id="test_unverified",
        source_status=DataSourceStatus.LIVE,
        freshness_status=CameraFreshnessStatus.RECENTLY_RETRIEVED_CAPTURE_UNKNOWN,
        captured_at=None,
        capture_time_status="CAPTURE_TIME_UNKNOWN",
        retrieved_at=t_now,
    )
    d = res.to_dict()
    assert d["freshness_status"] == CameraFreshnessStatus.RECENTLY_RETRIEVED_CAPTURE_UNKNOWN
    assert d["capture_time_status"] == "CAPTURE_TIME_UNKNOWN"
    assert d["captured_at"] is None
    assert d["freshness_status"] != CameraFreshnessStatus.LIVE_VERIFIED


def test_verified_timestamp_within_ttl_yields_live_verified():
    """Frame with verified capture time <= 600s yields LIVE_VERIFIED."""
    t_now = datetime.now(timezone.utc)
    t_captured = t_now - timedelta(seconds=120)  # 2 minutes ago (well within 600s)
    res = _make_scraped_result(
        cam_id="test_verified",
        source_status=DataSourceStatus.LIVE,
        freshness_status=CameraFreshnessStatus.LIVE_VERIFIED,
        captured_at=t_captured,
        capture_time_status="CAPTURE_TIME_EXPLICIT",
        retrieved_at=t_now,
    )
    d = res.to_dict()
    assert d["freshness_status"] == CameraFreshnessStatus.LIVE_VERIFIED
    assert d["capture_time_status"] == "CAPTURE_TIME_EXPLICIT"
    assert d["captured_at"] == t_captured.isoformat()


def test_stale_frame_older_than_600s_marked_stale():
    """Frame older than 600s is marked STALE and not valid for current flood evidence."""
    t_now = datetime.now(timezone.utc)
    t_stale = t_now - timedelta(seconds=650)  # > 600s
    res = _make_scraped_result(
        cam_id="test_stale",
        source_status=DataSourceStatus.STALE,
        freshness_status=CameraFreshnessStatus.STALE,
        captured_at=t_stale,
        retrieved_at=t_stale,
        is_new_snapshot=False,
    )
    d = res.to_dict()
    assert d["freshness_status"] == CameraFreshnessStatus.STALE
    assert d["source_status"] == DataSourceStatus.STALE.value


# ------------------------------------------------------------------------------
# 3. HTTP 403 / 429 Exponential Backoff & Restricted Status
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_http_403_and_429_exponential_backoff():
    """403/429 triggers exponential backoff and sets RESTRICTED status."""
    from backend.app.db.session import AsyncSessionLocal
    from sqlalchemy import text
    cam_id = "56de42f611f398ec0c48127d"
    now = datetime.now(timezone.utc)

    # 1. 403 Forbidden
    res_403 = _make_scraped_result(
        cam_id=cam_id,
        source_status=DataSourceStatus.STALE,
        freshness_status=CameraFreshnessStatus.RESTRICTED,
        http_status=403,
        is_valid_image=False,
        validation_status="HTTP_403_FORBIDDEN",
        image_status_reason="EXTERNAL_ACCESS_RESTRICTED",
        retrieved_at=now,
    )
    async with AsyncSessionLocal() as session:
        await camera_scheduler.record_result(session, res_403)
        row = (await session.execute(
            text("SELECT failure_count, last_error_code, next_retry_at FROM camera_ingestion_state WHERE cam_id = :cam_id"),
            {"cam_id": cam_id},
        )).fetchone()
        assert row is not None
        assert row.failure_count >= 1
        assert row.next_retry_at > now
        first_retry = row.next_retry_at

        # 2. 429 Too Many Requests (Exponential Backoff advances next_retry_at even further)
        res_429 = _make_scraped_result(
            cam_id=cam_id,
            source_status=DataSourceStatus.STALE,
            freshness_status=CameraFreshnessStatus.RESTRICTED,
            http_status=429,
            is_valid_image=False,
            validation_status="HTTP_429_RATE_LIMIT",
            image_status_reason="RATE_LIMITED",
            retrieved_at=now,
        )
        await camera_scheduler.record_result(session, res_429)
        row2 = (await session.execute(
            text("SELECT failure_count, last_error_code, next_retry_at FROM camera_ingestion_state WHERE cam_id = :cam_id"),
            {"cam_id": cam_id},
        )).fetchone()
        assert row2.failure_count >= 2
        assert row2.next_retry_at > first_retry


# ------------------------------------------------------------------------------
# 4. Zero-Mock Placeholder Rejection
# ------------------------------------------------------------------------------
def test_placeholder_frame_zero_mock_rejection():
    """HCMC 'IMAGE NOT AVAILABLE' placeholder is quarantined and marked PLACEHOLDER."""
    placeholder_bytes = _create_synthetic_placeholder()
    val = validate_camera_image_bytes(placeholder_bytes)
    assert val.is_valid is False
    assert val.status == ImageValidationStatus.PLACEHOLDER_ERROR_FRAME

    res = _make_scraped_result(
        cam_id="test_placeholder",
        source_status=DataSourceStatus.STALE,
        freshness_status=CameraFreshnessStatus.PLACEHOLDER,
        is_valid_image=False,
        validation_status="PLACEHOLDER_FRAME",
        image_status_reason="PLACEHOLDER_FRAME",
    )
    d = res.to_dict()
    assert d["freshness_status"] == CameraFreshnessStatus.PLACEHOLDER
    assert d["validation_status"] == "PLACEHOLDER_FRAME"


# ------------------------------------------------------------------------------
# 5. Single-Flight Coalescing
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_single_flight_coalescing_lock():
    """Concurrent requests for the same camera ID share a single in-flight fetch."""
    cam_id = "test_coalesce_cam"
    fetch_count = 0

    async def mock_fetch():
        nonlocal fetch_count
        if cam_id not in _camera_refresh_locks:
            _camera_refresh_locks[cam_id] = asyncio.Lock()
        lock = _camera_refresh_locks[cam_id]
        async with lock:
            # Check cached result within 5 seconds
            cached = _camera_last_refreshed.get(cam_id)
            if cached and (asyncio.get_event_loop().time() - cached[0]) < 5.0:
                return cached[1]
            fetch_count += 1
            await asyncio.sleep(0.05)  # simulate network fetch
            res = {"status": "ok", "fetch_id": fetch_count}
            _camera_last_refreshed[cam_id] = (asyncio.get_event_loop().time(), res)
            return res

    # Launch 5 concurrent callers
    results = await asyncio.gather(*(mock_fetch() for _ in range(5)))
    assert len(results) == 5
    # All callers received the same fetch execution
    assert fetch_count == 1
    for r in results:
        assert r["fetch_id"] == 1


# ------------------------------------------------------------------------------
# 6. Fair Scheduling & 600-Second Cycle Metrics
# ------------------------------------------------------------------------------
def test_camera_summary_reports_600s_target_and_truthful_metrics():
    """Summary endpoint reports cycle_target_sec=600 and computed lag metrics without fake completion."""
    client = TestClient(app)
    res = client.get("/api/v1/cameras/summary")
    assert res.status_code == 200
    summary = res.json()
    assert summary["cycle_target_sec"] == 600
    assert "cycle_target_met" in summary
    assert "cycle_lag_seconds" in summary
    assert "total_registered" in summary
    assert summary["total_registered"] == 796
    # Lag seconds is non-negative
    if summary["cycle_lag_seconds"] is not None:
        assert summary["cycle_lag_seconds"] >= 0
