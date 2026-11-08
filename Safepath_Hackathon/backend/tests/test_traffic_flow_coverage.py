"""Synthetic provider fixtures only; no HTTP/provider credentials or DB writes."""
from datetime import datetime, timedelta, timezone
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.app.core.config import settings
from backend.app.services.traffic_providers.coverage import cached_record, observed_fraction, valid_confidence
from backend.app.services.traffic_providers import tomtom, here

ROUTE = [[106.700, 10.77], [106.710, 10.77]]
HALF = [[106.700, 10.77], [106.705, 10.77]]
STEP = {"length_meters": 1000., "geojson_path": {"coordinates": ROUTE}}


def test_partial_overlap_does_not_extrapolate_endpoints():
    assert observed_fraction(ROUTE, [HALF]) == pytest.approx(.5)
    assert observed_fraction(ROUTE, [ROUTE]) == pytest.approx(1.)


@pytest.mark.parametrize('source', [list(reversed(ROUTE)), [[106.7,10.771],[106.71,10.771]],
    [[106.705,10.765],[106.705,10.775]], [], [[float('nan'),10.77],[106.71,10.77]]])
def test_wrong_direction_parallel_crossing_and_missing_geometry_are_not_observed(source):
    assert observed_fraction(ROUTE, [source]) == 0


def test_sparse_vertices_and_curved_lines_match_the_line_not_just_vertices():
    dense_route = [[106.700,10.77],[106.705,10.77],[106.710,10.77]]
    assert observed_fraction(dense_route, [ROUTE]) == pytest.approx(1.)
    curved = [[106.700,10.77],[106.705,10.77],[106.705,10.775]]
    assert observed_fraction(curved, [curved]) == pytest.approx(1.)


def test_disconnected_links_do_not_invent_a_connecting_road():
    links = [[[106.700,10.77],[106.702,10.77]],[[106.708,10.77],[106.710,10.77]]]
    assert observed_fraction(ROUTE, links) == pytest.approx(.4)


@pytest.mark.parametrize('value', [None, -.1, 1.1, float('nan'), float('inf'), 'invalid', True])
def test_invalid_or_unknown_confidence_is_rejected(value):
    assert valid_confidence(value) is None


def test_cached_records_require_real_nonfuture_timestamps():
    now = datetime.now(timezone.utc)
    for record in ({'speed':1}, {'payload':{}}, {'payload':{},'cached_at':None},
                   {'payload':{},'cached_at':(now+timedelta(seconds=5)).isoformat()},
                   {'payload':{},'cached_at':(now-timedelta(seconds=181)).isoformat()},
                   {'payload':{},'cached_at':'2026-01-01T00:00:00'}):
        assert cached_record(record, now, 180) is None
    timestamp = now-timedelta(seconds=30)
    assert cached_record({'payload':{},'cached_at':timestamp.isoformat()}, now, 180) == ({},timestamp)


def tomtom_payload(points=HALF, confidence=.9):
    return {'flowSegmentData': {'currentSpeed':30.,'freeFlowSpeed':60.,'confidence':confidence,'roadClosure':False,
        'coordinates': {'coordinate':[{'longitude':x,'latitude':y} for x,y in points]}}}


@pytest.mark.asyncio
async def test_tomtom_admits_only_partial_directed_flow(monkeypatch):
    monkeypatch.setattr(settings, 'TOMTOM_API_KEY','qa_fixture_only')
    monkeypatch.setattr(tomtom.TomTomTrafficProvider, '_circuit_open_until',0.)
    fetch = AsyncMock(return_value=httpx.Response(200,json=tomtom_payload()))
    monkeypatch.setattr(tomtom,'get_json_response',fetch)
    result = await tomtom.TomTomTrafficProvider().get_corridor_traffic(ROUTE,[STEP])
    assert result[0].observed_length_meters == pytest.approx(500.)
    assert result[0].traffic_delay_seconds == pytest.approx(30.)
    assert result[0].current_speed_kmh == 30
    fetch.return_value=httpx.Response(200,json=tomtom_payload(points=[]))
    assert await tomtom.TomTomTrafficProvider().get_corridor_traffic(ROUTE,[STEP]) == {}
    fetch.return_value=httpx.Response(200,json=tomtom_payload(confidence=None))
    assert await tomtom.TomTomTrafficProvider().get_corridor_traffic(ROUTE,[STEP]) == {}


@pytest.mark.asyncio
async def test_tomtom_drops_legacy_cache_instead_of_refreshing_its_age(monkeypatch):
    monkeypatch.setattr(settings, 'TOMTOM_API_KEY','qa_fixture_only')
    cache=AsyncMock()
    cache.get.return_value=json.dumps(tomtom_payload()['flowSegmentData'])
    fetch=AsyncMock(return_value=httpx.Response(200,json=tomtom_payload(points=[])))
    monkeypatch.setattr(tomtom,'get_json_response',fetch)
    result=await tomtom.TomTomTrafficProvider().get_corridor_traffic(ROUTE,[STEP],cache)
    assert result == {}
    fetch.assert_awaited_once()


