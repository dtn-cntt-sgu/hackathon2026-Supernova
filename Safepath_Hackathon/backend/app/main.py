"""
SafePathAI Core FastAPI Application and Real-Time WebSocket Server.
Exposes RESTful endpoints for routing, camera evidence, environmental observations,
and WebSocket streams for real-time traffic and flood alerts.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Tuple
import cv2
from pydantic import BaseModel, Field
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from geoalchemy2.elements import WKTElement
import httpx
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.auth import (
    create_user_session_token,
    verify_proxy_identity_signature,
    verify_user_session_token,
)
from backend.app.core.config import settings
from backend.app.core.observability import configure_json_logging, install_observability, metrics_response, observe_operation, set_gauge
from backend.app.db.models import (
    RoadSegment,
    TrafficCamera,
    User,
    UserPreference,
    UserRouteHistory,
    UserSavedPlace,
)
from backend.app.db.session import (
    AsyncSessionLocal,
    _is_testing_environment,
    close_db,
    get_db,
    get_redis_client,
    init_db,
)
from backend.app.schemas.contracts import (
    ActiveCameraRegisterRequest,
    ActiveCameraResponse,
    ActiveRouteRegisterRequest,
    CameraEvidence,
    CameraFreshnessStatus,
    CameraImageMetadata,
    CameraSummary,
    ConfidenceSummaryDTO,
    Coordinates,
    CreateRouteHistoryRequest,
    CreateSavedPlaceRequest,
    DataSourceStatus,
    EvidenceEligibility,
    ImageAccessStatus,
    ImageQualityAssessment,
    PlaceResult,
    PlaceSearchResponse,
    RiskLevel,
    RouteSearchRequest,
    SafeRouteResponse,
    TrafficDensityLevel,
    UserPreferenceDTO,
    UserProfileResponse,
    UserRouteHistoryDTO,
    UserSavedPlaceDTO,
    UserSyncRequest,
    WeatherTideSignal,
    WebSocketAlertMessage,
    build_camera_alert,
)
from backend.app.services.camera_scheduler import camera_scheduler
from backend.app.services.geocoding import reverse_geocode, search_places
from backend.app.services.image_validator import validate_camera_image_bytes
from backend.app.services.mcp_explanation import generate_route_explanation
from backend.app.services.routing import find_safe_route, RoutingError
from backend.app.services.scraper import (
    evict_stale_disk_images,
    is_valid_cam_id,
    portal_circuit_breaker,
    scrape_active_cameras,
)
from backend.app.services.vision import (
    DEFAULT_FLOOD_UNET_PATH,
    DEFAULT_YOLO_PATH,
    assess_image_quality,
    verified_model_manifest_entry,
)
from backend.app.services.weather_tide import (
    LocationWeatherResponse,
    fetch_location_weather,
    get_cached_weather_tide,
    get_combined_weather_tide,
    sync_weather_tide_to_redis,
)
from backend.app.services.hydrology_service import (
    hydrology_service,
    HydrologyStationMetadata,
    HydrologyLatestResponse,
    HydrologyObservationDTO,
)
from backend.app.services.traffic_news import (
    NearbyTrafficNewsResponse,
    TrafficNewsHighlightsResponse,
    TrafficNewsListResponse,
    TrafficNewsSummaryResponse,
    fetch_aggregated_hcm_traffic_news,
    get_nearby_traffic_news,
    get_traffic_news_highlights,
    get_traffic_news_summary,
    list_all_traffic_news,
)

logger = logging.getLogger("safepath.api")
logging.basicConfig(level=logging.INFO)
configure_json_logging()
# HTTPX info logs contain provider URLs, including secret query credentials.
logging.getLogger("httpx").setLevel(logging.WARNING)


# ==============================================================================
# Real-Time WebSocket Alert Broadcaster
# ==============================================================================
class AlertBroadcaster:
    """Manages active WebSocket client connections and broadcasts alerts."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info("WebSocket client connected. Active: %d", len(self.active_connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info("WebSocket client disconnected. Active: %d", len(self.active_connections))

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Broadcasts a JSON dictionary payload to all connected clients."""
        async with self._lock:
            dead_connections = set()
            for connection in self.active_connections:
                try:
                    await connection.send_json(message)
                except Exception as exc:
                    logger.warning("Failed to send WebSocket message: %s", exc)
                    dead_connections.add(connection)
            self.active_connections.difference_update(dead_connections)


broadcaster = AlertBroadcaster()


# ==============================================================================
# Decoupled Background Workers (Fetch, Vision, Weather, News)
# ==============================================================================


async def acquire_or_renew_worker_leader_lock(
    redis: Optional[Redis],
    worker_name: str,
    instance_id: str,
    ttl_seconds: int = 90,
) -> bool:
    """
    Ensures only one backend process/worker runs singleton background daemons
    when horizontally scaled or started with multiple Uvicorn workers (R01).
    """
    if redis is None:
        return True
    lock_key = f"safepath:leader:{worker_name}"
    try:
        current_holder = await redis.get(lock_key)
        if current_holder is not None:
            holder_str = current_holder.decode() if isinstance(current_holder, bytes) else str(current_holder)
            if holder_str == instance_id:
                await redis.expire(lock_key, ttl_seconds)
                return True
            return False
        acquired = await redis.set(lock_key, instance_id, ex=ttl_seconds, nx=True)
        return bool(acquired)
    except Exception as exc:
        logger.debug("Worker leader lock check degraded for %s: %s", worker_name, exc)
        return True


async def background_camera_fetch_worker_loop(stop_event: asyncio.Event) -> None:
    """
    Autonomous Fetch Scheduler:
    - Rotates across all 796 verified PostGIS camera nodes with 10-minute target cycle (600s).
    - Paces requests (~14 cameras per batch every 10 seconds) within provider rate limits.
    - Applies CameraUrlResolver (canonical first, then variants) to recover camera images.
    - Stores validated frames and metadata only; route requests own inference.
    """
    instance_id = f"pid-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    logger.info("Starting background camera fetch worker daemon (10m / 600s target cycle, instance=%s)...", instance_id)
    last_eviction_time = 0.0
    while not stop_event.is_set():
        try:
            # Evict stale snapshots past retention threshold once every 5 minutes (purges frames older than 1 hour)
            now_ts = time.time()
            if (now_ts - last_eviction_time) > 300.0:
                last_eviction_time = now_ts
                try:
                    evicted = evict_stale_disk_images("storage/cams", max_hours=1.0)
                    if evicted > 0:
                        logger.info("Evicted %d stale camera snapshots from disk cache.", evicted)
                    async with AsyncSessionLocal() as purge_session:
                        purged_rows = await camera_scheduler.purge_expired_camera_snapshots(purge_session, max_age_seconds=3600)
                        if purged_rows > 0:
                            logger.info("Purged %d expired snapshots past 1 hour from DB.", purged_rows)
                except Exception as e:
                    logger.debug("Disk eviction skipped: %s", e)

            can_scrape = (
                bool(getattr(settings, "CAMERA_INGESTION_ENABLED", True))
                and (settings.CAMERA_INGESTION_PERMITTED or settings.CAMERA_ALLOW_VIEW_ONLY)
            )
            if can_scrape and portal_circuit_breaker.can_request():
                redis = get_redis_client()
                try:
                    is_leader = await acquire_or_renew_worker_leader_lock(
                        redis, "camera_fetch", instance_id, ttl_seconds=max(90, int(settings.CAMERA_SCRAPE_INTERVAL_SEC) * 3)
                    )
                    if not is_leader:
                        logger.debug("Camera fetch skipped on follower instance %s", instance_id)
                        cams = []
                    else:
                        async with AsyncSessionLocal() as session:
                            cams = await camera_scheduler.acquire_batch(
                                session=session,
                                redis=redis,
                                batch_size=getattr(settings, "CAMERA_BATCH_SIZE", 14),
                                worker_id=f"safepath-fetch-{instance_id}",
                            )
                    if cams:
                        scraped = await scrape_active_cameras(cams, redis=redis)
                        async with AsyncSessionLocal() as session:
                            for s in scraped:
                                await camera_scheduler.record_result(session=session, res=s, redis=redis)

                except Exception as exc:
                    logger.warning("Camera fetch batch error: %s", exc)
                finally:
                    if redis is not None:
                        await redis.aclose()
            elif not can_scrape:
                logger.debug("Camera ingestion disabled by configuration.")
            else:
                logger.debug("Camera ingestion paused: portal circuit breaker is OPEN.")

            # Pacing delay: 18 seconds for ~100 batches per 1800s (30m)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=float(settings.CAMERA_SCRAPE_INTERVAL_SEC))
            except asyncio.TimeoutError:
                pass
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Error in camera fetch worker iteration: %s", exc)
            await asyncio.sleep(5.0)

    logger.info("Background camera fetch worker daemon stopped.")


async def background_vision_worker_loop(stop_event: asyncio.Event) -> None:
    """Compatibility entry point; persisted pre-refactor jobs must not run."""
    # Route inference is synchronous with ranking; legacy queued jobs are never consumed.
    logger.info("Background vision consumer disabled: inference is route-only.")


async def background_weather_worker_loop(stop_event: asyncio.Event) -> None:
    """
    Independent Weather & Tide Worker:
    Periodically syncs real-world Open-Meteo rain and tidal predictions
    on an independent 5-minute freshness schedule.
    """
    logger.info("Starting background weather & tide worker daemon...")
    while not stop_event.is_set():
        try:
            redis = get_redis_client()
            try:
                await sync_weather_tide_to_redis(redis_client=redis)
            except Exception as exc:
                logger.warning("Weather worker sync error: %s", exc)
            finally:
                if redis is not None:
                    await redis.aclose()

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=300.0)  # 5 minutes
            except asyncio.TimeoutError:
                pass
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Error in weather worker iteration: %s", exc)
            await asyncio.sleep(10.0)

    logger.info("Background weather & tide worker daemon stopped.")


async def background_hydrology_bulletin_worker_loop(stop_event: asyncio.Event) -> None:
    """Poll the official daily bulletin at a conservative cadence; no camera work."""
    from backend.app.services.hydrology_bulletin import ingest_latest_bulletin
    instance_id = f"hydrology-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    while not stop_event.is_set():
        redis = get_redis_client()
        try:
            if settings.HYDROLOGY_BULLETIN_ENABLED and await acquire_or_renew_worker_leader_lock(
                redis, "hydrology_bulletin", instance_id,
                ttl_seconds=settings.HYDROLOGY_BULLETIN_POLL_SECONDS + 60,
            ):
                async with AsyncSessionLocal() as session:
                    await ingest_latest_bulletin(session, redis)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Hydrology bulletin ingestion unavailable: %s", type(exc).__name__)
        finally:
            if redis is not None:
                await redis.aclose()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.HYDROLOGY_BULLETIN_POLL_SECONDS)
        except asyncio.TimeoutError:
            pass


async def background_news_worker_loop(stop_event: asyncio.Event) -> None:
    """
    Independent Traffic News Worker:
    Periodically aggregates, categorizes, and persists real traffic news & municipal alerts
    from verified sources on an independent 15-minute schedule.
    """
    logger.info("Starting background traffic news worker daemon...")
    while not stop_event.is_set():
        try:
            redis = get_redis_client()
            try:
                await fetch_aggregated_hcm_traffic_news()
            except Exception as exc:
                logger.warning("News worker aggregation error: %s", exc)
            finally:
                if redis is not None:
                    await redis.aclose()

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=900.0)  # 15 minutes
            except asyncio.TimeoutError:
                pass
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("Error in news worker iteration: %s", exc)
            await asyncio.sleep(30.0)

    logger.info("Background traffic news worker daemon stopped.")


# ==============================================================================
# Application Lifespan
# ==============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manages application startup and graceful shutdown."""
    logger.info("Initializing SafePathAI Backend Infrastructure...")
    try:
        await init_db()
    except Exception as exc:
        if settings.APP_ENV in {"staging", "production"}:
            raise
        logger.warning("Database initialization deferred: %s", type(exc).__name__)
    try:
        from backend.app.services.news_sources.hcm_geocoding import HcmPostgisGeocodingIndex
        await HcmPostgisGeocodingIndex.get_instance().ensure_loaded()
    except Exception as exc:
        logger.warning("Geocoding index prewarm deferred: %s", exc)
    from backend.app.services.camera_proxy import CameraProxy
    from backend.app.services.route_camera_ai import route_camera_ai
    route_camera_ai.reopen()
    app.state.camera_proxy_client = httpx.AsyncClient(verify=True, follow_redirects=False, timeout=settings.CAMERA_PROXY_TIMEOUT_SECONDS)
    app.state.camera_proxy = CameraProxy(app.state.camera_proxy_client)
    app.state.osrm_client = httpx.AsyncClient(timeout=8.0, limits=httpx.Limits(max_connections=100, max_keepalive_connections=20))

    stop_event = asyncio.Event()
    worker_tasks: List[asyncio.Task] = []
    if getattr(settings, "ENABLE_BACKGROUND_WORKERS", True) and os.getenv("TESTING", "").lower() not in ("true", "1", "yes"):
        worker_tasks = [
            asyncio.create_task(background_camera_fetch_worker_loop(stop_event)),
            asyncio.create_task(background_weather_worker_loop(stop_event)),
            asyncio.create_task(background_news_worker_loop(stop_event)),
            asyncio.create_task(background_hydrology_bulletin_worker_loop(stop_event)),
        ]

    yield

    # Teardown
    stop_event.set()
    for task in worker_tasks:
        task.cancel()
    await asyncio.gather(*worker_tasks, return_exceptions=True)

    from backend.app.services.route_camera_ai import route_camera_ai
    await route_camera_ai.close()
    await app.state.camera_proxy.close()
    await app.state.camera_proxy_client.aclose()
    await app.state.osrm_client.aclose()
    await close_db()
    logger.info("SafePathAI Backend Shutdown complete.")


