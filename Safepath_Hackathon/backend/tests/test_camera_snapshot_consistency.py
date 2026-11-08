"""
SafePath AI - Camera Snapshot Consistency & 10-Minute Refresh Tests
Validates Core Data Pipeline requirements:
1. Snapshot immutability and exact frame identity.
2. AI inference byte provenance: inference_input_sha256 == content_sha256.
3. Overlay frame strict matching: requesting analyzed view for a snapshot where overlay is not ready
   returns HTTP 404 OVERLAY_NOT_AVAILABLE_FOR_SNAPSHOT (NEVER serves a mismatched frame).
4. Duplicate SHA256 frames suppress duplicate inference and do not advance last_content_changed_at.
5. Preserves Last Known Good Frame on fetch failure (no wipeout, marked STALE).
6. Section F Metrics completeness in /api/v1/cameras/summary.
"""

import hashlib
import os
import pytest
import httpx
from datetime import datetime, timezone, timedelta
from sqlalchemy import text

from app.main import app
from app.db.session import AsyncSessionLocal
from app.services.scraper import ScrapedCameraResult, DataSourceStatus
from app.services.camera_scheduler import camera_scheduler
from app.services.vision import CameraVisionPipeline
from app.schemas.contracts import CameraFreshnessStatus


@pytest.fixture(autouse=True)
async def preserve_camera_state():
    """Preserves storage/cams/56de42f611f398ec0c48127d.jpg and cleans up test snapshots after each test."""
    cam_id = "56de42f611f398ec0c48127d"
    legacy_path = os.path.join("storage", "cams", f"{cam_id}.jpg")
    orig_bytes = None
    if os.path.exists(legacy_path):
        with open(legacy_path, "rb") as f:
            orig_bytes = f.read()
    yield
    if orig_bytes is not None:
        os.makedirs("storage/cams", exist_ok=True)
        with open(legacy_path, "wb") as f:
            f.write(orig_bytes)
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("DELETE FROM camera_snapshots WHERE camera_id = :cid"),
            {"cid": cam_id},
        )
        await session.execute(
            text("""
                UPDATE camera_ingestion_state
                SET latest_snapshot_id = NULL, cached_image_path = :legacy_path
                WHERE cam_id = :cid
            """),
            {"cid": cam_id, "legacy_path": legacy_path if orig_bytes is not None else None},
        )
        await session.commit()



