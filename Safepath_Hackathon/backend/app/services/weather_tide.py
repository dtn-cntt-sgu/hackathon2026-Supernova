"""
Weather and Tide Data Ingestion Service for SafePathAI (Zero-Mock Runtime).
Fetches real-time hydrometeorological signals for Ho Chi Minh City:
- Open-Meteo API for real precipitation and rainfall intensity.
  If unreachable or error, returns None / WEATHER_UNAVAILABLE (NEVER returns 0.0 mm/h).
- Tidal observation for HCMC stations (Phú An / Nhà Bè) with vertical datum Hòn Dấu (VN-2000).
  In absence of a live telemetry feed, returns None / TIDE_UNAVAILABLE (NEVER fabricates sine waves).
- Caches signals in Redis with grid-based coordinate rounding and TTL matching source cadences.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import math
from urllib.parse import urlparse
from typing import Optional
from backend.app.core.external_http import get_json_response
import httpx
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from backend.app.core.config import settings
from backend.app.db.session import get_redis_client
from backend.app.schemas.contracts import WeatherTideSignal

logger = logging.getLogger(__name__)

# WMO Weather interpretation table (Vietnamese localization)
WMO_WEATHER_DESCRIPTIONS: dict[int, str] = {
    0: "Trời quang đãng",
    1: "Chủ yếu trời quang",
    2: "Có mây rải rác",
    3: "Nhiều mây, âm u",
    45: "Sương mù",
    48: "Sương mù đóng băng",
    51: "Mưa phùn nhẹ",
    53: "Mưa phùn vừa",
    55: "Mưa phùn dày đặc",
    61: "Mưa nhẹ",
    63: "Mưa vừa",
    65: "Mưa to",
    80: "Mưa rào nhẹ",
    81: "Mưa rào vừa",
    82: "Mưa rào rất to",
    95: "Dông sét nhẹ đến vừa",
    96: "Dông kèm mưa đá nhỏ",
    99: "Dông sét mạnh, nguy hiểm",
}


class LocationWeatherResponse(BaseModel):
    lat: float
    lng: float
    temperature_c: Optional[float] = None
    humidity_pct: Optional[int] = None
    rain_mm_per_hour: Optional[float] = None
    rain_probability_pct: Optional[int] = None
    wind_speed_kmh: Optional[float] = None
    weather_code: Optional[int] = None
    weather_description: str = "Chưa có dữ liệu thời tiết"
    observed_at: Optional[datetime] = None
    freshness_seconds: Optional[int] = None
    status: str = "LIVE"  # "LIVE" or "OBSERVATION_UNAVAILABLE"
    source_url: str = settings.OPEN_METEO_URL

# Redis cache keys
REDIS_WEATHER_TIDE_KEY = "env:current_weather_tide"
REDIS_TIDE_BULLETIN_KEY = "env:tide:verified_bulletin"
REDIS_WEATHER_GRID_PREFIX = "env:weather:"

# Standard vertical datum and alert thresholds for Ho Chi Minh City
# Datum: Mốc cao độ Quốc gia Hòn Dấu (VN-2000)
# Trạm Phú An (sông Sài Gòn) & Trạm Nhà Bè (sông Đồng Điền)
DATUM_HON_DAU_VN2000 = "Hòn Dấu (VN-2000)"
TIDE_ALARM_LEVEL_1_METERS = 1.40
TIDE_ALARM_LEVEL_2_METERS = 1.50
TIDE_ALARM_LEVEL_3_METERS = 1.60
HIGH_TIDE_ALERT_THRESHOLD_METERS = TIDE_ALARM_LEVEL_2_METERS

WEATHER_CACHE_TTL_SECONDS = 900  # 15 minutes (Open-Meteo cadence)
TIDE_BULLETIN_TTL_SECONDS = 10800  # 3 hours


def _observation_age(observed_at: Optional[datetime], now: Optional[datetime] = None) -> Optional[float]:
    if observed_at is None or observed_at.tzinfo is None:
        return None
    return ((now or datetime.now(timezone.utc)) - observed_at).total_seconds()


def _fresh_weather(observed_at: Optional[datetime]) -> bool:
    age = _observation_age(observed_at)
    return age is not None and -60 <= age <= WEATHER_CACHE_TTL_SECONDS


def _weather_ttl(observed_at: datetime) -> int:
    return max(1, int(WEATHER_CACHE_TTL_SECONDS - max(0, _observation_age(observed_at) or 0)))


def _source_observed_at(data: dict) -> Optional[datetime]:
    try:
        value = datetime.fromisoformat(data.get("current", {}).get("time", ""))
        if value.tzinfo is None:
            offset = data.get("utc_offset_seconds")
            if not isinstance(offset, int) or not -43200 <= offset <= 50400:
                return None
            value = value.replace(tzinfo=timezone(timedelta(seconds=offset)))
        return value
    except (ValueError, TypeError):
        return None


def _valid_rain(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def verified_tide_source_url(value: Optional[str]) -> bool:
    """A provider homepage alone does not identify a verified observation bulletin."""
    if not value:
        return False
    parsed = urlparse(value)
    return bool(parsed.scheme == "https" and parsed.hostname in {
        "kttv-nb.gov.vn", "www.kttv-nb.gov.vn", "kttv.gov.vn", "www.kttv.gov.vn",
        "nchmf.gov.vn", "www.nchmf.gov.vn",
    } and parsed.path.strip("/") and not parsed.username and not parsed.password)


async def fetch_hcm_weather(
    lat: float = 10.7769,
    lng: float = 106.7009,
    client: Optional[httpx.AsyncClient] = None,
    redis_client: Optional[Redis] = None,
) -> tuple[Optional[float], str, Optional[datetime], Optional[int]]:
    """
    Fetches real-time rainfall precipitation in mm/hour from Open-Meteo API.
    
    Returns:
        tuple of (rain_mm_per_hour, rain_status, rain_observed_at, weather_code)
    
    Zero-Mock Rule:
        If external API is unreachable or fails, returns (None, "WEATHER_UNAVAILABLE", None, None).
        NEVER defaults to 0.0 mm/h.
    """
    lat_round = round(lat, 2)
    lng_round = round(lng, 2)
    grid_cache_key = f"{REDIS_WEATHER_GRID_PREFIX}{lat_round}:{lng_round}"

    close_redis = False
    if redis_client is None:
        try:
            redis_client = get_redis_client()
            close_redis = True
        except Exception:
            redis_client = None

    # Check cache first
    if redis_client is not None:
        try:
            cached_raw = await redis_client.get(grid_cache_key)
            if cached_raw:
                data = json.loads(cached_raw)
                observed_at = None
                if data.get("rain_observed_at"):
                    observed_at = datetime.fromisoformat(data["rain_observed_at"])
                if (_fresh_weather(observed_at) and data.get("rain_status") == "LIVE"
                        and _valid_rain(data.get("rain_mm_per_hour"))):
                    if close_redis:
                        await redis_client.aclose()
                    return (data["rain_mm_per_hour"], "LIVE", observed_at, data.get("weather_code"))
        except Exception as exc:
            logger.debug("Redis weather cache read failed: %s", exc)

    url = (
        f"{settings.OPEN_METEO_URL}?latitude={lat}&longitude={lng}"
        "&current=precipitation,rain,weather_code&timezone=Asia%2FHo_Chi_Minh"
    )

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=6.0)
        close_client = True

    try:
        response = await get_json_response(client, url, operation="weather", budget_seconds=6)
        if response.status_code == 200:
            data = response.json()
            current = data.get("current", {})
            rain_val = current.get("rain")
            if rain_val is None:
                rain_val = current.get("precipitation")
            
            rain_mm = float(rain_val) if rain_val is not None else None
            weather_code = current.get("weather_code")
            
            observed_at = _source_observed_at(data)
            if observed_at is None or not _valid_rain(rain_mm):
                return (None, "WEATHER_UNAVAILABLE", None, weather_code)
            if not _fresh_weather(observed_at):
                return (None, "WEATHER_STALE", observed_at, weather_code)

            rain_status = "LIVE"

            # Cache the result
            if redis_client is not None and rain_mm is not None:
                try:
                    payload = json.dumps({
                        "rain_mm_per_hour": rain_mm,
                        "rain_status": rain_status,
                        "rain_observed_at": observed_at.isoformat(),
                        "weather_code": weather_code,
                    })
                    await redis_client.set(grid_cache_key, payload, ex=_weather_ttl(observed_at))
                except Exception as exc:
                    logger.debug("Redis weather cache write failed: %s", exc)

            return (rain_mm, rain_status, observed_at, weather_code)
        else:
            logger.warning("Open-Meteo API returned status %d", response.status_code)
            return (None, "WEATHER_UNAVAILABLE", None, None)
    except Exception as exc:
        logger.warning("Failed to fetch Open-Meteo weather data: %s", exc)
        return (None, "WEATHER_UNAVAILABLE", None, None)
    finally:
        if close_client:
            await client.aclose()
        if close_redis and redis_client is not None:
            await redis_client.aclose()


async def fetch_location_weather(
    lat: float,
    lng: float,
    client: Optional[httpx.AsyncClient] = None,
    redis_client: Optional[Redis] = None,
) -> LocationWeatherResponse:
    """
    Fetches real-time localized hydrometeorological signals for an exact GPS coordinate
    (e.g., camera location or route point) via Open-Meteo.
    Cached in Redis for 10 minutes by rounded coordinate.
    """
    lat_round = round(lat, 2)
    lng_round = round(lng, 2)
    loc_cache_key = f"env:weather:loc:{lat_round}:{lng_round}"

    close_redis = False
    if redis_client is None:
        try:
            redis_client = get_redis_client()
            close_redis = True
        except Exception:
            redis_client = None

    if redis_client is not None:
        try:
            cached_raw = await redis_client.get(loc_cache_key)
            if cached_raw:
                data = json.loads(cached_raw)
                cached = LocationWeatherResponse.model_validate(data)
                if cached.status == "LIVE" and _fresh_weather(cached.observed_at):
                    cached.freshness_seconds = max(0, int(_observation_age(cached.observed_at) or 0))
                    if close_redis:
                        await redis_client.aclose()
                    return cached
        except Exception as exc:
            logger.debug("Redis location weather read failed: %s", exc)

    url = (
        f"{settings.OPEN_METEO_URL}?latitude={lat}&longitude={lng}"
        "&current=temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m"
        "&hourly=precipitation_probability&forecast_days=1&timezone=Asia%2FHo_Chi_Minh"
    )

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=6.0)
        close_client = True

    now = datetime.now(timezone.utc)
    try:
        response = await get_json_response(client, url, operation="weather", budget_seconds=6)
        if response.status_code == 200:
            data = response.json()
            current = data.get("current", {})
            temp = current.get("temperature_2m")
            humidity = current.get("relative_humidity_2m")
            precip = current.get("rain") if current.get("rain") is not None else current.get("precipitation")
            wcode = current.get("weather_code")
            wind = current.get("wind_speed_10m")

            hourly_prob = data.get("hourly", {}).get("precipitation_probability", [])
            rain_prob = hourly_prob[0] if hourly_prob else None

            desc = WMO_WEATHER_DESCRIPTIONS.get(wcode, "Chưa có mô tả thời tiết")

            observed_at = _source_observed_at(data)
            if observed_at is None or not _fresh_weather(observed_at):
                return LocationWeatherResponse(
                    lat=lat, lng=lng, observed_at=observed_at,
                    weather_description="Bản tin thời tiết đã cũ" if observed_at else "Thiếu thời điểm quan trắc",
                    status="OBSERVATION_STALE" if observed_at else "OBSERVATION_UNAVAILABLE",
                )
            freshness = max(0, int(_observation_age(observed_at) or 0))

            res = LocationWeatherResponse(
                lat=lat,
                lng=lng,
                temperature_c=float(temp) if temp is not None else None,
                humidity_pct=int(humidity) if humidity is not None else None,
                rain_mm_per_hour=float(precip) if _valid_rain(precip) else None,
                rain_probability_pct=int(rain_prob) if rain_prob is not None else None,
                wind_speed_kmh=float(wind) if wind is not None else None,
                weather_code=int(wcode) if wcode is not None else None,
                weather_description=desc,
                observed_at=observed_at,
                freshness_seconds=max(0, freshness),
                status="LIVE",
                source_url=settings.OPEN_METEO_URL,
            )

            if redis_client is not None:
                try:
                    await redis_client.set(loc_cache_key, res.model_dump_json(), ex=min(600, _weather_ttl(observed_at)))
                except Exception as exc:
                    logger.debug("Redis location weather write error: %s", exc)

            return res
        else:
            return LocationWeatherResponse(
                lat=lat,
                lng=lng,
                weather_description="Thời tiết tạm thời không khả dụng",
                status="OBSERVATION_UNAVAILABLE",
                source_url=settings.OPEN_METEO_URL,
            )
    except Exception as exc:
        logger.warning("Failed to fetch location weather from Open-Meteo: %s", exc)
        return LocationWeatherResponse(
            lat=lat,
            lng=lng,
            weather_description="Thời tiết tạm thời không khả dụng",
            status="OBSERVATION_UNAVAILABLE",
            source_url=settings.OPEN_METEO_URL,
        )
    finally:
        if close_client:
            await client.aclose()
        if close_redis and redis_client is not None:
            await redis_client.aclose()


async def ingest_verified_tide_bulletin(
    station: str,
    level_meters: float,
    observed_at: datetime,
    source_url: str,
    datum: str = DATUM_HON_DAU_VN2000,
    redis_client: Optional[Redis] = None,
) -> WeatherTideSignal:
    """
    Ingests an authorized, verified hydrographic bulletin from official sources
    (e.g., Đài Khí tượng Thủy văn Nam Bộ / Trung tâm Dự báo KTTV Quốc gia).
    """
    is_alert = level_meters >= HIGH_TIDE_ALERT_THRESHOLD_METERS
    signal = WeatherTideSignal(
        rain_mm_per_hour=None,
        rain_status="WEATHER_UNAVAILABLE",
        tide_level_meters=round(level_meters, 2),
        tide_status="LIVE",
        tide_observed_at=observed_at,
        tide_source_url=source_url,
        tide_station=station,
        tide_datum=datum,
        is_high_tide_alert=is_alert,
        timestamp=observed_at,
        source_url=source_url,
    )

    close_redis = False
    if redis_client is None:
        redis_client = get_redis_client()
        close_redis = True

    try:
        payload = signal.model_dump_json()
        await redis_client.set(REDIS_TIDE_BULLETIN_KEY, payload, ex=TIDE_BULLETIN_TTL_SECONDS)
        logger.info("Ingested verified tide bulletin to Redis (TTL %ds): %s", TIDE_BULLETIN_TTL_SECONDS, payload)
    except Exception as exc:
        logger.warning("Failed to save verified tide bulletin to Redis: %s", exc)
    finally:
        if close_redis:
            await redis_client.aclose()

    return signal


async def fetch_tide_signal(
    now: Optional[datetime] = None,
    redis_client: Optional[Redis] = None,
    check_db: bool = False,
) -> WeatherTideSignal:
    """
    Retrieves the current tidal observation for HCMC stations.
    
    Zero-Mock Rules:
    - Checks Redis for an active verified bulletin.
    - If no verified bulletin exists, returns tide_status="TIDE_UNAVAILABLE", tide_level_meters=None.
      NEVER generates harmonic sine waves or assumes calm tides.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Check for verified bulletin in Redis
    close_redis = False
    if redis_client is None:
        try:
            redis_client = get_redis_client()
            close_redis = True
        except Exception:
            redis_client = None

    if redis_client is not None:
        try:
            cached_raw = await redis_client.get(REDIS_TIDE_BULLETIN_KEY)
            if cached_raw:
                data = json.loads(cached_raw)
                signal = WeatherTideSignal.model_validate(data)
                # This key contains a tide-only bulletin; preserve its own provenance.
                signal.tide_observed_at = signal.tide_observed_at or signal.timestamp
                signal.tide_source_url = signal.tide_source_url or signal.source_url
                observed = signal.tide_observed_at
                if not verified_tide_source_url(signal.tide_source_url):
                    signal.tide_level_meters = None
                    signal.tide_status = "TIDE_UNAVAILABLE"
                    signal.is_high_tide_alert = None
                    signal.tide_unavailable_reason = "SOURCE_PROVENANCE_UNVERIFIED"
                    return signal
                if (signal.tide_status != "LIVE" or not signal.tide_source_url or observed is None
                        or observed.tzinfo is None or not 0 <= (now - observed).total_seconds() <= TIDE_BULLETIN_TTL_SECONDS):
                    signal.tide_status = "STALE"
                    signal.is_high_tide_alert = None
                return signal
        except Exception as exc:
            logger.debug("Failed to read tide bulletin from Redis: %s", exc)
        finally:
            if close_redis:
                await redis_client.aclose()

    # Optional database fallback
    if check_db:
        try:
            from backend.app.db.session import AsyncSessionLocal
            from backend.app.db.models import HydrologyObservation
            from sqlalchemy import select, desc
            async with AsyncSessionLocal() as session:
                stmt = (select(HydrologyObservation)
                        .where(HydrologyObservation.quality_status.in_(["OBSERVED_LIVE", "OBSERVED_STALE"]))
                        .order_by(desc(HydrologyObservation.observed_at)).limit(20))
                res = await session.execute(stmt)
                obs = next((item for item in res.scalars().all() if verified_tide_source_url(item.source_url)), None)
                if obs is not None:
                    diff_sec = (now - obs.observed_at).total_seconds()
                    status = "LIVE" if 0 <= diff_sec <= TIDE_BULLETIN_TTL_SECONDS else "STALE"
                    is_alert = (obs.water_level_m >= HIGH_TIDE_ALERT_THRESHOLD_METERS) if status == "LIVE" else None
                    return WeatherTideSignal(
                        rain_mm_per_hour=None,
                        rain_status="WEATHER_UNAVAILABLE",
                        tide_level_meters=obs.water_level_m,
                        tide_status=status,
                        tide_observed_at=obs.observed_at,
                        tide_source_url=obs.source_url,
                        tide_station=f"{obs.station_name} ({obs.river_name})",
                        tide_datum=obs.vertical_datum,
                        is_high_tide_alert=is_alert,
                        timestamp=obs.observed_at,
                        source_url=obs.source_url,
                    )
        except Exception as exc:
            logger.debug("Database fallback for tide signal check failed: %s", exc)

    # No verified bulletin available
    return WeatherTideSignal(
        rain_mm_per_hour=None,
        rain_status="WEATHER_UNAVAILABLE",
        tide_level_meters=None,
        tide_status="TIDE_UNAVAILABLE",
        tide_unavailable_reason="VERIFIED_FEED_NOT_CONFIGURED",
        tide_station=None,
        tide_datum=DATUM_HON_DAU_VN2000,
        is_high_tide_alert=None,
        timestamp=None,
        source_url=None,
    )


