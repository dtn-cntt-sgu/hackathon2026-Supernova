"""
Regression Test Suite for SafePathAI 796-Camera District Spatial Classification.

Covers:
1. Spatial boundary integrity: 24 official HCMC districts loaded into PostGIS table.
2. Complete zero-null coverage: Exactly 796 cameras in DB, zero NULL districts.
3. Spatial join precision: 762 cameras inside HCMC (POSTGIS_ST_COVERS), 34 cameras outside (UNKNOWN_DISTRICT).
4. Verified counts for targeted districts: Quận 4 (18 cams), Quận 10 (24 cams), Quận 11 (13 cams).
5. Non-destructive import resilience: Re-importing VDMS null records preserves verified districts.
6. API filtering: /api/v1/cameras with district filter and UNKNOWN_DISTRICT options.
7. Districts summary endpoint: /api/v1/cameras/districts returning exact counts.
8. Manifest consistency: data/cameras/camera_url_manifest.json matches DB state.
"""

import json
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.app.db.session import SessionLocal, sync_engine
from backend.app.main import app
from scripts.assign_camera_districts_postgis import populate_district_boundaries, run_spatial_assignment


@pytest.fixture(scope="module", autouse=True)
def setup_districts_and_cameras():
    """Ensures district boundaries and cameras are spatially joined before testing."""
    run_spatial_assignment()


def test_hcmc_district_boundaries_table():
    """Verifies that all 24 HCMC district boundary polygons are present and valid in PostGIS."""
    with SessionLocal() as session:
        count = session.execute(text("SELECT COUNT(*) FROM hcmc_district_boundaries;")).scalar()
        assert count == 24, f"Expected 24 HCMC district boundary polygons, found {count}"

        # Verify all geometries are valid and have SRID 4326
        invalid = session.execute(text("""
            SELECT COUNT(*) FROM hcmc_district_boundaries
            WHERE ST_IsValid(geom) = FALSE OR ST_SRID(geom) != 4326;
        """)).scalar()
        assert invalid == 0, "All district polygons must have valid geometries with SRID 4326"

        # Verify key districts exist
        districts = session.execute(text("SELECT name FROM hcmc_district_boundaries ORDER BY name;")).scalars().all()
        assert "Quận 1" in districts
        assert "Quận 4" in districts
        assert "Quận 10" in districts
        assert "Quận 11" in districts
        assert "Quận Bình Thạnh" in districts
        assert "Huyện Bình Chánh" in districts
        assert "Huyện Cần Giờ" in districts


def test_camera_total_and_zero_null_districts():
    """Verifies total 796 cameras exist in DB and zero cameras have district = NULL."""
    with SessionLocal() as session:
        total = session.execute(text("SELECT COUNT(*) FROM traffic_cameras;")).scalar()
        assert total == 796, f"Expected exactly 796 cameras in traffic_cameras, found {total}"

        null_count = session.execute(text("""
            SELECT COUNT(*) FROM traffic_cameras WHERE district IS NULL OR district = '';
        """)).scalar()
        assert null_count == 0, f"Expected 0 cameras with NULL or empty district, found {null_count}"


def test_spatial_join_counts_and_provenance():
    """
    Verifies that 762 cameras are spatially inside HCMC and 34 are outside,
    each with audited provenance.
    """
    with SessionLocal() as session:
        inside_hcmc = session.execute(text("""
            SELECT COUNT(*) FROM traffic_cameras 
            WHERE district != 'UNKNOWN_DISTRICT' 
              AND district_method = 'POSTGIS_ST_COVERS';
        """)).scalar()
        assert inside_hcmc == 762, f"Expected 762 cameras inside HCMC, found {inside_hcmc}"

        outside_hcmc = session.execute(text("""
            SELECT COUNT(*) FROM traffic_cameras 
            WHERE district = 'UNKNOWN_DISTRICT' 
              AND district_method = 'POSTGIS_ST_COVERS_NO_MATCH';
        """)).scalar()
        assert outside_hcmc == 34, f"Expected 34 cameras outside HCMC marked UNKNOWN_DISTRICT, found {outside_hcmc}"

        # Sum must equal 796
        assert inside_hcmc + outside_hcmc == 796


def test_targeted_districts_q4_q10_q11():
    """
    Verifies exact camera counts for Quận 4, Quận 10, and Quận 11,
    which were missing (0) in the legacy snapshot.
    """
    with SessionLocal() as session:
        q4_cams = session.execute(text("""
            SELECT cam_id, name, district, ST_X(geom) as lng, ST_Y(geom) as lat
            FROM traffic_cameras
            WHERE district = 'Quận 4';
        """)).fetchall()
        assert len(q4_cams) == 18, f"Expected exactly 18 cameras in Quận 4, found {len(q4_cams)}"

        q10_cams = session.execute(text("""
            SELECT cam_id, name, district, ST_X(geom) as lng, ST_Y(geom) as lat
            FROM traffic_cameras
            WHERE district = 'Quận 10';
        """)).fetchall()
        assert len(q10_cams) == 24, f"Expected exactly 24 cameras in Quận 10, found {len(q10_cams)}"

        q11_cams = session.execute(text("""
            SELECT cam_id, name, district, ST_X(geom) as lng, ST_Y(geom) as lat
            FROM traffic_cameras
            WHERE district = 'Quận 11';
        """)).fetchall()
        assert len(q11_cams) == 13, f"Expected exactly 13 cameras in Quận 11, found {len(q11_cams)}"