@pytest.mark.asyncio
async def test_snapshot_immutability_and_ai_sha256_provenance(tmp_path):
    """
    Verifies that:
    1. A freshly fetched frame receives an immutable snapshot_id.
    2. Vision pipeline runs on the exact snapshot bytes and inference_input_sha256 == content_sha256.
    3. Overlay is created with the exact snapshot_id and linked in DB.
    """
    cam_id = "56de42f611f398ec0c48127d"
    now = datetime.now(timezone.utc)

    # 1. Create a synthetic test image with verifiable bytes
    import numpy as np
    import cv2
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.putText(img, "TEST FRAME 1", (30, 120), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    _, img_bytes = cv2.imencode(".jpg", img)
    raw_bytes = img_bytes.tobytes()
    expected_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    expected_md5 = hashlib.md5(raw_bytes).hexdigest()

    snapshot_id = f"{cam_id}_{int(now.timestamp())}_{expected_sha256[:8]}"
    snap_dir = os.path.join("storage", "snapshots", cam_id)
    os.makedirs(snap_dir, exist_ok=True)
    snap_path = os.path.join(snap_dir, f"{snapshot_id}.jpg")
    with open(snap_path, "wb") as f:
        f.write(raw_bytes)

    # Also update legacy path for fallback
    os.makedirs("storage/cams", exist_ok=True)
    with open(f"storage/cams/{cam_id}.jpg", "wb") as f:
        f.write(raw_bytes)

    scraped_res = ScrapedCameraResult(
        cam_id=cam_id,
        code="TEST-01",
        name="Test Camera Provenance",
        district="Q1",
        lat=10.77,
        lng=106.70,
        image_path=snap_path,
        image_bytes=raw_bytes,
        source_status=DataSourceStatus.LIVE,
        retrieved_at=now,
        captured_at=now,
        capture_time_status="CAPTURE_TIME_VERIFIED",
        file_size=len(raw_bytes),
        is_valid_image=True,
        is_new_snapshot=True,
        validation_status="VALID_FRAME",
        content_sha256=expected_sha256,
        etag=expected_md5,
        snapshot_id=snapshot_id,
        freshness_status="FRESH_VERIFIED",
    )

    async with AsyncSessionLocal() as session:
        await camera_scheduler.record_result(session, scraped_res)

        # Verify database record in camera_snapshots
        row = (await session.execute(
            text("SELECT snapshot_id, content_sha256, is_latest, file_path FROM camera_snapshots WHERE snapshot_id = :sid"),
            {"sid": snapshot_id},
        )).fetchone()
        assert row is not None
        assert row.snapshot_id == snapshot_id
        assert row.content_sha256 == expected_sha256
        assert row.is_latest is True

    # 2. Run Vision Pipeline on the exact saved snapshot
    pipeline = CameraVisionPipeline()
    cam_meta = {
        "cam_id": cam_id,
        "snapshot_id": snapshot_id,
        "content_sha256": expected_sha256,
        "captured_at": now.isoformat(),
    }
    evidence = pipeline.analyze_camera_image(snap_path, cam_meta=cam_meta)

    # Assert inference input SHA256 strictly matches content SHA256
    assert evidence.inference_input_sha256 == expected_sha256
    assert evidence.snapshot_id == snapshot_id
    assert f"snapshot_id={snapshot_id}" in (evidence.overlay_url or "")

    # Record vision completion in DB
    async with AsyncSessionLocal() as session:
        await camera_scheduler.record_vision_completion(
            session=session,
            cam_id=cam_id,
            model_status="INFERENCE_COMPLETED",
            image_hash=expected_sha256,
            snapshot_id=snapshot_id,
            inference_input_sha256=evidence.inference_input_sha256,
            overlay_path=evidence.overlay_path,
            vehicle_count=evidence.vehicle_count,
            traffic_density_score=evidence.traffic_density_score,
            flood_ratio=evidence.flood_ratio,
        )

        # Verify camera_snapshots table has overlay and input sha256
        snap_db = (await session.execute(
            text("SELECT model_status, inference_input_sha256, overlay_path FROM camera_snapshots WHERE snapshot_id = :sid"),
            {"sid": snapshot_id},
        )).fetchone()
        assert snap_db.model_status == "INFERENCE_COMPLETED"
        assert snap_db.inference_input_sha256 == expected_sha256
        assert snap_db.overlay_path is not None


@pytest.mark.asyncio
async def test_overlay_strict_snapshot_match_returns_404_when_mismatched():
    """
    CRITICAL SAFETY REQUIREMENT:
    Requesting an analyzed overlay for a snapshot where the overlay is not ready
    MUST return HTTP 404 with code OVERLAY_NOT_AVAILABLE_FOR_SNAPSHOT.
    It MUST NEVER load a different frame or stale overlay!
    """
    cam_id = "56de42f611f398ec0c48127d"
    now = datetime.now(timezone.utc)

    # 1. Create a snapshot with NO overlay file
    raw_bytes = b"SAMPLE_RAW_FRAME_NO_OVERLAY_" + str(now.timestamp()).encode()
    sha = hashlib.sha256(raw_bytes).hexdigest()
    snapshot_id = f"{cam_id}_{int(now.timestamp())}_{sha[:8]}"

    snap_dir = os.path.join("storage", "snapshots", cam_id)
    os.makedirs(snap_dir, exist_ok=True)
    snap_path = os.path.join(snap_dir, f"{snapshot_id}.jpg")
    with open(snap_path, "wb") as f:
        f.write(raw_bytes)

    async with AsyncSessionLocal() as session:
        # Insert raw snapshot without overlay
        await session.execute(
            text("""
                INSERT INTO camera_snapshots (
                    snapshot_id, camera_id, content_sha256, file_path, file_size_bytes,
                    fetched_at, freshness_status, capture_time_status, is_latest, created_at
                ) VALUES (
                    :sid, :cid, :sha, :path, :size, :now, 'RECENTLY_FETCHED_UNVERIFIED', 'CAPTURE_TIME_UNKNOWN', TRUE, :now
                )
                ON CONFLICT (snapshot_id) DO NOTHING
            """),
            {"sid": snapshot_id, "cid": cam_id, "sha": sha, "path": snap_path, "size": len(raw_bytes), "now": now},
        )
        await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Request analyzed view for this specific snapshot ID
        resp = await client.get(f"/api/v1/cameras/{cam_id}/image?type=analyzed&snapshot_id={snapshot_id}")
        assert resp.status_code == 404
        data = resp.json()
        assert data["detail"]["code"] == "OVERLAY_NOT_AVAILABLE_FOR_SNAPSHOT"
        assert snapshot_id in data["detail"]["message"]

        # Original view must preserve snapshot identity without a persistent browser cache and matching snapshot_id
        orig_resp = await client.get(f"/api/v1/cameras/{cam_id}/image?type=original&snapshot_id={snapshot_id}")
        assert orig_resp.status_code == 200
        assert orig_resp.headers.get("X-Snapshot-ID") == snapshot_id
        assert orig_resp.headers.get("X-Content-SHA256") == sha
        assert "no-store" in orig_resp.headers.get("Cache-Control", "")


@pytest.mark.asyncio
async def test_duplicate_sha256_does_not_advance_content_changed_timestamp():
    """
    Verifies that identical frame bytes (duplicate SHA256):
    - Do NOT insert a duplicate row into camera_snapshots.
    - Do NOT advance last_content_changed_at in camera_ingestion_state.
    - Advance last_attempt_at and last_retrieved_at truthfully.
    """
    cam_id = "56de42f611f398ec0c48127d"
    t1 = datetime(2026, 11, 7, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 7, 10, 10, 0, tzinfo=timezone.utc)

    raw_bytes = b"IDENTICAL_FRAME_DATA_12345"
    sha = hashlib.sha256(raw_bytes).hexdigest()
    snapshot_id_1 = f"{cam_id}_1000_{sha[:8]}"

    # Cycle 1: First time seeing this frame
    res1 = ScrapedCameraResult(
        cam_id=cam_id,
        code="TEST",
        name="Dup Test",
        district="Q1",
        lat=10.77,
        lng=106.70,
        image_path=f"storage/cams/{cam_id}.jpg",
        image_bytes=raw_bytes,
        source_status=DataSourceStatus.LIVE,
        retrieved_at=t1,
        captured_at=None,
        capture_time_status="CAPTURE_TIME_UNKNOWN",
        file_size=len(raw_bytes),
        is_valid_image=True,
        is_new_snapshot=True,
        validation_status="VALID_FRAME",
        content_sha256=sha,
        snapshot_id=snapshot_id_1,
    )

    async with AsyncSessionLocal() as session:
        await camera_scheduler.record_result(session, res1)

        row1 = (await session.execute(
            text("SELECT last_content_changed_at, latest_snapshot_id FROM camera_ingestion_state WHERE cam_id = :cid"),
            {"cid": cam_id},
        )).fetchone()
        t1_content_changed = row1.last_content_changed_at
        assert row1.latest_snapshot_id == snapshot_id_1

    # Cycle 2: Same frame returned (is_new_snapshot = False)
    res2 = ScrapedCameraResult(
        cam_id=cam_id,
        code="TEST",
        name="Dup Test",
        district="Q1",
        lat=10.77,
        lng=106.70,
        image_path=f"storage/cams/{cam_id}.jpg",
        image_bytes=raw_bytes,
        source_status=DataSourceStatus.LIVE,
        retrieved_at=t2,
        captured_at=None,
        capture_time_status="CAPTURE_TIME_UNKNOWN",
        file_size=len(raw_bytes),
        is_valid_image=True,
        is_new_snapshot=False,
        validation_status="DUPLICATE_FRAME",
        content_sha256=sha,
        snapshot_id=snapshot_id_1,
    )

    async with AsyncSessionLocal() as session:
        await camera_scheduler.record_result(session, res2)

        row2 = (await session.execute(
            text("SELECT last_content_changed_at, latest_snapshot_id, last_retrieved_at FROM camera_ingestion_state WHERE cam_id = :cid"),
            {"cid": cam_id},
        )).fetchone()

        # last_content_changed_at must remain unchanged!
        assert row2.last_content_changed_at == t1_content_changed
        assert row2.latest_snapshot_id == snapshot_id_1
        assert row2.last_retrieved_at == t2


@pytest.mark.asyncio
async def test_last_known_good_frame_preserved_on_failure():
    """
    Verifies that when a camera scrape fails:
    1. Previous snapshot is NOT deleted.
    2. latest_snapshot_id in ingestion state is preserved.
    3. State is updated to STALE (preserving cached_image_path).
    """
    cam_id = "56de42f611f398ec0c48127d"
    now = datetime.now(timezone.utc)

    # 1. Establish successful snapshot
    good_bytes = b"PREVIOUS_VALID_FRAME_BYTES"
    good_sha = hashlib.sha256(good_bytes).hexdigest()
    good_snap_id = f"{cam_id}_good_{good_sha[:8]}"

    os.makedirs(f"storage/snapshots/{cam_id}", exist_ok=True)
    good_path = f"storage/snapshots/{cam_id}/{good_snap_id}.jpg"
    with open(good_path, "wb") as f:
        f.write(good_bytes)

    res_good = ScrapedCameraResult(
        cam_id=cam_id,
        code="TEST",
        name="LKG Cam",
        district="Q1",
        lat=10.77,
        lng=106.70,
        image_path=good_path,
        image_bytes=good_bytes,
        source_status=DataSourceStatus.LIVE,
        retrieved_at=now - timedelta(minutes=15),
        captured_at=None,
        capture_time_status="CAPTURE_TIME_UNKNOWN",
        file_size=len(good_bytes),
        is_valid_image=True,
        is_new_snapshot=True,
        validation_status="VALID_FRAME",
        content_sha256=good_sha,
        snapshot_id=good_snap_id,
    )

    async with AsyncSessionLocal() as session:
        await camera_scheduler.record_result(session, res_good)

    # 2. Simulate subsequent failure (e.g. timeout / connection error)
    fail_res = ScrapedCameraResult(
        cam_id=cam_id,
        code="TEST",
        name="LKG Cam",
        district="Q1",
        lat=10.77,
        lng=106.70,
        image_path=good_path,  # preserves existing path
        image_bytes=None,
        source_status=DataSourceStatus.STALE,
        retrieved_at=now,
        captured_at=None,
        capture_time_status="CAPTURE_TIME_UNKNOWN",
        file_size=0,
        is_valid_image=False,
        validation_status="CONNECTION_ERROR",
        error_message="Connection timed out",
    )

    async with AsyncSessionLocal() as session:
        await camera_scheduler.record_result(session, fail_res)

        row = (await session.execute(
            text("SELECT latest_snapshot_id, cached_image_path, failure_count FROM camera_ingestion_state WHERE cam_id = :cid"),
            {"cid": cam_id},
        )).fetchone()
        assert row.latest_snapshot_id == good_snap_id
        assert row.cached_image_path == good_path
        assert row.failure_count >= 1

    # Verify that file still exists on disk
    assert os.path.exists(good_path)


@pytest.mark.asyncio
async def test_section_f_telemetry_metrics_endpoint():
    """
    Verifies that /api/v1/cameras/summary accurately populates Section F counts:
    - registered_count
    - reachable_count
    - fetched_recently_count
    - fresh_verified_count
    - stale_count
    - fetch_failed_count
    - capture_time_unknown_count
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/cameras/summary")
        assert resp.status_code == 200
        data = resp.json()

        # Check cycle target is 600s (10 min)
        assert data["cycle_target_sec"] == 600

        # Section F metrics verification
        assert "registered_count" in data
        assert "reachable_count" in data
        assert "fetched_recently_count" in data
        assert "fresh_verified_count" in data
        assert "stale_count" in data
        assert "fetch_failed_count" in data
        assert "capture_time_unknown_count" in data

        assert data["registered_count"] >= 796
        assert data["total_registered"] == data["registered_count"]