async def get_combined_weather_tide(
    lat: float = 10.7769,
    lng: float = 106.7009,
    client: Optional[httpx.AsyncClient] = None,
    redis_client: Optional[Redis] = None,
) -> WeatherTideSignal:
    """
    Gathers both Open-Meteo weather precipitation and tide signal into a unified WeatherTideSignal.
    Zero-Mock: All fields reflect verified inputs; missing measurements are explicitly None.
    """
    rain_mm, rain_status, rain_observed_at, weather_code = await fetch_hcm_weather(
        lat=lat, lng=lng, client=client, redis_client=redis_client
    )
    tide_signal = await fetch_tide_signal(
        redis_client=redis_client, check_db=True,
    )

    return WeatherTideSignal(
        rain_mm_per_hour=rain_mm,
        rain_status=rain_status,
        rain_observed_at=rain_observed_at,
        weather_code=weather_code,
        tide_level_meters=tide_signal.tide_level_meters,
        tide_status=tide_signal.tide_status,
        tide_observed_at=tide_signal.tide_observed_at,
        tide_source_url=tide_signal.tide_source_url,
        tide_station=tide_signal.tide_station,
        tide_datum=tide_signal.tide_datum,
        tide_unavailable_reason=tide_signal.tide_unavailable_reason,
        is_high_tide_alert=tide_signal.is_high_tide_alert,
        timestamp=rain_observed_at or tide_signal.timestamp,
        source_url=settings.OPEN_METEO_URL if rain_status == "LIVE" else tide_signal.source_url,
    )


