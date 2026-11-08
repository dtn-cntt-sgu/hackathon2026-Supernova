"""Offline tests using httpx.MockTransport; never contact the camera provider."""
import asyncio
import importlib.util
from pathlib import Path
import sys

import httpx
import pytest

MODULE = Path(__file__).resolve().parents[1] / "app/services/camera_live_proxy.py"
spec = importlib.util.spec_from_file_location("camera_live_proxy_starter", MODULE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
CameraLiveProxy = module.CameraLiveProxy
CameraProxyError = module.CameraProxyError


def make_proxy(handler):
    return CameraLiveProxy(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        validator=lambda _: True,  # Tests isolate proxy logic; production uses SafePath validator.
        ttl_seconds=20,
    )


@pytest.mark.asyncio
async def test_only_registered_shape_and_fixed_upstream():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=b"fake-jpeg", headers={"content-type":"image/jpeg"})
    proxy = make_proxy(handler)
    with pytest.raises(CameraProxyError) as ex:
        await proxy.get_frame("https://evil.invalid/")
    assert ex.value.status_code == 400
    assert not requests
    with pytest.raises(ValueError):
        CameraLiveProxy(upstream_url="https://evil.invalid/image", validator=lambda _: True)


@pytest.mark.asyncio
async def test_proxy_fixed_upstream_id_and_memory_cache():
    requests = []
    def handler(req):
        requests.append(req)
        return httpx.Response(200, content=b"fake-jpeg", headers={"content-type":"image/jpeg"})
    proxy = make_proxy(handler)
    camera_id = "586e28a0f9fab7001111b0b3"
    first, second = await asyncio.gather(proxy.get_frame(camera_id), proxy.get_frame(camera_id))
    assert len(requests) == 1
    assert requests[0].url.host == "giaothong.hochiminhcity.gov.vn"
    assert requests[0].url.params["id"] == camera_id
    assert first.data == second.data == b"fake-jpeg"
    assert first.from_cache != second.from_cache


@pytest.mark.asyncio
async def test_no_html_or_redirect_is_proxied():
    camera_id = "586e28a0f9fab7001111b0b3"
    html_proxy = make_proxy(lambda r: httpx.Response(200, content=b"<html>", headers={"content-type":"text/html"}))
    with pytest.raises(CameraProxyError, match="NOT_AN_IMAGE"):
        await html_proxy.get_frame(camera_id)
    redirect_proxy = make_proxy(lambda r: httpx.Response(302, headers={"location":"https://evil.invalid/"}))
    with pytest.raises(CameraProxyError, match="UPSTREAM_ERROR"):
        await redirect_proxy.get_frame(camera_id)


@pytest.mark.asyncio
async def test_restricted_source_returns_503():
    proxy = make_proxy(lambda r: httpx.Response(429))
    with pytest.raises(CameraProxyError) as ex:
        await proxy.get_frame("586e28a0f9fab7001111b0b3")
    assert ex.value.status_code == 503
    assert ex.value.reason == "UPSTREAM_RESTRICTED"


@pytest.mark.asyncio
async def test_placeholder_rejected_by_validator():
    proxy = CameraLiveProxy(
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"image", headers={"content-type":"image/png"}))),
        validator=lambda _: False,
    )
    with pytest.raises(CameraProxyError, match="INVALID_OR_PLACEHOLDER_FRAME"):
        await proxy.get_frame("586e28a0f9fab7001111b0b3")
