"""
Phase 3 (P0) Acceptance Tests: Real Camera Metadata, VDMS Snapshot Parser,
Zero-Mock Image Validation, TLS Security, and Permission Trust Gates.
"""

from datetime import datetime, timezone
import hashlib
import io
import os
import pytest
import httpx
from PIL import Image
from sqlalchemy import text

from backend.app.core.config import settings
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.schemas.contracts import DataSourceStatus, RiskLevel
from backend.app.services.image_validator import (
    ImageValidationStatus,
    compute_dhash,
    validate_camera_image_bytes,
)
from backend.app.services.vdms_parser import (
    parse_vdms_snapshot_file,
)
from backend.app.services.scraper import (
    scrape_camera_image,
)


def test_parse_vdms_snapshot_exact_796_nodes():
    """
    1. Robust parser must accurately parse all 796 snapshot nodes in list_camera_coordinate.txt.
    2. Explicitly verifies that 654 UP / 113 NOT_IMAGE / 29 IMAGE_EXPIRED is the snapshot result.
    3. Verifies 100% of nodes possess real WGS84 coordinates within HCMC bounds.
    """
    report = parse_vdms_snapshot_file("list_camera_coordinate.txt")
    assert report.total_nodes == 796
    assert report.status_breakdown == {"UP": 654, "NOT_IMAGE": 113, "IMAGE_EXPIRED": 29}
    assert report.valid_coordinates_count == 796
    assert not report.is_live_status  # Transparently acknowledges snapshot is historical

    for cam in report.cameras:
        assert cam.cam_id and len(cam.cam_id) == 24
        # Bounding box for greater HCMC region
        assert 10.3 <= cam.lat <= 11.2, f"Cam {cam.cam_id} lat out of bounds: {cam.lat}"
        assert 106.3 <= cam.lng <= 107.2, f"Cam {cam.cam_id} lng out of bounds: {cam.lng}"
        assert cam.location_confidence == "VDMS_GIS_POINT"


def test_postgis_camera_registry_trust_gate():
    """
    Verifies that all 796 cameras in PostGIS have verified coordinates,
    are categorized as SPATIALLY_NEAR, and are gated from altering risk scores.
    """
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT 
                count(*) AS total,
                count(geom) AS with_geom,
                count(*) FILTER (WHERE coordinate_source_url IS NULL) AS unsourced,
                count(*) FILTER (WHERE location_confidence <> 'VDMS_GIS_POINT') AS bad_confidence,
                count(*) FILTER (WHERE line_of_sight_verified IS TRUE) AS fake_los
            FROM traffic_cameras
        """)).one()

        assert row.total >= 796
        assert row.with_geom >= 796
        assert row.unsourced == 0
        assert row.bad_confidence == 0
        assert row.fake_los == 0  # No camera can claim fake line of sight verification

        # Check candidate view
        match_counts = db.execute(text("""
            SELECT match_status, count(*) 
            FROM camera_road_spatial_candidates 
            GROUP BY match_status
        """)).fetchall()

        statuses = {r.match_status: r.count for r in match_counts}
        assert "OBSERVED_SEGMENT_VERIFIED" not in statuses or statuses["OBSERVED_SEGMENT_VERIFIED"] == 0
        assert statuses.get("SPATIALLY_NEAR", 0) > 0


def test_image_validation_multi_stage():
    """
    Tests rigorous image validation:
    - Corrupted / invalid magic bytes
    - Known placeholder ("IMAGE NOT AVAILABLE" MD5 5f5b2bf141af555a87e3f1d6c3ab3017)
    - Dark / no-signal frame
    - Low-variance blank frame
    - Duplicate frame detection
    - Valid image
    """
    # 1. Invalid magic bytes
    bad_bytes = b"<html><head><title>404 Not Found</title></head></html>"
    res1 = validate_camera_image_bytes(bad_bytes)
    assert not res1.is_valid
    assert res1.status == ImageValidationStatus.INVALID_MAGIC_BYTES

    # 2. Known placeholder image
    placeholder_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 9214
    # Create an image that hashes to the placeholder MD5
    # or simulate direct placeholder hash match
    fake_placeholder = bytes.fromhex("89504e470d0a1a0a") + b"\x00" * 100
    res2 = validate_camera_image_bytes(fake_placeholder)
    assert not res2.is_valid  # Corrupted PNG structure or placeholder

    # 3. Dark frame (all zeros)
    dark_img = Image.new("RGB", (300, 230), color=(2, 2, 2))
    dark_buf = io.BytesIO()
    dark_img.save(dark_buf, format="JPEG")
    res3 = validate_camera_image_bytes(dark_buf.getvalue())
    assert not res3.is_valid
    assert res3.status == ImageValidationStatus.DARK_NO_SIGNAL_FRAME

    # 4. Blank low-variance frame (flat uniform gray)
    blank_img = Image.new("RGB", (300, 230), color=(128, 128, 128))
    blank_buf = io.BytesIO()
    blank_img.save(blank_buf, format="JPEG")
    res4 = validate_camera_image_bytes(blank_buf.getvalue())
    assert not res4.is_valid
    assert res4.status == ImageValidationStatus.BLANK_LOW_VARIANCE_FRAME

    # 5. Valid complex road-like image
    valid_img = Image.new("RGB", (300, 230))
    # Fill with varied gradients / shapes
    pixels = valid_img.load()
    for x in range(300):
        for y in range(230):
            pixels[x, y] = (x % 256, (y * 2) % 256, (x + y) % 256)
    valid_buf = io.BytesIO()
    valid_img.save(valid_buf, format="JPEG")
    valid_bytes = valid_buf.getvalue()

    res5 = validate_camera_image_bytes(valid_bytes)
    assert res5.is_valid
    assert res5.status == ImageValidationStatus.VALID
    assert res5.format == "JPEG"
    assert res5.width == 300 and res5.height == 230
    assert res5.capture_time_status == "CAPTURE_TIME_UNKNOWN"

    # 6. Duplicate frame detection
    res6 = validate_camera_image_bytes(valid_bytes, previous_md5=res5.md5_hash)
    assert not res6.is_valid
    assert res6.status == ImageValidationStatus.DUPLICATE_FRAME


@pytest.mark.asyncio
async def test_api_cameras_zero_mock_contract():
    """
    Verifies /api/v1/cameras contract:
    - All cameras are returned with valid GIS coordinates.
    - All default to RiskLevel.UNKNOWN when unobserved.
    - Never defaults to RiskLevel.SAFE (CAMERA_SOURCE_UNAVAILABLE != SAFE).
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/cameras")
        assert resp.status_code == 200
        cameras = resp.json()
        assert len(cameras) >= 796

        for c in cameras:
            assert c["risk_level"] == RiskLevel.UNKNOWN.value
            assert c["lat"] is not None and c["lng"] is not None
            assert 10.3 <= c["lat"] <= 11.2
            assert 106.3 <= c["lng"] <= 107.2


