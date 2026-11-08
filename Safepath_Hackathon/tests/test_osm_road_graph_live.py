"""Live acceptance: OSM PBF import, PostGIS edge candidates, and camera trust gates.

Run with OSM_ROAD_LIVE_TESTS=1 and live OSRM/PostGIS. No test fixtures are
written to the production road table.
"""
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from backend.app.db.session import SessionLocal
from backend.app.services.routing import _get_osrm_raw_routes, _edge_candidates_for_step
from backend.app.services.risk_engine import calculate_segment_risk
from backend.app.schemas.contracts import CameraEvidence, DataSourceStatus, RiskLevel

PAIRS = [
    (10.7725, 106.6980, 10.8012, 106.7115),
    (10.8185, 106.6588, 10.7725, 106.6980),
    (10.7950, 106.7218, 10.8020, 106.7560),
]


def test_spatially_near_camera_does_not_score_segment():
    segment = {"osm_way_id": 123456789, "edge_index": 7, "street_name": "fixture",
               "length_meters": 72.5, "source_url": "https://www.openstreetmap.org/way/123456789"}
    candidate = CameraEvidence(
        cam_id="fixture", name="fixture", lat=10.78, lng=106.70,
        coordinate_source_url="https://example.org/camera-gps", spatial_match_status="SPATIALLY_NEAR",
        observed_osm_way_id=None, image_url="fixture", vehicle_count=0,
        traffic_density_score=0, flood_ratio=0, risk_level=RiskLevel.UNKNOWN,
        source_status=DataSourceStatus.LIVE, updated_at=datetime.now(timezone.utc),
    )
    result = calculate_segment_risk(segment, [candidate])
    assert result.risk_level == RiskLevel.UNKNOWN and result.risk_score is None
    assert result.length_meters == 72.5 and not result.evidence_cameras
    observed = candidate.model_copy(update={
        "spatial_match_status": "OBSERVED_SEGMENT_VERIFIED",
        "observed_osm_way_id": segment["osm_way_id"],
        "observed_edge_index": segment["edge_index"],
        "view_verification_source_url": "https://example.org/review-fixture",
        "line_of_sight_verified": True,
    })
    low_observation = calculate_segment_risk(segment, [observed])
    assert low_observation.risk_level == RiskLevel.UNKNOWN  # one clear frame is not SAFE


def require_live():
    if os.getenv("OSM_ROAD_LIVE_TESTS") != "1":
        pytest.skip("Set OSM_ROAD_LIVE_TESTS=1 with OSRM and PostGIS running")


def test_osm_source_srid_lengths_indexes_and_camera_gate():
    require_live()
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT count(*) AS n, count(*) FILTER (WHERE source_pbf_md5 IS NULL) AS unsourced,
                   count(*) FILTER (WHERE osm_way_id IN (1001,4004)) AS sample_ids,
                   count(*) FILTER (WHERE ST_SRID(geom) <> 4326 OR length_meters <= 0) AS bad_geom,
                   count(DISTINCT osm_way_id) AS unique_ids
            FROM road_segments
        """)).one()
        assert row.n > 0 and row.unsourced == 0 and row.sample_ids == 0
        assert row.bad_geom == 0 and row.unique_ids == row.n
        edge_row = db.execute(text("""
            SELECT count(*) AS n,
                   count(*) FILTER (WHERE ST_SRID(geom) <> 4326 OR length_meters <= 0) AS invalid
            FROM road_edges
        """)).one()
        assert edge_row.n > row.n and edge_row.invalid == 0
        indexes = db.execute(text("""
            SELECT indexdef FROM pg_indexes WHERE tablename IN ('road_segments','road_edges')
        """)).scalars().all()
        assert sum("USING gist" in definition and "geom" in definition for definition in indexes) >= 2
        assert any("road_edges_pkey" in definition and "UNIQUE" in definition for definition in indexes)
        bad_cameras = db.execute(text("""
            SELECT count(*) FROM traffic_cameras
            WHERE geom IS NOT NULL AND (coordinate_source_url IS NULL OR coordinate_verified_at IS NULL)
        """)).scalar_one()
        assert bad_cameras == 0
        assert db.execute(text("""
            SELECT count(*) FROM camera_road_spatial_candidates
            WHERE match_status = 'OBSERVED_SEGMENT_VERIFIED'
        """)).scalar_one() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("points", PAIRS)
async def test_three_real_osrm_routes_have_sourced_road_candidates(points):
    require_live()
    route = (await _get_osrm_raw_routes(*points))[0]
    steps = [step for leg in route["legs"] for step in leg["steps"]
             if step.get("distance", 0) > 10 and len(step.get("geometry", {}).get("coordinates", [])) >= 2]
    assert steps
    matched = 0
    with SessionLocal() as db:
        for step in steps:
            edges = await _edge_candidates_for_step(step["geometry"]["coordinates"], db)
            assert edges is not None
            pairs = [(e["osm_way_id"], e["edge_index"]) for e in edges]
            assert len(pairs) == len(set(pairs))
            if edges:
                matched += 1
                sourced_count = db.execute(text("""
                    SELECT count(*) FROM road_edges e JOIN road_segments r USING (osm_way_id)
                    WHERE e.osm_way_id = :way_id AND e.edge_index = :edge_index
                      AND r.source_pbf_md5 IS NOT NULL
                """), {"way_id": edges[0]["osm_way_id"],
                        "edge_index": edges[0]["edge_index"]}).scalar_one()
                assert sourced_count == 1
    assert matched == len(steps), "At least one OSRM step lacked an imported OSM Way candidate"
