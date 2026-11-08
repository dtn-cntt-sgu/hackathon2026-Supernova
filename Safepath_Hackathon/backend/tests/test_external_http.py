import asyncio
import httpx
import pytest
from backend.app.core import external_http as source


@pytest.fixture(autouse=True)
def clear_cooldowns():
    source._COOLDOWNS.clear()
    yield
    source._COOLDOWNS.clear()


@pytest.mark.asyncio
async def test_transient_get_failure_retries_then_recovers():
    calls = []
    def handler(request):
        calls.append(request.method)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={'current': {}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        response = await source.get_json_response(client, 'https://source.example/a', operation='weather')
    assert response.status_code == 200
    assert calls == ['GET', 'GET']
    assert not source._COOLDOWNS


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['malformed', 'timeout', 'quota'])
async def test_failure_cooldown_and_recovery(kind):
    calls = []
    healthy = False
    async def handler(request):
        calls.append(request)
        if healthy:
            return httpx.Response(200, json={})
        if kind == 'timeout':
            await asyncio.sleep(0.1)
        if kind == 'quota':
            return httpx.Response(429)
        return httpx.Response(200, content=b'not JSON')
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        if kind == 'quota':
            assert (await source.get_json_response(client, 'https://source.example/a', operation='weather')).status_code == 429
        else:
            with pytest.raises((ValueError, TimeoutError)):
                await source.get_json_response(client, 'https://source.example/a', operation='weather', budget_seconds=0.01)
        before = len(calls)
        with pytest.raises(httpx.ConnectError):
            await source.get_json_response(client, 'https://source.example/a', operation='weather')
        assert len(calls) == before
        healthy = True
        for key in source._COOLDOWNS:
            source._COOLDOWNS[key] = 0
        assert (await source.get_json_response(client, 'https://source.example/a', operation='weather')).status_code == 200