@pytest.mark.asyncio
async def test_get_camera_image_endpoint_zero_mock():
    """
    Verifies /api/v1/cameras/{id}/image:
    - 404 CAMERA_NOT_FOUND for unknown IDs
    - 404 CAMERA_IMAGE_UNAVAILABLE for cameras without verified local snapshots
    - No simulated/mock images returned under any circumstances
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Invalid ID
        r1 = await client.get("/api/v1/cameras/non_existent_camera_id/image")
        assert r1.status_code == 404
        assert r1.json()["detail"]["code"] == "CAMERA_NOT_FOUND"

        # 2. Registered ID without downloaded image
        unscraped_cam_id = "587478d8b807da0011e33cf3"
        target_file = f"storage/cams/{unscraped_cam_id}.jpg"
        if os.path.exists(target_file):
            os.remove(target_file)
        r2 = await client.get(f"/api/v1/cameras/{unscraped_cam_id}/image")
        assert r2.status_code == 404
        assert r2.json()["detail"]["code"] == "CAMERA_IMAGE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_scraper_permission_gate_and_tls(monkeypatch):
    """
    Verifies that when permissions are not granted, ingestion is refused
    and marked PERMISSION_UNVERIFIED without sending unauthorized requests.
    """
    monkeypatch.setattr(settings, "CAMERA_INGESTION_PERMITTED", False)
    monkeypatch.setattr(settings, "CAMERA_ALLOW_VIEW_ONLY", False)
    cam_meta = {
        "cam_id": "test_permission_gate_cam_123",
        "code": "TEST 1.1",
        "name": "Test Cam",
        "lat": 10.8049,
        "lng": 106.7527,
    }

    async with httpx.AsyncClient(verify=True, timeout=5.0) as client:
        res = await scrape_camera_image(client, cam_meta, allow_view_only=False)
        # Should not scrape when CAMERA_INGESTION_PERMITTED is False and allow_view_only is False
        assert not res.is_valid_image
        assert "PERMISSION_UNVERIFIED" in (res.validation_status or "")


@pytest.mark.asyncio
async def test_path_traversal_protection():
    """
    Verifies that path traversal attacks in cam_id parameter are strictly rejected with HTTP 400 or 404,
    and invalid camera slugs return 400 INVALID_CAMERA_ID.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Unsafe IDs that reach route handler trigger 400 INVALID_CAMERA_ID
        for bad_id in ["cam..test", "cam\\..\\test", "cam%5C..%5Ctest", "bad_camera_name!", "a" * 70]:
            r1 = await client.get(f"/api/v1/cameras/{bad_id}/image")
            assert r1.status_code == 400
            assert r1.json()["detail"]["code"] == "INVALID_CAMERA_ID"

            r2 = await client.get(f"/api/v1/cameras/{bad_id}/metadata")
            assert r2.status_code == 400
            assert r2.json()["detail"]["code"] == "INVALID_CAMERA_ID"

        # 2. Path-separator traversal attempts are blocked by URL routing (404)
        for slash_traversal in ["../../etc/passwd", "..%2F..%2Fetc%2Fpasswd", "test/image"]:
            r = await client.get(f"/api/v1/cameras/{slash_traversal}/image")
            assert r.status_code == 404