async def sync_weather_tide_to_redis(
    signal: Optional[WeatherTideSignal] = None,
    redis_client: Optional[Redis] = None,
    ttl_seconds: int = 900,
) -> WeatherTideSignal:
    """
    Saves the latest WeatherTideSignal payload into Redis with a TTL (default 900s).
    If signal is omitted, fetches the latest signal before saving.
    """
    close_redis = False
    if redis_client is None:
        redis_client = get_redis_client()
        close_redis = True

    if signal is None:
        signal = await get_combined_weather_tide(redis_client=redis_client)

    try:
        payload = signal.model_dump_json()
        # Never make an aging provider observation live for another full cache period.
        if signal.rain_status == "LIVE" and signal.rain_observed_at is not None:
            ttl_seconds = min(ttl_seconds, _weather_ttl(signal.rain_observed_at))
        else:
            ttl_seconds = min(ttl_seconds, 60)
        await redis_client.set(REDIS_WEATHER_TIDE_KEY, payload, ex=max(1, ttl_seconds))
        logger.info("Synchronized weather-tide signal to Redis (TTL: %ds): %s", ttl_seconds, payload)
    except Exception as exc:
        logger.warning("Failed to synchronize weather-tide to Redis: %s", exc)
    finally:
        if close_redis:
            await redis_client.aclose()

    return signal


async def get_cached_weather_tide(
    redis_client: Optional[Redis] = None,
) -> Optional[WeatherTideSignal]:
    """
    Reads the cached WeatherTideSignal from Redis.
    Returns None if cache is expired or Redis is unreachable.
    """
    close_redis = False
    if redis_client is None:
        redis_client = get_redis_client()
        close_redis = True

    try:
        raw_val = await redis_client.get(REDIS_WEATHER_TIDE_KEY)
        if not raw_val:
            return None
        data = json.loads(raw_val)
        signal = WeatherTideSignal.model_validate(data)
        if signal.rain_status == "LIVE" and not _fresh_weather(signal.rain_observed_at):
            return None
        if signal.tide_status == "LIVE":
            age = _observation_age(signal.tide_observed_at)
            if (not verified_tide_source_url(signal.tide_source_url) or age is None
                    or not 0 <= age <= TIDE_BULLETIN_TTL_SECONDS):
                return None
        return signal
    except Exception as exc:
        logger.warning("Failed to retrieve cached weather-tide from Redis: %s", exc)
        return None
    finally:
        if close_redis:
            await redis_client.aclose()
