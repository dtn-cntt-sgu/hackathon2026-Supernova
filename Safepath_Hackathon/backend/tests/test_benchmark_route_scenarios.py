"""Synthetic business-rule scenarios, not field AI accuracy or measured travel times.

Expected outcomes come from safety requirements: missing/unmatched/stale evidence
cannot prove a road safe; a verified severe flood must outrank travel-time savings.
Only external transport/database/context adapters are replaced, never risk/ranking.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.app.schemas.contracts import CameraEvidence, RiskLevel, WeatherTideSignal
from backend.app.services import routing
from backend.app.services.risk_engine import calculate_segment_risk
from backend.app.services.route_camera_ai import model_version
from backend.tests.unit_routing_fixtures import install_unit_osrm


SEGMENT = {"osm_way_id": 72001, "edge_index": 1, "length_meters": 1800,
           "street_name": "Synthetic benchmark road", "is_flood_prone_history": False}


def evidence(**changes):
    now = datetime.now(timezone.utc)
    fields = dict(cam_id="synthetic-benchmark-camera", name="Synthetic test only",
                  lat=10.7725, lng=106.698, coordinate_source_url="https://example.test/gps",
                  view_verification_source_url="https://example.test/view", line_of_sight_verified=True,
                  observed_osm_way_id=72001, observed_edge_index=1,
                  spatial_match_status="OBSERVED_SEGMENT_VERIFIED", evidence_eligibility="ROUTING_ELIGIBLE",
                  source_status="LIVE", updated_at=now, captured_at=now, retrieved_at=now,
                  flood_ratio=.60, traffic_density_score=None, risk_level="UNKNOWN",
                  permitted_use="ROUTING_EVIDENCE_PERMITTED", route_ai_model_version=model_version())
    fields.update(changes)
    return CameraEvidence(**fields)


@pytest.mark.parametrize("scenario", ["no_camera", "stale_camera", "wrong_edge", "missing_weather", "severe_verified_flood"])
def test_independent_segment_safety_expectations(scenario):
    cameras, weather = [evidence()], None
    if scenario == "no_camera":
        cameras = []
        now = datetime.now(timezone.utc)
        # Even fresh heavy regional rain does not prove water on this exact road.
        weather = WeatherTideSignal(rain_mm_per_hour=60, rain_status="LIVE", rain_observed_at=now,
                                    timestamp=now, source_url="https://example.test/weather")
    elif scenario == "stale_camera":
        cameras = [evidence(updated_at=datetime.now(timezone.utc) - timedelta(hours=1))]
    elif scenario == "wrong_edge":
        cameras = [evidence(observed_edge_index=2)]
    elif scenario == "missing_weather":
        cameras = [evidence(flood_ratio=0)]
    result = calculate_segment_risk(SEGMENT, cameras, weather_tide=weather)
    if scenario == "severe_verified_flood":
        assert result.risk_level == RiskLevel.CRITICAL
        assert result.evidence_cameras
    else:
        assert result.risk_level == RiskLevel.UNKNOWN
        assert result.risk_score is None
        assert result.risk_level != RiskLevel.SAFE


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_code", ["NoRoute", "NoSegment"])
async def test_provider_no_connected_path_returns_no_route_not_invented_geometry(monkeypatch, provider_code):
    monkeypatch.setattr(routing, "_osrm_circuit_open_until", 0.0)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"code": provider_code, "routes": []}))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(routing.RoutingError) as raised:
            await routing._get_osrm_raw_routes(10.7725, 106.698, 10.7835, 106.709, client)
    assert raised.value.code == "NO_ROUTE_FOUND"
    assert raised.value.status_code == 404
    assert not hasattr(raised.value, "geojson_path")


@pytest.mark.asyncio
async def test_provider_timeout_returns_unavailable_without_substitute_route(monkeypatch):
    monkeypatch.setattr(routing, "_osrm_circuit_open_until", 0.0)

    def timeout(request):
        raise httpx.ReadTimeout("Synthetic transport timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(routing.RoutingError) as raised:
            await routing._get_osrm_raw_routes(10.7725, 106.698, 10.7835, 106.709, client)
    assert raised.value.code == "ROUTING_PROVIDER_UNAVAILABLE"
    assert raised.value.status_code == 503
    assert not hasattr(raised.value, "geojson_path")


@pytest.mark.asyncio
@pytest.mark.parametrize("all_hazardous", [False, True])
async def test_real_route_assembly_prefers_noncritical_and_never_recommends_all_hazardous(monkeypatch, all_hazardous):
    _, routes = install_unit_osrm(monkeypatch)
    # Exact-match proof is synthetic adapter input here; actual topology verification
    # has separate PostGIS tests. No DB, camera requests, or model inference runs.
    edge = {**SEGMENT, "route_match_verified": True, "geometry": routes[0]["geometry"]}
    edges, cameras = {(0, 0): [edge]}, {(0, 0): [evidence()]}
    if all_hazardous:
        edges[(1, 0)] = [{**edge, "length_meters": routes[1]["distance"]}]
        cameras[(1, 0)] = [evidence()]
    monkeypatch.setattr(routing, "_batched_spatial_context", AsyncMock(return_value=(edges, cameras, True, True)))
    monkeypatch.setattr(routing, "_get_flood_prone_way_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr("backend.app.services.community_incidents.load_verified_incidents", AsyncMock(return_value={}))
    monkeypatch.setattr(routing.settings, "CAMERA_ROUTING_EVIDENCE_PERMITTED", True)
    monkeypatch.setattr(routing.settings, "ROUTE_CAMERA_AI_ENABLED", False)
    result = await routing.find_safe_route(10.7725, 106.698, 10.7835, 106.709, None)
    assert len(result) == 2
    if all_hazardous:
        assert all(route.overall_risk == RiskLevel.CRITICAL for route in result)
        assert all(route.route_status == "NO_SAFE_ROUTE" and not route.is_recommended for route in result)
    else:
        assert result[0].total_distance_km == 2.1  # Longer alternative beats shorter confirmed hazard.
        assert result[0].overall_risk == RiskLevel.UNKNOWN  # Absence of evidence does not prove SAFE.
        assert result[0].is_recommended
        assert result[1].total_distance_km == 1.8
        assert result[1].overall_risk == RiskLevel.CRITICAL and not result[1].is_recommended
