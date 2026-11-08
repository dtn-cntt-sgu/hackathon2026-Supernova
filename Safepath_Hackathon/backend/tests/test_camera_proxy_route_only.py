"""Offline contract tests; provider availability is not inferred from these fixtures."""
import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import numpy as np
from PIL import Image
import pytest

from backend.app.core.config import settings
from backend.app.services.camera_proxy import CameraProxy, CameraProxyError
from backend.app.services.scraper import portal_circuit_breaker

CAM = "586e28a0f9fab7001111b0b3"


def image_bytes():
    out = BytesIO()
    Image.fromarray(np.random.default_rng(42).integers(20, 230, (230, 300, 3), dtype=np.uint8)).save(out, format="JPEG")
    return out.getvalue()


@pytest.fixture(autouse=True, params=["hcmc", "vietmap"])
def proxy_config(monkeypatch, request):
    portal_circuit_breaker.reset()
    monkeypatch.setattr(settings, "CAMERA_PROXY_PROVIDER", request.param)
    monkeypatch.setattr(settings, "CAMERA_PROXY_MIN_REQUEST_INTERVAL_SECONDS", 0.)
    yield
    portal_circuit_breaker.reset()


@pytest.mark.asyncio
async def test_coalesced_cache_original_bytes_and_fixed_source():
    calls = []
    payload = image_bytes()
    async def source(request):
        calls.append(request)
        await asyncio.sleep(.01)
        return httpx.Response(200, content=payload, headers={"content-type": "image/jpeg"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(source)) as client:
        proxy = CameraProxy(client)
        frames = await asyncio.gather(*(proxy.get_frame(CAM) for _ in range(100)))
        again = await proxy.get_frame(CAM)
    assert len(calls) == 1
    assert all(f.data == payload for f in frames)
    assert again.source_status == "RECENTLY_RETRIEVED_CAPTURE_UNKNOWN"
    if settings.CAMERA_PROXY_PROVIDER == "vietmap":
        assert calls[0].url.host == "cdn.vietmap.live"
        assert calls[0].url.path == f"/cctv/{CAM}/snapshot"
        assert set(calls[0].url.params) == {"t"}
        assert len(calls[0].url.params["t"]) == 13
        assert not calls[0].headers.get("referer")
    else:
        assert calls[0].url.host == "giaothong.hochiminhcity.gov.vn"
        assert calls[0].url.params["id"] == CAM
    assert not calls[0].headers.get("cookie")
    assert not proxy.pending


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["../etc/passwd", "abc", "http://127.0.0.1", CAM + "?url=http://localhost"])
async def test_bad_id_never_fetches(bad):
    proxy = CameraProxy()
    with pytest.raises(CameraProxyError) as error:
        await proxy.get_frame(bad)
    assert error.value.http_status == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(403,"RESTRICTED"), (429,"RESTRICTED"), (404,"OFFLINE"), (500,"FETCH_FAILED"), (302,"FETCH_FAILED")])
