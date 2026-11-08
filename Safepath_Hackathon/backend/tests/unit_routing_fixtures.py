"""Explicit synthetic OSRM fixtures for unit contract tests only, never runtime data."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock


def install_unit_osrm(monkeypatch):
    """Exercise real route assembly/ranking without a network OSRM or invented live evidence."""
    from backend.app.services import routing
    coordinates = [[106.698 + i * .001, 10.7725 + i * .001] for i in range(12)]
    geometry = {"type": "LineString", "coordinates": coordinates}
    routes = []
    for distance, duration in ((1800.0, 300.0), (2100.0, 360.0)):
        routes.append({
            "distance": distance, "duration": duration, "geometry": geometry,
            "legs": [{"steps": [{"distance": distance, "duration": duration,
                "geometry": geometry, "name": "Unit-test fixture road",
                "maneuver": {"type": "depart", "location": coordinates[0]}}]}],
        })
    provider = AsyncMock(side_effect=lambda *args, **kwargs: deepcopy(routes))
    monkeypatch.setattr(routing, "_get_osrm_raw_routes", provider)
    monkeypatch.setattr(routing, "_osrm_cache_key", lambda *args: None)
    monkeypatch.setattr(routing, "_batched_spatial_context", AsyncMock(return_value=({}, {}, True, True)))
    monkeypatch.setattr(routing, "get_traffic_provider", lambda: SimpleNamespace(is_configured=lambda: False))
    return provider, routes


class UnitRedis:
    """Isolated in-memory cache/rate-counter fake for API unit tests."""
    def __init__(self):
        self.values = {}
        self.counts = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, **kwargs):
        self.values[key] = value
        return True

    async def eval(self, script, count, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def aclose(self):
        pass
