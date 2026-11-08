"""Bounded, original-byte camera viewing; no vision dependency or arbitrary URLs."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import re
from time import monotonic, time
from urllib.parse import urlparse

import httpx

from backend.app.core.config import settings
from backend.app.services.camera_url_resolver import get_canonical_camera_url, get_default_camera_headers
from backend.app.services.image_validator import validate_camera_image_bytes
from backend.app.services.scraper import CircuitBreaker, portal_circuit_breaker

CAMERA_ID = re.compile(r"^[0-9a-fA-F]{24}$")


class CameraProxyError(Exception):
    def __init__(self, code: str, status: str = "FETCH_FAILED", http_status: int = 502):
        super().__init__(code)
        self.code, self.status, self.http_status = code, status, http_status


@dataclass(frozen=True)
class ProxyFrame:
    data: bytes
    content_type: str
    content_hash: str
    retrieved_at: datetime
    source_status: str = "RECENTLY_RETRIEVED_CAPTURE_UNKNOWN"
    upstream_error: str = ""
    provider: str = ""
    source_url: str = ""


class CameraProxy:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client
        self.provider = settings.CAMERA_PROXY_PROVIDER
        # Provider restrictions must not disable a separately selected source.
        self.breaker = CircuitBreaker() if self.provider == "vietmap" else portal_circuit_breaker
        self.frames: OrderedDict[str, ProxyFrame] = OrderedDict()
        self.failures: OrderedDict[str, tuple[float, CameraProxyError]] = OrderedDict()
        self.pending: dict[str, asyncio.Task] = {}
        self.semaphore = asyncio.Semaphore(settings.CAMERA_PROXY_MAX_CONCURRENCY)
        self.pacing = asyncio.Lock()
        self.next_request_at = 0.0

    async def get_frame(self, cam_id: str) -> ProxyFrame:
        if not CAMERA_ID.fullmatch(cam_id):
            raise CameraProxyError("INVALID_CAMERA_ID", http_status=400)
        cam_id = cam_id.lower()
        frame = self.frames.get(cam_id)
        age = (datetime.now(timezone.utc) - frame.retrieved_at).total_seconds() if frame else float("inf")
        if frame and age < settings.CAMERA_PROXY_CACHE_TTL_SECONDS:
            self.frames.move_to_end(cam_id)
            return frame
        failure = self.failures.get(cam_id)
        if failure and monotonic() < failure[0]:
            return self._stale_or_raise(frame, failure[1])
        task = self.pending.get(cam_id)
        if task is None:
            if len(self.pending) >= settings.CAMERA_PROXY_MAX_PENDING:
                return self._stale_or_raise(frame, CameraProxyError("PROXY_BUSY", http_status=503))
            task = asyncio.create_task(self._retrieve(cam_id))
            self.pending[cam_id] = task
            def completed(done):
                self.pending.pop(cam_id, None)
                if not done.cancelled():
                    done.exception()  # Observe exceptions even when all viewers disconnect.
            task.add_done_callback(completed)
        try:
            return await asyncio.shield(task)
        except CameraProxyError as exc:
            return self._stale_or_raise(frame, exc)

    def _stale_or_raise(self, frame: ProxyFrame | None, error: CameraProxyError) -> ProxyFrame:
        if frame and (datetime.now(timezone.utc) - frame.retrieved_at).total_seconds() <= settings.CAMERA_PROXY_STALE_MAX_SECONDS:
            return replace(frame, source_status="STALE", upstream_error=error.code)
        raise error

    async def _retrieve(self, cam_id: str) -> ProxyFrame:
        try:
            # Includes semaphore/pacing wait in the total timeout budget.
            async with asyncio.timeout(settings.CAMERA_PROXY_TIMEOUT_SECONDS):
                async with self.semaphore:
                    async with self.pacing:
                        await asyncio.sleep(max(0., self.next_request_at - monotonic()))
                        if not self.breaker.can_request():
                            raise CameraProxyError("UPSTREAM_RESTRICTED", "RESTRICTED", 503)
                        self.next_request_at = monotonic() + settings.CAMERA_PROXY_MIN_REQUEST_INTERVAL_SECONDS
                    frame = await self._fetch(cam_id)
            self.frames[cam_id] = frame
            self.frames.move_to_end(cam_id)
            while len(self.frames) > settings.CAMERA_PROXY_MAX_CACHED_FRAMES:
                self.frames.popitem(last=False)
            self.failures.pop(cam_id, None)
            return frame
        except (TimeoutError, httpx.TimeoutException) as exc:
            error = CameraProxyError("UPSTREAM_TIMEOUT", http_status=504)
            self._remember_failure(cam_id, error)
            raise error from exc
        except httpx.TransportError as exc:
            error = CameraProxyError("UPSTREAM_UNAVAILABLE")
            self._remember_failure(cam_id, error)
            raise error from exc
        except CameraProxyError as exc:
            self._remember_failure(cam_id, exc)
            raise

    def _remember_failure(self, cam_id: str, error: CameraProxyError):
        self.failures[cam_id] = (monotonic() + settings.CAMERA_PROXY_FAILURE_BACKOFF_SECONDS, error)
        self.failures.move_to_end(cam_id)
        while len(self.failures) > settings.CAMERA_PROXY_MAX_CACHED_FRAMES * 2:
            self.failures.popitem(last=False)

    def source_url(self, cam_id: str) -> str:
        if not CAMERA_ID.fullmatch(cam_id):
            raise CameraProxyError("INVALID_CAMERA_ID", http_status=400)
        if self.provider == "vietmap":
            return f"https://cdn.vietmap.live/cctv/{cam_id.lower()}/snapshot"
        if self.provider != "hcmc":
            raise CameraProxyError("INVALID_UPSTREAM_CONFIGURATION", http_status=503)
        url = get_canonical_camera_url(cam_id.lower())
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname != "giaothong.hochiminhcity.gov.vn"
                or parsed.port != 8007 or parsed.path != "/Render/CameraHandler.ashx"
                or parsed.username or parsed.password or parsed.fragment):
            raise CameraProxyError("INVALID_UPSTREAM_CONFIGURATION", http_status=503)
        return url

    async def _fetch(self, cam_id: str) -> ProxyFrame:
        url = self.source_url(cam_id)
        if self.provider == "vietmap":
            headers = {"User-Agent": "SafePathCameraViewer/1.0"}
            url = httpx.URL(url).copy_add_param("t", str(int(time() * 1000)))
        else:
            headers = get_default_camera_headers()
            # Viewing never forwards provider credentials to either source.
            headers.pop("Cookie", None)
            url = httpx.URL(url).copy_add_param("_", str(int(time())))
        headers["Accept"] = "image/jpeg,image/png,image/webp"
        owned = self.client is None
        client = self.client or httpx.AsyncClient(verify=True, follow_redirects=False,
                                                 timeout=settings.CAMERA_PROXY_TIMEOUT_SECONDS)
        try:
            async with client.stream("GET", url, headers=headers,
                                     follow_redirects=False) as response:
                if response.status_code in (401, 403, 429):
                    self.breaker.record_failure(403 if response.status_code == 401 else response.status_code)
                    raise CameraProxyError("UPSTREAM_RESTRICTED", "RESTRICTED", 503)
                if response.status_code == 404:
                    raise CameraProxyError("UPSTREAM_OFFLINE", "OFFLINE", 404)
                if response.status_code != 200:
                    raise CameraProxyError("UPSTREAM_ERROR")
                mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if mime not in {"image/jpeg", "image/png", "image/webp"}:
                    raise CameraProxyError("NOT_AN_IMAGE")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(data) + len(chunk) > settings.CAMERA_PROXY_MAX_BYTES:
                        raise CameraProxyError("FRAME_TOO_LARGE")
                    data.extend(chunk)
        finally:
            if owned:
                await client.aclose()
        payload = bytes(data)
        validation = await asyncio.to_thread(validate_camera_image_bytes, payload, max_pixels=settings.CAMERA_PROXY_MAX_PIXELS)
        if not validation.is_valid:
            reason = str(validation.status)
            state = "PLACEHOLDER" if "PLACEHOLDER" in reason else "FETCH_FAILED"
            raise CameraProxyError("INVALID_OR_PLACEHOLDER_FRAME", state)
        # Serve the decoded format, rather than trusting a mismatched upstream MIME.
        mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(validation.format, mime)
        self.breaker.record_success()
        return ProxyFrame(payload, mime, sha256(payload).hexdigest(), datetime.now(timezone.utc),
                          provider=self.provider, source_url=self.source_url(cam_id))

    async def close(self):
        tasks = list(self.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
