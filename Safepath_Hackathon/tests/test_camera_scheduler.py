"""
Test suite for SafePathAI Camera Ingestion Scheduler & Fair Queue Manager (Phase 1).
Verifies starvation prevention, multi-tier priority rotation across all 796 nodes,
distributed lease locking, exponential backoff, and administrative telemetry endpoints.
"""

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.session import AsyncSessionLocal, get_redis_client
from backend.app.main import app
from backend.app.services.camera_scheduler import camera_scheduler
from backend.app.services.scraper import ScrapedCameraResult, DataSourceStatus


@pytest.mark.asyncio
async def test_scheduler_starvation_prevention_rotation():
    """
    Verifies that the scheduler does NOT repeatedly select the same fixed 8 cameras.
    Consecutive acquire_batch calls must progress across different camera IDs.
    """
    redis = get_redis_client()
    try:
        keys = await redis.keys("camera:lease:*")
        if keys:
            await redis.delete(*keys)
        async with AsyncSessionLocal() as session:
            batch1 = await camera_scheduler.acquire_batch(session, redis, batch_size=4, worker_id="test-worker-1")
            batch2 = await camera_scheduler.acquire_batch(session, redis, batch_size=4, worker_id="test-worker-1")

            assert len(batch1) == 4
            assert len(batch2) == 4

            cams1 = [c["cam_id"] for c in batch1]
            cams2 = [c["cam_id"] for c in batch2]

            # Overlap between consecutive batches must be zero
            overlap = set(cams1).intersection(set(cams2))
            assert len(overlap) == 0, f"Scheduler starved rotation: found overlap {overlap}"
    finally:
        await redis.aclose()


@pytest.mark.asyncio
async def test_scheduler_priority_tiers():
    """
    Verifies that active viewed cameras (Tier 0) and active route cameras (Tier 1)
    jump ahead in the queue over normal round-robin candidates.
    """
    redis = get_redis_client()
    try:
        # Pick 2 arbitrary camera IDs from the registry
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text
            rows = (await session.execute(text("SELECT cam_id FROM traffic_cameras ORDER BY cam_id DESC LIMIT 2"))).fetchall()
            target_viewed_cam = rows[0].cam_id
            target_route_cam = rows[1].cam_id

        # Mark in Redis sets (clean stale priority sets for test isolation)
        await redis.delete(
            f"camera:lease:{target_viewed_cam}",
            f"camera:lease:{target_route_cam}",
            "active_viewed_cameras",
            "active_route_cameras",
            "active_viewed_cameras_zset",
            "active_route_cameras_zset",
        )
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE camera_ingestion_state SET next_retry_at = NULL WHERE cam_id IN (:c1, :c2)"),
                {"c1": target_viewed_cam, "c2": target_route_cam},
            )
            await session.commit()

        await redis.sadd("active_viewed_cameras", target_viewed_cam)
        await redis.sadd("active_route_cameras", target_route_cam)

        async with AsyncSessionLocal() as session:
            batch = await camera_scheduler.acquire_batch(session, redis, batch_size=2, worker_id="test-worker-priority")
            batch_ids = [c["cam_id"] for c in batch]

            assert target_viewed_cam in batch_ids or target_route_cam in batch_ids
            assert batch[0]["priority_tier"] in (0, 1)
    finally:
        await redis.srem("active_viewed_cameras", target_viewed_cam)
        await redis.srem("active_route_cameras", target_route_cam)
        await redis.aclose()


@pytest.mark.asyncio
async def test_scheduler_distributed_lease_locking():
    """
    Verifies that when a camera is locked by worker A with an active lease,
    worker B skips it and acquires the next available candidate.
    """
    redis = get_redis_client()
    try:
        keys = await redis.keys("camera:lease:*")
        if keys:
            await redis.delete(*keys)
        async with AsyncSessionLocal() as session:
            # Let worker A lock batch of 2 cameras
            batch_a = await camera_scheduler.acquire_batch(session, redis, batch_size=2, worker_id="worker-A")
            locked_ids = {c["cam_id"] for c in batch_a}

            # Worker B immediately attempts to acquire batch
            batch_b = await camera_scheduler.acquire_batch(session, redis, batch_size=2, worker_id="worker-B")
            worker_b_ids = {c["cam_id"] for c in batch_b}

            # No overlap allowed while worker A holds leases
            assert len(locked_ids.intersection(worker_b_ids)) == 0
    finally:
        # Clean up leases
        for cid in locked_ids.union(worker_b_ids):
            await redis.delete(f"camera:lease:{cid}")
        await redis.aclose()


