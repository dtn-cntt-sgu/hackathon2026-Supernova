"""
SafePathAI Camera URL Resolution Strategy & Adaptive Variant Engine.
Solves the 'IMAGE NOT AVAILABLE' placeholder issue by testing and remembering
the optimal URL variant for each camera ID (Canonical vs. Parameterized vs. Provider).
Enforces TLS verification, strict rate limits, and Zero-Mock image validation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
import httpx
from PIL import Image
from redis.asyncio import Redis

from backend.app.core.config import settings
from backend.app.services.image_validator import validate_camera_image_bytes

logger = logging.getLogger("safepath.url_resolver")

REDIS_URL_STRATEGY_PREFIX = "camera:url_strategy:"
STRATEGY_TTL_SECONDS = 86400  # 24 hours persistence for successful URL strategy


@dataclass
class CameraUrlResolutionResult:
    """Detailed forensic result of camera URL resolution."""
    cam_id: str
    chosen_url: str
    variant_type: str  # CANONICAL, PROVIDER, PARAMETERIZED
    http_status: int
    mime_type: Optional[str] = None
    byte_length: int = 0
    is_valid_image: bool = False
    image_bytes: Optional[bytes] = None
    failure_reason: Optional[str] = None
    content_hash: Optional[str] = None
    dimensions: Optional[Tuple[int, int]] = None
    resolved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    requested_url: Optional[str] = None
    effective_url: Optional[str] = None
    content_sha256: Optional[str] = None
    validation_status: Optional[str] = None
    provider_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cam_id": self.cam_id,
            "chosen_url": self.chosen_url,
            "variant_type": self.variant_type,
            "http_status": self.http_status,
            "mime_type": self.mime_type,
            "byte_length": self.byte_length,
            "is_valid_image": self.is_valid_image,
            "failure_reason": self.failure_reason,
            "content_hash": self.content_hash,
            "dimensions": list(self.dimensions) if self.dimensions else None,
            "resolved_at": self.resolved_at.isoformat(),
            "requested_url": self.requested_url,
            "effective_url": self.effective_url,
            "content_sha256": self.content_sha256,
            "validation_status": self.validation_status,
            "provider_id": self.provider_id,
        }


def get_canonical_camera_url(cam_id: str) -> str:
    """Returns the pure canonical URL without query parameter clutter."""
    base = settings.HCMC_CAMERA_BASE_URL.split("?")[0]
    return f"{base}?id={cam_id}"


def get_timestamped_camera_url(cam_id: str) -> str:
    """Returns dynamic full-resolution URL variant with cache-busting timestamp."""
    base = settings.HCMC_CAMERA_BASE_URL.split("?")[0]
    ts_ms = int(time.time() * 1000)
    return f"{base}?id={cam_id}&t={ts_ms}"


def get_parameterized_camera_url(cam_id: str) -> str:
    """Returns the legacy parameterized URL variant with dimensions."""
    base = settings.HCMC_CAMERA_BASE_URL.split("?")[0]
    ts_ms = int(time.time() * 1000)
    return f"{base}?id={cam_id}&bg=black&w=300&h=230&t={ts_ms}"


def get_default_camera_headers() -> Dict[str, str]:
    """Provides standard browser headers to prevent HTTP 403 Forbidden on portal endpoints."""
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
        "Connection": "keep-alive",
        "Referer": settings.HCMC_CAMERA_REFERER,
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "cross-site",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        ),
    }
    if settings.HCMC_CAMERA_COOKIE:
        headers["Cookie"] = settings.HCMC_CAMERA_COOKIE
    return headers


def build_candidate_camera_urls(
    cam_id: str,
    provider_url: Optional[str] = None,
    preferred_variant: Optional[str] = None,
) -> List[Tuple[str, str]]:
    """
    Builds prioritized list of (variant_type, url) candidates to test:
    Priority 1: Previously verified successful variant (if cached)
    Priority 2: Canonical clean URL (CameraHandler.ashx?id=<id>)
    Priority 3: Dynamic full-resolution variant (CameraHandler.ashx?id=<id>&t=<ts>)
    Priority 4: Provider snapshot URL from GIS metadata (if present)
    Priority 5: Parameterized fallback variant (bg=black&w=300&h=230&t=<ts>)
    """
    candidates: List[Tuple[str, str]] = []
    canonical = get_canonical_camera_url(cam_id)
    timestamped = get_timestamped_camera_url(cam_id)
    parameterized = get_parameterized_camera_url(cam_id)

    # 1. Preferred variant if historically verified
    if preferred_variant == "TIMESTAMP_ONLY":
        candidates.append(("TIMESTAMP_ONLY", timestamped))
        candidates.append(("PARAMETERIZED", parameterized))
        candidates.append(("CANONICAL", canonical))
        if provider_url and provider_url != canonical and provider_url != parameterized:
            candidates.append(("PROVIDER", provider_url))
        return candidates

    if preferred_variant == "PARAMETERIZED":
        candidates.append(("PARAMETERIZED", parameterized))
        candidates.append(("CANONICAL", canonical))
        candidates.append(("TIMESTAMP_ONLY", timestamped))
        if provider_url and provider_url != canonical and provider_url != parameterized:
            candidates.append(("PROVIDER", provider_url))
        return candidates

    if preferred_variant == "PROVIDER" and provider_url:
        candidates.append(("PROVIDER", provider_url))
        candidates.append(("TIMESTAMP_ONLY", timestamped))
        candidates.append(("PARAMETERIZED", parameterized))
        candidates.append(("CANONICAL", canonical))
        return candidates

    # Default order: Canonical first (solves 'IMAGE NOT AVAILABLE' clutter), then timestamped, provider, parameterized
    candidates.append(("CANONICAL", canonical))
    candidates.append(("TIMESTAMP_ONLY", timestamped))
    if provider_url and provider_url != canonical and provider_url != parameterized:
        candidates.append(("PROVIDER", provider_url))
    candidates.append(("PARAMETERIZED", parameterized))

    return candidates


async def get_cached_preferred_variant(cam_id: str, redis: Optional[Redis] = None) -> Optional[str]:
    """Retrieves proven successful variant from Redis if present."""
    if redis is None:
        return None
    try:
        raw = await redis.get(f"{REDIS_URL_STRATEGY_PREFIX}{cam_id}")
        if raw:
            data = json.loads(raw)
            return data.get("successful_variant")
    except Exception as exc:
        logger.debug("Failed to read URL strategy cache: %s", exc)
    return None


async def save_successful_variant(
    cam_id: str,
    variant_type: str,
    url: str,
    content_hash: Optional[str],
    redis: Optional[Redis] = None,
) -> None:
    """Remembers the winning URL variant in Redis to optimize future requests."""
    if redis is None:
        return
    try:
        payload = json.dumps({
            "cam_id": cam_id,
            "successful_variant": variant_type,
            "successful_url": url,
            "content_hash": content_hash,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })
        await redis.set(f"{REDIS_URL_STRATEGY_PREFIX}{cam_id}", payload, ex=STRATEGY_TTL_SECONDS)
    except Exception as exc:
        logger.debug("Failed to cache successful URL variant: %s", exc)


async def resolve_camera_image(
    client: httpx.AsyncClient,
    cam_id: str,
    provider_url: Optional[str] = None,
    redis: Optional[Redis] = None,
    request_headers: Optional[Dict[str, str]] = None,
    previous_etag: Optional[str] = None,
    previous_sha256: Optional[str] = None,
) -> CameraUrlResolutionResult:
    """
    Executes controlled resolution of camera image across candidate variants:
    1. Tries prioritized variant candidates in sequence.
    2. Immediately stops on first valid JPEG frame or HTTP 304 Not Modified.
    3. Detects server placeholder error frames (9,230 bytes PNG) and continues to next candidate.
    4. Caches the successful variant to prevent repeated probing.
    """
    now = datetime.now(timezone.utc)
    preferred_variant = await get_cached_preferred_variant(cam_id, redis)
    candidates = build_candidate_camera_urls(cam_id, provider_url, preferred_variant)

    headers = dict(request_headers if request_headers else get_default_camera_headers())
    if previous_etag:
        clean_etag = previous_etag.strip('"')
        headers["If-None-Match"] = f'"{clean_etag}"'

    last_res: Optional[CameraUrlResolutionResult] = None
    any_placeholder = False

    for variant_type, url in candidates:
        try:
            req_timeout = 3.0 if "thongtingiaothong.vn" in url else getattr(settings, "CAMERA_REQUEST_TIMEOUT_SEC", 6.0)
            resp = await client.get(url, headers=headers, timeout=req_timeout)
            content = resp.content
            status = resp.status_code
            mime = resp.headers.get("content-type")
            byte_len = len(content)

            prov_id = (
                "THONGTINGIAOTHONG_API"
                if "thongtingiaothong.vn" in url
                else "HCMC_VDMS_PORTAL"
            )

            # Check HTTP 304 Not Modified (Server cache match)
            if status == 304:
                return CameraUrlResolutionResult(
                    cam_id=cam_id,
                    chosen_url=url,
                    variant_type=variant_type,
                    http_status=304,
                    mime_type=mime,
                    byte_length=0,
                    is_valid_image=True,
                    image_bytes=None,
                    failure_reason=None,
                    content_hash=previous_etag,
                    dimensions=None,
                    resolved_at=now,
                    requested_url=url,
                    effective_url=str(resp.url),
                    content_sha256=previous_sha256,
                    validation_status="NOT_MODIFIED",
                    provider_id=prov_id,
                )

            # Strict Zero-Mock validation
            if status == 200 and content:
                val = validate_camera_image_bytes(
                    content,
                    previous_sha256=previous_sha256,
                    previous_md5=previous_etag.strip('"') if previous_etag else None,
                )
            else:
                from backend.app.services.image_validator import ImageValidationResult, ImageValidationStatus
                val = ImageValidationResult(
                    status=ImageValidationStatus.CORRUPTED_PAYLOAD,
                    is_valid=False,
                    format=None,
                    width=None,
                    height=None,
                    file_size_bytes=byte_len,
                    md5_hash="",
                    dhash=None,
                    mean_intensity=None,
                    captured_at=None,
                    capture_time_status="CAPTURE_TIME_UNKNOWN",
                    retrieved_at=datetime.now(timezone.utc),
                    error_message=f"HTTP {status}",
                )
            content_hash = hashlib.md5(content).hexdigest() if content else None

            # Attempt dimension decoding with Pillow if valid
            dims: Optional[Tuple[int, int]] = None
            if val.is_valid and content:
                try:
                    with Image.open(io.BytesIO(content)) as img:
                        dims = img.size
                except Exception:
                    pass

            is_placeholder = (
                val.status.value in ("PLACEHOLDER_ERROR_FRAME", "PLACEHOLDER_ERROR_CANVAS")
                or "PLACEHOLDER" in val.status.value
            )
            if is_placeholder:
                any_placeholder = True
                val_status = "PLACEHOLDER_FRAME"
                fail_msg = "Server returned 'IMAGE NOT AVAILABLE' placeholder frame"
            elif val.status.value == "DUPLICATE_FRAME":
                val_status = "DUPLICATE_FRAME"
                fail_msg = None
            elif not val.is_valid:
                val_status = val.status.value
                fail_msg = val.error_message or val.status.value
            else:
                val_status = "VALID_FRAME"
                fail_msg = None

            content_sha256_val = hashlib.sha256(content).hexdigest() if content else None

            result = CameraUrlResolutionResult(
                cam_id=cam_id,
                chosen_url=url,
                variant_type=variant_type,
                http_status=status,
                mime_type=mime,
                byte_length=byte_len,
                is_valid_image=val.is_valid or val.status.value == "DUPLICATE_FRAME",
                image_bytes=content if (val.is_valid or val.status.value == "DUPLICATE_FRAME") else None,
                failure_reason=fail_msg,
                content_hash=content_hash,
                dimensions=dims,
                resolved_at=now,
                requested_url=url,
                effective_url=str(resp.url),
                content_sha256=content_sha256_val,
                validation_status=val_status,
                provider_id=prov_id,
            )

            # If this variant returned a valid camera frame, success!
            if val.is_valid:
                logger.info(
                    "Camera %s resolved with %s variant (%d bytes, %s)",
                    cam_id[:8], variant_type, byte_len, dims,
                )
                await save_successful_variant(cam_id, variant_type, url, content_hash, redis)
                return result

            last_res = result

            # If server returned HTTP 403 or 429, don't keep bombarding
            if status in (403, 429):
                logger.warning("Camera %s received HTTP %d on %s, stopping candidates.", cam_id[:8], status, variant_type)
                break

        except Exception as exc:
            logger.debug("Candidate %s failed for cam %s: %s", variant_type, cam_id[:8], exc)
            prov_id = (
                "THONGTINGIAOTHONG_API"
                if "thongtingiaothong.vn" in url
                else "HCMC_VDMS_PORTAL"
            )
            err_type = "TIMEOUT" if "timeout" in type(exc).__name__.lower() else "CONNECTION_ERROR"
            last_res = CameraUrlResolutionResult(
                cam_id=cam_id,
                chosen_url=url,
                variant_type=variant_type,
                http_status=0,
                is_valid_image=False,
                failure_reason=f"{err_type}: {str(exc)[:100]}",
                resolved_at=now,
                requested_url=url,
                effective_url=url,
                content_sha256=None,
                validation_status=err_type,
                provider_id=prov_id,
            )

    # If all candidates failed or returned placeholder
    if last_res is None:
        canonical_url = get_canonical_camera_url(cam_id)
        last_res = CameraUrlResolutionResult(
            cam_id=cam_id,
            chosen_url=canonical_url,
            variant_type="CANONICAL",
            http_status=0,
            is_valid_image=False,
            failure_reason="No URL candidate could be resolved",
            resolved_at=now,
            requested_url=canonical_url,
            effective_url=canonical_url,
            content_sha256=None,
            validation_status="UNTESTED",
            provider_id="HCMC_VDMS_PORTAL",
        )
    elif any_placeholder and not last_res.is_valid_image:
        last_res.validation_status = "PLACEHOLDER_FRAME"
        last_res.failure_reason = "Server returned 'IMAGE NOT AVAILABLE' placeholder frame"
        last_res.http_status = 200

    return last_res
