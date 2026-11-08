"""Synthetic OSM/OSRM topology in disposable PostGIS; never live evidence or production mocks."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.tests.test_database_migrations import migration_db, upgrade
from backend.app.services import route_matching as matching
from backend.app.services import routing
from backend.app.services.risk_engine import calculate_segment_risk, aggregate_edge_risks
from backend.app.schemas.contracts import CameraEvidence, RiskLevel, RouteSegmentRisk
from backend.tests.unit_routing_fixtures import install_unit_osrm

GEOM = {"type": "LineString", "coordinates": [[106.698, 10.7725], [106.699, 10.7725], [106.700, 10.7725]]}
PROOF = {"pbf_md5": "a" * 32, "identity": "synthetic-test-only"}


def route(nodes=(1, 2, 3), geometry=GEOM):
    return {"geometry": geometry, "distance": 220., "duration": 60., "legs": [{
        "annotation": {"nodes": list(nodes)}, "steps": [{"distance": 220., "duration": 60., "geometry": geometry, "name": "Fixture Street"}]}]}


def insert_way(db, way=101, nodes=(1, 2, 3), y=10.7725, oneway=None, md5="a" * 32):
    coords = [[106.698 + i * .001, y] for i in range(len(nodes))]
    db.execute(text("""INSERT INTO road_segments(osm_way_id,geom,source_url,source_pbf_md5,oneway,osm_node_ids)
      VALUES(:way,ST_SetSRID(ST_GeomFromGeoJSON(:geom),4326),:url,:md5,:oneway,CAST(:nodes AS jsonb))"""),
      {"way": way, "geom": json.dumps({"type": "LineString", "coordinates": coords}), "url": matching.SOURCE_URL,
       "md5": md5, "oneway": oneway, "nodes": json.dumps(nodes)})
    for i, (a, b) in enumerate(zip(nodes, nodes[1:]), 1):
        db.execute(text("""INSERT INTO road_edges(osm_way_id,edge_index,geom,length_meters,source_node_id,target_node_id)
          VALUES(:way,:edge,ST_SetSRID(ST_GeomFromGeoJSON(:geom),4326),110,:a,:b)"""),
          {"way": way, "edge": i, "geom": json.dumps({"type": "LineString", "coordinates": coords[i-1:i+1]}), "a": a, "b": b})


@pytest.fixture
def graph_db(migration_db):
    upgrade(migration_db)
    with Session(migration_db) as db:
        insert_way(db)
        yield db


@pytest.mark.asyncio
async def test_exact_multi_edge_and_parallel_bridge_junction(graph_db):
    # Parallel carriageway and overpass have different node IDs even near identical geometry.
    insert_way(graph_db, way=202, nodes=(21, 22, 23), y=10.7725001)
    insert_way(graph_db, way=303, nodes=(31, 32, 33))
    # Branch at the middle node is not traversed by the annotation sequence.
    insert_way(graph_db, way=404, nodes=(2, 41))
    matches = await matching.verified_step_edges([route()], graph_db, PROOF)
    assert [(e["osm_way_id"], e["edge_index"]) for e in matches[0, 0]] == [(101, 1), (101, 2)]
    assert all(e["route_match_verified"] for e in matches[0, 0])


@pytest.mark.asyncio
async def test_direction_provenance_ambiguity_and_missing_coverage(graph_db):
    reverse_geom = {**GEOM, "coordinates": list(reversed(GEOM["coordinates"]))}
    assert await matching.verified_step_edges([route((3, 2, 1), reverse_geom)], graph_db, PROOF)
    assert not await matching.verified_step_edges([route((3, 2, 1))], graph_db, PROOF)
    graph_db.execute(text("UPDATE road_segments SET oneway='yes' WHERE osm_way_id=101"))
    assert not await matching.verified_step_edges([route((3, 2, 1))], graph_db, PROOF)
    assert not await matching.verified_step_edges([route()], graph_db, {**PROOF, "pbf_md5": "b" * 32})
    assert not await matching.verified_step_edges([route((1, 2))], graph_db, PROOF)
    assert not await matching.verified_step_edges([route()], graph_db, None)
    insert_way(graph_db, way=505, nodes=(1, 2, 3))
    assert not await matching.verified_step_edges([route()], graph_db, PROOF)


def camera(edge=2, flood=.6):
    return CameraEvidence(cam_id="synthetic-camera", name="Fixture", code="T", lat=10.7725, lng=106.699,
        coordinate_source_url="https://example.test/gps-proof", view_verification_source_url="https://example.test/view-proof",
        observed_osm_way_id=101, observed_edge_index=edge, line_of_sight_verified=True,
        spatial_match_status="OBSERVED_SEGMENT_VERIFIED", evidence_eligibility="ROUTING_ELIGIBLE",
        source_status="LIVE", updated_at=datetime.now(timezone.utc), flood_ratio=flood,
        traffic_density_score=.2, image_url="", risk_level="UNKNOWN",
        permitted_use="ROUTING_EVIDENCE_PERMITTED", captured_at=datetime.now(timezone.utc),
        retrieved_at=datetime.now(timezone.utc), route_ai_model_version=__import__(
            "backend.app.services.route_camera_ai", fromlist=["model_version"]).model_version())


def test_multi_edge_aggregation_preserves_second_edge_hazard_and_requires_edge_proof():
    evidence = camera()
    risks = [calculate_segment_risk({"osm_way_id": 101, "edge_index": edge, "length_meters": 110}, [evidence]) for edge in (1, 2)]
    assert risks[0].risk_level == RiskLevel.UNKNOWN
    assert risks[1].risk_level == RiskLevel.CRITICAL
    aggregate = aggregate_edge_risks(risks)
    assert aggregate.risk_level == RiskLevel.CRITICAL
    assert aggregate.osm_way_id is None
    assert aggregate.evidence_coverage == "PARTIAL_VERIFIED_EDGE_OBSERVATIONS"
    assert len(aggregate.evidence_cameras) == 1
    assert aggregate.traffic_observed_length_meters == 110
    evidence.observed_edge_index = None
    assert calculate_segment_risk({"osm_way_id": 101, "edge_index": 2, "length_meters": 110}, [evidence]).risk_level == RiskLevel.UNKNOWN


@pytest.mark.asyncio
async def test_matched_serious_evidence_changes_ranking_and_all_hazardous_is_not_recommended(graph_db, monkeypatch):
    monkeypatch.setattr(routing.settings, "CAMERA_ROUTING_EVIDENCE_PERMITTED", True)
    exact = await matching.verified_step_edges([route()], graph_db, PROOF)
    _, raw_routes = install_unit_osrm(monkeypatch)
    raw_routes[0].update(route())  # SQL match and route assembly share the identical geometry.
    monkeypatch.setattr(routing, "_batched_spatial_context", AsyncMock(return_value=(
        {(0, 0): exact[0, 0]}, {(0, 0): [camera()]}, True, True)))
    # Actual assembly and risk engine run; only the external OSRM transport is synthetic.
    result = await routing.find_safe_route(10.7725, 106.698, 10.7835, 106.709, graph_db)
    assert result[0].overall_risk == RiskLevel.UNKNOWN
    hazardous = next(r for r in result if r.overall_risk == RiskLevel.CRITICAL)
    assert hazardous.ranking_cost > result[0].ranking_cost
    assert not hazardous.is_recommended
    # Camera density supports a hazard warning, not measured speed or live ETA.
    assert hazardous.traffic_coverage_ratio == 0
    assert hazardous.segments[0].traffic_observed_length_meters == pytest.approx(exact[0, 0][1]["length_meters"])
    raw_routes[1].update(route())  # Both synthetic candidates now traverse the proven hazardous edges.
    monkeypatch.setattr(routing, "_batched_spatial_context", AsyncMock(return_value=(
        {(0, 0): exact[0, 0], (1, 0): exact[0, 0]}, {(0, 0): [camera()], (1, 0): [camera()]}, True, True)))
    result = await routing.find_safe_route(10.7725, 106.698, 10.7835, 106.709, graph_db)
    assert all(r.route_status == "NO_SAFE_ROUTE" and not r.is_recommended for r in result)
    assert all(r.ai_explanation.startswith("Chưa tìm được tuyến tránh nguy hiểm.") for r in result)
    assert all("NO_SAFE_ROUTE" not in r.ai_explanation and "chi phí xếp hạng" not in r.ai_explanation for r in result)


def test_graph_manifest_invalidates_modified_artifact(tmp_path, monkeypatch):
    files = {}
    for name in ("vietnam-latest.osrm.mldgr", "vietnam-latest.osrm.geometry", "vietnam-latest.osrm.nbg_nodes", "vietnam-latest.osrm.properties"):
        (tmp_path / name).write_bytes(b"synthetic artifact only")
        files[name] = hashlib.sha256(b"synthetic artifact only").hexdigest()
    manifest = tmp_path / "graph-manifest.json"
    manifest.write_text(json.dumps({"schema": 1, "source_url": matching.SOURCE_URL, "pbf_md5": "a" * 32, "files": files}))
    monkeypatch.setattr(matching, "settings", SimpleNamespace(OSRM_GRAPH_MANIFEST_PATH=str(manifest)))
    assert matching.graph_proof()["pbf_md5"] == "a" * 32
    (tmp_path / "vietnam-latest.osrm.mldgr").write_bytes(b"different graph")
    assert matching.graph_proof() is None
    manifest.unlink()
    assert matching.graph_proof() is None


def test_news_closure_wins_over_congestion_and_dry_camera():
    common = dict(title="Fixture Street incident", summary="", lat=10.7725, lng=106.699,
        location_confidence="EXACT", event_status="ACTIVE_HAZARD", published_at=datetime.now(timezone.utc))
    congestion = SimpleNamespace(**common, category="CONGESTION", source_url="https://example.test/congestion")
    closed = SimpleNamespace(**common, category="ROAD_CLOSURE", source_url="https://example.test/closure")
    risk = calculate_segment_risk({"osm_way_id": 101, "edge_index": 2, "length_meters": 110,
        "street_name": "Fixture Street", "geojson_path": GEOM}, [camera(flood=0)],
        traffic_news=[congestion, closed, closed])
    assert risk.risk_level == RiskLevel.CRITICAL
    assert risk.is_closed
    assert risk.traffic_status.value == "CLOSED"


def test_community_requires_review_exact_edge_and_freshness():
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    segment = {"osm_way_id": 101, "edge_index": 2, "length_meters": 110}
    incident = {"incident_id": 7, "osm_way_id": 101, "edge_index": 2, "status": "VERIFIED",
        "category": "BLOCKED", "observed_at": now, "expires_at": now + timedelta(hours=1),
        "evidence_url": "https://example.test/independent-proof", "confidence": .8}
    risk = calculate_segment_risk(segment, [], community_incidents=[incident, incident])
    assert risk.risk_level == RiskLevel.CRITICAL and risk.is_closed
    for change in ({"status": "PENDING"}, {"edge_index": 1}, {"observed_at": now-timedelta(hours=4)},
                   {"expires_at": now-timedelta(seconds=1)}, {"evidence_url": ""}):
        assert calculate_segment_risk(segment, [], community_incidents=[{**incident, **change}]).risk_level == RiskLevel.UNKNOWN
    assert calculate_segment_risk(segment, [], community_incidents=[{**incident, "category": "FLOOD"}]).risk_level == RiskLevel.MODERATE


@pytest.mark.parametrize("uncertain", [RiskLevel.UNKNOWN,RiskLevel.INSUFFICIENT_EVIDENCE])
def test_aggregate_safe_plus_uncertain_remains_unknown_and_hazards_are_preserved(uncertain):
    unknown = RouteSegmentRisk(length_meters=100,risk_level=uncertain)
    safe = RouteSegmentRisk(length_meters=100,risk_level=RiskLevel.SAFE,risk_score=0)
    result = aggregate_edge_risks([safe,unknown])
    assert result.risk_level == RiskLevel.UNKNOWN and result.risk_score is None
    for hazard in (RiskLevel.MODERATE,RiskLevel.CRITICAL):
        risk = RouteSegmentRisk(length_meters=100,risk_level=hazard,risk_score=80)
        assert aggregate_edge_risks([risk,unknown]).risk_level == hazard


@pytest.mark.asyncio
async def test_edge_scoring_exception_cannot_turn_partial_safe_step_into_safe_route(monkeypatch):
    install_unit_osrm(monkeypatch)
    edges = [{"osm_way_id":101,"edge_index":i,"route_match_verified":True,"length_meters":100} for i in (1,2)]
    monkeypatch.setattr(routing,"_batched_spatial_context",AsyncMock(return_value=({(0,0):edges},{},True,True)))
    def score(segment,**kwargs):
        if segment["edge_index"]==2:
            raise RuntimeError("Synthetic edge scoring failure")
        return RouteSegmentRisk(length_meters=100,risk_level=RiskLevel.SAFE,risk_score=0)
    monkeypatch.setattr(routing,"calculate_segment_risk",score)
    responses=await routing.find_safe_route(10.7725,106.698,10.7835,106.709,None)
    assert all(r.overall_risk == RiskLevel.UNKNOWN for r in responses)
    assert all(r.route_status == "ROUTE_FOUND_RISK_UNKNOWN" for r in responses)
    assert all(s.risk_level != RiskLevel.SAFE for r in responses for s in r.segments)