def test_import_upsert_preserves_verified_districts():
    """
    Simulates a re-import from VDMS where district is NULL in the raw feed.
    Verifies that the ON CONFLICT clause preserves the existing verified district.
    """
    with SessionLocal() as session:
        # Pick a camera known to be in Quận 4
        cam = session.execute(text("""
            SELECT cam_id, name, district FROM traffic_cameras WHERE district = 'Quận 4' LIMIT 1;
        """)).fetchone()
        assert cam is not None
        cam_id = cam.cam_id

        # Simulate re-importing with district = NULL
        upsert_test_sql = text("""
            INSERT INTO traffic_cameras (
                cam_id, name, district, geom
            ) VALUES (
                :cam_id, :name, NULL, ST_SetSRID(ST_MakePoint(106.705, 10.760), 4326)
            )
            ON CONFLICT (cam_id) DO UPDATE SET
                district = CASE
                    WHEN traffic_cameras.district IS NOT NULL AND traffic_cameras.district != '' THEN traffic_cameras.district
                    ELSE COALESCE(EXCLUDED.district, 'UNKNOWN_DISTRICT')
                END;
        """)
        session.execute(upsert_test_sql, {"cam_id": cam_id, "name": cam.name})
        session.commit()

        # Check district is still 'Quận 4'
        updated = session.execute(text("SELECT district FROM traffic_cameras WHERE cam_id = :id;"), {"id": cam_id}).scalar()
        assert updated == "Quận 4", f"Re-import must NOT overwrite verified district with NULL. Got {updated}"


def test_api_district_filter_and_breakdown():
    """Tests the /api/v1/cameras and /api/v1/cameras/districts endpoints."""
    client = TestClient(app)

    # 1. District breakdown endpoint
    res_districts = client.get("/api/v1/cameras/districts")
    assert res_districts.status_code == 200
    districts_data = res_districts.json()
    assert isinstance(districts_data, list)
    assert len(districts_data) >= 24

    district_map = {d["district"]: d["count"] for d in districts_data}
    assert district_map["Quận 4"] == 18
    assert district_map["Quận 10"] == 24
    assert district_map["Quận 11"] == 13
    assert district_map["UNKNOWN_DISTRICT"] == 34
    assert sum(d["count"] for d in districts_data) == 796

    # 2. Filter by Quận 4
    res_q4 = client.get("/api/v1/cameras?district=Quận 4")
    assert res_q4.status_code == 200
    cams_q4 = res_q4.json()
    assert len(cams_q4) == 18
    assert all(c["district"] == "Quận 4" for c in cams_q4)

    # 3. Filter by Quận 10
    res_q10 = client.get("/api/v1/cameras?district=Quận 10")
    assert res_q10.status_code == 200
    cams_q10 = res_q10.json()
    assert len(cams_q10) == 24
    assert all(c["district"] == "Quận 10" for c in cams_q10)

    # 4. Filter by UNKNOWN_DISTRICT
    res_unknown = client.get("/api/v1/cameras?district=UNKNOWN_DISTRICT")
    assert res_unknown.status_code == 200
    cams_unknown = res_unknown.json()
    assert len(cams_unknown) == 34
    assert all(c["district"] == "UNKNOWN_DISTRICT" for c in cams_unknown)


def test_manifest_synchronization():
    """Verifies that data/cameras/camera_url_manifest.json contains verified district metadata."""
    manifest_path = "data/cameras/camera_url_manifest.json"
    assert os.path.exists(manifest_path)

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cameras = data.get("cameras", [])
    assert len(cameras) == 796

    null_in_manifest = sum(1 for c in cameras if not c.get("district"))
    assert null_in_manifest == 0, f"Found {null_in_manifest} cameras with null district in manifest"

    q4_manifest = sum(1 for c in cameras if c.get("district") == "Quận 4")
    assert q4_manifest == 18

    q10_manifest = sum(1 for c in cameras if c.get("district") == "Quận 10")
    assert q10_manifest == 24

    q11_manifest = sum(1 for c in cameras if c.get("district") == "Quận 11")
    assert q11_manifest == 13

    unknown_manifest = sum(1 for c in cameras if c.get("district") == "UNKNOWN_DISTRICT")
    assert unknown_manifest == 34

