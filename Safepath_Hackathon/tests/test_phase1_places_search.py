"""
Test Suite for Phase 1 Geocoding and Place Search Endpoints.
Verifies real search functionality, coordinate parsing, short query handling,
reverse geocoding, and resilient fallback mechanisms.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from backend.app.main import app


@pytest.mark.asyncio
async def test_places_search_vietnamese_query():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/places/search", params={"q": "Nguyen Hue", "limit": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "Nguyen Hue"
        assert len(data["results"]) >= 1
        first = data["results"][0]
        assert "lat" in first and "lng" in first
        assert 10.0 <= first["lat"] <= 11.5
        assert 106.0 <= first["lng"] <= 107.5
        assert first["provenance"] in ("photon.komoot.io", "postgis.osm_road_segments")


@pytest.mark.asyncio
async def test_places_search_coordinates_input():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/places/search", params={"q": "10.7725, 106.6980"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "coordinates"
        assert len(data["results"]) == 1
        assert abs(data["results"][0]["lat"] - 10.7725) < 1e-4
        assert abs(data["results"][0]["lng"] - 106.6980) < 1e-4


@pytest.mark.asyncio
async def test_places_search_short_query_returns_empty():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/places/search", params={"q": "ab"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["results"] == []


@pytest.mark.asyncio
async def test_places_reverse_geocoding():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/places/reverse", params={"lat": 10.7725, "lng": 106.6980})
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data and "display_name" in data
        assert abs(data["lat"] - 10.7725) < 1e-4
        assert abs(data["lng"] - 106.6980) < 1e-4