def here_candidate(points=HALF,speed=10.,confidence=.9):
    return {'location':{'description':'same street', 'shape':{'links':[{'points':[{'lng':x,'lat':y} for x,y in points]}]}},
            'currentFlow':{'speed':speed,'freeFlow':20.,'confidence':confidence,'jamFactor':2.}}


@pytest.mark.asyncio
async def test_here_matches_geometry_and_keeps_mps_conversion(monkeypatch):
    monkeypatch.setattr(settings, 'HERE_API_KEY','qa_fixture_only')
    monkeypatch.setattr(here.HereTrafficProvider,'_circuit_open_until',0.)
    bad = here_candidate(points=[])
    good = here_candidate()
    fetch = AsyncMock(return_value=httpx.Response(200,json={'results':[bad,good]}))
    monkeypatch.setattr(here,'get_json_response',fetch)
    result = await here.HereTrafficProvider().get_corridor_traffic(ROUTE,[STEP])
    assert result[0].observed_length_meters == pytest.approx(500.)
    assert result[0].current_speed_kmh == 36.
    assert result[0].traffic_delay_seconds == pytest.approx(25.)
    fetch.return_value=httpx.Response(200,json={'results':[bad]})
    assert await here.HereTrafficProvider().get_corridor_traffic(ROUTE,[STEP]) == {}
    fetch.return_value=httpx.Response(200,json={'results':[good,here_candidate(speed=15.)]})
    assert await here.HereTrafficProvider().get_corridor_traffic(ROUTE,[STEP]) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize('vendor', ['tomtom','here'])
async def test_verified_closure_keeps_warning_without_inventing_speeds(monkeypatch, vendor):
    if vendor == 'tomtom':
        monkeypatch.setattr(settings,'TOMTOM_API_KEY','qa_fixture_only')
        module, provider = tomtom, tomtom.TomTomTrafficProvider()
        payload = tomtom_payload()
        payload['flowSegmentData'].update(roadClosure=True,currentSpeed=None,freeFlowSpeed=None)
    else:
        monkeypatch.setattr(settings,'HERE_API_KEY','qa_fixture_only')
        module, provider = here, here.HereTrafficProvider()
        candidate=here_candidate()
        candidate['currentFlow'].update(traversability='closed',speed=None,freeFlow=None)
        payload={'results':[candidate]}
    monkeypatch.setattr(module,'get_json_response',AsyncMock(return_value=httpx.Response(200,json=payload)))
    result=await provider.get_corridor_traffic(ROUTE,[STEP])
    assert result[0].is_closed
    assert result[0].current_speed_kmh == 0
    assert result[0].free_flow_speed_kmh is None
    assert result[0].traffic_delay_seconds == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('vendor', ['tomtom','here'])
async def test_newly_fetched_flow_age_uses_completion_clock(monkeypatch, vendor):
    start = datetime(2026,11,8,3,0,tzinfo=timezone.utc)
    times = iter([start, start+timedelta(seconds=2), start+timedelta(seconds=3)])

    class ControlledClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return next(times)

    if vendor == 'tomtom':
        monkeypatch.setattr(settings,'TOMTOM_API_KEY','qa_fixture_only')
        module, provider, payload = tomtom, tomtom.TomTomTrafficProvider(), tomtom_payload()
    else:
        monkeypatch.setattr(settings,'HERE_API_KEY','qa_fixture_only')
        module, provider, payload = here, here.HereTrafficProvider(), {'results':[here_candidate()]}
    monkeypatch.setattr(type(provider),'_circuit_open_until',0.)
    monkeypatch.setattr(module,'datetime',ControlledClock)
    monkeypatch.setattr(module,'get_json_response',AsyncMock(return_value=httpx.Response(200,json=payload)))
    result=await provider.get_corridor_traffic(ROUTE,[STEP])
    assert result[0].observed_at == start+timedelta(seconds=2)
    assert result[0].freshness_seconds == 1.


def test_repeated_directed_traversals_count_without_duplicating_provider_overlap():
    start,end = ROUTE
    repeated = [start,end,start,end]
    assert observed_fraction(repeated,[ROUTE]) == pytest.approx(2/3)
    assert observed_fraction(repeated,[ROUTE,ROUTE]) == pytest.approx(2/3)
    assert observed_fraction(repeated,[HALF]) == pytest.approx(1/3)
    assert observed_fraction(repeated,[list(reversed(ROUTE))]) == pytest.approx(1/3)