# ==============================================================================
# FastAPI App Initialization & CORS
# ==============================================================================
app = FastAPI(
    title="SafePathAI Navigation Engine",
    description=(
        "Dynamic flood-aware traffic routing and computer vision surveillance API "
        "for Ho Chi Minh City."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

from backend.app.core.http_limits import RequestBodyLimit
app.add_middleware(RequestBodyLimit, max_bytes=settings.MAX_REQUEST_BODY_BYTES)
install_observability(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["ETag", "X-Camera-Source-Status", "X-Retrieved-At", "X-Snapshot-ID", "X-Upstream-Error", "X-Camera-Provider", "X-Camera-Source"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    try:
        if request.url.path.startswith("/api/v1/user/") and request.method != "OPTIONS":
            await enforce_rate_limit(request, "user", 60)
        response = await call_next(request)
    except HTTPException as exc:
        response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith(("/api/v1/user/", "/api/v1/admin/", "/api/v1/cameras/")):
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Request-ID"] = request.state.request_id
    return response


# ==============================================================================
# Rate Limiting & User Ownership Verification Helpers (B02, R07, R14)
# ==============================================================================
_local_rate_limit_windows: Dict[str, List[float]] = {}


async def enforce_rate_limit(
    request: Request,
    bucket: str,
    limit_per_minute: int,
) -> None:
    """
    Sliding-window per-client rate limiter for high-cost endpoints (R07).
    """
    if _is_testing_environment() and request.headers.get("X-Test-Enforce-Rate-Limit") != "1":
        return
    client_ip = request.client.host if request.client else "unknown"
    try:
        trusted = any(ipaddress.ip_address(client_ip) in ipaddress.ip_network(net) for net in settings.TRUSTED_PROXY_IPS)
        forwarded = request.headers.get("X-Forwarded-For", "").split(",")[-1].strip()
        if trusted and forwarded:
            client_ip = str(ipaddress.ip_address(forwarded))
    except ValueError:
        pass
    proxy_ip = request.headers.get("X-Proxy-Client-IP", "")
    proxy_timestamp = request.headers.get("X-Proxy-Timestamp", "")
    proxy_signature = request.headers.get("X-Proxy-Signature", "")
    try:
        expected = hmac.new(settings.AUTH_SECRET.encode(), f"client:{proxy_ip}:{proxy_timestamp}".encode(), hashlib.sha256).hexdigest()
        if abs(time.time() - int(proxy_timestamp)) <= 60 and hmac.compare_digest(expected.encode(), proxy_signature.encode()):
            client_ip = str(ipaddress.ip_address(proxy_ip))
    except ValueError:
        pass
    key = f"rate:{bucket}:{hashlib.sha256(client_ip.encode()).hexdigest()[:32]}"
    now_ts = time.time()
    redis = get_redis_client()
    try:
        count = await redis.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n", 1, key)
        if int(count) > limit_per_minute:
            raise HTTPException(429, detail={"code": "RATE_LIMIT_EXCEEDED"}, headers={"Retry-After": "60"})
        return
    except HTTPException:
        raise
    except Exception:
        if settings.APP_ENV in {"staging", "production"}:
            raise HTTPException(503, detail={"code": "RATE_LIMIT_SERVICE_UNAVAILABLE"})
    finally:
        if redis is not None:
            await redis.aclose()
    hits = [t for t in _local_rate_limit_windows.get(key, []) if t > now_ts - 60]
    if len(hits) >= limit_per_minute:
        raise HTTPException(429, detail={"code": "RATE_LIMIT_EXCEEDED"}, headers={"Retry-After": "60"})
    if len(_local_rate_limit_windows) >= 4096:
        for old in list(_local_rate_limit_windows):
            if not _local_rate_limit_windows[old] or _local_rate_limit_windows[old][-1] <= now_ts - 60:
                _local_rate_limit_windows.pop(old, None)
        if len(_local_rate_limit_windows) >= 4096:
            raise HTTPException(503, detail={"code": "RATE_LIMIT_CAPACITY"})
    _local_rate_limit_windows[key] = hits + [now_ts]


async def require_service_access(request: Request) -> None:
    token = request.headers.get("Authorization", "")
    expected = settings.SERVICE_AUTH_TOKEN
    if not expected or not hmac.compare_digest(token.encode(), ("Bearer " + expected).encode()):
        logger.warning("service_access_denied path=%s request_id=%s", request.url.path, getattr(request.state, "request_id", ""))
        raise HTTPException(401, detail={"code": "SERVICE_AUTH_REQUIRED"})
    await enforce_rate_limit(request, "service_write", 10)
    logger.info("service_access_authorized path=%s request_id=%s", request.url.path, getattr(request.state, "request_id", ""))


def verify_proxy_row_owner(user: User, email: Optional[str], provider_id: Optional[str], signature: Optional[str]) -> None:
    if not user.is_active:
        raise HTTPException(403, detail={"code": "ACCOUNT_DISABLED"})
    if signature and (not email or user.email.lower() != email.lower().strip()
                      or not provider_id or user.provider_account_id != provider_id.strip()):
        raise HTTPException(403, detail={"code": "FORBIDDEN_USER_MISMATCH"})


def verify_authenticated_user_access(
    target_user_id: Optional[str],
    authorization: Optional[str] = None,
    x_user_token: Optional[str] = None,
    x_auth_user_email: Optional[str] = None,
    x_auth_provider_id: Optional[str] = None,
    x_auth_timestamp: Optional[str] = None,
    x_auth_signature: Optional[str] = None,
    expected_user_email: Optional[str] = None,
    expected_provider_id: Optional[str] = None,
) -> str:
    """
    Enforces strict user ownership on `/api/v1/user/*` endpoints (B02, R14):
    1. If a signed session token (`Authorization: Bearer <token>` or `X-User-Token`) is present,
       validates its HMAC signature and checks that `token.sub == target_user_id` (or `token.pid == target_user_id`).
       If valid for User A but `target_user_id` is User B, raises 403 FORBIDDEN (prevents IDOR).
    2. If Next.js server-side proxy headers (`X-Auth-Signature`, `X-Auth-User-Email`, `X-Auth-Provider-Id`)
       are present, verifies the HMAC signature and checks identity match.
    3. Rejects invalid/forged tokens with 401 UNAUTHORIZED.
    """
    token_candidate = authorization or x_user_token
    if token_candidate:
        payload = verify_user_session_token(token_candidate)
        if payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_SESSION_TOKEN", "message": "Invalid or expired user session token."},
            )
        token_sub = str(payload.get("sub") or "")
        token_pid = str(payload.get("pid") or "")
        if target_user_id and target_user_id not in (token_sub, token_pid):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FORBIDDEN_USER_MISMATCH",
                    "message": "Authenticated token does not match requested X-User-Id / user_id.",
                },
            )
        return token_sub

    if x_auth_signature and x_auth_user_email and x_auth_timestamp:
        if not verify_proxy_identity_signature(
            email=x_auth_user_email,
            provider_account_id=x_auth_provider_id or "",
            timestamp_str=x_auth_timestamp,
            signature=x_auth_signature,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "INVALID_PROXY_SIGNATURE", "message": "Invalid proxy identity signature."},
            )
        if expected_user_email and x_auth_user_email.lower().strip() != expected_user_email.lower().strip():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN_USER_MISMATCH", "message": "Session email does not match target user."},
            )
        if expected_provider_id and x_auth_provider_id and x_auth_provider_id.strip() != expected_provider_id.strip():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN_USER_MISMATCH", "message": "Provider account ID mismatch."},
            )
        return target_user_id or ""

    raise HTTPException(401, detail={"code": "MISSING_SESSION_TOKEN", "message": "Signed session token required."})


async def authenticated_community_user(request: Request, session: AsyncSession = Depends(get_db)) -> User:
    headers = request.headers
    user_id = verify_authenticated_user_access(
        headers.get("x-user-id"), authorization=headers.get("authorization"),
        x_user_token=headers.get("x-user-token"), x_auth_user_email=headers.get("x-auth-user-email"),
        x_auth_provider_id=headers.get("x-auth-provider-id"), x_auth_timestamp=headers.get("x-auth-timestamp"),
        x_auth_signature=headers.get("x-auth-signature"),
    )
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(401, detail={"code": "UNAUTHORIZED"})
    verify_proxy_row_owner(user, headers.get("x-auth-user-email"), headers.get("x-auth-provider-id"), headers.get("x-auth-signature"))
    return user


from backend.app.api.community import build_community_router
app.include_router(build_community_router(authenticated_community_user, require_service_access, enforce_rate_limit))


@app.get("/api/v1/metrics", dependencies=[Depends(require_service_access)], include_in_schema=False)
async def metrics():
    return metrics_response()


# ==============================================================================
# REST Endpoints
# ==============================================================================
@app.get("/api/v1/models/status", tags=["Surveillance"])
async def model_status() -> Dict[str, Any]:
    """Expose weight provenance, benchmark scope, and deployment validation transparently (C09, C10)."""
    vehicle = verified_model_manifest_entry("vehicle_detector", DEFAULT_YOLO_PATH)
    flood = verified_model_manifest_entry("flood_segmenter", DEFAULT_FLOOD_UNET_PATH)
    return {
        "vehicle_detector": {
            "status": "VALIDATED" if vehicle and vehicle.get("deployment_validation") == "VALIDATED_HCMC" else ("EXPERIMENTAL" if vehicle else "MODEL_UNAVAILABLE"),
            "model_name": vehicle.get("model_name") if vehicle else None,
            "version": vehicle.get("version") if vehicle else None,
            "sha256": vehicle.get("sha256") if vehicle else None,
            "source_url": vehicle.get("source_url") if vehicle else None,
            "provenance_status": vehicle.get("provenance_status") if vehicle else None,
            "deployment_validation": vehicle.get("deployment_validation") if vehicle else None,
            "validation_scope": vehicle.get("validation_scope") if vehicle else None,
            "field_calibration_status": vehicle.get("field_calibration_status") if vehicle else None,
            "benchmark_metrics": vehicle.get("benchmark_metrics") if vehicle else None,
        },
        "flood_segmenter": {
            "status": "VALIDATED" if flood else "MODEL_UNAVAILABLE",
            "model_name": flood.get("model_name") if flood else None,
            "version": flood.get("version") if flood else None,
            "sha256": flood.get("sha256") if flood else None,
            "source_url": flood.get("source_url") if flood else None,
            "provenance_status": flood.get("provenance_status") if flood else None,
            "deployment_validation": flood.get("deployment_validation") if flood else None,
            "validation_scope": flood.get("validation_scope") if flood else None,
            "field_calibration_status": flood.get("field_calibration_status") if flood else None,
            "benchmark_metrics": flood.get("benchmark_metrics") if flood else None,
        },
    }


@app.get(
    "/api/v1/places/search",
    response_model=PlaceSearchResponse,
    summary="Search places, addresses, and POIs in TP.HCM",
    tags=["Geocoding"],
)
async def search_hcm_places(
    request: Request,
    q: str = Query(..., min_length=1, description="Address, street name, POI, or coordinates"),
    limit: int = Query(6, ge=1, le=15, description="Max results to return"),
    session: AsyncSession = Depends(get_db),
) -> PlaceSearchResponse:
    """
    Searches for real locations in TP. Hồ Chí Minh using Photon (Komoot OSM)
    with local PostGIS road segments fallback and coordinate parsing.
    Zero-Mock: Returns genuine geocoded results or empty list; never fabricates fake locations.
    """
    await enforce_rate_limit(request, "places_search", int(getattr(settings, "RATE_LIMIT_PLACES_PER_MINUTE", 120)))
    redis = get_redis_client()
    try:
        return await search_places(q=q, limit=limit, session=session, redis=redis)
    finally:
        if redis is not None:
            await redis.aclose()


@app.get(
    "/api/v1/places/reverse",
    response_model=PlaceResult,
    summary="Reverse geocode coordinates to an address or nearest road",
    tags=["Geocoding"],
)
async def reverse_hcm_place(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Latitude"),
    lng: float = Query(..., ge=-180.0, le=180.0, description="Longitude"),
    session: AsyncSession = Depends(get_db),
) -> PlaceResult:
    """
    Reverse geocodes a WGS84 point into an address or street name.
    """
    redis = get_redis_client()
    try:
        return await reverse_geocode(lat=lat, lng=lng, session=session, redis=redis)
    finally:
        if redis is not None:
            await redis.aclose()


