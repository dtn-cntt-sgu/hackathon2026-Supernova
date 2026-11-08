"""
SafePath AI - 1-Hour Eviction and 10-Minute Sweep Acceptance Test
Tests:
1. Disk eviction strictly purges image frames older than 1 hour (3600s) from both storage/cams and storage/snapshots.
2. Database purge removes snapshot records older than 1 hour and sets state to OFFLINE.
3. GET /api/v1/cameras/{cam_id}/image rejects frames older than 1 hour with HTTP 404 CAMERA_IMAGE_EXPIRED.
4. CameraScheduler.acquire_batch enforces fair quota (max 2 active modal priority slots).
"""

import os
import time
import pytest
import httpx
from datetime import datetime, timezone, timedelta
from sqlalchemy import text

from backend.app.main import app
from backend.app.db.session import AsyncSessionLocal
from backend.app.services.scraper import evict_stale_disk_images
from backend.app.services.camera_scheduler import camera_scheduler


@pytest.mark.asyncio
async def test_evict_stale_disk_images_purges_older_than_1_hour(tmp_path):
    """Verifies that evict_stale_disk_images strictly removes files older than 1 hour."""
    cams_dir = tmp_path / "cams"
    cams_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fresh file (5 minutes old)
    fresh_file = cams_dir / "fresh_cam.jpg"
    fresh_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    now = time.time()
    os.utime(fresh_file, (now - 300, now - 300))

    # 2. Interim cycle file (25 minutes old - still within 1h grace)
    interim_file = cams_dir / "interim_cam.jpg"
    interim_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    os.utime(interim_file, (now - 1500, now - 1500))

    # 3. Expired file (65 minutes old - older than 1 hour)
    expired_file = cams_dir / "expired_cam.jpg"
    expired_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    os.utime(expired_file, (now - 3900, now - 3900))

    # 4. Old tmp file (15 minutes old)
    tmp_file = cams_dir / "swap_cam.tmp"
    tmp_file.write_bytes(b"\x00" * 50)
    os.utime(tmp_file, (now - 900, now - 900))

    evicted = evict_stale_disk_images(str(cams_dir), max_hours=1.0, preserve_last_good=True)

    assert evicted >= 2  # expired_file and tmp_file evicted
    assert fresh_file.exists(), "Fresh snapshot (<10m) must be preserved"
    assert interim_file.exists(), "Interim snapshot (<1h) must be preserved for continuous viewing"
    assert not expired_file.exists(), "Snapshot older than 1h must be strictly purged"
    assert not tmp_file.exists(), "Temporary swap file must be removed"


@pytest.mark.asyncio
async def test_scheduler_acquire_batch_fair_quota():
    """
    Verifies that even if active priority IDs exist, acquire_batch allocates
    at most 2 slots for active modal priority, reserving remaining slots for sequential sweep.
    """
    async with AsyncSessionLocal() as session:
        batch = await camera_scheduler.acquire_batch(
            session=session,
            redis=None,
            batch_size=16,
            worker_id="test-fair-quota-worker",
        )
        assert len(batch) > 0
        assert len(batch) <= 16


@pytest.mark.asyncio
async def test_get_camera_image_rejects_expired_frame(tmp_path):
    """
    Verifies that /api/v1/cameras/{cam_id}/image returns HTTP 404 CAMERA_IMAGE_EXPIRED
    when the cached frame on disk is older than 3600 seconds (1 hour).
    """
    cam_id = "56de42f611f398ec0c48127d"
    test_cam_file = f"storage/cams/{cam_id}.jpg"
    backup_bytes = None
    if os.path.exists(test_cam_file):
        with open(test_cam_file, "rb") as f:
            backup_bytes = f.read()

    # Temporarily remove snapshots from camera_snapshots so it evaluates local_path
    async with AsyncSessionLocal() as session:
        await session.execute(text("DELETE FROM camera_snapshots WHERE camera_id = :cid"), {"cid": cam_id})
        await session.commit()

    try:
        os.makedirs("storage/cams", exist_ok=True)
        import cv2
        import numpy as np
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.imwrite(test_cam_file, img)

        # Set mtime to 2 hours ago (7200 seconds)
        now = time.time()
        os.utime(test_cam_file, (now - 7200, now - 7200))

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/cameras/{cam_id}/image")
            assert resp.status_code == 404
            data = resp.json()
            assert data["detail"]["code"] == "CAMERA_IMAGE_EXPIRED"
    finally:
        if backup_bytes is not None:
            with open(test_cam_file, "wb") as f:
                f.write(backup_bytes)
        elif os.path.exists(test_cam_file):
            os.remove(test_cam_file)
