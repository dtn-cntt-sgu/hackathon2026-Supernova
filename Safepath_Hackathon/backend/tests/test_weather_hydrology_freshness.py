"""Isolated observation freshness/provenance regressions; never publish fixture data."""
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.app.services import weather_tide as weather
from backend.app.services.hydrology_service import (
    HydrologySourceAdapter, HydrologyIngestionService, HydrologyLatestResponse,
)
from backend.app.schemas.contracts import WeatherTideSignal


class MemoryRedis:
    def __init__(self, values=None):
        self.values = values or {}
        self.ttls = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None, **kwargs):
        self.values[key] = value
        self.ttls[key] = ex

    async def delete(self, key):
        self.values.pop(key, None)


def provider_payload(age_seconds=0, **fields):
    observed = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return dict(utc_offset_seconds=0, current={"time": observed.isoformat(), "rain": 0.0,
                                             "weather_code": 0, **fields})


@pytest.mark.asyncio
async def test_stale_grid_cache_refetches_and_preserves_real_zero():
    redis = MemoryRedis({"env:weather:10.78:106.7": json.dumps({
        "rain_mm_per_hour": 9, "rain_status": "LIVE",
        "rain_observed_at": (datetime.now(timezone.utc) - timedelta(minutes=18)).isoformat(),
    })})
    calls = []
    def source(request):
        calls.append(request)
        return httpx.Response(200, json=provider_payload())
    async with httpx.AsyncClient(transport=httpx.MockTransport(source)) as client:
        amount, status, observed, _ = await weather.fetch_hcm_weather(redis_client=redis, client=client)
    assert len(calls) == 1 and amount == 0.0 and status == "LIVE"
    assert observed is not None


@pytest.mark.asyncio
async def test_nested_composite_cache_never_renews_old_observation():
    signal = WeatherTideSignal(rain_status="LIVE", rain_mm_per_hour=0,
                              rain_observed_at=datetime.now(timezone.utc) - timedelta(minutes=18))
    redis = MemoryRedis({weather.REDIS_WEATHER_TIDE_KEY: signal.model_dump_json()})
    assert await weather.get_cached_weather_tide(redis) is None
    signal.rain_observed_at = datetime.now(timezone.utc) - timedelta(minutes=14)
    await weather.sync_weather_tide_to_redis(signal, redis)
    assert 1 <= redis.ttls[weather.REDIS_WEATHER_TIDE_KEY] <= 60


@pytest.mark.asyncio
async def test_old_provider_observation_cannot_claim_live():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=provider_payload(1200))
    )) as client:
        amount, status, observed, _ = await weather.fetch_hcm_weather(client=client, redis_client=MemoryRedis())
    assert amount is None and status == "WEATHER_STALE" and observed is not None


@pytest.mark.asyncio
async def test_location_missing_precipitation_never_becomes_zero():
    payload = provider_payload(temperature_2m=25)
    del payload["current"]["rain"]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        result = await weather.fetch_location_weather(10.7, 106.7, client=client, redis_client=MemoryRedis())
    assert result.rain_mm_per_hour is None and result.temperature_c == 25


@pytest.mark.asyncio
async def test_location_missing_timestamp_never_becomes_now():
    payload = provider_payload()
    del payload["current"]["time"]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))) as client:
        result = await weather.fetch_location_weather(10.7, 106.7, client=client, redis_client=MemoryRedis())
    assert result.observed_at is None and result.status == "OBSERVATION_UNAVAILABLE"


def test_bulletins_require_observation_timestamp_and_reject_forecast():
    adapter = HydrologySourceAdapter()
    assert adapter.parse_bulletin_text("Phú An ghi nhận 1.45m, Nhà Bè ghi nhận 1.51m.") == []
    assert adapter.parse_bulletin_text("Dự báo Phú An đạt 1.58m lúc 17h30 ngày 24/10/2026.") == []
    parsed = adapter.parse_bulletin_text("Phú An ghi nhận 1.58m lúc 17h30 ngày 24/10/2026.")
    assert parsed[0]["observed_at"].isoformat() == "2026-10-24T17:30:00+07:00"


@pytest.mark.asyncio
async def test_no_verified_station_does_not_fabricate_zero_or_time():
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None)))
    latest = await HydrologyIngestionService().get_latest_observations(session, MemoryRedis())
    assert latest.quality_status == "UNAVAILABLE"
    assert latest.unavailable_reason == "VERIFIED_FEED_NOT_CONFIGURED"
    assert latest.max_alarm_level is None and latest.is_flood_warning is None
    assert all(s.water_level_m is None and s.observed_at is None and s.alarm_level is None for s in latest.stations)


def test_legacy_homepage_fixture_record_is_not_a_verified_observation():
    now = datetime.now(timezone.utc)
    fixture = SimpleNamespace(station_id="tram_phu_an", station_name="Phú An", river_name="Sài Gòn",
                              district="Bình Thạnh", latitude=10.7, longitude=106.7, water_level_m=1.45,
                              alarm_level=1, vertical_datum="Hòn Dấu", measurement_type="TIDAL_OBSERVATION",
                              observed_at=now, quality_status="OBSERVED_LIVE", source_name="KTTV",
                              source_url="http://kttv-nb.gov.vn", created_at=now)
    dto = HydrologyIngestionService()._model_to_dto(fixture)
    assert dto.quality_status == "UNVERIFIED"
    assert dto.water_level_m is None and dto.alarm_level is None and dto.is_flood_warning is None


@pytest.mark.asyncio
async def test_homepage_adapter_does_not_poll_unsupported_feed():
    client = SimpleNamespace(get=AsyncMock())
    assert await HydrologySourceAdapter().fetch_external_hydro_feed("tram_phu_an", client) is None
    client.get.assert_not_called()


@pytest.mark.asyncio
async def test_manual_text_is_never_elevated_to_verified_provider_data():
    service = HydrologyIngestionService()
    service.record_observation = AsyncMock(return_value=SimpleNamespace())
    await service.run_ingestion_cycle(None, MemoryRedis(), bulletin_text=(
        "Phú An ghi nhận 1.58m lúc 17h30 ngày 24/10/2026. "
        "Nguồn: https://kttv.gov.vn/bulletin/test-fixture"
    ))
    assert service.record_observation.call_args.kwargs["source_verified"] is False


@pytest.mark.parametrize("source", [None, "http://kttv-nb.gov.vn", "https://kttv.gov.vn/",
                                    "https://evil.test/bulletin", "https://kttv.gov.vn@evil.test/bulletin"])
def test_tide_source_requires_specific_official_https_bulletin(source):
    assert not weather.verified_tide_source_url(source)
