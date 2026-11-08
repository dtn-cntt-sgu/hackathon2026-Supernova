"""Run with OSRM_LIVE_TESTS=1 after scripts/setup_osrm_hcm.sh and compose up."""
import os
import math

import httpx
import pytest

from backend.app.services.routing import _get_osrm_raw_routes, RoutingError

PAIRS = [
    (10.7725, 106.6980, 10.8012, 106.7115),
    (10.8185, 106.6588, 10.7725, 106.6980),
    (10.7950, 106.7218, 10.8020, 106.7560),
    (10.7769, 106.7009, 10.7290, 106.7290),
    (10.7600, 106.6900, 10.8400, 106.8100),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("points", PAIRS)
async def test_real_osrm_geometry_and_metrics(points):
    if os.getenv("OSRM_LIVE_TESTS") != "1":
        pytest.skip("Set OSRM_LIVE_TESTS=1 with a running local OSRM container")
    routes = await _get_osrm_raw_routes(*points)
    assert routes
    for route in routes:
        coords = route["geometry"]["coordinates"]
        assert len(coords) >= 10  # full road geometry, not a few hand-picked anchors
        assert len({tuple(pt[:2]) for pt in coords}) >= 10
        assert route["distance"] > 0 and route["duration"] > 0
        assert all(math.isfinite(v) for pt in coords for v in pt[:2])
        # Compare against direct distance: a genuine graph path has multiple bends.
        assert any(abs(coords[i+1][0] - coords[i][0]) > 1e-7 or
                   abs(coords[i+1][1] - coords[i][1]) > 1e-7
                   for i in range(len(coords)-1))


@pytest.mark.asyncio
async def test_provider_down_returns_structured_error(monkeypatch):
    import backend.app.services.routing as routing
    monkeypatch.setattr(routing.settings, "OSRM_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(routing, "_osrm_cache_key", lambda *args: None)
    monkeypatch.setattr(routing, "_osrm_circuit_open_until", 0.0)
    with pytest.raises(RoutingError) as error:
        await _get_osrm_raw_routes(*PAIRS[0])
    assert error.value.status_code == 503
    assert error.value.code == "ROUTING_PROVIDER_UNAVAILABLE"


@pytest.mark.asyncio
async def test_rejects_invalid_coordinates_before_request():
    with pytest.raises(RoutingError) as error:
        await _get_osrm_raw_routes(91, 106.7, 10.8, 106.8)
    assert error.value.status_code == 422
    assert error.value.code == "INVALID_COORDINATES"


@pytest.mark.asyncio
async def test_api_reports_provider_down_without_route(monkeypatch):
    from backend.app.main import app
    from backend.app.db.session import get_db
    import backend.app.services.routing as routing

    async def no_db_connection():
        yield None  # OSRM fails before corridor query

    app.dependency_overrides[get_db] = no_db_connection
    monkeypatch.setattr(routing.settings, "OSRM_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(routing, "_osrm_circuit_open_until", 0.0)
    monkeypatch.setattr("backend.app.main.get_redis_client", lambda: None)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/routes/search", json={
                "origin": {"lat": 10.7725, "lng": 106.6980},
                "destination": {"lat": 10.8012, "lng": 106.7115},
            })
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "ROUTING_PROVIDER_UNAVAILABLE"
        assert "geojson_path" not in response.json()
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("points", PAIRS)
async def test_live_api_preserves_osrm_route(points):
    if os.getenv("OSRM_LIVE_TESTS") != "1" or not os.getenv("API_LIVE_BASE_URL"):
        pytest.skip("Set OSRM_LIVE_TESTS=1 and API_LIVE_BASE_URL with live services")
    origin_lat, origin_lng, dest_lat, dest_lng = points
    osrm_route = (await _get_osrm_raw_routes(*points))[0]
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"{os.environ['API_LIVE_BASE_URL'].rstrip('/')}/api/v1/routes/search", json={
            "origin": {"lat": origin_lat, "lng": origin_lng},
            "destination": {"lat": dest_lat, "lng": dest_lng},
        })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["geojson_path"] == osrm_route["geometry"]
    assert body["total_distance_km"] == round(osrm_route["distance"] / 1000, 3)
    assert body["estimated_time_mins"] == round(osrm_route["duration"] / 60, 2)
    assert body["overall_risk"] == "UNKNOWN"
    first_step = osrm_route["legs"][0]["steps"][0]
    first_segment = body["segments"][0]
    assert first_segment["maneuver_type"] == first_step["maneuver"]["type"]
    assert first_segment["maneuver_modifier"] == first_step["maneuver"].get("modifier")
    assert first_segment["maneuver_location"] == first_step["maneuver"]["location"]
    assert first_segment["length_meters"] == first_step["distance"]