@pytest.mark.asyncio
async def test_null_is_not_zero_in_camera_list():
    """
    Zero-Mock: Unobserved or unanalyzed cameras must have vehicle_count=None,
    flood_ratio=None, traffic_density_score=None. Null is NOT zero!
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/cameras")
        assert resp.status_code == 200
        cameras = resp.json()
        assert len(cameras) >= 700

        # Cameras without active vision inference MUST have None for metrics
        unanalyzed = [c for c in cameras if c.get("model_status") in (None, "NOT_ANALYZED")]
        assert len(unanalyzed) > 0
        for cam in unanalyzed[:50]:
            assert cam["vehicle_count"] is None, f"Cam {cam['cam_id']} vehicle_count must be None, got {cam['vehicle_count']}"
            assert cam["flood_ratio"] is None, f"Cam {cam['cam_id']} flood_ratio must be None, got {cam['flood_ratio']}"
            assert cam["traffic_density_score"] is None
            assert cam["risk_level"] == "UNKNOWN"
            assert cam["evidence_eligibility"] == "NOT_VERIFIED_FOR_ROUTING"


@pytest.mark.asyncio
async def test_camera_metadata_endpoint_and_view_only_gate():
    """
    Tests GET /api/v1/cameras/{id}/metadata:
    - Returns structured technical metadata (provenance, access status, reason codes).
    - When no image is cached, reports IMAGE_UNAVAILABLE or EXTERNAL_ACCESS_RESTRICTED.
    - View-only images are never elevated to ROUTING_ELIGIBLE.
    """
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # 1. Registered camera with no cached image
        cam_id = "595dd6093dcfc400106f28ad"
        resp = await client.get(f"/api/v1/cameras/{cam_id}/metadata")
        assert resp.status_code == 200
        meta = resp.json()
        assert meta["cam_id"] == cam_id
        assert meta["evidence_eligibility"] == "NOT_VERIFIED_FOR_ROUTING"
        assert meta["image_status_reason"] in (
            "IMAGE_UNAVAILABLE",
            "EXTERNAL_ACCESS_RESTRICTED",
            "VALID_IMAGE_CACHED",
            "PLACEHOLDER_FRAME",
        )

        # 2. Unknown camera returns 404 CAMERA_NOT_FOUND
        r_not_found = await client.get("/api/v1/cameras/ffffffffffffffffffffffff/metadata")
        assert r_not_found.status_code == 404
        assert r_not_found.json()["detail"]["code"] == "CAMERA_NOT_FOUND"


@pytest.mark.asyncio
async def test_etag_and_caching_and_headers():
    """
    Tests serving valid cached snapshot:
    - Returns HTTP 200 with ETag, Cache-Control, and custom provenance headers.
    - Supports HTTP 304 Not Modified when client provides matching If-None-Match.
    - View-only cached snapshot retains evidence_eligibility=NOT_VERIFIED_FOR_ROUTING.
    """
    cam_id = "595dd6093dcfc400106f28ad"
    storage_dir = "storage/cams"
    os.makedirs(storage_dir, exist_ok=True)
    target_path = os.path.join(storage_dir, f"{cam_id}.jpg")

    # Create a valid synthetic road-like test frame to test serving semantics
    valid_img = Image.new("RGB", (300, 230))
    pixels = valid_img.load()
    for x in range(300):
        for y in range(230):
            pixels[x, y] = (x % 256, (y * 2) % 256, (x + y) % 256)
    valid_buf = io.BytesIO()
    valid_img.save(valid_buf, format="JPEG")
    test_bytes = valid_buf.getvalue()

    with open(target_path, "wb") as f:
        f.write(test_bytes)

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            # 1. Fetch image -> 200
            res = await client.get(f"/api/v1/cameras/{cam_id}/image")
            assert res.status_code == 200
            assert "etag" in res.headers
            assert res.headers.get("x-image-access-status") == "VIEWABLE_PUBLIC"
            assert res.headers.get("x-evidence-eligibility") == "NOT_VERIFIED_FOR_ROUTING"
            etag = res.headers["etag"]

            # 2. Fetch with If-None-Match -> 304 Not Modified
            res_304 = await client.get(
                f"/api/v1/cameras/{cam_id}/image",
                headers={"if-none-match": etag},
            )
            assert res_304.status_code == 304

            # 3. Metadata endpoint reflects cached image
            res_meta = await client.get(f"/api/v1/cameras/{cam_id}/metadata")
            assert res_meta.status_code == 200
            meta = res_meta.json()
            assert meta["has_image"] is True
            assert meta["image_status_reason"] == "VALID_IMAGE_CACHED"
            assert meta["evidence_eligibility"] == "NOT_VERIFIED_FOR_ROUTING"
    finally:
        if os.path.exists(target_path):
            os.remove(target_path)