@pytest.mark.asyncio
async def test_scheduler_exponential_backoff_and_reset():
    """
    Verifies that consecutive failures trigger exponential backoff,
    and a successful fetch resets failure count to 0.
    """
    cam_id = "56de42f611f398ec0c48127d"
    now = datetime.now(timezone.utc)

    # 1. Simulate failure
    failed_res = ScrapedCameraResult(
        cam_id=cam_id,
        code="TEST",
        name="Test Cam",
        district="Q1",
        lat=10.77,
        lng=106.70,
        image_path=None,
        image_bytes=None,
        source_status=DataSourceStatus.STALE,
        retrieved_at=now,
        captured_at=None,
        capture_time_status="UNKNOWN",
        file_size=0,
        is_valid_image=False,
        validation_status="CAMERA_OFFLINE",
        image_status_reason="NETWORK_TIMEOUT",
    )

    async with AsyncSessionLocal() as session:
        await camera_scheduler.record_result(session, failed_res)

        from sqlalchemy import text
        res = await session.execute(
            text("SELECT failure_count, source_status, last_error_code, next_retry_at FROM camera_ingestion_state WHERE cam_id = :cam_id"),
            {"cam_id": cam_id},
        )
        row = res.fetchone()
        assert row.failure_count >= 1
        assert row.source_status == "OFFLINE"
        assert row.last_error_code == "NETWORK_TIMEOUT"
        assert row.next_retry_at > now

    # 2. Simulate success -> resets failure count
    success_res = ScrapedCameraResult(
        cam_id=cam_id,
        code="TEST",
        name="Test Cam",
        district="Q1",
        lat=10.77,
        lng=106.70,
        image_path=f"storage/cams/{cam_id}.jpg",
        image_bytes=b"dummybytes",
        source_status=DataSourceStatus.LIVE,
        retrieved_at=now,
        captured_at=now,
        capture_time_status="CAPTURE_TIME_VALID",
        file_size=1000,
        is_valid_image=True,
        validation_status="VALID_FRAME",
        etag="testhash123",
    )

    async with AsyncSessionLocal() as session:
        await camera_scheduler.record_result(session, success_res)
        res = await session.execute(
            text("SELECT failure_count, source_status, last_error_code FROM camera_ingestion_state WHERE cam_id = :cam_id"),
            {"cam_id": cam_id},
        )
        row = res.fetchone()
        assert row.failure_count == 0
        assert row.source_status == "LIVE"
        assert row.last_error_code is None


def test_admin_camera_ingestion_status_endpoint():
    """
    Verifies that GET /api/v1/admin/camera-ingestion/status returns comprehensive metrics
    without leaking sensitive tokens or cookies.
    """
    with TestClient(app) as client:
        res = client.get("/api/v1/admin/camera-ingestion/status")
        assert res.status_code == 200
        data = res.json()

        assert data["status"] == "healthy"
        assert data["total_registered_cameras"] >= 796
        assert data["geolocated_cameras"] >= 796
        assert "tracked_in_scheduler" in data
        assert "live_cameras" in data
        assert "error_breakdown" in data
        assert "cookie" not in str(data).lower()
        assert "token" not in str(data).lower()


@pytest.mark.asyncio
async def test_worker_leader_lock_prevents_duplicate_workers():
    """
    Verifies R01: Only the leader instance acquires the singleton background worker lock,
    preventing duplicate camera fetch loops across multiple worker processes.
    """
    from backend.app.main import acquire_or_renew_worker_leader_lock

    redis = get_redis_client()
    try:
        await redis.delete("safepath:leader:test_worker_lock")
        leader_ok = await acquire_or_renew_worker_leader_lock(
            redis, "test_worker_lock", "worker-instance-1", ttl_seconds=30
        )
        follower_ok = await acquire_or_renew_worker_leader_lock(
            redis, "test_worker_lock", "worker-instance-2", ttl_seconds=30
        )
        renew_ok = await acquire_or_renew_worker_leader_lock(
            redis, "test_worker_lock", "worker-instance-1", ttl_seconds=30
        )
        assert leader_ok is True
        assert follower_ok is False
        assert renew_ok is True
    finally:
        await redis.delete("safepath:leader:test_worker_lock")
        await redis.aclose()


def test_liveness_and_readiness_endpoints():
    """Verifies R10: /api/v1/live and /api/v1/ready return structured probe responses."""
    with TestClient(app) as client:
        live_res = client.get("/api/v1/live")
        assert live_res.status_code == 200
        assert live_res.json()["status"] == "alive"

        ready_res = client.get("/api/v1/ready")
        assert ready_res.status_code == 200
        ready_data = ready_res.json()
        assert ready_data["ready"] is True
        assert ready_data["database"] == "healthy"
        assert ready_data["redis"] == "healthy"

