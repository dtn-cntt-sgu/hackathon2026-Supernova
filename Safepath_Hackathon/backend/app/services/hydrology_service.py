"""
SafePathAI Real-Time Hydrology & Tidal Ingestion Service (Zero-Mock Runtime).

Authoritative source integration for Ho Chi Minh City hydrological observation stations:
- Trạm Phú An (Sài Gòn River): 10.793°N, 106.711°E (Bình Thạnh)
- Trạm Nhà Bè (Đồng Điền / Nhà Bè River): 10.655°N, 106.745°E (Nhà Bè)

Vertical Datum: Hệ mốc cao độ Quốc gia Hải đồ Hòn Dấu (VN-2000).
Official Alarm Levels (Quyết định 18/2021/QĐ-TTg & Đài KTTV khu vực Nam Bộ):
- Cấp Báo động I: 1.40m
- Cấp Báo động II: 1.50m
- Cấp Báo động III: 1.60m
- Triều cường nguy hiểm: > 1.60m (Nguy cơ ngập sâu các tuyến đường ven sông)

Zero-Mock Policy:
- Explicit status labeling: OBSERVED_LIVE, OBSERVED_STALE, FORECAST, UNAVAILABLE.
- Never fabricates synthetic sine wave tides or fake observed_at timestamps.
- Falls back truthfully to latest database record or reports UNAVAILABLE when offline.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.db.models import HydrologyObservation
from backend.app.services.weather_tide import (
    DATUM_HON_DAU_VN2000,
    TIDE_ALARM_LEVEL_1_METERS,
    TIDE_ALARM_LEVEL_2_METERS,
    TIDE_ALARM_LEVEL_3_METERS,
    ingest_verified_tide_bulletin,
    verified_tide_source_url,
)

logger = logging.getLogger("safepath.hydrology")

# ==============================================================================
# HCMC Monitoring Station Registry
# ==============================================================================

HCMC_HYDROLOGY_STATIONS: Dict[str, Dict[str, Any]] = {
    "tram_phu_an": {
        "station_id": "tram_phu_an",
        "station_name": "Trạm Phú An",
        "river_name": "Sông Sài Gòn",
        "district": "Bình Thạnh",
        "latitude": 10.793,
        "longitude": 106.711,
        "alarm_1_m": TIDE_ALARM_LEVEL_1_METERS,
        "alarm_2_m": TIDE_ALARM_LEVEL_2_METERS,
        "alarm_3_m": TIDE_ALARM_LEVEL_3_METERS,
        "vertical_datum": DATUM_HON_DAU_VN2000,
        "source_name": "Đài Khí tượng Thủy văn khu vực Nam Bộ",
        "source_url": "http://kttv-nb.gov.vn",
        "description": "Trạm đo thủy triều và mực nước Sông Sài Gòn khu vực trung tâm TP.HCM",
    },
    "tram_nha_be": {
        "station_id": "tram_nha_be",
        "station_name": "Trạm Nhà Bè",
        "river_name": "Sông Đồng Điền",
        "district": "Nhà Bè",
        "latitude": 10.655,
        "longitude": 106.745,
        "alarm_1_m": TIDE_ALARM_LEVEL_1_METERS,
        "alarm_2_m": TIDE_ALARM_LEVEL_2_METERS,
        "alarm_3_m": TIDE_ALARM_LEVEL_3_METERS,
        "vertical_datum": DATUM_HON_DAU_VN2000,
        "source_name": "Đài Khí tượng Thủy văn khu vực Nam Bộ",
        "source_url": "http://kttv-nb.gov.vn",
        "description": "Trạm đo thủy triều khu vực hạ lưu hợp lưu sông Đồng Nai - Đồng Điền",
    },
}

REDIS_HYDROLOGY_LATEST_KEY = "hydrology:stations:latest"
REDIS_HYDROLOGY_STATION_PREFIX = "hydrology:station:"


# ==============================================================================
# DTO Schemas
# ==============================================================================

class HydrologyStationMetadata(BaseModel):
    station_id: str
    station_name: str
    river_name: str
    district: str
    latitude: float
    longitude: float
    alarm_1_m: float
    alarm_2_m: float
    alarm_3_m: float
    vertical_datum: str
    source_name: str
    source_url: str
    description: str


class HydrologyObservationDTO(BaseModel):
    station_id: str
    station_name: str
    river_name: str
    district: Optional[str] = None
    latitude: float
    longitude: float
    water_level_m: Optional[float] = None
    alarm_level: Optional[int] = Field(default=None, description="0: Normal, 1: BD I, 2: BD II, 3: BD III")
    alarm_description: str
    vertical_datum: str
    measurement_type: str = "TIDAL_OBSERVATION"
    observed_at: Optional[datetime] = None
    quality_status: str = Field(..., description="OBSERVED_LIVE, OBSERVED_STALE, FORECAST, UNAVAILABLE")
    source_name: str
    source_url: Optional[str] = None
    is_flood_warning: Optional[bool] = None
    created_at: Optional[datetime] = None
    unavailable_reason: Optional[str] = None


class HydrologyLatestResponse(BaseModel):
    timestamp: datetime
    quality_status: str
    max_alarm_level: Optional[int] = None
    is_flood_warning: Optional[bool] = None
    stations: List[HydrologyObservationDTO]
    bulletin: Optional[dict] = None
    unavailable_reason: Optional[str] = None


# ==============================================================================
# Domain Logic: Alarms & Quality Status
# ==============================================================================

def compute_alarm_level(water_level_m: float) -> int:
    """
    Computes HCMC standard tidal alarm level according to Decision 18/2021/QD-TTg:
    - Level >= 1.60m: Alarm Level 3 (Báo động III - Dangerous widespread tidal flooding)
    - Level >= 1.50m: Alarm Level 2 (Báo động II - Moderate tidal flooding)
    - Level >= 1.40m: Alarm Level 1 (Báo động I - Low-lying riverside inundation)
    - Level < 1.40m: 0 (Normal)
    """
    if water_level_m >= TIDE_ALARM_LEVEL_3_METERS:
        return 3
    elif water_level_m >= TIDE_ALARM_LEVEL_2_METERS:
        return 2
    elif water_level_m >= TIDE_ALARM_LEVEL_1_METERS:
        return 1
    return 0


def get_alarm_description(alarm_level: int) -> str:
    if alarm_level >= 3:
        return "Báo động III (Nguy hiểm - Triều cường gây ngập diện rộng)"
    elif alarm_level == 2:
        return "Báo động II (Cảnh báo - Ngập các vùng trũng thấp ven sông)"
    elif alarm_level == 1:
        return "Báo động I (Chú ý - Mực nước xấp xỉ mép đường thấp)"
    return "Bình thường (Dưới mức báo động)"


def assess_quality_status(
    observed_at: datetime,
    is_forecast: bool = False,
    now: Optional[datetime] = None,
) -> str:
    """
    Evaluates provenance status based on timestamp freshness:
    - OBSERVED_LIVE: Real observation <= 6 hours old
    - OBSERVED_STALE: Real observation between 6 and 48 hours old
    - FORECAST: Official forecast peak
    - UNAVAILABLE: Missing or older than 48 hours
    """
    if is_forecast:
        return "FORECAST"
    if now is None:
        now = datetime.now(timezone.utc)
    
    # Ensure timezone awareness
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
        
    diff_sec = (now - observed_at).total_seconds()
    if diff_sec < 0:
        return "FORECAST"
    if diff_sec <= 21600:  # <= 6 hours
        return "OBSERVED_LIVE"
    elif diff_sec <= 172800:  # <= 48 hours
        return "OBSERVED_STALE"
    return "UNAVAILABLE"


# ==============================================================================
# Hydrology Source Adapter
# ==============================================================================

class HydrologySourceAdapter:
    """
    Ingests and parses hydrological bulletin data from Nam Bo KTTV / NCHMF / municipal feeds.
    """

    @staticmethod
    def parse_bulletin_text(raw_text: str, default_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Parses official hydrographic bulletin text in Vietnamese to extract station measurements.
        Example text formats:
        - "Mực nước đỉnh triều tại trạm Phú An đạt 1.58m lúc 17h00 ngày 24/10"
        - "Trạm Nhà Bè đạt 1.62m (trên BĐ3 0.02m)"
        """
        # A measurement requires its own stated observation date/time. Publication
        # or ingestion time is not a substitute, and forecasts are not observations.
        results: List[Dict[str, Any]] = []
        if not raw_text or re.search(r"dự báo|dự kiến|\bsẽ\b|có khả năng", raw_text, re.IGNORECASE):
            return results
        source_match = re.search(r"https://[^\s<>]+", raw_text)
        source_url = source_match.group(0).rstrip(".,)") if source_match else None
        station_pattern = r"Ph[uú]\s*An|Nh[aà]\s*B[eè]"
        matches = list(re.finditer(station_pattern, raw_text, re.IGNORECASE))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
            segment = raw_text[match.start():min(end, match.start() + 350)]
            level = re.search(r"(?:ghi nhận|đạt|đo được|là)\s*([0-9]+[.,][0-9]{1,2})\s*m\b", segment, re.IGNORECASE)
            stamp = re.search(r"lúc\s*(\d{1,2})(?:h|:)(\d{2})?\s*(?:phút)?\s*ngày\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})", segment, re.IGNORECASE)
            if not level or not stamp:
                continue
            try:
                hour, minute, day, month, year = stamp.groups()
                observed_at = datetime(int(year), int(month), int(day), int(hour), int(minute or 0),
                                       tzinfo=timezone(timedelta(hours=7)))
                if observed_at > datetime.now(timezone.utc):
                    continue
                results.append({
                    "station_id": "tram_phu_an" if re.match(r"Ph", match.group(), re.IGNORECASE) else "tram_nha_be",
                    "water_level_m": float(level.group(1).replace(",", ".")),
                    "observed_at": observed_at,
                    "measurement_type": "TIDAL_OBSERVATION",
                    "source_url": source_url,
                    "raw_text_segment": segment,
                })
            except (ValueError, TypeError):
                continue
        return results

    async def fetch_external_hydro_feed(
        self,
        station_id: str,
        client: Optional[httpx.AsyncClient] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Attempts to query external hydrographic portal.
        Returns parsed dict or None if unreachable.
        """
        st_meta = HCMC_HYDROLOGY_STATIONS.get(station_id)
        if not st_meta:
            return None

        target_url = st_meta["source_url"]
        # The registry currently supplies homepages, not a timestamped telemetry feed.
        if not verified_tide_source_url(target_url):
            return None
        close_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=5.0)
            close_client = True

        try:
            resp = await client.get(target_url)
            if resp.status_code == 200:
                parsed_list = self.parse_bulletin_text(resp.text)
                for item in parsed_list:
                    if item["station_id"] == station_id:
                        return {**item, "source_url": target_url}
        except Exception as exc:
            logger.debug("External hydro feed fetch failed for %s (%s): %s", station_id, target_url, exc)
        finally:
            if close_client:
                await client.aclose()

        return None


# ==============================================================================
# Hydrology Ingestion Service
# ==============================================================================

class HydrologyIngestionService:
    """
    Coordinates ingestion, persistence, cache propagation, and API queries
    for HCMC hydrological monitoring stations.
    """

    def __init__(self, adapter: Optional[HydrologySourceAdapter] = None):
        self.adapter = adapter or HydrologySourceAdapter()

    def get_registered_stations(self) -> List[HydrologyStationMetadata]:
        """Returns metadata for all registered HCMC monitoring stations."""
        return [
            HydrologyStationMetadata(**meta)
            for meta in HCMC_HYDROLOGY_STATIONS.values()
        ]

    async def record_observation(
        self,
        session: AsyncSession,
        redis: Optional[Redis],
        station_id: str,
        water_level_m: float,
        observed_at: datetime,
        measurement_type: str = "TIDAL_OBSERVATION",
        quality_status: Optional[str] = None,
        source_name: Optional[str] = None,
        source_url: Optional[str] = None,
        source_verified: bool = False,
    ) -> HydrologyObservation:
        """
        Persists a verified hydrology observation in PostgreSQL and syncs to Redis caches.
        """
        meta = HCMC_HYDROLOGY_STATIONS.get(station_id)
        if not meta:
            raise ValueError(f"Unknown hydrology station: {station_id}")

        if observed_at.tzinfo is None:
            raise ValueError("Hydrology observation requires an explicit timezone")

        alarm = compute_alarm_level(water_level_m)
        status = quality_status or assess_quality_status(
            observed_at,
            is_forecast=(measurement_type == "FORECAST_PEAK"),
        )
        if not source_verified or not verified_tide_source_url(source_url):
            status = "UNVERIFIED"
        now_utc = datetime.now(timezone.utc)

        obs = HydrologyObservation(
            station_id=station_id,
            station_name=meta["station_name"],
            river_name=meta["river_name"],
            district=meta.get("district"),
            latitude=meta["latitude"],
            longitude=meta["longitude"],
            water_level_m=round(water_level_m, 2),
            alarm_level=alarm,
            vertical_datum=meta["vertical_datum"],
            measurement_type=measurement_type,
            observed_at=observed_at,
            quality_status=status,
            source_name=source_name or meta["source_name"],
            source_url=source_url or meta["source_url"],
            created_at=now_utc,
        )

        session.add(obs)
        await session.commit()
        await session.refresh(obs)

        # Update Redis caches
        if redis is not None:
            try:
                dto = self._model_to_dto(obs)
                cache_payload = dto.model_dump_json()

                # Per-station cache
                await redis.set(
                    f"{REDIS_HYDROLOGY_STATION_PREFIX}{station_id}:latest",
                    cache_payload,
                    ex=10800,  # 3 hours
                )

                # Update composite latest cache
                await self._refresh_composite_cache(session, redis)

                # Sync to legacy verified tide bulletin if this is Phu An or highest alarm
                if status == "OBSERVED_LIVE":
                    await ingest_verified_tide_bulletin(
                        station=f"{obs.station_name} ({obs.river_name})",
                        level_meters=obs.water_level_m,
                        observed_at=obs.observed_at,
                        source_url=obs.source_url,
                        datum=obs.vertical_datum,
                        redis_client=redis,
                    )
            except Exception as exc:
                logger.warning("Failed to update Redis cache for hydrology observation: %s", exc)

        logger.info(
            "Recorded hydrology observation for %s: %.2fm (Alarm %d, %s)",
            station_id,
            water_level_m,
            alarm,
            status,
        )
        return obs

    async def get_latest_observations(
        self,
        session: AsyncSession,
        redis: Optional[Redis] = None,
    ) -> HydrologyLatestResponse:
        """
        Retrieves the latest verified readings for all registered stations.
        Falls back to PostgreSQL if Redis cache is miss.
        """
        # Try Redis composite cache
        if redis is not None:
            try:
                cached_raw = await redis.get(REDIS_HYDROLOGY_LATEST_KEY)
                if cached_raw:
                    data = json.loads(cached_raw)
                    cached = HydrologyLatestResponse.model_validate(data)
                    if all((station.water_level_m is None or verified_tide_source_url(station.source_url))
                           and (station.quality_status != "OBSERVED_LIVE" or
                                assess_quality_status(station.observed_at) == "OBSERVED_LIVE")
                           for station in cached.stations):
                        if cached.quality_status != "OBSERVED_LIVE":
                            cached.max_alarm_level = None
                            cached.is_flood_warning = None
                        from backend.app.services.hydrology_bulletin import get_latest_bulletin
                        cached.bulletin = await get_latest_bulletin(session, redis)
                        return cached
            except Exception as exc:
                logger.debug("Failed reading composite hydrology cache: %s", exc)

        # Read from database
        stations_dtos: List[HydrologyObservationDTO] = []
        max_alarm = 0
        overall_status = "UNAVAILABLE"
        now_utc = datetime.now(timezone.utc)

        for st_id, meta in HCMC_HYDROLOGY_STATIONS.items():
            stmt = (
                select(HydrologyObservation)
                .where(HydrologyObservation.station_id == st_id)
                .order_by(desc(HydrologyObservation.observed_at))
                .limit(1)
            )
            result = await session.execute(stmt)
            obs = result.scalar_one_or_none()

            if obs is not None:
                # Re-assess freshness against current time
                current_status = assess_quality_status(
                    obs.observed_at,
                    is_forecast=(obs.measurement_type == "FORECAST_PEAK"),
                    now=now_utc,
                )
                dto = self._model_to_dto(obs, quality_status_override=current_status)
                stations_dtos.append(dto)
                current_status = dto.quality_status
                if dto.alarm_level is not None and current_status == "OBSERVED_LIVE" and dto.alarm_level > max_alarm:
                    max_alarm = dto.alarm_level
                if current_status == "OBSERVED_LIVE":
                    overall_status = "OBSERVED_LIVE"
                elif overall_status != "OBSERVED_LIVE" and current_status == "OBSERVED_STALE":
                    overall_status = "OBSERVED_STALE"
            else:
                # No data recorded in DB yet
                stations_dtos.append(
                    HydrologyObservationDTO(
                        station_id=st_id,
                        station_name=meta["station_name"],
                        river_name=meta["river_name"],
                        district=meta["district"],
                        latitude=meta["latitude"],
                        longitude=meta["longitude"],
                        water_level_m=None,
                        alarm_level=None,
                        alarm_description="Dữ liệu quan trắc trạm chưa khả dụng",
                        vertical_datum=meta["vertical_datum"],
                        measurement_type="TIDAL_OBSERVATION",
                        observed_at=None,
                        quality_status="UNAVAILABLE",
                        source_name=meta["source_name"],
                        source_url=meta["source_url"],
                        is_flood_warning=None,
                        created_at=None,
                        unavailable_reason="NO_VERIFIED_OBSERVATION",
                    )
                )

        from backend.app.services.hydrology_bulletin import get_latest_bulletin
        response = HydrologyLatestResponse(
            bulletin=await get_latest_bulletin(session, redis),
            timestamp=now_utc,
            quality_status=overall_status,
            max_alarm_level=max_alarm if overall_status == "OBSERVED_LIVE" else None,
            is_flood_warning=(max_alarm >= 2) if overall_status == "OBSERVED_LIVE" else None,
            stations=stations_dtos,
            unavailable_reason="VERIFIED_FEED_NOT_CONFIGURED" if overall_status == "UNAVAILABLE" else None,
        )

        if redis is not None:
            try:
                await redis.set(
                    REDIS_HYDROLOGY_LATEST_KEY,
                    response.model_dump_json(),
                    ex=600,  # 10 minutes
                )
            except Exception as exc:
                logger.debug("Failed saving composite hydrology cache: %s", exc)

        return response

    async def get_station_history(
        self,
        session: AsyncSession,
        station_id: str,
        limit: int = 24,
    ) -> List[HydrologyObservationDTO]:
        """Returns historical observations for a specific monitoring station."""
        stmt = (
            select(HydrologyObservation)
            .where(HydrologyObservation.station_id == station_id)
            .order_by(desc(HydrologyObservation.observed_at))
            .limit(limit)
        )
        result = await session.execute(stmt)
        records = result.scalars().all()
        return [self._model_to_dto(r) for r in records]

    async def run_ingestion_cycle(
        self,
        session: AsyncSession,
        redis: Optional[Redis] = None,
        bulletin_text: Optional[str] = None,
    ) -> List[HydrologyObservation]:
        """
        Executes a scheduled ingestion cycle.
        If bulletin_text is provided, parses it directly; otherwise attempts external feed.
        """
        ingested: List[HydrologyObservation] = []
        now_utc = datetime.now(timezone.utc)

        if bulletin_text:
            parsed_items = self.adapter.parse_bulletin_text(bulletin_text)
            for item in parsed_items:
                obs = await self.record_observation(
                    session=session,
                    redis=redis,
                    station_id=item["station_id"],
                    water_level_m=item["water_level_m"],
                    observed_at=item["observed_at"],
                    measurement_type=item.get("measurement_type", "TIDAL_OBSERVATION"),
                    source_url=item.get("source_url"),
                    source_verified=False,  # Unauthenticated submitted text is not a verified provider feed.
                )
                ingested.append(obs)
            return ingested

        # Default routine: query external feeds
        async with httpx.AsyncClient(timeout=5.0) as client:
            for st_id in HCMC_HYDROLOGY_STATIONS.keys():
                feed_data = await self.adapter.fetch_external_hydro_feed(st_id, client=client)
                if feed_data:
                    obs = await self.record_observation(
                        session=session,
                        redis=redis,
                        station_id=st_id,
                        water_level_m=feed_data["water_level_m"],
                        observed_at=feed_data["observed_at"],
                        measurement_type=feed_data.get("measurement_type", "TIDAL_OBSERVATION"),
                        source_url=feed_data.get("source_url"),
                        source_verified=True,
                    )
                    ingested.append(obs)

        return ingested

    async def _refresh_composite_cache(self, session: AsyncSession, redis: Redis) -> None:
        """Internal helper to refresh REDIS_HYDROLOGY_LATEST_KEY."""
        await redis.delete(REDIS_HYDROLOGY_LATEST_KEY)
        await self.get_latest_observations(session, redis)

    def _model_to_dto(
        self,
        obs: HydrologyObservation,
        quality_status_override: Optional[str] = None,
    ) -> HydrologyObservationDTO:
        status = quality_status_override or obs.quality_status
        verified = (obs.quality_status in {"OBSERVED_LIVE", "OBSERVED_STALE", "FORECAST"}
                    and verified_tide_source_url(obs.source_url))
        if not verified:
            status = "UNVERIFIED"
        return HydrologyObservationDTO(
            station_id=obs.station_id,
            station_name=obs.station_name,
            river_name=obs.river_name,
            district=obs.district,
            latitude=obs.latitude,
            longitude=obs.longitude,
            water_level_m=obs.water_level_m if verified else None,
            alarm_level=obs.alarm_level if verified else None,
            alarm_description=get_alarm_description(obs.alarm_level) if verified else "Chưa có số đo được xác minh",
            vertical_datum=obs.vertical_datum,
            measurement_type=obs.measurement_type,
            observed_at=obs.observed_at,
            quality_status=status,
            source_name=obs.source_name,
            source_url=obs.source_url,
            is_flood_warning=(obs.alarm_level >= 2) if verified and status == "OBSERVED_LIVE" else None,
            created_at=obs.created_at,
            unavailable_reason=None if verified else "SOURCE_PROVENANCE_UNVERIFIED",
        )


hydrology_service = HydrologyIngestionService()

