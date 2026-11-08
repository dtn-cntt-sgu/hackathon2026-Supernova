"""Read-only, on-demand reverse proxy for publicly viewable HCMC camera snapshots.

Designed for SafePath's existing FastAPI stack. This module DOES NOT perform AI
inference, persist images, bypass provider controls, or accept arbitrary URLs.

Use this in monitoring only when the upstream source permits your use.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic, time
from typing import Callable
from urllib.parse import urlparse
import re

import httpx


UPSTREAM_URL = "https://giaothong.hochiminhcity.gov.vn:8007/Render/CameraHandler.ashx"
UPSTREAM_REFERER = "https://giaothong.hochiminhcity.gov.vn/"
_ID_PATTERN = re.compile(r"^[0-9a-f]{24}$", re.IGNORECASE)
_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


class CameraProxyError(Exception):
    def __init__(self, reason: str, status_code: int = 502):
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


@dataclass(frozen=True)
class CameraProxyFrame:
    data: bytes
    content_type: str
    sha256_hex: str
    retrieved_at: datetime
    from_cache: bool = False


class CameraLiveProxy:
    """Bounded, single-flight cache on a fixed, permitted camera endpoint.

    Multi-worker deployments need shared throttling (e.g., Redis); this local
    cache protects only one application worker. No frame is labelled LIVE merely
    because it was retrieved recently; actual capture time is unverified.
    """

    def __init__(
        self,
        *,
        upstream_url: str = UPSTREAM_URL,
        referer: str = UPSTREAM_REFERER,
        ttl_seconds: float = 10.0,
        max_cached: int = 64,
        max_bytes: int = 3_000_000,
        concurrency: int = 4,
        timeout_seconds: float = 8.0,
        client: httpx.AsyncClient | None = None,
        validator: Callable[[bytes], bool] | None = None,
    ) -> None:
        parsed = urlparse(upstream_url)
        # A configuration mistake must not turn this endpoint into an open proxy.
        if (
            parsed.scheme != "https"
            or parsed.hostname != "giaothong.hochiminhcity.gov.vn"
            or parsed.port != 8007
            or parsed.path != "/Render/CameraHandler.ashx"
            or parsed.username or parsed.password or parsed.query or parsed.fragment
        ):
            raise ValueError("Only the fixed official camera handler is allowed")
        if not (1 <= max_cached <= 256 and 4096 <= max_bytes <= 10_000_000):
            raise ValueError("Invalid cache capacity or byte limit")
        self.upstream_url = upstream_url
        self.referer = referer
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self.max_cached = max_cached
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self._client = client
        self._validator = validator
        self._cache: OrderedDict[str, tuple[float, CameraProxyFrame]] = OrderedDict()
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(concurrency)

    async def get_frame(self, cam_id: str) -> CameraProxyFrame:
        if not isinstance(cam_id, str) or not _ID_PATTERN.fullmatch(cam_id):
            raise CameraProxyError("INVALID_CAMERA_ID", 400)
        cam_id = cam_id.lower()
        cached = self._read_cache(cam_id)
        if cached is not None:
            return replace(cached, from_cache=True)

        async with self._guard:
            lock = self._locks.setdefault(cam_id, asyncio.Lock())
        async with lock:
            cached = self._read_cache(cam_id)
            if cached is not None:
                return replace(cached, from_cache=True)
            frame = await self._fetch(cam_id)
            self._cache[cam_id] = (monotonic() + self.ttl_seconds, frame)
            self._cache.move_to_end(cam_id)
            while len(self._cache) > self.max_cached:
                evicted_id, _ = self._cache.popitem(last=False)
                if evicted_id != cam_id:
                    self._locks.pop(evicted_id, None)
            return frame

    def _read_cache(self, cam_id: str) -> CameraProxyFrame | None:
        entry = self._cache.get(cam_id)
        if not entry:
            return None
        expiry, frame = entry
        if monotonic() >= expiry:
            self._cache.pop(cam_id, None)
            return None
        self._cache.move_to_end(cam_id)
        return frame

    async def _fetch(self, cam_id: str) -> CameraProxyFrame:
        headers = {
            "Accept": "image/jpeg,image/png,image/webp",
            "Accept-Language": "vi,en;q=0.8",
            "Referer": self.referer,
            "User-Agent": "SafePathCameraViewer/1.0",
        }
        owned_client = self._client is None
        client = self._client or httpx.AsyncClient(
            verify=True,
            follow_redirects=False,
            timeout=httpx.Timeout(self.timeout_seconds, connect=3.0),
        )
        try:
            async with self._semaphore:
                async with client.stream(
                    "GET", self.upstream_url,
                    params={"id": cam_id, "_": int(time())},
                    headers=headers,
                    follow_redirects=False,
                ) as response:
                    if response.status_code in (403, 429):
                        raise CameraProxyError("UPSTREAM_RESTRICTED", 503)
                    if response.status_code != 200:
                        raise CameraProxyError("UPSTREAM_ERROR")
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if content_type not in _MIME_TYPES:
                        raise CameraProxyError("NOT_AN_IMAGE")
                    chunks: list[bytes] = []
                    total_bytes = 0
                    async for chunk in response.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > self.max_bytes:
                            raise CameraProxyError("FRAME_TOO_LARGE")
                        chunks.append(chunk)
                    content = b"".join(chunks)
        except CameraProxyError:
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise CameraProxyError("UPSTREAM_UNAVAILABLE") from exc
        finally:
            if owned_client:
                await client.aclose()

        if not content:
            raise CameraProxyError("EMPTY_FRAME")
        if self._validator is None:
            # Reuse SafePath's existing Zero-Mock / placeholder validation.
            from backend.app.services.image_validator import validate_camera_image_bytes
            valid = bool(validate_camera_image_bytes(content).is_valid)
        else:
            valid = self._validator(content)
        if not valid:
            raise CameraProxyError("INVALID_OR_PLACEHOLDER_FRAME")
        return CameraProxyFrame(
            data=content,
            content_type=content_type,
            sha256_hex=sha256(content).hexdigest(),
            retrieved_at=datetime.now(timezone.utc),
        )


camera_live_proxy = CameraLiveProxy()