async def test_upstream_errors_back_off(status, expected):
    calls = []
    def source(request):
        calls.append(request)
        return httpx.Response(status, headers={"location": "http://127.0.0.1/private"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(source)) as client:
        proxy = CameraProxy(client)
        for _ in range(2):
            with pytest.raises(CameraProxyError) as error:
                await proxy.get_frame(CAM)
            assert error.value.status == expected
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_html_oversize_placeholder_and_timeout(monkeypatch):
    async def timeout(request):
        raise httpx.ReadTimeout("offline")
    cases = [
        (lambda r: httpx.Response(200, text="html", headers={"content-type": "text/html"}), "NOT_AN_IMAGE"),
        (lambda r: httpx.Response(200, content=b"x"*101, headers={"content-type": "image/jpeg"}), "FRAME_TOO_LARGE"),
        (lambda r: httpx.Response(200, content=b"broken", headers={"content-type": "image/jpeg"}), "INVALID_OR_PLACEHOLDER_FRAME"),
        (timeout, "UPSTREAM_TIMEOUT"),
    ]
    monkeypatch.setattr(settings, "CAMERA_PROXY_MAX_BYTES", 100)
    for handler, code in cases:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(CameraProxyError) as error:
                await CameraProxy(client).get_frame(CAM)
            assert error.value.code == code


@pytest.mark.asyncio
async def test_stale_keeps_original_time_and_expired_is_not_served(monkeypatch):
    payload = image_bytes()
    fail = False
    def source(request):
        return httpx.Response(503) if fail else httpx.Response(200, content=payload, headers={"content-type":"image/jpeg"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(source)) as client:
        proxy = CameraProxy(client)
        first = await proxy.get_frame(CAM)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=25)
        from dataclasses import replace
        proxy.frames[CAM] = replace(first, retrieved_at=old_time)
        fail = True
        stale = await proxy.get_frame(CAM)
        assert stale.source_status == "STALE" and stale.data == payload
        assert stale.retrieved_at == old_time
        proxy.frames[CAM] = replace(first, retrieved_at=old_time - timedelta(hours=1))
        with pytest.raises(CameraProxyError):
            await proxy.get_frame(CAM)


@pytest.mark.asyncio
async def test_configuration_cannot_make_open_proxy(monkeypatch):
    monkeypatch.setattr(settings, "CAMERA_PROXY_PROVIDER", "hcmc")
    monkeypatch.setattr(settings, "HCMC_CAMERA_BASE_URL", "https://localhost/private")
    with pytest.raises(CameraProxyError, match="INVALID_UPSTREAM_CONFIGURATION"):
        await CameraProxy().get_frame(CAM)


@pytest.mark.asyncio
async def test_api_registry_permission_headers_and_no_vision(monkeypatch):
    from backend.app.main import app, get_camera_proxy, background_vision_worker_loop
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: CAM)))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(camera_proxy=SimpleNamespace(get_frame=AsyncMock()))))
    from backend.app.services.camera_proxy import ProxyFrame
    proxy = request.app.state.camera_proxy
    proxy.get_frame.return_value = ProxyFrame(b"image", "image/jpeg", "a"*64, datetime.now(timezone.utc),
                                             provider="vietmap", source_url=f"https://cdn.vietmap.live/cctv/{CAM}/snapshot")
    import backend.app.main as main
    monkeypatch.setattr(main, "enforce_rate_limit", AsyncMock())
    monkeypatch.setattr(settings, "CAMERA_ALLOW_VIEW_ONLY", True)
    result = await get_camera_proxy(CAM, request, session)
    assert result.body == b"image"
    assert result.headers["x-camera-source-status"] == "RECENTLY_RETRIEVED_CAPTURE_UNKNOWN"
    assert result.headers["x-snapshot-id"] == "a"*64
    assert result.headers["x-content-type-options"] == "nosniff"
    assert result.headers["cache-control"] == "no-store"
    assert result.headers["x-camera-provider"] == "vietmap"
    assert result.headers["x-camera-source"] == f"https://cdn.vietmap.live/cctv/{CAM}/snapshot"
    from fastapi import HTTPException
    session.execute.return_value.scalar_one_or_none = lambda: None
    with pytest.raises(HTTPException) as error:
        await get_camera_proxy(CAM, request, session)
    assert error.value.status_code == 404
    monkeypatch.setattr(settings, "CAMERA_ALLOW_VIEW_ONLY", False)
    monkeypatch.setattr(settings, "CAMERA_INGESTION_PERMITTED", False)
    with pytest.raises(HTTPException) as error:
        await get_camera_proxy(CAM, request, session)
    assert error.value.status_code == 403
    # An old persisted vision job cannot run even if someone calls the legacy loop.
    await asyncio.wait_for(background_vision_worker_loop(asyncio.Event()), .1)


def test_fetch_worker_has_no_inference_edge():
    import ast
    from pathlib import Path
    tree = ast.parse(Path("backend/app/main.py").read_text())
    worker = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "background_camera_fetch_worker_loop")
    calls = [getattr(n.func, "attr", getattr(n.func, "id", "")) for n in ast.walk(worker) if isinstance(n, ast.Call)]
    assert "enqueue_vision_job" not in calls
    assert "process_all_cameras_vision" not in calls
    assert "record_result" in calls