@app.get(
    "/api/v1/live",
    summary="Container Liveness Probe",
    tags=["System"],
)
async def get_liveness() -> Dict[str, Any]:
    """Lightweight liveness check confirming FastAPI event loop is responsive (R10)."""
    return {
        "status": "alive",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get(
    "/api/v1/ready",
    summary="Infrastructure Readiness Probe",
    tags=["System"],
)
async def get_readiness(
    session: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Readiness probe verifying PostgreSQL and Redis connectivity (OSRM optional degraded)."""
    health_data = await get_health(session=session)
    core_ready = health_data.get("database") == "healthy" and health_data.get("redis") == "healthy"
    schema_status = "NOT_REQUIRED_FOR_DEVELOPMENT"
    if core_ready and settings.APP_ENV in {"staging", "production"}:
        from backend.app.db.session import check_schema_revision
        try:
            connection = await session.connection()
            await connection.run_sync(check_schema_revision)
            schema_status = "CURRENT"
        except Exception:
            core_ready = False
            schema_status = "MIGRATIONS_REQUIRED"
    models = await asyncio.to_thread(lambda: {
        "vehicle": bool(verified_model_manifest_entry("vehicle_detector", settings.VEHICLE_MODEL_PATH)),
        "flood": bool(verified_model_manifest_entry("flood_segmenter", DEFAULT_FLOOD_UNET_PATH)),
    })
    permission = settings.CAMERA_INGESTION_PERMITTED and settings.CAMERA_ROUTING_EVIDENCE_PERMITTED
    inference_status = "BLOCKED_BY_PERMISSION" if not permission else ("WEIGHTS_VERIFIED" if all(models.values()) else "MODEL_UNAVAILABLE")
    payload = {
        "ready": core_ready,
        "status": health_data.get("status") if core_ready else "not_ready",
        "database": health_data.get("database"), "schema": schema_status,
        "redis": health_data.get("redis"), "osrm": health_data.get("osrm"),
        "routing_ready": core_ready and health_data.get("osrm") == "available",
        "inference_status": inference_status, "model_weights_verified": models,
        "timestamp": health_data.get("timestamp"),
    }
    return JSONResponse(payload, status_code=200 if core_ready else 503)



@app.get(
    "/api/v1/health",
    summary="System Health & Infrastructure Status",
    tags=["System"],
)
async def get_health(
    session: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Returns live connectivity status for PostgreSQL/PostGIS, Redis, OSRM,
    and reports the true timestamp/age of the latest camera update (null if unobserved).
    Zero-Mock: Never fabricates timestamps or simulation fallbacks.
    """
    # 1. Check PostgreSQL
    db_status = "unhealthy"
    try:
        await session.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as exc:
        db_status = "unhealthy"

    # 2. Check Redis & retrieve true camera update age
    redis = get_redis_client()
    redis_status = "unhealthy"
    latest_update: Optional[str] = None
    camera_data_age_seconds: Optional[float] = None
    try:
        if await redis.ping():
            redis_status = "healthy"
            raw_ts = await redis.get("camera:latest_verified_update")
            if raw_ts:
                latest_update = raw_ts.decode() if isinstance(raw_ts, bytes) else str(raw_ts)
                try:
                    dt = datetime.fromisoformat(latest_update)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    camera_data_age_seconds = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
                except Exception:
                    pass
    except Exception as exc:
        redis_status = "unhealthy"
    finally:
        if redis is not None:
            await redis.aclose()

    # 3. Check OSRM
    osrm_status = "available"
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(f"{settings.OSRM_BASE_URL}/route/v1/driving/106.7,10.7;106.8,10.8")
            if resp.status_code != 200 or resp.json().get("code") != "Ok":
                osrm_status = "unavailable"
    except Exception:
        osrm_status = "unavailable"

    set_gauge("postgres_up", db_status == "healthy")
    set_gauge("redis_up", redis_status == "healthy")
    set_gauge("osrm_up", osrm_status == "available")
    set_gauge("camera_observation_age_seconds", camera_data_age_seconds if camera_data_age_seconds is not None else float("nan"))
    return {
        "status": "healthy" if db_status == "healthy" and redis_status == "healthy" and osrm_status == "available" else "degraded",
        "database": db_status,
        "redis": redis_status,
        "osrm": osrm_status,
        "last_camera_update": latest_update,
        "camera_data_age_seconds": camera_data_age_seconds,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get(
    "/api/v1/weather-tide",
    response_model=WeatherTideSignal,
    summary="Get current hydrometeorological signal (rain precipitation and tide level)",
    tags=["Environmental"],
)
async def get_weather_tide() -> WeatherTideSignal:
    """
    Returns current verified weather precipitation and tidal water level for HCMC.
    Zero-Mock: Missing metrics return None / UNAVAILABLE, never defaults to 0.0 mm/h or fake tide.
    """
    redis = get_redis_client()
    try:
        cached = await get_cached_weather_tide(redis)
        if cached:
            return cached
        signal = await get_combined_weather_tide(redis_client=redis)
        await sync_weather_tide_to_redis(signal=signal, redis_client=redis)
        return signal
    finally:
        if redis is not None:
            await redis.aclose()


@app.get(
    "/api/v1/weather/location",
    response_model=LocationWeatherResponse,
    summary="Get localized weather by exact GPS coordinates",
    tags=["Environmental"],
)
async def get_location_weather(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Latitude"),
    lng: float = Query(..., ge=-180.0, le=180.0, description="Longitude"),
) -> LocationWeatherResponse:
    """
    Returns localized weather (temperature, precipitation, wind, weather code)
    for any camera, user location, or route waypoint in HCMC.
    """
    redis = get_redis_client()
    try:
        return await fetch_location_weather(lat=lat, lng=lng, redis_client=redis)
    finally:
        if redis is not None:
            await redis.aclose()


# ==============================================================================
# Hydrology & Tidal Monitoring Endpoints (HCMC Stations)
# ==============================================================================

@app.get(
    "/api/v1/hydrology/stations",
    response_model=List[HydrologyStationMetadata],
    summary="List all registered HCMC hydrological observation stations",
    tags=["Hydrology"],
)
async def get_hydrology_stations() -> List[HydrologyStationMetadata]:
    """
    Returns metadata for all verified HCMC hydrological monitoring stations:
    Trạm Phú An (Sài Gòn River) and Trạm Nhà Bè (Đồng Điền / Nhà Bè River),
    including official coordinates, datum, and Decision 18/2021 alarm thresholds.
    """
    return hydrology_service.get_registered_stations()


@app.get(
    "/api/v1/hydrology/latest",
    response_model=HydrologyLatestResponse,
    summary="Get latest verified water levels and tidal alarm status for HCMC stations",
    tags=["Hydrology"],
)
async def get_latest_hydrology(
    session: AsyncSession = Depends(get_db),
) -> HydrologyLatestResponse:
    """
    Returns the latest verified observations across all HCMC stations with alarm levels:
    - Báo động I: 1.40m
    - Báo động II: 1.50m
    - Báo động III: 1.60m
    Quality status indicates OBSERVED_LIVE, OBSERVED_STALE, FORECAST, or UNAVAILABLE.
    """
    redis = get_redis_client()
    try:
        return await hydrology_service.get_latest_observations(session, redis)
    finally:
        if redis is not None:
            await redis.aclose()


@app.get("/api/v1/hydrology/bulletin", tags=["Hydrology"],
         summary="Latest official daily tide bulletin with observed extrema and forecasts")
async def get_hydrology_bulletin(session: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    from backend.app.services.hydrology_bulletin import get_latest_bulletin
    redis = get_redis_client()
    try:
        return await get_latest_bulletin(session, redis)
    finally:
        if redis is not None:
            await redis.aclose()


@app.get(
    "/api/v1/hydrology/history",
    response_model=List[HydrologyObservationDTO],
    summary="Get historical hydrology observations for a specific station",
    tags=["Hydrology"],
)
async def get_hydrology_history(
    station_id: str = Query(..., description="Station ID, e.g. tram_phu_an or tram_nha_be"),
    limit: int = Query(24, ge=1, le=168, description="Maximum number of historical observations"),
    session: AsyncSession = Depends(get_db),
) -> List[HydrologyObservationDTO]:
    """
    Returns historical water level records for the specified station in chronological order.
    """
    return await hydrology_service.get_station_history(session, station_id=station_id, limit=limit)


class IngestHydrologyRequest(BaseModel):
    bulletin_text: Optional[str] = Field(None, max_length=100000, description="Raw text of hydrographic bulletin in Vietnamese")


@app.post(
    "/api/v1/hydrology/ingest",
    response_model=List[HydrologyObservationDTO],
    summary="Ingest hydrological bulletin or trigger external observation fetch",
    tags=["Hydrology"],
)
async def trigger_hydrology_ingestion(
    authorized: None = Depends(require_service_access),
    payload: Optional[IngestHydrologyRequest] = None,
    session: AsyncSession = Depends(get_db),
) -> List[HydrologyObservationDTO]:
    """
    Parses and ingests hydrographic bulletin text or triggers external observation fetch,
    updating PostgreSQL and Redis caches.
    """
    redis = get_redis_client()
    bulletin_text = payload.bulletin_text if payload else None
    try:
        records = await hydrology_service.run_ingestion_cycle(session, redis, bulletin_text=bulletin_text)
        return [hydrology_service._model_to_dto(r) for r in records]
    finally:
        if redis is not None:
            await redis.aclose()


@app.get(
    "/api/v1/traffic-news/nearby",
    response_model=NearbyTrafficNewsResponse,
    summary="Get real-time nearby traffic news and incident alerts",
    tags=["Environmental"],
)
async def get_traffic_news_nearby(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Latitude"),
    lng: float = Query(..., ge=-180.0, le=180.0, description="Longitude"),
    radius_km: float = Query(3.0, ge=0.5, le=25.0, description="Radius in km"),
) -> NearbyTrafficNewsResponse:
    """
    Returns verified municipal and news alerts (traffic jams, floods, accidents)
    within radius_km from the requested coordinate.
    """
    redis = get_redis_client()
    try:
        return await get_nearby_traffic_news(lat=lat, lng=lng, radius_km=radius_km, redis_client=redis)
    finally:
        if redis is not None:
            await redis.aclose()


@app.get(
    "/api/v1/traffic-news/highlights",
    response_model=TrafficNewsHighlightsResponse,
    summary="Get verified high-signal traffic news highlights for hero and spotlight",
    tags=["Environmental"],
)
async def get_traffic_news_highlights_endpoint(
    limit: int = Query(5, ge=1, le=20, description="Highlight items count"),
) -> TrafficNewsHighlightsResponse:
    """
    Returns prioritized highlight articles (active hazards, verified locations, fresh images).
    """
    redis = get_redis_client()
    try:
        return await get_traffic_news_highlights(limit=limit, redis_client=redis)
    finally:
        if redis is not None:
            await redis.aclose()


@app.get(
    "/api/v1/traffic-news/summary",
    response_model=TrafficNewsSummaryResponse,
    summary="Get aggregated traffic news metrics, categories, and source statuses",
    tags=["Environmental"],
)
async def get_traffic_news_summary_endpoint() -> TrafficNewsSummaryResponse:
    """
    Returns statistics, incident breakdown by category, and real-time source statuses.
    """
    redis = get_redis_client()
    try:
        return await get_traffic_news_summary(redis_client=redis)
    finally:
        if redis is not None:
            await redis.aclose()


@app.get(
    "/api/v1/traffic-news",
    response_model=TrafficNewsListResponse,
    summary="Get verified traffic news and incident list with pagination and filters",
    tags=["Environmental"],
)
async def get_all_traffic_news(
    limit: int = Query(30, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    category: Optional[str] = Query(None, description="Filter by category (e.g. FLOOD, CONGESTION, ACCIDENT, ROAD_CLOSURE)"),
    timeframe: Optional[str] = Query(None, description="Filter by timeframe: 24h, 7d, 30d, all"),
    search: Optional[str] = Query(None, description="Search keyword in title, summary, street"),
    lat: Optional[float] = Query(None, ge=-90.0, le=90.0, description="Optional GPS latitude for proximity filter"),
    lng: Optional[float] = Query(None, ge=-180.0, le=180.0, description="Optional GPS longitude for proximity filter"),
    radius_km: Optional[float] = Query(None, ge=0.5, le=50.0, description="Proximity radius in km (default 5km)"),
) -> TrafficNewsListResponse:
    """
    Returns verified municipal and news alerts for HCMC with pagination, category, timeframe, and search filters.
    """
    redis = get_redis_client()
    try:
        return await list_all_traffic_news(
            limit=limit,
            offset=offset,
            category=category,
            timeframe=timeframe,
            search=search,
            lat=lat,
            lng=lng,
            radius_km=radius_km,
            redis_client=redis,
        )
    finally:
        if redis is not None:
            await redis.aclose()


@app.get(
    "/api/v1/admin/camera-ingestion/status",
    summary="Get camera ingestion health and scheduler metrics",
    tags=["Surveillance"],
)
@app.get(
    "/api/v1/admin/cameras/metrics",
    summary="Get camera ingestion health and scheduler metrics (alias)",
    tags=["Surveillance"],
)
async def get_camera_ingestion_status(
    authorized: None = Depends(require_service_access),
    session: AsyncSession = Depends(get_db),
):
    """
    Returns real-time telemetry from the Camera Ingestion Scheduler:
    registered, geolocated, tracked, live, stale, offline, placeholders excluded,
    and error code breakdowns without exposing internal credentials.
    """
    redis = get_redis_client()
    try:
        metrics = await camera_scheduler.get_metrics(session=session, redis=redis)
        return metrics
    finally:
        if redis is not None:
            await redis.aclose()


@app.get(
    "/api/v1/cameras/summary",
    response_model=CameraSummary,
    summary="Get camera network summary metrics",
    tags=["Surveillance"],
)
async def get_cameras_summary(
    session: AsyncSession = Depends(get_db),
) -> CameraSummary:
    """
    Returns verified operational statistics of the 796-node HCMC traffic camera network:
    total registered, GPS coverage, real-time availability, vision analysis status,
    and circuit breaker status.
    """
    now = datetime.now(timezone.utc)
    cycle_target_sec = getattr(settings, "CAMERA_REFRESH_TARGET_SEC", 600)
    recent_cycle = now - timedelta(seconds=cycle_target_sec)

    stmt = text("""
        SELECT 
            (SELECT count(*) FROM traffic_cameras) AS total_registered,
            (SELECT count(*) FROM traffic_cameras WHERE geom IS NOT NULL) AS valid_gps_count,
            (SELECT count(*) FROM camera_ingestion_state WHERE last_attempt_at IS NOT NULL) AS checked_count,
            (SELECT count(*) FROM camera_ingestion_state WHERE source_status IN ('LIVE', 'FRESH_VERIFIED', 'RECENTLY_FETCHED_UNVERIFIED') AND last_success_at >= :recent_cycle) AS valid_images_count,
            (SELECT count(*) FROM camera_ingestion_state WHERE source_status = 'STALE' OR (last_success_at IS NOT NULL AND last_success_at < :recent_cycle)) AS stale_images_count,
            (SELECT count(*) FROM camera_ingestion_state WHERE source_status IN ('OFFLINE', 'FETCH_FAILED', 'RESTRICTED')) AS unavailable_count,
            (SELECT count(*) FROM camera_ingestion_state WHERE model_status = 'INFERENCE_COMPLETED') AS analyzed_count,
            (SELECT count(*) FROM camera_ingestion_state WHERE last_attempt_at >= :recent_cycle) AS cycle_checked_count,
            (SELECT max(last_attempt_at) FROM camera_ingestion_state) AS last_scheduler_cycle,
            (SELECT count(*) FROM camera_ingestion_state WHERE source_status IN ('LIVE', 'FRESH_VERIFIED', 'RECENTLY_FETCHED_UNVERIFIED') OR http_status = 200) AS reachable_count,
            (SELECT count(*) FROM camera_ingestion_state WHERE last_retrieved_at >= :recent_cycle) AS fetched_recently_count,
            (SELECT count(*) FROM camera_ingestion_state WHERE source_status = 'FRESH_VERIFIED' OR (last_captured_at IS NOT NULL AND last_success_at >= :recent_cycle)) AS fresh_verified_count,
            (SELECT count(*) FROM camera_ingestion_state WHERE failure_count > 0 OR source_status IN ('FETCH_FAILED', 'OFFLINE', 'RESTRICTED')) AS fetch_failed_count,
            (SELECT count(*) FROM camera_ingestion_state WHERE last_captured_at IS NULL AND (last_success_at IS NOT NULL OR last_retrieved_at IS NOT NULL)) AS capture_time_unknown_count
    """)
    res = await session.execute(stmt, {"recent_cycle": recent_cycle})
    row = res.fetchone()

    total_registered = row.total_registered if row else 0
    valid_gps_count = row.valid_gps_count if row else 0
    checked_count = row.checked_count if row else 0
    valid_images_count = row.valid_images_count if row else 0
    stale_images_count = row.stale_images_count if row else 0
    unavailable_count = (row.unavailable_count if row else 0) + max(0, total_registered - checked_count)
    analyzed_count = row.analyzed_count if row else 0
    cycle_checked_count = row.cycle_checked_count if row else 0
    cycle_pending_count = max(0, total_registered - cycle_checked_count)
    last_scheduler_cycle = row.last_scheduler_cycle if row else None

    return CameraSummary(
        total_registered=total_registered,
        valid_gps_count=valid_gps_count,
        checked_count=checked_count,
        valid_images_count=valid_images_count,
        stale_images_count=stale_images_count,
        unavailable_count=unavailable_count,
        analyzed_count=analyzed_count,
        last_scheduler_cycle=last_scheduler_cycle,
        circuit_breaker_open=(portal_circuit_breaker.state == "OPEN"),
        cycle_target_sec=cycle_target_sec,
        cycle_checked_count=cycle_checked_count,
        cycle_pending_count=cycle_pending_count,
        registered_count=total_registered,
        reachable_count=row.reachable_count if row else 0,
        fetched_recently_count=row.fetched_recently_count if row else 0,
        fresh_verified_count=row.fresh_verified_count if row else 0,
        stale_count=stale_images_count,
        fetch_failed_count=row.fetch_failed_count if row else 0,
        capture_time_unknown_count=row.capture_time_unknown_count if row else 0,
    )


async def validate_priority_camera_ids(request: Request, cam_ids: List[str], session: AsyncSession) -> None:
    await enforce_rate_limit(request, "camera_priority", 30)
    ids = list(set(cam_ids))
    if not all(is_valid_cam_id(value) for value in ids):
        raise HTTPException(400, detail={"code": "INVALID_CAMERA_ID"})
    result = await session.execute(select(TrafficCamera.cam_id).where(TrafficCamera.cam_id.in_(ids)))
    if set(result.scalars().all()) != set(ids):
        raise HTTPException(404, detail={"code": "CAMERA_NOT_FOUND"})


@app.post(
    "/api/v1/cameras/active-view",
    response_model=ActiveCameraResponse,
    summary="Register camera IDs as actively viewed for 60s priority refresh",
    tags=["Surveillance"],
)
async def register_active_view(request: ActiveCameraRegisterRequest, http_request: Request, session: AsyncSession = Depends(get_db)) -> ActiveCameraResponse:
    """
    Registers cameras that the user is currently viewing in a modal or viewport.
    Places them in Tier 0 (Active Viewed) in Redis with automatic TTL expiration,
    allowing the scheduler to refresh them every 60 seconds.
    """
    await validate_priority_camera_ids(http_request, request.cam_ids, session)
    redis = get_redis_client()
    try:
        registered = await camera_scheduler.register_active_viewed_cameras(
            redis=redis,
            cam_ids=request.cam_ids,
            ttl_seconds=request.ttl_seconds,
        )
        viewed, route = await camera_scheduler.get_active_priority_camera_ids(redis)
        return ActiveCameraResponse(
            status="ok",
            registered_count=registered,
            active_viewed_count=len(viewed),
            active_route_count=len(route),
        )
    finally:
        if redis is not None:
            await redis.aclose()


@app.delete(
    "/api/v1/cameras/{cam_id}/active-view",
    summary="Unregister camera from active view priority",
    tags=["Surveillance"],
)
async def unregister_active_view(cam_id: str, http_request: Request, session: AsyncSession = Depends(get_db)) -> Dict[str, Any]:
    """
    Removes a camera from the active priority set when the user closes its modal or pans away.
    """
    await validate_priority_camera_ids(http_request, [cam_id], session)
    redis = get_redis_client()
    try:
        await camera_scheduler.unregister_active_viewed_camera(redis=redis, cam_id=cam_id)
        return {"status": "ok", "cam_id": cam_id}
    finally:
        if redis is not None:
            await redis.aclose()


@app.post(
    "/api/v1/cameras/active-route",
    response_model=ActiveCameraResponse,
    summary="Register cameras along navigation route corridor for priority refresh",
    tags=["Surveillance"],
)
async def register_active_route(request: ActiveRouteRegisterRequest, http_request: Request, session: AsyncSession = Depends(get_db)) -> ActiveCameraResponse:
    """
    Registers cameras situated along an active navigation route corridor.
    Places them in Tier 1 in Redis for prioritized 60-second refreshes while navigating.
    """
    await validate_priority_camera_ids(http_request, request.cam_ids, session)
    redis = get_redis_client()
    try:
        registered = await camera_scheduler.register_active_route_cameras(
            redis=redis,
            cam_ids=request.cam_ids,
            ttl_seconds=request.ttl_seconds,
        )
        viewed, route = await camera_scheduler.get_active_priority_camera_ids(redis)
        return ActiveCameraResponse(
            status="ok",
            registered_count=registered,
            active_viewed_count=len(viewed),
            active_route_count=len(route),
        )
    finally:
        if redis is not None:
            await redis.aclose()



@app.get(
    "/api/v1/cameras/districts",
    summary="Get camera count breakdown by district",
    tags=["Surveillance"],
)
async def get_camera_districts(
    session: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Returns the distribution of cameras across all municipal districts and unknown zones.
    """
    stmt = text("""
        SELECT 
            COALESCE(district, 'UNKNOWN_DISTRICT') AS district_name,
            COUNT(*) AS count
        FROM traffic_cameras
        WHERE geom IS NOT NULL
        GROUP BY COALESCE(district, 'UNKNOWN_DISTRICT')
        ORDER BY 
            CASE WHEN COALESCE(district, 'UNKNOWN_DISTRICT') = 'UNKNOWN_DISTRICT' THEN 1 ELSE 0 END,
            count DESC,
            district_name ASC;
    """)
    res = await session.execute(stmt)
    rows = res.fetchall()
    return [{"district": r.district_name, "count": r.count} for r in rows]


@app.get(
    "/api/v1/cameras",
    response_model=List[CameraEvidence],
    summary="List all traffic cameras and live evidence",
    tags=["Surveillance"],
)
async def list_cameras(
    district: Optional[str] = Query(None, description="Optional filter by district name"),
    bbox: Optional[str] = Query(None, description="west,south,east,north WGS84 map bounds"),
    limit: int = Query(1000, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> List[CameraEvidence]:
    """
    Returns registered cameras with verified GIS coordinates and their latest evidence state.
    Zero-Mock: Cameras without verified real-time observations remain at RiskLevel.UNKNOWN.
    """
    query_str = """
        SELECT 
            c.cam_id,
            c.code,
            c.name,
            c.district,
            ST_Y(c.geom) AS lat,
            ST_X(c.geom) AS lng,
            c.nearest_osm_way_id AS osm_way_id,
            c.coordinate_source_url,
            c.observed_osm_way_id,
            c.observed_edge_index,
            c.view_verification_source_url,
            c.line_of_sight_verified,
            c.snapshot_cam_status,
            s.source_status AS cis_source_status,
            s.http_status AS cis_http_status,
            s.validation_status AS cis_val_status,
            s.last_error_code AS cis_error_code,
            s.failure_reason AS cis_failure_reason,
            s.last_success_at AS cis_last_success_at,
            s.last_attempt_at AS cis_last_attempt_at,
            s.last_retrieved_at AS cis_last_retrieved_at,
            s.model_status AS cis_model_status
        FROM traffic_cameras c
        LEFT JOIN camera_ingestion_state s ON c.cam_id = s.cam_id
        WHERE c.geom IS NOT NULL
    """
    params: Dict[str, Any] = {}
    if district:
        if district in ("UNKNOWN_DISTRICT", "UNKNOWN", "Chưa xác định", "Chưa xác định quận/huyện"):
            query_str += " AND (c.district = 'UNKNOWN_DISTRICT' OR c.district IS NULL OR c.district = '')"
        else:
            query_str += " AND c.district = :district"
            params["district"] = district
    if bbox:
        try:
            west, south, east, north = (float(value) for value in bbox.split(","))
            if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
                raise ValueError("invalid bounds")
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail="bbox must be west,south,east,north in WGS84")
        query_str += " AND c.geom && ST_MakeEnvelope(:west, :south, :east, :north, 4326)"
        params.update({"west": west, "south": south, "east": east, "north": north})
    query_str += " ORDER BY c.cam_id ASC LIMIT :limit OFFSET :offset"
    params.update({"limit": limit, "offset": offset})

    stmt = text(query_str)
    result = await session.execute(stmt, params)
    rows = result.fetchall()

    redis = get_redis_client()
    evidence_list: List[CameraEvidence] = []
    now = datetime.now(timezone.utc)

    try:
        try:
            cached_values = await redis.mget([f"camera_evidence:{row.cam_id}" for row in rows]) if rows else []
        except Exception:
            cached_values = [None] * len(rows)
        for row, cached_raw in zip(rows, cached_values):
            cam_id = row.cam_id
            redis_data = None
            try:
                if cached_raw:
                    redis_data = json.loads(cached_raw)
                    if redis_data.get("source_status") not in ("LIVE", "RECENT", "STALE"):
                        redis_data = None
            except Exception:
                pass

            local_image_path = os.path.join("storage", "cams", f"{cam_id}.jpg")
            has_local_file = os.path.exists(local_image_path)
            if has_local_file:
                file_age = now.timestamp() - os.path.getmtime(local_image_path)
                if file_age > settings.CAMERA_MAX_IMAGE_AGE_SECONDS:
                    try:
                        os.remove(local_image_path)
                    except Exception:
                        pass
                    has_local_file = False

            if redis_data:
                # Expire redis snapshot evidence older than CAMERA_MAX_IMAGE_AGE_SECONDS (1 hour)
                raw_time = redis_data.get("captured_at") or redis_data.get("retrieved_at") or redis_data.get("fetched_at")
                redis_age_sec = 0.0
                if raw_time:
                    try:
                        dt = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
                        redis_age_sec = (now - dt).total_seconds()
                    except Exception:
                        pass
                if redis_age_sec > settings.CAMERA_MAX_IMAGE_AGE_SECONDS:
                    redis_data = None

            if redis_data:
                evidence = CameraEvidence(**redis_data)
                evidence.district = row.district
                # Requirement 7: Unverified view direction/LOS never decides risk; remains UNKNOWN
                if not row.line_of_sight_verified or not settings.CAMERA_ROUTING_EVIDENCE_PERMITTED:
                    evidence.risk_level = RiskLevel.UNKNOWN
                    evidence.evidence_eligibility = EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING
            else:
                spatial_status = (
                    "OBSERVED_SEGMENT_VERIFIED"
                    if row.line_of_sight_verified and row.observed_osm_way_id is not None
                    else "SPATIALLY_NEAR" if row.osm_way_id is not None
                    else "UNVERIFIED"
                )
                is_fresh = False
                if has_local_file:
                    file_age = now.timestamp() - os.path.getmtime(local_image_path)
                    is_fresh = (file_age <= settings.CAMERA_IMAGE_TTL_SECONDS)

                # Granular truthful classification from ingestion state
                if row.cis_val_status in ("PLACEHOLDER_FRAME", "PLACEHOLDER_ERROR_FRAME") or row.cis_error_code == "PLACEHOLDER_FRAME":
                    granular_status = "PLACEHOLDER_FRAME"
                    granular_reason = "PLACEHOLDER_FRAME"
                elif row.cis_http_status == 403 or row.cis_error_code == "HTTP_403":
                    granular_status = "HTTP_403"
                    granular_reason = "HTTP_403"
                elif row.cis_http_status == 404 or row.cis_error_code == "HTTP_404":
                    granular_status = "HTTP_404"
                    granular_reason = "HTTP_404"
                elif row.cis_http_status == 429 or row.cis_error_code == "HTTP_429":
                    granular_status = "HTTP_429"
                    granular_reason = "HTTP_429"
                elif row.cis_http_status and row.cis_http_status >= 500:
                    granular_status = "HTTP_5XX"
                    granular_reason = f"HTTP_{row.cis_http_status}"
                elif row.cis_error_code == "TIMEOUT" or (row.cis_failure_reason and "TIMEOUT" in str(row.cis_failure_reason).upper()):
                    granular_status = "TIMEOUT"
                    granular_reason = "TIMEOUT"
                elif row.cis_error_code == "CONNECTION_ERROR" or (row.cis_failure_reason and "CONNECTION" in str(row.cis_failure_reason).upper()):
                    granular_status = "CONNECTION_ERROR"
                    granular_reason = "CONNECTION_ERROR"
                elif row.cis_source_status == "ATTEMPTING":
                    granular_status = "ATTEMPTING"
                    granular_reason = "ATTEMPTING"
                elif row.cis_val_status == "UNTESTED" or row.cis_last_attempt_at is None:
                    granular_status = "NOT_YET_TESTED"
                    granular_reason = "NOT_YET_TESTED"
                else:
                    granular_status = "URL_UNVERIFIED"
                    granular_reason = row.cis_error_code or "URL_UNVERIFIED"

                if has_local_file:
                    img_status = "VALID_FRESH_IMAGE" if (is_fresh and row.cis_source_status == "LIVE") else "VALID_STALE_IMAGE"
                    img_reason = "VALID_IMAGE_CACHED"
                    source_st = DataSourceStatus.LIVE if (is_fresh and row.cis_source_status == "LIVE") else DataSourceStatus.STALE
                else:
                    img_status = granular_status
                    img_reason = granular_reason
                    source_st = DataSourceStatus.STALE

                evidence = CameraEvidence(
                    cam_id=cam_id,
                    code=row.code,
                    name=row.name,
                    district=row.district,
                    lat=row.lat,
                    lng=row.lng,
                    osm_way_id=row.osm_way_id,
                    coordinate_source_url=row.coordinate_source_url,
                    spatial_match_status=spatial_status,
                    observed_osm_way_id=row.observed_osm_way_id,
                    observed_edge_index=row.observed_edge_index,
                    view_verification_source_url=row.view_verification_source_url,
                    line_of_sight_verified=bool(row.line_of_sight_verified),
                    image_url=f"/api/v1/cameras/{cam_id}/image" if has_local_file else "",
                    image_quality=None,
                    model_pipeline=None,
                    has_image=has_local_file,
                    image_access_status=ImageAccessStatus.VIEWABLE_PUBLIC if has_local_file else ImageAccessStatus.UNAVAILABLE,
                    evidence_eligibility=EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING,
                    image_status=img_status,
                    image_status_reason=img_reason,
                    model_status=row.cis_model_status or "NOT_ANALYZED",
                    vehicle_count=None,
                    traffic_density_score=None,
                    flood_ratio=None,
                    risk_level=RiskLevel.UNKNOWN,
                    captured_at=None,
                    retrieved_at=datetime.fromtimestamp(os.path.getmtime(local_image_path), timezone.utc) if has_local_file else None,
                    source_status=source_st,
                    updated_at=now,
                )
            if (evidence.captured_at is None or evidence.captured_at.tzinfo is None
                    or not 0 <= (now - evidence.captured_at).total_seconds() <= settings.CAMERA_IMAGE_TTL_SECONDS):
                evidence.source_status = DataSourceStatus.STALE
                evidence.evidence_eligibility = EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING
                evidence.risk_level = RiskLevel.UNKNOWN

            # Strict 1-Hour Expiration: never serve image or mark present if older than 1 hour
            ev_age = None
            if evidence.captured_at and evidence.captured_at.tzinfo:
                ev_age = (now - evidence.captured_at).total_seconds()
            elif evidence.retrieved_at and evidence.retrieved_at.tzinfo:
                ev_age = (now - evidence.retrieved_at).total_seconds()

            if ev_age is not None and ev_age > settings.CAMERA_MAX_IMAGE_AGE_SECONDS:
                evidence.has_image = False
                evidence.image_url = ""
                evidence.image_access_status = ImageAccessStatus.UNAVAILABLE
                evidence.image_status = "EXPIRED"
                evidence.image_status_reason = "SNAPSHOT_EXPIRED_PAST_1H"
                evidence.source_status = DataSourceStatus.STALE
            evidence_list.append(evidence)
    finally:
        if redis is not None:
            await redis.aclose()

    return evidence_list


@app.get("/api/v1/cameras/{cam_id}/proxy", tags=["Surveillance"])
async def get_camera_proxy(cam_id: str, request: Request, session: AsyncSession = Depends(get_db)):
    from backend.app.services.camera_proxy import CAMERA_ID, CameraProxyError
    if not CAMERA_ID.fullmatch(cam_id):
        raise HTTPException(400, detail={"code": "INVALID_CAMERA_ID"})
    if not settings.CAMERA_PROXY_ENABLED or not (settings.CAMERA_INGESTION_PERMITTED or settings.CAMERA_ALLOW_VIEW_ONLY):
        raise HTTPException(403, detail={"code": "CAMERA_VIEW_NOT_PERMITTED"}, headers={"X-Camera-Source-Status": "RESTRICTED"})
    cam_id = cam_id.lower()
    known = await session.execute(text("SELECT cam_id FROM traffic_cameras WHERE cam_id = :cam_id"), {"cam_id": cam_id})
    if not known.scalar_one_or_none():
        raise HTTPException(404, detail={"code": "CAMERA_NOT_FOUND"})
    await enforce_rate_limit(request, "camera_proxy", 120)
    try:
        frame = await request.app.state.camera_proxy.get_frame(cam_id)
    except CameraProxyError as exc:
        raise HTTPException(exc.http_status, detail={"code": exc.code}, headers={
            "X-Camera-Source-Status": exc.status, "X-Camera-Provider": settings.CAMERA_PROXY_PROVIDER,
            "Cache-Control": "no-store", "Retry-After": str(settings.CAMERA_PROXY_FAILURE_BACKOFF_SECONDS),
        }) from exc
    headers = {
        "Cache-Control": "no-store", "ETag": f'"{frame.content_hash}"',
        "X-Content-Type-Options": "nosniff", "X-Camera-Source-Status": frame.source_status,
        "X-Retrieved-At": frame.retrieved_at.isoformat(), "X-Snapshot-ID": frame.content_hash,
    }
    if frame.provider:
        headers["X-Camera-Provider"] = frame.provider
        headers["X-Camera-Source"] = frame.source_url
    if frame.upstream_error:
        headers["X-Upstream-Error"] = frame.upstream_error
    return Response(frame.data, media_type=frame.content_type, headers=headers)


class CameraAnalysisRequest(BaseModel):
    snapshot_id: Optional[str] = Field(None, pattern=r"^[a-f0-9]{64}$")


@app.post("/api/v1/cameras/{cam_id}/analysis", tags=["Surveillance"])
async def prepare_viewed_camera_analysis(cam_id: str, request: Request,
    payload: Optional[CameraAnalysisRequest] = None, session: AsyncSession = Depends(get_db)):
    """Analyze a selected source frame on explicit overlay/inspection interaction."""
    from backend.app.services.camera_proxy import CAMERA_ID, CameraProxyError
    from backend.app.services.camera_overlay import prepare_camera_overlay
    if not CAMERA_ID.fullmatch(cam_id):
        raise HTTPException(400, detail={"code": "INVALID_CAMERA_ID"})
    if not settings.CAMERA_VIEW_AI_ENABLED or not settings.CAMERA_PROXY_ENABLED or not (settings.CAMERA_ALLOW_VIEW_ONLY or settings.CAMERA_INGESTION_PERMITTED):
        raise HTTPException(403, detail={"code": "CAMERA_ANALYSIS_NOT_PERMITTED"})
    await enforce_rate_limit(request, "camera_analysis", 20)
    result = await session.execute(text("SELECT cam_id, name, code, district, ST_Y(geom) AS lat, ST_X(geom) AS lng FROM traffic_cameras WHERE cam_id = :cam_id"), {"cam_id": cam_id.lower()})
    camera = result.mappings().one_or_none()
    if camera is None:
        raise HTTPException(404, detail={"code": "CAMERA_NOT_FOUND"})
    try:
        with observe_operation("ai"):
            return await prepare_camera_overlay(dict(camera), request.app.state.camera_proxy,
                                                expected_snapshot_id=payload.snapshot_id if payload else None)
    except CameraProxyError as exc:
        raise HTTPException(exc.http_status, detail={"code": exc.code}) from exc


@app.get(
    "/api/v1/cameras/{cam_id}/image",
    summary="Get camera snapshot or AI analyzed evidence overlay",
    tags=["Surveillance"],
)
async def get_camera_image(
    cam_id: str,
    request: Request,
    type: str = Query("original", pattern="^(original|analyzed)$", description="Type of image: 'original' (source evidence) or 'analyzed' (detection overlay)"),
    snapshot_id: Optional[str] = Query(None, pattern=r"^[A-Za-z0-9_-]{1,160}$", description="Exact immutable snapshot identifier"),
    session: AsyncSession = Depends(get_db),
):
    """
    Returns verified image snapshot for the given camera ID.
    - type='original': Unaltered raw camera frame (canonical source evidence).
    - type='analyzed': AI detection overlay with bounding boxes and segmentations.
    - snapshot_id: Optional immutable snapshot identifier. When provided, serves the exact immutable frame.
    Zero-Mock: Returns HTTP 404/503 if no valid verified image exists.
    Never returns sample or simulated mock images.
    Enforces path traversal protection and returns ETag / Cache-Control headers.
    """
    if not is_valid_cam_id(cam_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_CAMERA_ID", "message": "Malformed or unsafe camera identifier."},
        )

    if not settings.CAMERA_ALLOW_VIEW_ONLY and not settings.CAMERA_INGESTION_PERMITTED:
        raise HTTPException(403, detail={"code": "CAMERA_VIEW_NOT_PERMITTED"})
    await enforce_rate_limit(request, "camera_image", 120)

    if type == "analyzed" and not snapshot_id:
        raise HTTPException(400, detail={"code": "SNAPSHOT_ID_REQUIRED", "message": "Overlay must identify its exact source frame."})

    # 1. Verify existence of camera in database
    cam_check = await session.execute(
        text("SELECT cam_id FROM traffic_cameras WHERE cam_id = :cam_id"),
        {"cam_id": cam_id},
    )
    if not cam_check.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CAMERA_NOT_FOUND", "message": f"Camera '{cam_id}' is not registered."},
        )

    # 2. Immutable Snapshot Handling (when snapshot_id is explicitly requested)
    if snapshot_id:
        snap_stmt = text("""
            SELECT snapshot_id, camera_id, content_sha256, content_md5, file_path,
                   source_captured_at, fetched_at, freshness_status, capture_time_status,
                   inference_completed_at, inference_input_sha256, overlay_path
            FROM camera_snapshots
            WHERE snapshot_id = :snapshot_id AND camera_id = :cam_id
        """)
        snap_res = await session.execute(snap_stmt, {"snapshot_id": snapshot_id, "cam_id": cam_id})
        db_snap = snap_res.fetchone()

        snap_orig = (db_snap.file_path if db_snap and db_snap.file_path and os.path.exists(db_snap.file_path)
                     else os.path.join("storage", "snapshots", cam_id, f"{snapshot_id}.jpg"))
        if not os.path.exists(snap_orig):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "SNAPSHOT_NOT_FOUND",
                    "message": f"Snapshot '{snapshot_id}' not found for camera '{cam_id}'.",
                    "snapshot_id": snapshot_id,
                },
            )

        if os.path.exists(snap_orig):
            snap_age = datetime.now(timezone.utc).timestamp() - os.path.getmtime(snap_orig)
            if snap_age > settings.CAMERA_MAX_IMAGE_AGE_SECONDS:
                try:
                    os.remove(snap_orig)
                except Exception:
                    pass
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": "CAMERA_IMAGE_EXPIRED",
                        "message": f"Snapshot '{snapshot_id}' for camera '{cam_id}' has expired (> 1 hour old) and was purged.",
                        "snapshot_id": snapshot_id,
                    },
                )

        if type == "analyzed":
            snap_overlay = (db_snap.overlay_path if db_snap and db_snap.overlay_path and os.path.exists(db_snap.overlay_path)
                            else os.path.join("storage", "snapshots", cam_id, f"{snapshot_id}_overlay.jpg"))
            if not os.path.exists(snap_overlay):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": "OVERLAY_NOT_AVAILABLE_FOR_SNAPSHOT",
                        "message": f"AI detection overlay not available for snapshot '{snapshot_id}'. Never serve mismatched frame overlay.",
                        "snapshot_id": snapshot_id,
                    },
                )
            with open(snap_overlay, "rb") as f:
                content = f.read()
            with open(snap_orig, "rb") as original_file:
                original_sha256 = hashlib.sha256(original_file.read()).hexdigest()
            etag = f'"{hashlib.md5(content).hexdigest()}"'
            if request.headers.get("if-none-match") == etag:
                return Response(status_code=status.HTTP_304_NOT_MODIFIED)
            headers = {
                "ETag": etag,
                "Cache-Control": "public, max-age=31536000, immutable",
                "X-Image-Kind": "analyzed",
                "X-Snapshot-ID": snapshot_id,
                "X-Source-Snapshot-ID": snapshot_id,
                "X-Inference-Input-SHA256": (db_snap.inference_input_sha256 if db_snap and db_snap.inference_input_sha256 else (db_snap.content_sha256 if db_snap else original_sha256)) or "",
                "X-Image-Access-Status": ImageAccessStatus.VIEWABLE_PUBLIC.value,
                "X-Evidence-Eligibility": EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING.value,
            }
            return FileResponse(snap_overlay, media_type="image/jpeg", headers=headers)


        # type == "original"
        with open(snap_orig, "rb") as f:
            content = f.read()
        val = validate_camera_image_bytes(content)
        etag = f'"{val.md5_hash}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED)
        headers = {
            "ETag": etag,
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Image-Kind": "original",
            "X-Snapshot-ID": snapshot_id,
            "X-Content-SHA256": (db_snap.content_sha256 if db_snap else hashlib.sha256(content).hexdigest()) or "",
            "X-Captured-At": db_snap.source_captured_at.isoformat() if (db_snap and db_snap.source_captured_at) else "UNKNOWN",
            "X-Fetched-At": db_snap.fetched_at.isoformat() if (db_snap and db_snap.fetched_at) else datetime.fromtimestamp(os.path.getmtime(snap_orig), timezone.utc).isoformat(),
            "X-Image-Access-Status": ImageAccessStatus.VIEWABLE_PUBLIC.value,
            "X-Evidence-Eligibility": EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING.value,
        }
        return FileResponse(snap_orig, media_type="image/jpeg", headers=headers)

    # 3. Default (latest) snapshot lookup
    latest_stmt = text("""
        SELECT snapshot_id, camera_id, content_sha256, content_md5, file_path,
               source_captured_at, fetched_at, freshness_status, capture_time_status,
               inference_completed_at, inference_input_sha256, overlay_path
        FROM camera_snapshots
        WHERE camera_id = :cam_id AND is_latest = TRUE
        ORDER BY created_at DESC
        LIMIT 1
    """)
    latest_res = await session.execute(latest_stmt, {"cam_id": cam_id})
    latest_snap = latest_res.fetchone()

    local_path = (latest_snap.file_path if latest_snap and latest_snap.file_path and os.path.exists(latest_snap.file_path)
                  else os.path.join("storage", "cams", f"{cam_id}.jpg"))

    # If analyzed detection overlay is requested


    # 2. Check local validated storage
    if not os.path.exists(local_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CAMERA_IMAGE_UNAVAILABLE",
                "message": f"No verified snapshot currently available for camera '{cam_id}'.",
            },
        )

    now_ts = datetime.now(timezone.utc).timestamp()
    file_age = now_ts - os.path.getmtime(local_path)
    if file_age > settings.CAMERA_MAX_IMAGE_AGE_SECONDS:
        try:
            os.remove(local_path)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CAMERA_IMAGE_EXPIRED",
                "message": f"Snapshot for camera '{cam_id}' has expired (> 1 hour old) and was purged.",
            },
        )

    # 3. Validate file on disk before serving
    try:
        with open(local_path, "rb") as f:
            content = f.read()
        val = validate_camera_image_bytes(content)
        if not val.is_valid:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "CAMERA_IMAGE_CORRUPTED",
                    "message": f"Cached frame failed validation: {val.error_message}",
                },
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "IMAGE_READ_ERROR", "message": str(exc)},
        )

    etag = f'"{val.md5_hash}"'
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)

    now = datetime.now(timezone.utc)
    file_age = now.timestamp() - os.path.getmtime(local_path)
    is_fresh = file_age <= settings.CAMERA_IMAGE_TTL_SECONDS

    media_type = "image/jpeg" if val.format == "JPEG" else f"image/{val.format.lower() if val.format else 'jpeg'}"
    headers = {
        "ETag": etag,
        "Cache-Control": "public, max-age=60" if is_fresh else "no-cache",
        "X-Image-Kind": "original",
        "X-Image-Access-Status": ImageAccessStatus.VIEWABLE_PUBLIC.value,
        "X-Evidence-Eligibility": EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING.value,
        "X-Captured-At": val.captured_at.isoformat() if val.captured_at else "UNKNOWN",
        "X-Retrieved-At": val.retrieved_at.isoformat(),
    }
    return FileResponse(local_path, media_type=media_type, headers=headers)


# Single-flight locks & cache to coalesce concurrent client requests for the same camera snapshot
_camera_refresh_locks: Dict[str, asyncio.Lock] = {}
_camera_last_refreshed: Dict[str, Tuple[float, Dict[str, Any]]] = {}


@app.post(
    "/api/v1/cameras/{cam_id}/refresh",
    summary="Trigger immediate rate-limited refresh for a camera",
    tags=["Surveillance"],
)
async def refresh_camera(
    cam_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Triggers an immediate on-demand fetch and validation of a specific camera snapshot.
    Enforces single-flight coalescing and a 10-second cooldown rate limit per camera ID
    so multiple concurrent client requests do not duplicate outbound HTTP calls.
    """
    if not is_valid_cam_id(cam_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_CAMERA_ID", "message": "Malformed camera identifier."},
        )

    if not settings.CAMERA_ALLOW_VIEW_ONLY and not settings.CAMERA_INGESTION_PERMITTED:
        raise HTTPException(403, detail={"code": "CAMERA_VIEW_NOT_PERMITTED"})
    await validate_priority_camera_ids(request, [cam_id], session)
    # Bound locks to registered cameras; unknown IDs never allocate process/Redis state.
    # In-memory single-flight lock per camera ID
    flight_lock = _camera_refresh_locks.setdefault(cam_id, asyncio.Lock())
    async with flight_lock:
        now_ts = time.time()
        last_entry = _camera_last_refreshed.get(cam_id)
        if last_entry and (now_ts - last_entry[0]) < 8.0:
            # Coalesced: another client or background worker just refreshed this snapshot
            return last_entry[1]

        redis = get_redis_client()
        try:
            # Rate limit check: max 1 refresh per 10s per camera
            if redis is not None:
                rl_key = f"camera:rate_limit:refresh:{cam_id}"
                is_limited = await redis.set(rl_key, "1", ex=10, nx=True)
                if not is_limited:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail={"code": "REFRESH_RATE_LIMITED", "message": "Camera was refreshed recently. Please wait a few seconds."},
                    )

            # Lookup camera from DB
            cam_row = (await session.execute(
                text("""
                    SELECT cam_id, code, name, district, ST_Y(geom) as lat, ST_X(geom) as lng, source_uri
                    FROM traffic_cameras WHERE cam_id = :cam_id
                """),
                {"cam_id": cam_id},
            )).fetchone()

            if not cam_row:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"code": "CAMERA_NOT_FOUND", "message": f"Camera '{cam_id}' not found."},
                )

            cam_data = {
                "cam_id": cam_row.cam_id,
                "code": cam_row.code,
                "name": cam_row.name,
                "district": cam_row.district,
                "lat": cam_row.lat,
                "lng": cam_row.lng,
                "source_uri": cam_row.source_uri,
            }

            # Execute scrape
            scraped_list = await scrape_active_cameras([cam_data], redis=redis, timeout_sec=8.0)
            if scraped_list:
                res = scraped_list[0]
                await camera_scheduler.record_result(session=session, res=res, redis=redis)
                res_payload = {
                    "status": "ok",
                    "cam_id": cam_id,
                    "is_valid_image": res.is_valid_image,
                    "validation_status": res.validation_status,
                    "source_status": res.source_status.value,
                    "freshness_status": res.freshness_status,
                    "image_url": f"/api/v1/cameras/{cam_id}/image" if res.is_valid_image else None,
                    "error_message": res.error_message,
                    "http_status": getattr(res, "http_status", 200 if res.is_valid_image else 0),
                    "refreshed_at": datetime.now(timezone.utc).isoformat(),
                }
                _camera_last_refreshed[cam_id] = (time.time(), res_payload)
                return res_payload
            return {"status": "error", "message": "Ingestion failed"}
        finally:
            if redis is not None:
                await redis.aclose()


@app.get(
    "/api/v1/cameras/{cam_id}/metadata",
    response_model=CameraImageMetadata,
    summary="Get camera snapshot technical metadata, provenance, and eligibility",
    tags=["Surveillance"],
)
async def get_camera_metadata(
    cam_id: str,
    session: AsyncSession = Depends(get_db),
) -> CameraImageMetadata:
    """
    Returns technical metadata for camera snapshot: ETag, access status, reason codes,
    provenance, and eligibility for routing without transferring large image bytes.
    """
    if not is_valid_cam_id(cam_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_CAMERA_ID", "message": "Malformed or unsafe camera identifier."},
        )

    stmt = text("""
        SELECT c.cam_id, c.code, c.name, c.district, ST_Y(c.geom) AS lat, ST_X(c.geom) AS lng,
               c.coordinate_source_url, c.source_uri, c.observed_osm_way_id, c.line_of_sight_verified
        FROM traffic_cameras c
        WHERE c.cam_id = :cam_id
    """)
    res = await session.execute(stmt, {"cam_id": cam_id})
    row = res.fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CAMERA_NOT_FOUND", "message": f"Camera '{cam_id}' is not registered."},
        )

    local_path = os.path.join("storage", "cams", f"{cam_id}.jpg")
    has_local = os.path.exists(local_path)
    etag = None
    content_length = None
    mime_type = None
    captured_at = None
    retrieved_at = None
    image_status_reason = "IMAGE_UNAVAILABLE"
    access_status = ImageAccessStatus.UNAVAILABLE
    eligibility = EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING

    redis = get_redis_client()
    redis_data = None
    try:
        raw = await redis.get(f"camera_evidence:{cam_id}")
        if raw:
            redis_data = json.loads(raw)
    except Exception:
        pass
    finally:
        if redis is not None:
            await redis.aclose()

    val = None
    image_hash = None
    if has_local:
        try:
            with open(local_path, "rb") as f:
                content = f.read()
            val = validate_camera_image_bytes(content)
            if val.is_valid:
                has_local = True
                image_hash = val.md5_hash
                etag = f'"{val.md5_hash}"'
                content_length = len(content)
                mime_type = "image/jpeg" if val.format == "JPEG" else f"image/{val.format.lower() if val.format else 'jpeg'}"
                captured_at = val.captured_at
                retrieved_at = datetime.fromtimestamp(os.path.getmtime(local_path), timezone.utc)
                image_status_reason = "VALID_IMAGE_CACHED"
                access_status = ImageAccessStatus.VIEWABLE_PUBLIC
            else:
                has_local = False
                image_status_reason = val.status.value
        except Exception:
            has_local = False
            image_status_reason = "IMAGE_READ_ERROR"

    if not has_local and not portal_circuit_breaker.can_request():
        access_status = ImageAccessStatus.EXTERNAL_ACCESS_RESTRICTED
        image_status_reason = "EXTERNAL_ACCESS_RESTRICTED"

    # Query persistent ingestion state for truthful error reason and last attempt
    ing_stmt = text("""
        SELECT last_attempt_at, last_success_at, last_captured_at, last_retrieved_at,
               last_error_code, failure_reason, validation_status, content_sha256,
               source_status, latest_snapshot_id, last_content_changed_at, last_source_captured_at
        FROM camera_ingestion_state
        WHERE cam_id = :cam_id
    """)
    ing_res = await session.execute(ing_stmt, {"cam_id": cam_id})
    ing_row = ing_res.fetchone()

    # Query latest snapshot record
    snap_stmt = text("""
        SELECT snapshot_id, content_sha256, content_md5, file_path, file_size_bytes,
               source_captured_at, fetched_at, freshness_status, capture_time_status,
               inference_completed_at, inference_input_sha256, overlay_path,
               model_status, vehicle_count, traffic_density_score, flood_ratio
        FROM camera_snapshots
        WHERE camera_id = :cam_id AND is_latest = TRUE
        ORDER BY created_at DESC
        LIMIT 1
    """)
    snap_res = await session.execute(snap_stmt, {"cam_id": cam_id})
    snap_row = snap_res.fetchone()

    cur_snap_id = snap_row.snapshot_id if snap_row else (ing_row.latest_snapshot_id if ing_row else None)

    now = datetime.now(timezone.utc)
    captured_at = (snap_row.source_captured_at if snap_row else None) or (ing_row.last_captured_at if ing_row else None) or captured_at
    retrieved_at = (snap_row.fetched_at if snap_row else None) or (ing_row.last_retrieved_at if ing_row else None) or retrieved_at
    fetched_at = retrieved_at

    freshness_status = CameraFreshnessStatus.OFFLINE
    capture_time_status = "CAPTURE_TIME_UNKNOWN"

    if has_local:
        if captured_at is not None:
            is_fresh = (now - captured_at).total_seconds() <= settings.CAMERA_IMAGE_TTL_SECONDS
            freshness_status = CameraFreshnessStatus.LIVE_VERIFIED if is_fresh else CameraFreshnessStatus.STALE
            capture_time_status = "CAPTURE_TIME_VERIFIED" if is_fresh else "STALE"
        else:
            file_mtime = retrieved_at or datetime.fromtimestamp(os.path.getmtime(local_path), timezone.utc)
            is_recent = (now - file_mtime).total_seconds() <= settings.CAMERA_IMAGE_TTL_SECONDS
            freshness_status = CameraFreshnessStatus.RECENTLY_RETRIEVED_CAPTURE_UNKNOWN if is_recent else CameraFreshnessStatus.STALE
            capture_time_status = "CAPTURE_TIME_UNKNOWN"
    else:
        if ing_row:
            if ing_row.last_error_code == "PLACEHOLDER_FRAME" or ing_row.validation_status in ("PLACEHOLDER_FRAME", "PLACEHOLDER_ERROR_FRAME"):
                image_status_reason = "PLACEHOLDER_FRAME"
                access_status = ImageAccessStatus.UNAVAILABLE
                freshness_status = CameraFreshnessStatus.PLACEHOLDER
            elif ing_row.last_error_code in ("HTTP_403", "EXTERNAL_ACCESS_RESTRICTED"):
                image_status_reason = "EXTERNAL_ACCESS_RESTRICTED"
                access_status = ImageAccessStatus.EXTERNAL_ACCESS_RESTRICTED
                freshness_status = CameraFreshnessStatus.RESTRICTED
            elif ing_row.source_status == "OFFLINE" or ing_row.last_error_code in ("TIMEOUT", "CONNECTION_ERROR"):
                image_status_reason = "IMAGE_UNAVAILABLE"
                access_status = ImageAccessStatus.UNAVAILABLE
                freshness_status = CameraFreshnessStatus.OFFLINE
            else:
                image_status_reason = "IMAGE_UNAVAILABLE"
                access_status = ImageAccessStatus.UNAVAILABLE
                freshness_status = CameraFreshnessStatus.FETCH_FAILED
        else:
            image_status_reason = "IMAGE_UNAVAILABLE"
            access_status = ImageAccessStatus.UNAVAILABLE
            freshness_status = CameraFreshnessStatus.OFFLINE

    source_url = row.source_uri or (
        f"{settings.HCMC_CAMERA_BASE_URL}?id={cam_id}&bg=black&w=300&h=230"
    )

    has_overlay = bool(snap_row and snap_row.overlay_path and os.path.exists(snap_row.overlay_path)) or (
        cur_snap_id is not None and os.path.exists(os.path.join("storage", "snapshots", cam_id, f"{cur_snap_id}_overlay.jpg"))
    )
    overlay_url = (f"/api/v1/cameras/{cam_id}/image?type=analyzed&snapshot_id={cur_snap_id}" if (has_overlay and cur_snap_id) else None)


    image_url = (f"/api/v1/cameras/{cam_id}/image?snapshot_id={cur_snap_id}" if (has_local and cur_snap_id) 
                 else (f"/api/v1/cameras/{cam_id}/image" if has_local else None))

    image_quality = None
    if redis_data and redis_data.get("image_quality"):
        try:
            image_quality = ImageQualityAssessment(**redis_data["image_quality"])
        except Exception:
            image_quality = None

    model_pipeline = redis_data.get("model_pipeline") if redis_data else None
    conf_summary = None
    if redis_data and isinstance(redis_data.get("confidence_summary"), dict):
        try:
            conf_summary = ConfidenceSummaryDTO(**redis_data["confidence_summary"])
        except Exception:
            conf_summary = None

    density_level = TrafficDensityLevel.UNKNOWN
    if redis_data and redis_data.get("traffic_density_level"):
        try:
            density_level = TrafficDensityLevel(redis_data["traffic_density_level"])
        except Exception:
            density_level = TrafficDensityLevel.UNKNOWN

    return CameraImageMetadata(
        cam_id=row.cam_id,
        snapshot_id=cur_snap_id,
        code=row.code,
        name=row.name,
        district=row.district,
        lat=row.lat,
        lng=row.lng,
        has_image=has_local,
        image_url=image_url,
        overlay_url=overlay_url,
        source_url=source_url,
        image_access_status=access_status,
        evidence_eligibility=eligibility,
        image_status_reason=image_status_reason,
        freshness_status=freshness_status,
        capture_time_status=capture_time_status,
        captured_at=captured_at,
        retrieved_at=retrieved_at,
        fetched_at=fetched_at,
        last_attempt_at=ing_row.last_attempt_at if ing_row else None,
        last_success_at=ing_row.last_success_at if ing_row else None,
        last_content_changed_at=ing_row.last_content_changed_at if ing_row else None,
        last_source_captured_at=ing_row.last_source_captured_at if ing_row else None,
        frame_sha256=(snap_row.content_sha256 if snap_row else (ing_row.content_sha256 if ing_row else None)),
        inference_input_sha256=(snap_row.inference_input_sha256 if snap_row else None),
        analyzed_at=(snap_row.inference_completed_at if snap_row and snap_row.inference_completed_at else (
            datetime.fromisoformat(redis_data["analyzed_at"]) if (redis_data and redis_data.get("analyzed_at")) else None
        )),
        source_updated_at=None,
        model_status=(snap_row.model_status if snap_row and snap_row.model_status else (
            redis_data.get("model_status", "NOT_ANALYZED") if redis_data else "NOT_ANALYZED"
        )),
        vehicle_count=(snap_row.vehicle_count if snap_row and snap_row.vehicle_count is not None else (
            redis_data.get("vehicle_count") if redis_data else None
        )),
        total_vehicles=redis_data.get("total_vehicles") if redis_data else (snap_row.vehicle_count if snap_row else None),
        vehicle_counts=redis_data.get("vehicle_counts") if redis_data else None,
        detections=redis_data.get("detections") if redis_data else None,
        confidence_summary=conf_summary,
        traffic_density_score=(snap_row.traffic_density_score if snap_row and snap_row.traffic_density_score is not None else (
            redis_data.get("traffic_density_score") if redis_data else None
        )),
        traffic_density_level=density_level,
        roi_occupancy_ratio=redis_data.get("roi_occupancy_ratio") if redis_data else None,
        analysis_confidence=redis_data.get("analysis_confidence") if redis_data else None,
        flood_ratio=(snap_row.flood_ratio if snap_row and snap_row.flood_ratio is not None else (
            redis_data.get("flood_ratio") if redis_data else None
        )),
        image_quality=image_quality,
        model_pipeline=model_pipeline,
        etag=etag,
        image_hash=image_hash,
        content_length=content_length,
        mime_type=mime_type,
    )


@app.post(
    "/api/v1/routes/search",
    response_model=SafeRouteResponse,
    summary="Return verified OSRM driving candidates and evidence coverage",
    tags=["Navigation"],
)
async def search_safe_route(
    request: RouteSearchRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db),
) -> SafeRouteResponse:
    """
    Query OSRM driving candidates. Distance and ETA come from road network + HCMC urban traffic calibration.
    Risk remains UNKNOWN until verified corridor observations are available.
    """
    await enforce_rate_limit(http_request, "routes_search", int(getattr(settings, "RATE_LIMIT_ROUTES_PER_MINUTE", 60)))
    redis = get_redis_client()
    try:
        # Execute mathematical routing
        try:
            routes = await find_safe_route(
                origin_lat=request.origin.lat,
                origin_lng=request.origin.lng,
                dest_lat=request.destination.lat,
                dest_lng=request.destination.lng,
                db_session=session,
                redis_client=redis,
                osrm_client=getattr(http_request.app.state, "osrm_client", None),
                request_id=http_request.state.request_id,
                transport_mode=request.transport_mode,
            )
        except RoutingError as exc:
            raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc

        if not routes:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No accessible route could be found between the specified coordinates.",
            )

        # Top recommended route and alternative routes
        recommended_route = routes[0]
        set_gauge("route_last_traffic_coverage_ratio", recommended_route.traffic_coverage_ratio)
        alternative_routes = routes[1:]

        recommended_route.alternative_routes = alternative_routes

        # Automatically register cameras along active route corridor for 60s priority refresh
        try:
            corridor_cam_ids = set()
            for r in routes:
                for seg in (getattr(r, "segments", []) or []):
                    for cam in (getattr(seg, "evidence_cameras", []) or []):
                        cid = getattr(cam, "cam_id", None)
                        if cid:
                            corridor_cam_ids.add(str(cid))
            if corridor_cam_ids and redis is not None:
                await camera_scheduler.register_active_route_cameras(
                    redis=redis,
                    cam_ids=list(corridor_cam_ids),
                    ttl_seconds=900,
                )
        except Exception as reg_exc:
            logger.debug("Failed to auto-register route corridor cameras: %s", reg_exc)

        return recommended_route
    finally:
        if redis is not None:
            await redis.aclose()


