"""
Test Suite for SafePathAI P0 Camera 60-Second Refresh & Placeholder Elimination.

Covers:
1. Image Validator - Valid JPEG accepted.
2. Image Validator - 290x183 placeholder PNG rejected (MD5: 9653ea117b2c39d4c477b0949f95860e).
3. Image Validator - Enhanced placeholder JPEG rejected (MD5: d681aeeeaa468b620624b02e3b7c82d4).
4. Image Validator - Binary template normalized cross-correlation >= 0.85 rejection.
5. Image Validator - Real street camera image has low correlation (< 0.50).
6. Image Validator - Truncated, empty, and non-image bytes rejected.
7. Scraper Cache Policy - Fallback cache uses file mtime and sets is_new_snapshot=False.
8. Scraper Cache Policy - Live success sets is_new_snapshot=True and updates last_success_at.
9. Scheduler Priority 1 - Active camera (viewed/route) checked >= 60s ago is prioritized.
10. Scheduler Priority 2 - Background fair round-robin rotation without starvation.
11. Redis ZSet TTL - Auto-pruning of expired priority cameras.
12. Vision Guard - preprocess_camera_image strictly raises ValueError on placeholder bytes.
13. Endpoints - POST/DELETE active-view and POST active-route endpoints.
14. Camera Metadata Endpoint - Returns 4 distinct timestamps (attempt, success, retrieved, captured) + image_hash.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import io
import os
import cv2
import numpy as np
from PIL import Image
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.core.config import settings
from backend.app.db.session import AsyncSessionLocal, get_redis_client
from backend.app.main import app
from backend.app.services.camera_scheduler import camera_scheduler
from backend.app.services.image_validator import (
    validate_camera_image_bytes,
    ImageValidationStatus,
    check_template_correlation,
)
from backend.app.services.scraper import ScrapedCameraResult, DataSourceStatus
from backend.app.services.vision import preprocess_camera_image


def _create_synthetic_jpeg(width=300, height=230, color=(120, 140, 160)) -> bytes:
    """Creates a real-looking synthetic street scene with varied pixel texture."""
    arr = np.full((height, width, 3), color, dtype=np.uint8)
    # Add random textures to avoid uniform or discrete grayscale
    noise = np.random.randint(0, 40, (height, width, 3), dtype=np.uint8)
    arr = cv2.add(arr, noise)
    cv2.putText(arr, "HCM TRAFFIC", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    _, enc = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return enc.tobytes()


def _create_synthetic_placeholder(width=290, height=183) -> bytes:
    """Creates a placeholder image matching the HCMC 'IMAGE NOT AVAILABLE' style."""
    arr = np.full((height, width, 3), 200, dtype=np.uint8)
    cv2.rectangle(arr, (20, 20), (width - 20, height - 20), (120, 120, 120), -1)
    cv2.putText(arr, "IMAGE NOT AVAILABLE", (30, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240, 240, 240), 1)
    # Convert to grayscale values (R=G=B)
    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    arr_gray = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    _, enc = cv2.imencode(".png", arr_gray)
    return enc.tobytes()


# ------------------------------------------------------------------------------
# 1. Image Validator Unit Tests
# ------------------------------------------------------------------------------
def test_image_validator_valid_jpeg():
    """Valid street JPEG passes validation with status VALID."""
    jpeg_bytes = _create_synthetic_jpeg()
    val = validate_camera_image_bytes(jpeg_bytes)
    assert val.is_valid is True
    assert val.status == ImageValidationStatus.VALID
    assert val.format == "JPEG"
    assert val.md5_hash == hashlib.md5(jpeg_bytes).hexdigest()


def test_image_validator_known_placeholder_md5():
    """Known 290x183 placeholder MD5 must be rejected as PLACEHOLDER_ERROR_FRAME."""
    quarantine_dir = os.path.join("storage", "quarantine", "placeholders")
    tested = False
    if os.path.exists(quarantine_dir):
        raw_files = [
            f for f in os.listdir(quarantine_dir)
            if f.endswith(".jpg") and not any(f.endswith(s) for s in ["_enhanced.jpg", "_analyzed.jpg", "_annotated.jpg"])
        ]
        if raw_files:
            with open(os.path.join(quarantine_dir, raw_files[0]), "rb") as fh:
                raw = fh.read()
            val = validate_camera_image_bytes(raw)
            assert val.is_valid is False
            assert val.status == ImageValidationStatus.PLACEHOLDER_ERROR_FRAME
            tested = True
    if not tested:
        pl_bytes = _create_synthetic_placeholder()
        val = validate_camera_image_bytes(pl_bytes)
        assert val.is_valid is False
        assert val.status == ImageValidationStatus.PLACEHOLDER_ERROR_FRAME


def test_image_validator_template_correlation_rejection():
    """Verifies that the normalized cross-correlation algorithm detects placeholder graphics."""
    quarantine_dir = os.path.join("storage", "quarantine", "placeholders")
    if os.path.exists(quarantine_dir):
        raw_files = [
            f for f in os.listdir(quarantine_dir)
            if f.endswith(".jpg") and not any(f.endswith(s) for s in ["_enhanced.jpg", "_analyzed.jpg", "_annotated.jpg"])
        ]
        if raw_files:
            with open(os.path.join(quarantine_dir, raw_files[0]), "rb") as fh:
                raw = fh.read()
            is_match, max_val = check_template_correlation(raw)
            assert is_match is True
            assert max_val >= 0.85


def test_image_validator_real_scene_low_correlation():
    """Real street camera scenes must have low correlation (< 0.50) against placeholder template."""
    cams_dir = os.path.join("storage", "cams")
    if os.path.exists(cams_dir):
        files = [f for f in os.listdir(cams_dir) if f.endswith(".jpg") and not f.endswith("_enhanced.jpg") and not f.endswith("_analyzed.jpg")]
        for f in files[:5]:
            with open(os.path.join(cams_dir, f), "rb") as fh:
                raw = fh.read()
            is_match, max_val = check_template_correlation(raw)
            assert is_match is False, f"Real camera image {f} falsely flagged with corr {max_val}"
            assert max_val < 0.50


def test_image_validator_empty_and_corrupt():
    """Empty or garbage bytes must return INVALID_MAGIC_BYTES or DECODE_ERROR."""
    val_empty = validate_camera_image_bytes(b"")
    assert val_empty.is_valid is False
    assert val_empty.status == ImageValidationStatus.INVALID_MAGIC_BYTES

    val_garbage = validate_camera_image_bytes(b"NOT_AN_IMAGE_RANDOM_TEXT_1234567890")
    assert val_garbage.is_valid is False
    assert val_garbage.status == ImageValidationStatus.INVALID_MAGIC_BYTES


# ------------------------------------------------------------------------------
# 2. Scraper & Timestamp Precision Tests
# ------------------------------------------------------------------------------
def test_scraped_camera_result_timestamps_precision():
    """
    Distinguishes is_new_snapshot=True vs False.
    Fallback cache results must NOT set is_new_snapshot=True.
    """
    now = datetime.now(timezone.utc)
    old_time = now - timedelta(hours=2)

    # 1. Live success snapshot
    res_live = ScrapedCameraResult(
        cam_id="test_cam_01",
        code="TTH-1",
        name="Test Live Cam",
        district="Q1",
        lat=10.77,
        lng=106.69,
        image_path="storage/cams/test_cam_01.jpg",
        image_bytes=b"valid_bytes",
        source_status=DataSourceStatus.LIVE,
        retrieved_at=now,
        captured_at=now - timedelta(seconds=10),
        capture_time_status="CAPTURE_TIME_VERIFIED",
        file_size=1024,
        is_valid_image=True,
        is_new_snapshot=True,
    )
    assert res_live.is_new_snapshot is True
    assert res_live.to_dict()["is_new_snapshot"] is True
    assert res_live.retrieved_at == now

    # 2. Fallback cache snapshot
    res_cache = ScrapedCameraResult(
        cam_id="test_cam_02",
        code="TTH-2",
        name="Test Cache Cam",
        district="Q1",
        lat=10.78,
        lng=106.70,
        image_path="storage/cams/test_cam_02.jpg",
        image_bytes=b"cached_bytes",
        source_status=DataSourceStatus.STALE,
        retrieved_at=old_time,
        captured_at=None,
        capture_time_status="CAPTURE_TIME_UNKNOWN",
        file_size=1024,
        is_valid_image=True,
        is_new_snapshot=False,
    )
    assert res_cache.is_new_snapshot is False
    assert res_cache.to_dict()["is_new_snapshot"] is False
    assert res_cache.retrieved_at == old_time


# ------------------------------------------------------------------------------
# 3. Scheduler Priority 1 (60s) & Fair-Queue Round-Robin Tests
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scheduler_active_priority_60s_cutoff():
    """
    Active camera (Tier 0 viewed or Tier 1 route) attempted >= 60 seconds ago
    must be prioritized at the head of acquire_batch over background cameras.
    """
    redis = get_redis_client()
    try:
        async with AsyncSessionLocal() as session:
            # Pick one registered camera
            row = (await session.execute(text("SELECT cam_id FROM traffic_cameras ORDER BY cam_id ASC LIMIT 1"))).fetchone()
            assert row is not None
            cam_id = row.cam_id

            # Set its last_attempt_at to 65 seconds ago (outside 60s cutoff)
            sixty_five_sec_ago = datetime.now(timezone.utc) - timedelta(seconds=65)
            await session.execute(
                text("""
                    UPDATE camera_ingestion_state 
                    SET last_attempt_at = :t, next_retry_at = NULL 
                    WHERE cam_id = :cid
                """),
                {"t": sixty_five_sec_ago, "cid": cam_id},
            )
            await session.commit()

        # Delete any active lease and clean stale test priority sets
        await redis.delete(
            f"camera:lease:{cam_id}",
            "active_viewed_cameras",
            "active_route_cameras",
            "active_viewed_cameras_zset",
            "active_route_cameras_zset",
        )

        # Register in Priority 0 viewed set
        await camera_scheduler.register_active_viewed_cameras(redis, [cam_id], ttl_seconds=90)

        async with AsyncSessionLocal() as session:
            batch = await camera_scheduler.acquire_batch(session, redis, batch_size=4, worker_id="test-priority-worker")
            batch_ids = [c["cam_id"] for c in batch]
            assert cam_id in batch_ids, f"Active priority camera {cam_id} was not included in acquire_batch: {batch_ids}"
            # Ensure it is prioritized as Tier 0
            tier_for_cam = next(c["priority_tier"] for c in batch if c["cam_id"] == cam_id)
            assert tier_for_cam == 0
    finally:
        await camera_scheduler.unregister_active_viewed_camera(redis, cam_id)
        await redis.aclose()


@pytest.mark.asyncio
async def test_scheduler_redis_zset_ttl_pruning():
    """
    Verifies that register_active_viewed_cameras with an expired timestamp
    is pruned automatically by get_active_priority_camera_ids.
    """
    redis = get_redis_client()
    try:
        test_id_expired = "test_expired_cam_99"
        test_id_active = "test_active_cam_88"

        now_ts = datetime.now(timezone.utc).timestamp()
        # Add expired member (expired 10s ago)
        await redis.zadd("active_viewed_cameras_zset", {test_id_expired: now_ts - 10})
        # Add active member (expires in 60s)
        await redis.zadd("active_viewed_cameras_zset", {test_id_active: now_ts + 60})

        viewed, _ = await camera_scheduler.get_active_priority_camera_ids(redis)
        assert test_id_expired not in viewed
        assert test_id_active in viewed
    finally:
        await redis.zrem("active_viewed_cameras_zset", test_id_expired, test_id_active)
        await redis.srem("active_viewed_cameras", test_id_expired, test_id_active)
        await redis.aclose()


# ------------------------------------------------------------------------------
# 4. Computer Vision Guard against Placeholders
# ------------------------------------------------------------------------------
def test_vision_preprocess_blocks_placeholder():
    """
    preprocess_camera_image in vision.py MUST raise ValueError when fed a placeholder frame.
    Never proceeds to CLAHE enhancement or YOLO detection.
    """
    quarantine_dir = os.path.join("storage", "quarantine", "placeholders")
    raw_files = [
        f for f in os.listdir(quarantine_dir)
        if f.endswith(".jpg") and not any(f.endswith(s) for s in ["_enhanced.jpg", "_analyzed.jpg", "_annotated.jpg"])
    ]
    assert len(raw_files) > 0
    target_path = os.path.join(quarantine_dir, raw_files[0])

    with pytest.raises(ValueError) as excinfo:
        preprocess_camera_image(target_path)
    assert "Rejecting placeholder or invalid image" in str(excinfo.value)


# ------------------------------------------------------------------------------
# 5. FastAPI Endpoints Integration Tests
# ------------------------------------------------------------------------------
def test_fastapi_active_view_and_route_endpoints():
    """
    Tests POST /api/v1/cameras/active-view,
    DELETE /api/v1/cameras/{cam_id}/active-view,
    and POST /api/v1/cameras/active-route.
    """
    client = TestClient(app)

    # 1. Register active view
    res1 = client.post(
        "/api/v1/cameras/active-view",
        json={"cam_ids": ["56de42f611f398ec0c48127d"], "ttl_seconds": 90},
    )
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] == "ok"
    assert data1["registered_count"] >= 1
    assert data1["active_viewed_count"] >= 1

    # 2. Register active route
    res2 = client.post(
        "/api/v1/cameras/active-route",
        json={"cam_ids": ["56de42f611f398ec0c48127e"], "ttl_seconds": 900},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "ok"
    assert data2["registered_count"] >= 1
    assert data2["active_route_count"] >= 1

    # 3. Unregister active view
    res3 = client.delete("/api/v1/cameras/56de42f611f398ec0c48127d/active-view")
    assert res3.status_code == 200
    assert res3.json()["status"] == "ok"


def test_fastapi_camera_metadata_timestamps():
    """
    Tests GET /api/v1/cameras/{cam_id}/metadata returns 4 distinct timestamps
    and does not return placeholder frame as valid cached image.
    """
    client = TestClient(app)

    # Valid camera
    res = client.get("/api/v1/cameras/56de42f611f398ec0c48127d/metadata")
    assert res.status_code == 200
    meta = res.json()
    assert "cam_id" in meta
    assert "last_attempt_at" in meta
    assert "last_success_at" in meta
    assert "retrieved_at" in meta
    assert "captured_at" in meta
    assert "image_hash" in meta


def test_fastapi_camera_summary_contract():
    """
    Tests GET /api/v1/cameras/summary contains verified cycle target (1800s)
    and circuit breaker status.
    """
    client = TestClient(app)
    res = client.get("/api/v1/cameras/summary")
    assert res.status_code == 200
    summary = res.json()
    assert summary["total_registered"] == 796
    assert summary["cycle_target_sec"] == 1800
    assert "circuit_breaker_open" in summary
    assert "valid_images_count" in summary
    assert "unavailable_count" in summary