@pytest.mark.asyncio
async def test_distinct_camera_concurrency_and_capacity(monkeypatch):
    monkeypatch.setattr(settings, "CAMERA_PROXY_MAX_CONCURRENCY", 2)
    monkeypatch.setattr(settings, "CAMERA_PROXY_MAX_PENDING", 2)
    monkeypatch.setattr(settings, "CAMERA_PROXY_MAX_CACHED_FRAMES", 1)
    running = 0
    maximum = 0
    release = asyncio.Event()
    async def source(request):
        nonlocal running, maximum
        running += 1
        maximum = max(maximum, running)
        await release.wait()
        running -= 1
        return httpx.Response(200, content=image_bytes(), headers={"content-type":"image/jpeg"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(source)) as client:
        proxy = CameraProxy(client)
        tasks = [asyncio.create_task(proxy.get_frame(f"{index:024x}")) for index in range(2)]
        while running < 2:
            await asyncio.sleep(.001)
        with pytest.raises(CameraProxyError, match="PROXY_BUSY"):
            await proxy.get_frame(f"{3:024x}")
        release.set()
        await asyncio.gather(*tasks)
        assert maximum == 2
        assert len(proxy.frames) == 1
        assert not proxy.pending


@pytest.mark.asyncio
async def test_restrictions_trip_shared_portal_breaker():
    calls = []
    def source(request):
        calls.append(request)
        return httpx.Response(403)
    async with httpx.AsyncClient(transport=httpx.MockTransport(source)) as client:
        proxy = CameraProxy(client)
        for index in range(4):
            with pytest.raises(CameraProxyError):
                await proxy.get_frame(f"{index:024x}")
        assert len(calls) == 3
        assert proxy.breaker.state == "OPEN"
        assert portal_circuit_breaker.state == ("OPEN" if settings.CAMERA_PROXY_PROVIDER == "hcmc" else "CLOSED")


def test_compressed_large_raster_is_rejected_before_pixel_conversion(monkeypatch):
    from backend.app.services.image_validator import validate_camera_image_bytes
    out = BytesIO()
    Image.new("L", (3000, 3000), 120).save(out, format="PNG")
    assert len(out.getvalue()) < 3_000_000
    def forbidden_conversion(*args, **kwargs):
        raise AssertionError("Oversized source must never be converted to pixel arrays")
    monkeypatch.setattr(Image.Image, "convert", forbidden_conversion)
    result = validate_camera_image_bytes(out.getvalue(), max_pixels=4_194_304)
    assert not result.is_valid
    assert result.status == "DIMENSIONS_TOO_LARGE"


@pytest.mark.asyncio
async def test_vietmap_works_when_hcmc_breaker_is_open(monkeypatch):
    monkeypatch.setattr(settings, "CAMERA_PROXY_PROVIDER", "vietmap")
    portal_circuit_breaker.state = "OPEN"
    from time import time
    portal_circuit_breaker.last_failure_time = time()
    calls = []
    def source(request):
        calls.append(request)
        return httpx.Response(200, content=image_bytes(), headers={"content-type":"image/jpeg"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(source)) as client:
        frame = await CameraProxy(client).get_frame(CAM)
    assert frame.provider == "vietmap"
    assert len(calls) == 1
    assert portal_circuit_breaker.state == "OPEN"


@pytest.mark.asyncio
async def test_source_rejection_never_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "CAMERA_PROXY_PROVIDER", "vietmap")
    calls = []
    def source(request):
        calls.append(request)
        return httpx.Response(403)
    async with httpx.AsyncClient(transport=httpx.MockTransport(source)) as client:
        with pytest.raises(CameraProxyError, match="UPSTREAM_RESTRICTED"):
            await CameraProxy(client).get_frame(CAM)
    assert len(calls) == 1 and calls[0].url.host == "cdn.vietmap.live"


def test_unsupported_provider_is_rejected_by_settings():
    from pydantic import ValidationError
    from backend.app.core.config import Settings
    with pytest.raises(ValidationError):
        Settings(CAMERA_PROXY_PROVIDER="https://localhost/private", _env_file=None)