# WebSocket Endpoint for Real-Time Alerts
# ==============================================================================
@app.websocket("/ws/alerts")
async def websocket_alerts_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for frontends:
    Pushes instantaneous notifications when road segments or cameras transition to CRITICAL.
    Every alert contains event_id, observed_at, severity, source, and expiry.
    """
    await broadcaster.connect(websocket)
    try:
        # Send initial welcome and state message with full schema contract
        welcome_msg = WebSocketAlertMessage(
            event_id=str(uuid.uuid4()),
            type="CONNECTION_ESTABLISHED",
            severity="INFO",
            source="safepath_engine",
            message="Connected to SafePathAI live traffic & flood alert stream.",
            observed_at=datetime.now(timezone.utc),
        )
        await websocket.send_text(welcome_msg.model_dump_json())

        # Keep connection alive and handle client pings
        while True:
            data = await websocket.receive_text()
            # Echo heartbeat ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        await broadcaster.disconnect(websocket)
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
        await broadcaster.disconnect(websocket)


# ==============================================================================
# Google OAuth & User Profile Management (PostgreSQL Persistence)
# ==============================================================================

@app.get(
    "/api/v1/auth/status",
    summary="Get Google OAuth system configuration status",
    tags=["Auth"],
)
async def get_auth_status():
    """
    Returns live Google OAuth readiness status based on environment variables.
    Reports BLOCKED_CONFIGURATION transparently if credentials are not configured.
    Zero-Mock: Never fabricates or emulates authentication credentials.
    """
    google_id = os.getenv("AUTH_GOOGLE_ID") or os.getenv("GOOGLE_CLIENT_ID") or ""
    google_secret = os.getenv("AUTH_GOOGLE_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET") or ""

    if not (google_id.strip() and google_secret.strip()):
        try:
            from dotenv import dotenv_values
            env_paths = [
                os.path.join(os.getcwd(), "frontend", ".env.local"),
                os.path.join(os.getcwd(), ".env"),
            ]
            for ep in env_paths:
                if os.path.exists(ep):
                    vals = dotenv_values(ep)
                    google_id = google_id or vals.get("AUTH_GOOGLE_ID") or vals.get("GOOGLE_CLIENT_ID") or ""
                    google_secret = google_secret or vals.get("AUTH_GOOGLE_SECRET") or vals.get("GOOGLE_CLIENT_SECRET") or ""
                    if google_id.strip() and google_secret.strip():
                        break
        except Exception:
            pass

    is_configured = bool(google_id.strip() and google_secret.strip())
    missing = []
    if not google_id.strip():
        missing.append("AUTH_GOOGLE_ID")
    if not google_secret.strip():
        missing.append("AUTH_GOOGLE_SECRET")

    return {
        "status": "CONFIGURED" if is_configured else "BLOCKED_CONFIGURATION",
        "google_oauth_configured": is_configured,
        "provider": "google",
        "callback_url": "/api/auth/callback/google",
        "missing_variables": missing,
    }


@app.post(
    "/api/v1/user/sync",
    response_model=UserProfileResponse,
    summary="Sync Google OAuth user identity to PostgreSQL",
    tags=["User"],
)
async def sync_user_profile(
    req: UserSyncRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
):
    """
    Upserts Google OAuth identity into PostgreSQL `users` table.
    Creates default preferences if new user.
    Returns complete profile with preferences, saved places, and route history.
    """
    if not verify_proxy_identity_signature(req.email, req.provider_account_id,
            request.headers.get("X-Auth-Timestamp", ""), request.headers.get("X-Auth-Signature", "")):
        raise HTTPException(401, detail={"code": "TRUSTED_IDENTITY_REQUIRED"})
    if request.headers.get("X-Auth-User-Email", "").lower().strip() != req.email.lower().strip() or request.headers.get("X-Auth-Provider-Id", "") != req.provider_account_id:
        raise HTTPException(403, detail={"code": "FORBIDDEN_USER_MISMATCH"})
    now = datetime.now(timezone.utc)
    stmt = (
        select(User)
        .options(
            selectinload(User.preference),
            selectinload(User.saved_places),
            selectinload(User.route_history),
        )
        .where(User.provider == req.provider, User.provider_account_id == req.provider_account_id)
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is not None and not user.is_active:
        raise HTTPException(403, detail={"code": "ACCOUNT_DISABLED"})

    if user is None:
        user_id = uuid.uuid4().hex
        user = User(
            id=user_id,
            provider=req.provider,
            provider_account_id=req.provider_account_id,
            email=req.email,
            display_name=req.display_name,
            avatar_url=req.avatar_url,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        # Add default preference
        pref = UserPreference(
            user_id=user_id,
            transport_mode="motorcycle",
            avoid_flood_level="MEDIUM",
            avoid_high_density=False,
            alert_notifications=True,
            voice_guidance_enabled=True,
            updated_at=now,
        )
        session.add(pref)
        await session.commit()

        # Re-fetch with relationships
        res = await session.execute(stmt)
        user = res.scalar_one()
    else:
        user.display_name = req.display_name
        user.avatar_url = req.avatar_url
        user.email = req.email
        user.updated_at = now
        await session.commit()

    session_token = create_user_session_token(
        user_id=user.id,
        email=user.email,
        provider_account_id=user.provider_account_id,
    )

    return UserProfileResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        is_active=user.is_active,
        session_token=session_token,
        preferences=UserPreferenceDTO(
            transport_mode=user.preference.transport_mode if user.preference else "motorcycle",
            avoid_flood_level=user.preference.avoid_flood_level if user.preference else "MEDIUM",
            avoid_high_density=user.preference.avoid_high_density if user.preference else False,
            alert_notifications=user.preference.alert_notifications if user.preference else True,
            voice_guidance_enabled=user.preference.voice_guidance_enabled if user.preference else True,
        ),
        saved_places=[
            UserSavedPlaceDTO(
                id=sp.id,
                name=sp.name,
                address=sp.address,
                lat=sp.lat,
                lng=sp.lng,
                category=sp.category,
                created_at=sp.created_at,
            ) for sp in (user.saved_places or [])
        ],
        route_history=[
            UserRouteHistoryDTO(
                id=rh.id,
                origin_name=rh.origin_name,
                dest_name=rh.dest_name,
                origin_lat=rh.origin_lat,
                origin_lng=rh.origin_lng,
                dest_lat=rh.dest_lat,
                dest_lng=rh.dest_lng,
                distance_km=rh.distance_km,
                duration_mins=rh.duration_mins,
                travel_mode=rh.travel_mode,
                created_at=rh.created_at,
            ) for rh in (user.route_history or [])
        ],
    )


@app.get(
    "/api/v1/user/profile",
    response_model=UserProfileResponse,
    summary="Get user profile by internal ID or provider account ID",
    tags=["User"],
)
async def get_user_profile(
    user_id: Optional[str] = Query(None),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    x_auth_user_email: Optional[str] = Header(None, alias="X-Auth-User-Email"),
    x_auth_provider_id: Optional[str] = Header(None, alias="X-Auth-Provider-Id"),
    x_auth_timestamp: Optional[str] = Header(None, alias="X-Auth-Timestamp"),
    x_auth_signature: Optional[str] = Header(None, alias="X-Auth-Signature"),
    session: AsyncSession = Depends(get_db),
):
    target_id = x_user_id or user_id
    verified_id = verify_authenticated_user_access(
        target_user_id=target_id,
        authorization=authorization,
        x_user_token=x_user_token,
        x_auth_user_email=x_auth_user_email,
        x_auth_provider_id=x_auth_provider_id,
        x_auth_timestamp=x_auth_timestamp,
        x_auth_signature=x_auth_signature,
    )
    lookup_id = target_id or verified_id
    if not lookup_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "User identifier required in header or query."},
        )

    stmt = (
        select(User)
        .options(
            selectinload(User.preference),
            selectinload(User.saved_places),
            selectinload(User.route_history),
        )
        .where((User.id == lookup_id) | (User.provider_account_id == lookup_id))
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": "User not registered in database."},
        )

    verify_proxy_row_owner(user, x_auth_user_email, x_auth_provider_id, x_auth_signature)

    session_token = create_user_session_token(
        user_id=user.id,
        email=user.email,
        provider_account_id=user.provider_account_id,
    )

    return UserProfileResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        is_active=user.is_active,
        session_token=session_token,
        preferences=UserPreferenceDTO(
            transport_mode=user.preference.transport_mode if user.preference else "motorcycle",
            avoid_flood_level=user.preference.avoid_flood_level if user.preference else "MEDIUM",
            avoid_high_density=user.preference.avoid_high_density if user.preference else False,
            alert_notifications=user.preference.alert_notifications if user.preference else True,
            voice_guidance_enabled=user.preference.voice_guidance_enabled if user.preference else True,
        ),
        saved_places=[
            UserSavedPlaceDTO(
                id=sp.id,
                name=sp.name,
                address=sp.address,
                lat=sp.lat,
                lng=sp.lng,
                category=sp.category,
                created_at=sp.created_at,
            ) for sp in (user.saved_places or [])
        ],
        route_history=[
            UserRouteHistoryDTO(
                id=rh.id,
                origin_name=rh.origin_name,
                dest_name=rh.dest_name,
                origin_lat=rh.origin_lat,
                origin_lng=rh.origin_lng,
                dest_lat=rh.dest_lat,
                dest_lng=rh.dest_lng,
                distance_km=rh.distance_km,
                duration_mins=rh.duration_mins,
                travel_mode=rh.travel_mode,
                created_at=rh.created_at,
            ) for rh in (user.route_history or [])
        ],
    )


@app.put(
    "/api/v1/user/preferences",
    response_model=UserPreferenceDTO,
    summary="Update user routing and safety preferences",
    tags=["User"],
)
async def update_user_preferences(
    prefs: UserPreferenceDTO,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    x_auth_user_email: Optional[str] = Header(None, alias="X-Auth-User-Email"),
    x_auth_provider_id: Optional[str] = Header(None, alias="X-Auth-Provider-Id"),
    x_auth_timestamp: Optional[str] = Header(None, alias="X-Auth-Timestamp"),
    x_auth_signature: Optional[str] = Header(None, alias="X-Auth-Signature"),
    session: AsyncSession = Depends(get_db),
):
    effective_user_id = verify_authenticated_user_access(
        target_user_id=x_user_id,
        authorization=authorization,
        x_user_token=x_user_token,
        x_auth_user_email=x_auth_user_email,
        x_auth_provider_id=x_auth_provider_id,
        x_auth_timestamp=x_auth_timestamp,
        x_auth_signature=x_auth_signature,
    )
    user_row = (await session.execute(select(User).where(User.id == effective_user_id))).scalar_one_or_none()
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "User not authorized."},
        )
    verify_proxy_row_owner(user_row, x_auth_user_email, x_auth_provider_id, x_auth_signature)

    stmt = select(UserPreference).where(UserPreference.user_id == effective_user_id)
    res = await session.execute(stmt)
    p = res.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not p:
        p = UserPreference(
            user_id=effective_user_id,
            transport_mode=prefs.transport_mode,
            avoid_flood_level=prefs.avoid_flood_level,
            avoid_high_density=prefs.avoid_high_density,
            alert_notifications=prefs.alert_notifications,
            voice_guidance_enabled=prefs.voice_guidance_enabled,
            updated_at=now,
        )
        session.add(p)
    else:
        p.transport_mode = prefs.transport_mode
        p.avoid_flood_level = prefs.avoid_flood_level
        p.avoid_high_density = prefs.avoid_high_density
        p.alert_notifications = prefs.alert_notifications
        p.voice_guidance_enabled = prefs.voice_guidance_enabled
        p.updated_at = now
    await session.commit()
    return prefs


@app.post(
    "/api/v1/user/saved-places",
    response_model=UserSavedPlaceDTO,
    summary="Add a saved place for user",
    tags=["User"],
)
async def add_saved_place(
    req: CreateSavedPlaceRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    x_auth_user_email: Optional[str] = Header(None, alias="X-Auth-User-Email"),
    x_auth_provider_id: Optional[str] = Header(None, alias="X-Auth-Provider-Id"),
    x_auth_timestamp: Optional[str] = Header(None, alias="X-Auth-Timestamp"),
    x_auth_signature: Optional[str] = Header(None, alias="X-Auth-Signature"),
    session: AsyncSession = Depends(get_db),
):
    effective_user_id = verify_authenticated_user_access(
        target_user_id=x_user_id,
        authorization=authorization,
        x_user_token=x_user_token,
        x_auth_user_email=x_auth_user_email,
        x_auth_provider_id=x_auth_provider_id,
        x_auth_timestamp=x_auth_timestamp,
        x_auth_signature=x_auth_signature,
    )
    user_row = (await session.execute(select(User).where(User.id == effective_user_id))).scalar_one_or_none()
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "User not authorized."},
        )
    verify_proxy_row_owner(user_row, x_auth_user_email, x_auth_provider_id, x_auth_signature)

    place_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    place = UserSavedPlace(
        id=place_id,
        user_id=effective_user_id,
        name=req.name,
        address=req.address,
        lat=req.lat,
        lng=req.lng,
        category=req.category,
        created_at=now,
    )
    session.add(place)
    await session.commit()
    return UserSavedPlaceDTO(
        id=place.id,
        name=place.name,
        address=place.address,
        lat=place.lat,
        lng=place.lng,
        category=place.category,
        created_at=place.created_at,
    )


@app.delete(
    "/api/v1/user/saved-places/{place_id}",
    summary="Delete a saved place",
    tags=["User"],
)
async def delete_saved_place(
    place_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    x_auth_user_email: Optional[str] = Header(None, alias="X-Auth-User-Email"),
    x_auth_provider_id: Optional[str] = Header(None, alias="X-Auth-Provider-Id"),
    x_auth_timestamp: Optional[str] = Header(None, alias="X-Auth-Timestamp"),
    x_auth_signature: Optional[str] = Header(None, alias="X-Auth-Signature"),
    session: AsyncSession = Depends(get_db),
):
    effective_user_id = verify_authenticated_user_access(
        target_user_id=x_user_id,
        authorization=authorization,
        x_user_token=x_user_token,
        x_auth_user_email=x_auth_user_email,
        x_auth_provider_id=x_auth_provider_id,
        x_auth_timestamp=x_auth_timestamp,
        x_auth_signature=x_auth_signature,
    )
    user_row = (await session.execute(select(User).where(User.id == effective_user_id))).scalar_one_or_none()
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "User not authorized."},
        )
    verify_proxy_row_owner(user_row, x_auth_user_email, x_auth_provider_id, x_auth_signature)

    stmt = select(UserSavedPlace).where(
        UserSavedPlace.id == place_id,
        UserSavedPlace.user_id == effective_user_id,
    )
    res = await session.execute(stmt)
    place = res.scalar_one_or_none()
    if not place:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Saved place not found or unauthorized."},
        )
    await session.delete(place)
    await session.commit()
    return {"deleted": True, "place_id": place_id}


@app.post(
    "/api/v1/user/history",
    response_model=UserRouteHistoryDTO,
    summary="Add a completed route to user history",
    tags=["User"],
)
async def add_route_history_entry(
    req: CreateRouteHistoryRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_user_token: Optional[str] = Header(None, alias="X-User-Token"),
    x_auth_user_email: Optional[str] = Header(None, alias="X-Auth-User-Email"),
    x_auth_provider_id: Optional[str] = Header(None, alias="X-Auth-Provider-Id"),
    x_auth_timestamp: Optional[str] = Header(None, alias="X-Auth-Timestamp"),
    x_auth_signature: Optional[str] = Header(None, alias="X-Auth-Signature"),
    session: AsyncSession = Depends(get_db),
):
    effective_user_id = verify_authenticated_user_access(
        target_user_id=x_user_id,
        authorization=authorization,
        x_user_token=x_user_token,
        x_auth_user_email=x_auth_user_email,
        x_auth_provider_id=x_auth_provider_id,
        x_auth_timestamp=x_auth_timestamp,
        x_auth_signature=x_auth_signature,
    )
    user_row = (await session.execute(select(User).where(User.id == effective_user_id))).scalar_one_or_none()
    if not user_row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": "User not authorized."},
        )
    verify_proxy_row_owner(user_row, x_auth_user_email, x_auth_provider_id, x_auth_signature)

    entry_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    entry = UserRouteHistory(
        id=entry_id,
        user_id=effective_user_id,
        origin_name=req.origin_name,
        dest_name=req.dest_name,
        origin_lat=req.origin_lat,
        origin_lng=req.origin_lng,
        dest_lat=req.dest_lat,
        dest_lng=req.dest_lng,
        distance_km=req.distance_km,
        duration_mins=req.duration_mins,
        travel_mode=req.travel_mode,
        created_at=now,
    )
    session.add(entry)
    await session.commit()
    return UserRouteHistoryDTO(
        id=entry.id,
        origin_name=entry.origin_name,
        dest_name=entry.dest_name,
        origin_lat=entry.origin_lat,
        origin_lng=entry.origin_lng,
        dest_lat=entry.dest_lat,
        dest_lng=entry.dest_lng,
        distance_km=entry.distance_km,
        duration_mins=entry.duration_mins,
        travel_mode=entry.travel_mode,
        created_at=entry.created_at,
    )
