"""OSRM driving candidates and evidence coverage for Ho Chi Minh City."""

import asyncio
import json
import hashlib
from functools import lru_cache
import logging
import math
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.schemas.contracts import (
    CameraEvidence,
    DataSourceStatus,
    ETABreakdownDTO,
    EvidenceEligibility,
    ImageAccessStatus,
    RiskLevel,
    RouteSegmentRisk,
    SafeRouteResponse,
    TrafficStatus,
    TransportMode,
    WeatherTideSignal,
)
from backend.app.services.weather_tide import get_cached_weather_tide
from backend.app.services.risk_engine import calculate_segment_risk, aggregate_edge_risks
from backend.app.services.traffic_providers import get_traffic_provider

logger = logging.getLogger(__name__)
CORRIDOR_BUFFER_METERS = 80.0
CRITICAL_FLOOD_PENALTY_MINUTES = 999.0
# A deliberately broad HCMC service envelope. The Vietnam extract supports the full box.
HCMC_BOUNDS = (106.30, 10.35, 107.10, 11.20)  # west, south, east, north
_osrm_circuit_open_until = 0.0
OSRM_CACHE_TTL_SECONDS = 60


@lru_cache(maxsize=512)
def _edge_cache_lock(key: str) -> asyncio.Lock:
    """One cold graph lookup per endpoint key in this API process."""
    return asyncio.Lock()


def _haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates haversine distance in meters between two WGS84 points."""
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _point_to_linestring_distance_meters(
    point_lat: float,
    point_lng: float,
    coords: List[List[float]],
) -> float:
    """Calculates min distance in meters from (point_lat, point_lng) to LineString [[lng, lat], ...]."""
    if not coords:
        return float("inf")

    def point_to_segment_dist(plat: float, plon: float, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        mid_lat = math.radians((lat1 + lat2 + plat) / 3.0)
        cos_mid = math.cos(mid_lat)
        kx = 111320.0 * cos_mid
        ky = 110540.0
        px, py = plon * kx, plat * ky
        x1, y1 = lon1 * kx, lat1 * ky
        x2, y2 = lon2 * kx, lat2 * ky
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 and dy == 0:
            return math.hypot(px - x1, py - y1)
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        return math.hypot(px - proj_x, py - proj_y)

    min_dist = float("inf")
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i][0], coords[i][1]
        lon2, lat2 = coords[i + 1][0], coords[i + 1][1]
        d = point_to_segment_dist(point_lat, point_lng, lat1, lon1, lat2, lon2)
        if d < min_dist:
            min_dist = d
    if len(coords) == 1:
        lon1, lat1 = coords[0][0], coords[0][1]
        d = point_to_segment_dist(point_lat, point_lng, lat1, lon1, lat1, lon1)
        min_dist = d
    return min_dist


class RoutingError(Exception):
    def __init__(self, code: str, status_code: int, message: str):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.message = message


def _validate_point(lat: float, lng: float) -> None:
    if not all(math.isfinite(v) for v in (lat, lng)) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise RoutingError("INVALID_COORDINATES", 422, "Coordinates must be finite WGS84 latitude/longitude.")
    west, south, east, north = HCMC_BOUNDS
    if not (west <= lng <= east and south <= lat <= north):
        raise RoutingError("OUTSIDE_SERVICE_AREA", 422, "Coordinates are outside the HCMC service area.")


def _valid_geometry(geometry: Any) -> bool:
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        return False
    coords = geometry.get("coordinates")
    return isinstance(coords, list) and len(coords) >= 2 and all(
        isinstance(pt, list) and len(pt) >= 2 and
        all(isinstance(v, (int, float)) and math.isfinite(v) for v in pt[:2]) and
        -180 <= pt[0] <= 180 and -90 <= pt[1] <= 90 for pt in coords
    )


def _valid_route(route: Any) -> bool:
    if not isinstance(route, dict) or not _valid_geometry(route.get("geometry")):
        return False
    try:
        return all(math.isfinite(float(route[k])) and float(route[k]) > 0 for k in ("distance", "duration"))
    except (KeyError, TypeError, ValueError):
        return False


def _osrm_cache_key(origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float) -> Optional[str]:
    """Cache only raw OSRM output and invalidate it when the local graph changes."""
    from backend.app.services.route_matching import MATCH_VERSION
    # Raw-response cache identity is cheap; topology proof hashes run off-loop below.
    try:
        with open(settings.OSRM_GRAPH_MANIFEST_PATH, "rb") as manifest:
            manifest_identity = hashlib.sha256(manifest.read()).hexdigest()
    except OSError:
        manifest_identity = "unproven"
    graph_version = settings.OSRM_GRAPH_VERSION
    if not graph_version:
        try:
            graph = os.stat("data/osrm/vietnam-latest.osrm.mldgr")
            graph_version = f"{graph.st_size}-{graph.st_mtime_ns}"
        except OSError:
            return None
    coordinates = f"{origin_lat:.6f},{origin_lng:.6f};{dest_lat:.6f},{dest_lng:.6f}"
    digest = hashlib.sha256(f"driving|{MATCH_VERSION}|{manifest_identity}|{graph_version}|{coordinates}".encode()).hexdigest()
    return f"osrm:raw:route:{digest}"


def _geodesic_distance_meters(coords: list[list[float]]) -> float:
    """Calculate total polyline length in meters using spherical geodesic (Haversine)."""
    if not coords or len(coords) < 2:
        return 0.0
    total = 0.0
    r = 6371000.0
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i][:2]
        lon2, lat2 = coords[i + 1][:2]
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
        total += 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return total


HCMC_ARTERIAL_KEYWORDS: Tuple[str, ...] = (
    "xa lộ",
    "quốc lộ",
    "võ văn kiệt",
    "phạm văn đồng",
    "nguyễn văn linh",
    "điện biên phủ",
    "trường chinh",
    "cộng hòa",
    "nam kỳ khởi nghĩa",
    "nguyễn hữu cảnh",
    "mai chí thọ",
    "đại lộ",
    "kinh dương vương",
    "hồng bàng",
    "hoàng văn thụ",
)

HCMC_COLLECTOR_KEYWORDS: Tuple[str, ...] = (
    "hẻm",
    "ngõ",
    "đường số",
    "nội bộ",
)

# HCMC Base Urban Free-Flow Speeds (km/h) by TransportMode and Road Class
HCMC_ROAD_CLASS_SPEEDS_KMH: Dict[TransportMode, Dict[str, float]] = {
    TransportMode.MOTORCYCLE: {
        "ARTERIAL": 31.0,
        "URBAN_STANDARD": 25.5,
        "COLLECTOR_ALLEY": 19.0,
    },
    TransportMode.CAR: {
        "ARTERIAL": 29.0,
        "URBAN_STANDARD": 22.0,
        "COLLECTOR_ALLEY": 14.0,
    },
    TransportMode.WALKING: {
        "ARTERIAL": 4.8,
        "URBAN_STANDARD": 4.8,
        "COLLECTOR_ALLEY": 4.8,
    },
}


def normalize_transport_mode(mode_raw: Optional[Union[str, TransportMode]]) -> TransportMode:
    """Normalizes string or enum transport_mode into TransportMode enum."""
    if isinstance(mode_raw, TransportMode):
        return mode_raw
    val = str(mode_raw or "motorcycle").strip().upper()
    if val in ("CAR", "AUTOMOBILE", "OTO"):
        return TransportMode.CAR
    if val in ("WALKING", "WALK", "PEDESTRIAN", "FOOT"):
        return TransportMode.WALKING
    return TransportMode.MOTORCYCLE


def _classify_hcmc_road_class(street_name: Optional[str], length_meters: float) -> str:
    """Classifies an HCMC road segment into ARTERIAL, URBAN_STANDARD, or COLLECTOR_ALLEY."""
    name_lower = (street_name or "").strip().lower()
    if any(k in name_lower for k in HCMC_COLLECTOR_KEYWORDS):
        return "COLLECTOR_ALLEY"
    if any(k in name_lower for k in HCMC_ARTERIAL_KEYWORDS):
        return "ARTERIAL"
    if not name_lower and length_meters < 75.0:
        return "COLLECTOR_ALLEY"
    return "URBAN_STANDARD"


def _get_hcmc_time_of_day_multiplier(
    mode: TransportMode,
    departure_dt: Optional[datetime] = None,
) -> Tuple[float, str]:
    """
    Returns (congestion_multiplier, period_label) for HCMC (UTC+7).
    - Morning Rush Hour (06:45 - 08:45): high congestion
    - Evening Rush Hour (16:30 - 19:15): peak urban congestion
    - Daytime Urban (08:45 - 16:30, 19:15 - 21:30): moderate urban activity
    - Night Free-Flow (21:30 - 06:45): minimal congestion
    """
    if mode == TransportMode.WALKING:
        return 1.0, "PEDESTRIAN_STEADY"

    if departure_dt is None:
        departure_dt = datetime.now(timezone.utc)
    elif departure_dt.tzinfo is None:
        departure_dt = departure_dt.replace(tzinfo=timezone.utc)

    hcmc_tz = timezone(timedelta(hours=7))
    local_dt = departure_dt.astimezone(hcmc_tz)
    hour_float = local_dt.hour + (local_dt.minute / 60.0)
    is_weekend = local_dt.weekday() >= 5

    if 6.75 <= hour_float <= 8.75 and not is_weekend:
        return (1.32 if mode == TransportMode.MOTORCYCLE else 1.54), "MORNING_PEAK_HCMC"
    if 16.5 <= hour_float <= 19.25:
        mult = (1.38 if mode == TransportMode.MOTORCYCLE else 1.64)
        if is_weekend:
            mult = round(1.0 + (mult - 1.0) * 0.75, 2)
        return mult, "EVENING_PEAK_HCMC"
    if (8.75 < hour_float < 16.5) or (19.25 < hour_float <= 21.5):
        return (1.14 if mode == TransportMode.MOTORCYCLE else 1.25), "DAYTIME_URBAN_HCMC"
    return 1.0, "NIGHT_FREE_FLOW_HCMC"


def calculate_hcmc_route_eta(
    segments: List[RouteSegmentRisk],
    total_distance_m: float,
    osrm_duration_seconds: float,
    transport_mode: Union[str, TransportMode] = TransportMode.MOTORCYCLE,
    departure_dt: Optional[datetime] = None,
    weather_tide: Optional[WeatherTideSignal] = None,
    has_live_corridor_provider: bool = False,
    provider_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Replace covered OSRM time with measured travel time; estimate only uncovered road.

    Risk/closure warnings remain separate from ETA. Density, rain and hypothetical
    traffic lights do not supply measured travel times. Motorbike routes still use
    the installed OSRM driving graph; their uncovered time is an estimate.
    """
    mode = normalize_transport_mode(transport_mode)
    rush_mult, time_period_label = _get_hcmc_time_of_day_multiplier(mode, departure_dt)

    def finite_nonnegative(value: Any) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) and number >= 0 else 0.0
        except (TypeError, ValueError):
            return 0.0

    distance = finite_nonnegative(total_distance_m)
    raw_duration = finite_nonnegative(osrm_duration_seconds)
    lengths = [finite_nonnegative(s.length_meters) for s in segments]
    segment_distance = sum(lengths)
    dist_scale = distance / segment_distance if segment_distance > 0 else 1.0
    # Preserve relative step times; distribute missing step times by distance.
    weights = [finite_nonnegative(s.osrm_duration_seconds) or
               (raw_duration * length / segment_distance if segment_distance else 0.0)
               for s, length in zip(segments, lengths)]
    weight_sum = sum(weights)
    fallback_speed = HCMC_ROAD_CLASS_SPEEDS_KMH[mode]["URBAN_STANDARD"] / 3.6
    base_travel_time_sec = live_traffic_delay_sec = urban_tod_delay_sec = 0.0
    covered_distance_m = confidence_distance = 0.0
    admitted_statuses: List[TrafficStatus] = []

    for seg, length, weight in zip(segments, lengths, weights):
        seg_len = length * dist_scale
        if seg_len <= 0:
            continue
        if mode == TransportMode.WALKING:
            base_travel_time_sec += seg_len / (4.8 / 3.6)
            continue
        step_base = (raw_duration * weight / weight_sum if raw_duration > 0 and weight_sum > 0
                     else seg_len / fallback_speed)
        speed = finite_nonnegative(seg.observed_speed_kmh)
        confidence = finite_nonnegative(seg.traffic_confidence)
        freshness = seg.traffic_freshness_seconds
        matched = seg.traffic_segment_match_status in ("CORRIDOR_MATCHED", "OBSERVED_SEGMENT_VERIFIED")
        observed_length = finite_nonnegative(seg.traffic_observed_length_meters)
        eligible = (
            not seg.is_closed and seg.traffic_status in
                (TrafficStatus.FREE_FLOW, TrafficStatus.SLOW, TrafficStatus.CONGESTED)
            and matched and 0 < speed <= 160 and .3 <= confidence <= 1
            and freshness is not None and math.isfinite(freshness) and 0 <= freshness <= 300
            and observed_length > 0
        )
        fraction = min(1.0, observed_length / length) if eligible and length > 0 else 0.0
        uncovered_base = step_base * (1.0 - fraction)
        base_travel_time_sec += uncovered_base
        urban_tod_delay_sec += uncovered_base * (rush_mult - 1.0)
        if fraction <= 0:
            continue
        observed_distance = seg_len * fraction
        observed_time = observed_distance / (speed / 3.6)
        free_speed = finite_nonnegative(seg.free_flow_speed_kmh)
        # A provider can report current speed above its normal free-flow baseline.
        # Keep total time exactly speed-derived instead of inventing negative delay.
        free_time = (min(observed_time, observed_distance / (free_speed / 3.6))
                     if 0 < free_speed <= 160 else observed_time)
        base_travel_time_sec += free_time
        live_traffic_delay_sec += observed_time - free_time
        covered_distance_m += observed_distance
        confidence_distance += observed_distance * confidence
        admitted_statuses.append(seg.traffic_status)

    if not segment_distance and distance > 0:
        base_travel_time_sec = (distance / (4.8 / 3.6) if mode == TransportMode.WALKING
                                else raw_duration or distance / fallback_speed)
        urban_tod_delay_sec = base_travel_time_sec * (rush_mult - 1.0)

    total_traffic_delay_sec = live_traffic_delay_sec + urban_tod_delay_sec
    estimated_duration_sec = base_travel_time_sec + total_traffic_delay_sec
    is_live = covered_distance_m > 0
    coverage_ratio = min(1.0, covered_distance_m / distance) if distance > 0 else 0.0
    effective_speed_kmh = (round(distance / 1000.0 / (estimated_duration_sec / 3600.0), 2)
                           if estimated_duration_sec > 0 else 0.0)
    statuses = {s.traffic_status for s in segments}
    if any(s.is_closed for s in segments) or TrafficStatus.CLOSED in statuses:
        route_traffic_status = TrafficStatus.CLOSED
    elif TrafficStatus.CONGESTED in statuses:
        route_traffic_status = TrafficStatus.CONGESTED
    elif TrafficStatus.SLOW in statuses:
        route_traffic_status = TrafficStatus.SLOW
    elif TrafficStatus.FREE_FLOW in admitted_statuses:
        route_traffic_status = TrafficStatus.FREE_FLOW
    else:
        route_traffic_status = TrafficStatus.UNKNOWN

    if mode == TransportMode.WALKING:
        eta_source, traffic_eta_status, data_freshness = "WALKING_DISTANCE_ESTIMATE", "BASE_OSRM_NO_TRAFFIC", "ESTIMATED"
    elif is_live:
        scope = "FULL" if coverage_ratio >= .999999 else "PARTIAL"
        source = provider_name if has_live_corridor_provider and provider_name else "VERIFIED_SPEED"
        eta_source = f"{source}_MEASURED_SPEED_{scope}"
        traffic_eta_status = ("TRAFFIC_ADJUSTED" if total_traffic_delay_sec > 0 or
                              any(s != TrafficStatus.FREE_FLOW for s in admitted_statuses)
                              else "TRAFFIC_VERIFIED_FREE_FLOW")
        data_freshness = "LIVE_VERIFIED"
    else:
        origin = "OSRM" if raw_duration > 0 else "DISTANCE"
        eta_source = f"{origin}_TIME_OF_DAY_ESTIMATE_{mode.value}_{time_period_label}"
        traffic_eta_status, data_freshness = "BASE_OSRM_NO_TRAFFIC", "ESTIMATED"
    # Confidence describes admitted observation support, never calibrated ETA accuracy.
    confidence = min(1.0, confidence_distance / distance) if distance > 0 else 0.0
    base_seconds, delay_seconds = round(base_travel_time_sec, 1), round(total_traffic_delay_sec, 1)
    estimated_seconds = round(base_seconds + delay_seconds, 1)
    breakdown = ETABreakdownDTO(
        osrm_raw_duration_seconds=round(raw_duration, 1),
        base_travel_time_seconds=base_seconds,
        traffic_delay_seconds=delay_seconds,
        additional_delay_seconds=0.0,
        intersection_delay_seconds=0.0,
        environmental_delay_seconds=0.0,
        intersection_turn_delay_seconds=0.0,
        weather_flood_delay_seconds=0.0,
        total_additional_delay_seconds=0.0,
        estimated_duration_seconds=estimated_seconds,
        time_of_day_multiplier=round(rush_mult, 2),
        rush_hour_multiplier=round(rush_mult, 2),
        time_of_day_period=time_period_label,
        effective_speed_kmh=effective_speed_kmh,
        transport_mode=mode.value,
        eta_source=eta_source,
        is_live_traffic=is_live,
        traffic_status=route_traffic_status.value,
        data_freshness=data_freshness,
        confidence=confidence,
    )
    return {
        "transport_mode": mode,
        "duration_seconds": round(raw_duration, 1),
        "baseline_duration_seconds": base_seconds,
        "duration_in_traffic_seconds": estimated_seconds if is_live else None,
        "estimated_duration_seconds": estimated_seconds,
        "traffic_adjusted_eta_seconds": estimated_seconds if is_live else None,
        "estimated_time_mins": round(estimated_seconds / 60.0, 1),
        "traffic_delay_seconds": delay_seconds,
        "live_traffic_delay_seconds": round(live_traffic_delay_sec, 1),
        "covered_distance_m": round(covered_distance_m, 1),
        "eta_source": eta_source,
        "traffic_eta_status": traffic_eta_status,
        "traffic_eta_source": eta_source,
        "is_live_traffic": is_live,
        "traffic_status": route_traffic_status,
        "data_freshness": data_freshness,
        "eta_breakdown": breakdown,
    }

async def _get_osrm_raw_routes(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """Fetch up to three alternatives; OSRM may return fewer or only one."""
    global _osrm_circuit_open_until
    for lat, lng in ((origin_lat, origin_lng), (dest_lat, dest_lng)):
        _validate_point(lat, lng)
    if origin_lat == dest_lat and origin_lng == dest_lng:
        raise RoutingError("INVALID_COORDINATES", 422, "Origin and destination must differ.")
    if time.monotonic() < _osrm_circuit_open_until:
        raise RoutingError("ROUTING_PROVIDER_UNAVAILABLE", 503, "OSRM is temporarily unavailable.")

    base_url = settings.OSRM_BASE_URL.rstrip("/")
    url = (f"{base_url}/route/v1/driving/"
           f"{origin_lng},{origin_lat};{dest_lng},{dest_lat}")
    params = {"alternatives": "3", "steps": "true", "geometries": "geojson", "overview": "full", "annotations": "nodes"}
    close_client = client is None or getattr(client, "is_closed", False)
    if close_client:
        client = httpx.AsyncClient(timeout=8.0)
    try:
        from backend.app.core.observability import observe_operation
        with observe_operation("osrm"):
            response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        _osrm_circuit_open_until = time.monotonic() + 15.0
        logger.warning("OSRM request failed: %s", exc)
        raise RoutingError("ROUTING_PROVIDER_UNAVAILABLE", 503, "OSRM did not return a valid response.") from exc
    finally:
        if close_client:
            await client.aclose()

    if not isinstance(data, dict):
        raise RoutingError("ROUTING_PROVIDER_UNAVAILABLE", 503, "OSRM returned malformed JSON.")
    if data.get("code") in ("NoRoute", "NoSegment"):
        raise RoutingError("NO_ROUTE_FOUND", 404, "OSRM found no connected driving route.")
    if data.get("code") != "Ok":
        raise RoutingError("ROUTING_PROVIDER_UNAVAILABLE", 503, "OSRM returned an error.")
    routes = data.get("routes")
    if not isinstance(routes, list) or not routes:
        raise RoutingError("ROUTING_PROVIDER_UNAVAILABLE", 503, "OSRM returned no routes despite code=Ok.")
    if not all(_valid_route(route) for route in routes):
        raise RoutingError("ROUTING_PROVIDER_UNAVAILABLE", 503, "OSRM returned incomplete route geometry or metrics.")
    waypoints = data.get("waypoints")
    if isinstance(waypoints, list):
        for route in routes:
            route["_waypoints"] = waypoints
    return routes


async def _count_cameras_in_corridor(
    coords: list[list[float]], db_session: Union[AsyncSession, Session]
) -> Optional[int]:
    """Count cameras with independently verified GPS near this line only."""
    if not _valid_geometry({"type": "LineString", "coordinates": coords}):
        return None
    wkt = "LINESTRING(" + ", ".join(f"{lng} {lat}" for lng, lat in (pt[:2] for pt in coords)) + ")"
    query = text("""SELECT count(DISTINCT cam_id) FROM traffic_cameras
        WHERE geom IS NOT NULL AND coordinate_source_url IS NOT NULL
          AND coordinate_verified_at IS NOT NULL
          AND ST_DWithin(geom::geography,
            ST_SetSRID(ST_GeomFromText(:line), 4326)::geography, :radius)""")
    try:
        result = await db_session.execute(query, {"line": wkt, "radius": CORRIDOR_BUFFER_METERS}) if isinstance(db_session, AsyncSession) else db_session.execute(query, {"line": wkt, "radius": CORRIDOR_BUFFER_METERS})
        return int(result.scalar_one())
    except Exception as exc:
        logger.warning("Camera corridor coverage unavailable: %s", exc)
        return None


async def _edge_candidates_for_step(
    coords: list[list[float]], db_session: Union[AsyncSession, Session]
) -> Optional[list[dict[str, int]]]:
    """Nearby OSM vertex-pair edges. A spatial candidate is not a verified OSRM edge ID."""
    if not _valid_geometry({"type": "LineString", "coordinates": coords}):
        return None
    wkt = "LINESTRING(" + ", ".join(f"{lng} {lat}" for lng, lat in (pt[:2] for pt in coords)) + ")"
    query = text("""
        SELECT e.osm_way_id, e.edge_index FROM road_edges e
        JOIN road_segments r ON r.osm_way_id = e.osm_way_id
        WHERE r.source_url = 'https://download.geofabrik.de/asia/vietnam-latest.osm.pbf'
          AND ST_DWithin(e.geom::geography,
              ST_SetSRID(ST_GeomFromText(:line), 4326)::geography, 8)
        ORDER BY ST_Distance(e.geom::geography,
            ST_SetSRID(ST_GeomFromText(:line), 4326)::geography),
            e.osm_way_id, e.edge_index
        LIMIT 16
    """)
    try:
        result = await db_session.execute(query, {"line": wkt}) if isinstance(db_session, AsyncSession) else db_session.execute(query, {"line": wkt})
        return [{"osm_way_id": int(row[0]), "edge_index": int(row[1])} for row in result.fetchall()]
    except Exception as exc:
        logger.warning("OSM edge candidates unavailable: %s", exc)
        return None


async def _get_flood_prone_way_ids(
    way_ids: list[int], db_session: Union[AsyncSession, Session]
) -> Set[int]:
    """Returns the set of way_ids documented as flood prone in municipal records."""
    if not way_ids:
        return set()
    query = text("""
        SELECT osm_way_id FROM road_segments
        WHERE osm_way_id = ANY(:way_ids) AND is_flood_prone_history = TRUE
    """)
    try:
        if isinstance(db_session, AsyncSession):
            result = await db_session.execute(query, {"way_ids": way_ids})
        else:
            result = db_session.execute(query, {"way_ids": way_ids})
        return set(int(row[0]) for row in result.fetchall())
    except Exception as exc:
        logger.warning("Failed to query flood prone ways: %s", exc)
        return set()


async def _get_cameras_for_step(
    coords: list[list[float]],
    db_session: Union[AsyncSession, Session],
    redis_client: Optional[Redis] = None,
) -> list[CameraEvidence]:
    """Fetches cameras within corridor and resolves their latest live evidence state."""
    if not _valid_geometry({"type": "LineString", "coordinates": coords}):
        return []
    wkt = "LINESTRING(" + ", ".join(f"{lng} {lat}" for lng, lat in (pt[:2] for pt in coords)) + ")"
    query = text("""
        SELECT c.cam_id, c.code, c.name, c.district, ST_Y(c.geom) AS lat, ST_X(c.geom) AS lng,
               c.nearest_osm_way_id AS osm_way_id,
               c.coordinate_source_url, c.observed_osm_way_id,
               c.observed_edge_index, c.view_verification_source_url, c.line_of_sight_verified
        FROM traffic_cameras c
        WHERE c.geom IS NOT NULL AND c.coordinate_source_url IS NOT NULL
          AND c.coordinate_verified_at IS NOT NULL
          AND ST_DWithin(c.geom::geography,
              ST_SetSRID(ST_GeomFromText(:line), 4326)::geography, :radius)
    """)
    try:
        if isinstance(db_session, AsyncSession):
            res = await db_session.execute(query, {"line": wkt, "radius": CORRIDOR_BUFFER_METERS})
        else:
            res = db_session.execute(query, {"line": wkt, "radius": CORRIDOR_BUFFER_METERS})
        rows = res.fetchall()
        cameras: list[CameraEvidence] = []
        for r in rows:
            cam_data = None
            if redis_client is not None:
                try:
                    cached_raw = await redis_client.get(f"camera_evidence:{r.cam_id}")
                    if cached_raw:
                        cam_data = json.loads(cached_raw)
                except Exception:
                    pass

            if cam_data:
                try:
                    cameras.append(CameraEvidence.model_validate(cam_data))
                    continue
                except Exception:
                    pass

            match_status = "OBSERVED_SEGMENT_VERIFIED" if r.observed_osm_way_id is not None else "SPATIALLY_NEAR"
            has_local = os.path.exists(os.path.join("storage", "cams", f"{r.cam_id}.jpg"))
            cameras.append(CameraEvidence(
                cam_id=r.cam_id,
                code=r.code,
                name=r.name,
                district=r.district,
                lat=r.lat,
                lng=r.lng,
                osm_way_id=r.osm_way_id,
                coordinate_source_url=r.coordinate_source_url,
                spatial_match_status=match_status,
                observed_osm_way_id=r.observed_osm_way_id,
                observed_edge_index=r.observed_edge_index,
                view_verification_source_url=r.view_verification_source_url,
                line_of_sight_verified=bool(r.line_of_sight_verified),
                image_url=f"/api/v1/cameras/{r.cam_id}/image" if has_local else "",
                has_image=has_local,
                image_access_status=ImageAccessStatus.VIEWABLE_PUBLIC if has_local else ImageAccessStatus.UNAVAILABLE,
                evidence_eligibility=EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING,
                image_status="VALID_IMAGE_CACHED" if has_local else "NO_IMAGE",
                image_status_reason="VALID_IMAGE_CACHED" if has_local else "IMAGE_UNAVAILABLE",
                model_status="NOT_ANALYZED",
                vehicle_count=None,
                traffic_density_score=None,
                flood_ratio=None,
                risk_level=RiskLevel.UNKNOWN,
                source_status=DataSourceStatus.STALE,
                updated_at=datetime.now(timezone.utc),
            ))
        return cameras
    except Exception as exc:
        logger.warning("Failed to fetch corridor cameras: %s", exc)
        return []


async def _batched_spatial_context(
    routes: list[dict[str, Any]],
    db_session: Union[AsyncSession, Session],
    redis_client: Optional[Redis],
    spatial_cache_key: Optional[str] = None,
) -> tuple[dict[tuple[int, int], list[dict[str, int]]], dict[tuple[int, int], list[CameraEvidence]], bool, bool]:
    """Two PostGIS queries for all OSRM steps, then one Redis MGET for camera state.

    Proximity returns candidates only. Exact directed node pairs, same-PBF graph
    proof, ambiguity rejection and full-step coverage are checked independently.
    """
    steps = []
    for route_idx, route in enumerate(routes):
        step_idx = 0
        for leg in route.get("legs", []):
            for step in leg.get("steps", []):
                if _valid_geometry(step.get("geometry")):
                    steps.append({"route_idx": route_idx, "step_idx": step_idx, "geometry": step["geometry"]})
                step_idx += 1
    if not steps:
        return {}, {}, True, True

    step_cte = """WITH step_lines AS (
        SELECT s.route_idx, s.step_idx,
               ST_SetSRID(ST_GeomFromGeoJSON(s.geometry::text), 4326)::geography AS geog
        FROM jsonb_to_recordset(CAST(:steps AS jsonb))
             AS s(route_idx integer, step_idx integer, geometry jsonb)
    )"""
    edge_sql = text(step_cte + """
        SELECT s.route_idx, s.step_idx, e.osm_way_id, e.edge_index
        FROM step_lines s JOIN LATERAL (
            SELECT e.osm_way_id, e.edge_index
            FROM road_edges e JOIN road_segments r ON r.osm_way_id = e.osm_way_id
            WHERE r.source_url = 'https://download.geofabrik.de/asia/vietnam-latest.osm.pbf'
              AND ST_DWithin(e.geom::geography, s.geog, 8)
            ORDER BY ST_Distance(e.geom::geography, s.geog), e.osm_way_id, e.edge_index
            LIMIT 16
        ) e ON TRUE
    """)
    camera_sql = text(step_cte + """
        SELECT s.route_idx, s.step_idx, c.cam_id, c.code, c.name, c.district,
               ST_Y(c.geom) AS lat, ST_X(c.geom) AS lng,
               c.nearest_osm_way_id AS osm_way_id, c.coordinate_source_url,
               c.observed_osm_way_id, c.observed_edge_index,
               c.view_verification_source_url, c.line_of_sight_verified, c.permitted_use
        FROM step_lines s JOIN traffic_cameras c
          ON c.geom IS NOT NULL AND c.coordinate_source_url IS NOT NULL
         AND c.coordinate_verified_at IS NOT NULL
         AND ST_DWithin(c.geom::geography, s.geog, :radius)
    """)
    params = {"steps": json.dumps(steps, separators=(",", ":")), "radius": CORRIDOR_BUFFER_METERS}
    edges: dict[tuple[int, int], list[dict[str, int]]] = {}
    cameras: dict[tuple[int, int], list[CameraEvidence]] = {}
    edges_available = True
    cameras_available = True
    async def load_cached_edges() -> bool:
        nonlocal edges
        if not spatial_cache_key or redis_client is None:
            return False
        try:
            raw_edges = await redis_client.get(f"{spatial_cache_key}:edges")
            if raw_edges:
                encoded = json.loads(raw_edges)
                if isinstance(encoded, dict):
                    edges = {tuple(map(int, key.split(":"))): [{**edge, "route_match_verified": False} for edge in value] for key, value in encoded.items()}
                    return True
        except Exception:
            pass
        return False

    async def query_and_cache_edges() -> None:
        nonlocal edges_available
        try:
            result = await db_session.execute(edge_sql, params) if isinstance(db_session, AsyncSession) else db_session.execute(edge_sql, params)
            for row in result.fetchall():
                edges.setdefault((row.route_idx, row.step_idx), []).append({"osm_way_id": int(row.osm_way_id), "edge_index": int(row.edge_index), "route_match_verified": False})
            if spatial_cache_key and redis_client is not None:
                encoded = {f"{key[0]}:{key[1]}": value for key, value in edges.items()}
                try:
                    await redis_client.set(f"{spatial_cache_key}:edges", json.dumps(encoded), ex=300)
                except Exception:
                    pass
        except Exception as exc:
            edges_available = False
            logger.warning("Batched road candidates unavailable: %s", exc)

    if not await load_cached_edges():
        if spatial_cache_key:
            async with _edge_cache_lock(spatial_cache_key):
                if not await load_cached_edges():
                    await query_and_cache_edges()
        else:
            await query_and_cache_edges()

    # Revalidate against topology and current graph proof on every request. Cached
    # candidate flags can never grant verified status after graph/import changes.
    from backend.app.services.route_matching import graph_proof, verified_step_edges
    try:
        proof = await asyncio.to_thread(graph_proof)
        proven_edges = await verified_step_edges(routes, db_session, proof)
        edges.update(proven_edges)
    except Exception as exc:
        logger.warning("Exact OSM node matching unavailable: %s", exc)

    try:
        result = await db_session.execute(camera_sql, params) if isinstance(db_session, AsyncSession) else db_session.execute(camera_sql, params)
        rows = result.fetchall()
    except Exception as exc:
        cameras_available = False
        logger.warning("Batched camera coverage unavailable: %s", exc)
        rows = []

    unique_ids = list(dict.fromkeys(str(row.cam_id) for row in rows))
    cached: dict[str, CameraEvidence] = {}
    if unique_ids and redis_client is not None:
        try:
            from backend.app.services.camera_scheduler import camera_scheduler
            await camera_scheduler.register_active_route_cameras(redis_client, unique_ids, ttl_seconds=900)
        except Exception as exc:
            logger.debug("Failed registering corridor cameras to priority queue: %s", exc)
        try:
            values = await redis_client.mget([f"camera_evidence:{cam_id}" for cam_id in unique_ids])
            for cam_id, raw in zip(unique_ids, values):
                if raw:
                    try:
                        cached[cam_id] = CameraEvidence.model_validate_json(raw)
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning("Batched camera cache read unavailable: %s", exc)

    fallback: dict[str, CameraEvidence] = {}
    for row in rows:
        cam_id = str(row.cam_id)
        evidence = cached.get(cam_id)
        if evidence is None:
            if cam_id not in fallback:
                has_local = os.path.exists(os.path.join("storage", "cams", f"{cam_id}.jpg"))
                fallback[cam_id] = CameraEvidence(
                    cam_id=cam_id, code=row.code, name=row.name, district=row.district,
                    lat=row.lat, lng=row.lng, osm_way_id=row.osm_way_id,
                    coordinate_source_url=row.coordinate_source_url,
                    spatial_match_status="OBSERVED_SEGMENT_VERIFIED" if row.observed_osm_way_id is not None and row.line_of_sight_verified else "SPATIALLY_NEAR",
                    observed_osm_way_id=row.observed_osm_way_id, observed_edge_index=row.observed_edge_index,
                    view_verification_source_url=row.view_verification_source_url,
                    line_of_sight_verified=bool(row.line_of_sight_verified),
                    image_url=f"/api/v1/cameras/{cam_id}/image" if has_local else "",
                    has_image=has_local,
                    image_access_status=ImageAccessStatus.VIEWABLE_PUBLIC if has_local else ImageAccessStatus.UNAVAILABLE,
                    evidence_eligibility=EvidenceEligibility.NOT_VERIFIED_FOR_ROUTING,
                    image_status="VALID_IMAGE_CACHED" if has_local else "NO_IMAGE",
                    image_status_reason="VALID_IMAGE_CACHED" if has_local else "IMAGE_UNAVAILABLE",
                    model_status="NOT_ANALYZED", vehicle_count=None, traffic_density_score=None,
                    flood_ratio=None, risk_level=RiskLevel.UNKNOWN, source_status=DataSourceStatus.STALE,
                    updated_at=datetime.now(timezone.utc),
                )
            evidence = fallback[cam_id]
        # Registry provenance wins over historical metadata embedded in AI caches.
        evidence = evidence.model_copy(update={
            "coordinate_source_url": row.coordinate_source_url,
            "permitted_use": getattr(row, "permitted_use", None),
            "observed_osm_way_id": row.observed_osm_way_id,
            "observed_edge_index": row.observed_edge_index,
            "view_verification_source_url": row.view_verification_source_url,
            "line_of_sight_verified": bool(row.line_of_sight_verified),
            "spatial_match_status": "OBSERVED_SEGMENT_VERIFIED" if row.observed_osm_way_id is not None and row.line_of_sight_verified else "SPATIALLY_NEAR",
        })
        cameras.setdefault((row.route_idx, row.step_idx), []).append(evidence)
    return edges, cameras, edges_available, cameras_available


async def find_safe_route(
    origin_lat: float, origin_lng: float, dest_lat: float, dest_lng: float,
    db_session: Union[AsyncSession, Session], redis_client: Optional[Redis] = None,
    osrm_client: Optional[httpx.AsyncClient] = None, request_id: Optional[str] = None,
    transport_mode: Union[str, TransportMode] = TransportMode.MOTORCYCLE,
    departure_dt: Optional[datetime] = None,
) -> list[SafeRouteResponse]:
    """Return OSRM alternatives ranked using independently verified edge evidence."""
    mode_enum = normalize_transport_mode(transport_mode)
    started_at = time.perf_counter()
    cache_key = _osrm_cache_key(origin_lat, origin_lng, dest_lat, dest_lng)
    raw_routes = None
    cache_hit = False
    if cache_key and redis_client is not None:
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                candidate = json.loads(cached)
                if isinstance(candidate, list) and candidate and all(_valid_route(route) for route in candidate):
                    raw_routes = candidate
                    cache_hit = True
        except Exception:
            pass
    if raw_routes is None:
        raw_routes = await _get_osrm_raw_routes(origin_lat, origin_lng, dest_lat, dest_lng, client=osrm_client)
        if cache_key and redis_client is not None:
            try:
                await redis_client.set(cache_key, json.dumps(raw_routes, separators=(",", ":")), ex=OSRM_CACHE_TTL_SECONDS)
            except Exception:
                pass
    osrm_done_at = time.perf_counter()
    edges_by_step, cameras_by_step, edges_available, cameras_available = await _batched_spatial_context(raw_routes, db_session, redis_client, cache_key)
    db_done_at = time.perf_counter()

    weather_tide: Optional[WeatherTideSignal] = None
    if redis_client is not None:
        try:
            weather_tide = await get_cached_weather_tide(redis_client)
        except Exception:
            pass

    traffic_news: List[Any] = []
    if redis_client is not None:
        try:
            from backend.app.services.traffic_news import get_cached_news_feed
            articles, _ = await get_cached_news_feed(redis_client)
            traffic_news = articles or []
        except Exception:
            pass

    # C02: Batch lookup of municipal historical flood-prone OSM ways across all candidate edges
    all_candidate_way_ids = list({
        edge["osm_way_id"]
        for edge_list in edges_by_step.values()
        for edge in edge_list
        if "osm_way_id" in edge
    })
    flood_prone_ways = await _get_flood_prone_way_ids(all_candidate_way_ids, db_session) if all_candidate_way_ids else set()

    community_by_edge = {}
    edge_ids = {(edge["osm_way_id"], edge["edge_index"]) for items in edges_by_step.values()
                for edge in items if edge.get("route_match_verified") is True}
    if edge_ids:
        try:
            from backend.app.services.community_incidents import load_verified_incidents
            community_by_edge = await load_verified_incidents(db_session, edge_ids)
        except Exception as exc:
            logger.warning("Verified community incidents unavailable: %s", exc)

    # Resolve reliable context first; an established hazard needs no extra visual inference.
    from backend.app.services.route_camera_ai import enrich_route_cameras
    step_context = {}
    for route_idx, route in enumerate(raw_routes):
        step_idx = 0
        for leg in route.get("legs", []):
            for step in leg.get("steps", []):
                step_context[(route_idx, step_idx)] = step
                step_idx += 1
    cameras_by_step = await enrich_route_cameras(
        cameras_by_step, edges_by_step, db_session, redis_client,
        weather_tide=weather_tide, traffic_news=traffic_news, step_context=step_context,
    )

    responses: list[SafeRouteResponse] = []
    explanation_elapsed = 0.0
    for route_idx, route in enumerate(raw_routes):
        camera_count = len({camera.cam_id for (ri, _), cams in cameras_by_step.items() if ri == route_idx for camera in cams}) if cameras_available else None
        route_coords = route["geometry"]["coordinates"]

        # Prepare segment descriptors for external live traffic flow provider
        raw_steps_list = []
        for leg in route.get("legs", []):
            for step in leg.get("steps", []):
                raw_steps_list.append({
                    "length_meters": step.get("distance", 0.0),
                    "geojson_path": step.get("geometry"),
                    "street_name": step.get("name"),
                })

        traffic_provider = get_traffic_provider()
        corridor_traffic = {}
        if traffic_provider.is_configured():
            try:
                corridor_traffic = await traffic_provider.get_corridor_traffic(
                    route_coords, raw_steps_list, redis_client=redis_client
                )
            except Exception as tp_err:
                logger.warning("Corridor traffic query error from %s: %s", traffic_provider.name, tp_err)

        segments: list[RouteSegmentRisk] = []
        step_idx = -1
        for leg in route.get("legs", []):
            for step in leg.get("steps", []):
                step_idx += 1
                geometry = step.get("geometry")
                if not _valid_geometry(geometry):
                    continue
                distance = step.get("distance")
                if not isinstance(distance, (int, float)) or not math.isfinite(distance) or distance < 0:
                    continue
                maneuver = step.get("maneuver") if isinstance(step.get("maneuver"), dict) else {}
                raw_location = maneuver.get("location")
                maneuver_location = (
                    [float(raw_location[0]), float(raw_location[1])]
                    if isinstance(raw_location, list) and len(raw_location) >= 2
                    and all(isinstance(v, (int, float)) and math.isfinite(v) for v in raw_location[:2])
                    else None
                )
                maneuver_fields = {
                    "maneuver_type": maneuver.get("type") if isinstance(maneuver.get("type"), str) else None,
                    "maneuver_modifier": maneuver.get("modifier") if isinstance(maneuver.get("modifier"), str) else None,
                    "maneuver_location": maneuver_location,
                    "maneuver_exit": maneuver.get("exit") if isinstance(maneuver.get("exit"), int) and maneuver.get("exit") > 0 else None,
                }
                edge_candidates = edges_by_step.get((route_idx, step_idx), [])
                road_candidates = list(dict.fromkeys(edge["osm_way_id"] for edge in edge_candidates))
                step_cameras = cameras_by_step.get((route_idx, step_idx), [])

                # Proximity is not an OSRM-step/edge proof (bridges and parallel roads).
                verified_edges = [edge for edge in edge_candidates if edge.get("route_match_verified") is True]
                best_way_id = verified_edges[0]["osm_way_id"] if len(verified_edges) == 1 else None
                best_edge_index = verified_edges[0]["edge_index"] if len(verified_edges) == 1 else None
                edge_risks = []
                for edge in verified_edges:
                    try:
                        edge_risks.append(calculate_segment_risk(
                            segment={
                                "osm_way_id": edge["osm_way_id"], "edge_index": edge["edge_index"],
                                "street_name": step.get("name") or None,
                                "length_meters": edge.get("length_meters", distance / len(verified_edges)),
                                "geojson_path": edge.get("geometry", geometry),
                                "is_flood_prone_history": edge["osm_way_id"] in flood_prone_ways,
                                "source_url": "https://download.geofabrik.de/asia/vietnam-latest.osm.pbf",
                            }, camera_evidences=step_cameras, weather_tide=weather_tide, traffic_news=traffic_news,
                            community_incidents=community_by_edge.get((edge["osm_way_id"], edge["edge_index"]), []),
                        ))
                    except Exception as risk_err:
                        logger.warning("Edge risk scoring failed: %s", risk_err)
                        edge_risks.append(RouteSegmentRisk(
                            osm_way_id=edge["osm_way_id"], osm_edge_index=edge["edge_index"],
                            length_meters=distance / len(verified_edges), risk_level=RiskLevel.UNKNOWN,
                            evidence_coverage="EDGE_RISK_UNAVAILABLE", traffic_observed_length_meters=0.0,
                        ))
                evaluated_risk = aggregate_edge_risks(edge_risks) if edge_risks else None

                # Prioritize commercial real-time flow provider if data exists for this segment
                provider_flow = corridor_traffic.get(step_idx)
                seg_is_closed = False
                if provider_flow and provider_flow.traffic_status != TrafficStatus.UNKNOWN:
                    seg_traffic_status = provider_flow.traffic_status
                    seg_is_closed = bool(getattr(provider_flow, "is_closed", False) or provider_flow.traffic_status == TrafficStatus.CLOSED)
                    seg_observed_speed = provider_flow.current_speed_kmh
                    seg_free_flow_speed = provider_flow.free_flow_speed_kmh
                    seg_traffic_density = None
                    seg_traffic_confidence = provider_flow.confidence
                    seg_traffic_freshness = provider_flow.freshness_seconds
                    seg_traffic_source = provider_flow.source
                    seg_traffic_method = "COMMERCIAL_FLOW_API"
                    seg_traffic_match = provider_flow.match_status
                    seg_traffic_delay = provider_flow.traffic_delay_seconds
                    seg_observed_at = provider_flow.observed_at
                elif evaluated_risk is not None:
                    seg_traffic_status = evaluated_risk.traffic_status
                    seg_is_closed = bool(evaluated_risk.is_closed or evaluated_risk.traffic_status == TrafficStatus.CLOSED)
                    seg_observed_speed = evaluated_risk.observed_speed_kmh
                    seg_free_flow_speed = None
                    seg_traffic_density = evaluated_risk.traffic_density_score
                    seg_traffic_confidence = evaluated_risk.traffic_confidence
                    seg_traffic_freshness = evaluated_risk.traffic_freshness_seconds
                    seg_traffic_source = evaluated_risk.traffic_source
                    seg_traffic_method = evaluated_risk.traffic_estimation_method
                    seg_traffic_match = evaluated_risk.traffic_segment_match_status
                    seg_traffic_delay = evaluated_risk.traffic_delay_seconds
                    seg_observed_at = None
                else:
                    seg_traffic_status = TrafficStatus.UNKNOWN
                    seg_is_closed = False
                    seg_observed_speed = None
                    seg_free_flow_speed = None
                    seg_traffic_density = None
                    seg_traffic_confidence = None
                    seg_traffic_freshness = None
                    seg_traffic_source = None
                    seg_traffic_method = None
                    seg_traffic_match = "UNMATCHED"
                    seg_traffic_delay = 0.0
                    seg_observed_at = None

                if evaluated_risk is not None:
                    seg_risk_level = evaluated_risk.risk_level
                    seg_risk_score = evaluated_risk.risk_score
                    seg_coverage = evaluated_risk.evidence_coverage
                    seg_freshness = evaluated_risk.freshness_seconds
                    seg_weather = evaluated_risk.weather_risk
                    seg_road_status = "OSRM_NODE_PAIRS_VERIFIED"
                    seg_street = step.get("name") or evaluated_risk.street_name
                    seg_hist_flood = evaluated_risk.historical_flood_prone
                    seg_hist_cause = evaluated_risk.historical_flood_cause
                else:
                    seg_risk_level = RiskLevel.UNKNOWN
                    seg_risk_score = None
                    seg_coverage = "CORRIDOR_DATA_UNAVAILABLE" if not cameras_available else "SPATIALLY_NEAR_UNVERIFIED_VIEW" if step_cameras else "NO_VERIFIED_CAMERA_GPS"
                    seg_freshness = None
                    seg_weather = None
                    seg_road_status = "ROAD_GRAPH_UNAVAILABLE" if not edges_available else "CANDIDATE_ONLY" if edge_candidates else "NO_ROAD_EDGE_MATCH"
                    seg_street = step.get("name") or None
                    seg_hist_flood = (best_way_id in flood_prone_ways) if best_way_id is not None else None
                    seg_hist_cause = None

                if evaluated_risk is not None and evaluated_risk.is_closed:
                    seg_is_closed = True
                # B06: If commercial flow or verified news reports a closed road, elevate segment risk to CRITICAL
                if seg_is_closed or seg_traffic_status == TrafficStatus.CLOSED:
                    seg_traffic_status = TrafficStatus.CLOSED
                    seg_is_closed = True
                    seg_risk_level = RiskLevel.CRITICAL
                    seg_risk_score = max(seg_risk_score or 0.0, 95.0)

                segments.append(RouteSegmentRisk(
                    osm_way_id=best_way_id if (evaluated_risk and evaluated_risk.evidence_coverage == "OBSERVED_SEGMENT_VERIFIED") else None,
                    osm_edge_index=best_edge_index if (evaluated_risk and evaluated_risk.evidence_coverage == "OBSERVED_SEGMENT_VERIFIED") else None,
                    candidate_osm_way_ids=road_candidates,
                    candidate_road_edges=[{key: edge[key] for key in ("osm_way_id", "edge_index", "route_match_verified") if key in edge} for edge in edge_candidates],
                    road_match_status=seg_road_status,
                    street_name=seg_street,
                    geojson_path=geometry,
                    length_meters=distance,
                    osrm_duration_seconds=step.get("duration"),
                    risk_score=seg_risk_score,
                    risk_level=seg_risk_level,
                    historical_flood_prone=seg_hist_flood,
                    historical_flood_cause=seg_hist_cause,
                    weather_risk=seg_weather,
                    evidence_coverage=seg_coverage,
                    evidence_cameras=step_cameras,
                    freshness_seconds=seg_freshness,
                    traffic_status=seg_traffic_status,
                    traffic_observed_length_meters=((getattr(provider_flow, "observed_length_meters", None) or 0.0) if provider_flow and provider_flow.traffic_status != TrafficStatus.UNKNOWN
                        else getattr(evaluated_risk, "traffic_observed_length_meters", None) if evaluated_risk else 0.0),
                    is_closed=seg_is_closed,
                    observed_speed_kmh=seg_observed_speed,
                    free_flow_speed_kmh=seg_free_flow_speed,
                    traffic_density_score=seg_traffic_density,
                    traffic_confidence=seg_traffic_confidence,
                    traffic_freshness_seconds=seg_traffic_freshness,
                    traffic_source=seg_traffic_source,
                    traffic_estimation_method=seg_traffic_method,
                    traffic_segment_match_status=seg_traffic_match,
                    traffic_delay_seconds=seg_traffic_delay,
                    observed_at=seg_observed_at,
                    **maneuver_fields,
                ))

        if not segments:
            continue
        total_distance_m = float(route["distance"])
        total_distance_km = round(total_distance_m / 1000.0, 3)
        duration_seconds = float(route["duration"])
        osrm_duration_seconds = round(duration_seconds, 1)

        eta_calc = calculate_hcmc_route_eta(
            segments=segments,
            total_distance_m=total_distance_m,
            osrm_duration_seconds=osrm_duration_seconds,
            transport_mode=mode_enum,
            departure_dt=departure_dt,
            weather_tide=weather_tide,
            has_live_corridor_provider=bool(corridor_traffic),
            provider_name=traffic_provider.name if corridor_traffic else None,
        )

        baseline_duration_seconds = eta_calc["baseline_duration_seconds"]
        estimated_duration_seconds = eta_calc["estimated_duration_seconds"]
        duration_in_traffic_seconds = eta_calc["duration_in_traffic_seconds"]
        traffic_adjusted_eta_seconds = eta_calc["traffic_adjusted_eta_seconds"]
        traffic_eta_status = eta_calc["traffic_eta_status"]
        traffic_eta_source = eta_calc["traffic_eta_source"]
        estimated_time_mins = eta_calc["estimated_time_mins"]
        total_traffic_delay = eta_calc["traffic_delay_seconds"]
        covered_distance_m = eta_calc["covered_distance_m"]

        closed_status_val = getattr(TrafficStatus, "CLOSED", None)
        closed_filter = (closed_status_val,) if closed_status_val else ()
        verified_traffic_statuses = (TrafficStatus.FREE_FLOW, TrafficStatus.SLOW, TrafficStatus.CONGESTED) + closed_filter

        verified_traffic_count = sum(1 for s in segments if s.traffic_status in verified_traffic_statuses)
        closed_count = sum(1 for s in segments if (closed_status_val and s.traffic_status == closed_status_val) or getattr(s, "is_closed", False))
        congested_count = sum(1 for s in segments if s.traffic_status == TrafficStatus.CONGESTED)
        slow_count = sum(1 for s in segments if s.traffic_status == TrafficStatus.SLOW)
        traffic_coverage_ratio = round(covered_distance_m / max(total_distance_m, 1.0), 3) if total_distance_m > 0 else 0.0

        # Audit polyline geodesic length vs OSRM distance
        route_id = str(uuid.uuid4())
        geo_len = _geodesic_distance_meters(route_coords)
        step_len = sum(s.length_meters for s in segments)
        diff_geo_pct = abs(geo_len - total_distance_m) / max(total_distance_m, 1.0) * 100.0

        snapped_origin = route.get("_waypoints", [{}])[0].get("location") if route.get("_waypoints") else None
        snapped_dest = route.get("_waypoints", [{}])[-1].get("location") if route.get("_waypoints") else None

        logger.info(
            "OSRM Route Audit: route_id=%s, mode=%s, origin=[%.5f, %.5f], dest=[%.5f, %.5f], snapped_origin=%s, snapped_dest=%s, osrm_dist=%.1fm, geo_dist=%.1fm (diff=%.3f%%), step_dist=%.1fm, osrm_dur=%.1fs, hcmc_eta=%.1fs (%.1f min), vertices=%s, traffic_coverage=%.1f%%",
            route_id, mode_enum.value, origin_lat, origin_lng, dest_lat, dest_lng, snapped_origin, snapped_dest, total_distance_m, geo_len, diff_geo_pct, step_len, duration_seconds, estimated_duration_seconds, estimated_time_mins, len(route_coords), traffic_coverage_ratio * 100.0
        )
        if diff_geo_pct > 5.0:
            logger.warning(
                "OSRM distance vs polyline geodesic distance discrepancy exceeds 5%%: osrm=%.1fm, geo=%.1fm",
                total_distance_m, geo_len
            )

        explain_started = time.perf_counter()

        critical_count = sum(1 for s in segments if s.risk_level == RiskLevel.CRITICAL)
        moderate_count = sum(1 for s in segments if s.risk_level == RiskLevel.MODERATE)
        unknown_count = sum(1 for s in segments if s.risk_level in (RiskLevel.UNKNOWN, RiskLevel.INSUFFICIENT_EVIDENCE))

        journey_text = f"Dự kiến {estimated_time_mins} phút, quãng đường {total_distance_km} km."
        delay_text = (f" Thời gian này đã tính khoảng {round(total_traffic_delay / 60.0, 1)} phút chậm do xe đông."
                      if total_traffic_delay > 0 else "")

        if critical_count > 0:
            overall_risk = RiskLevel.CRITICAL
            route_status = "ROUTE_CRITICAL_HAZARDS_DETECTED"
            explanation = (
                f"{journey_text} Có {critical_count} đoạn có cảnh báo nguy hiểm hoặc đường bị chặn. "
                "Bạn nên chọn tuyến khác nếu có thể."
            )
        elif moderate_count > 0:
            overall_risk = RiskLevel.MODERATE
            route_status = "ROUTE_MODERATE_RISK_DETECTED"
            explanation = (
                f"{journey_text}{delay_text} Có {moderate_count} đoạn cần lưu ý. "
                "Hãy đi chậm và chú ý quan sát khi đi qua."
            )
        elif congested_count > 0:
            overall_risk = RiskLevel.MODERATE
            route_status = "ROUTE_CONGESTION_DETECTED"
            flood_note = (" Chưa rõ tình trạng ngập trên một số đoạn, bạn nên chú ý khi đi qua."
                          if unknown_count > 0 else " Hãy tiếp tục chú ý tình trạng đường khi di chuyển.")
            explanation = f"{journey_text}{delay_text} Có {congested_count} đoạn xe đông.{flood_note}"
        elif unknown_count > 0 or not segments:
            overall_risk = RiskLevel.UNKNOWN
            route_status = "ROUTE_FOUND_RISK_UNKNOWN"
            explanation = (
                f"{journey_text}{delay_text} Chưa có đủ thông tin để biết toàn tuyến có ngập hay không. "
                "Hãy chú ý tình trạng đường và các biển báo khi di chuyển."
            )
        else:
            overall_risk = RiskLevel.SAFE
            route_status = "ROUTE_FOUND_OPTIMAL"
            explanation = (
                f"{journey_text}{delay_text} Chưa ghi nhận cảnh báo đáng chú ý trên tuyến này. "
                "Tình trạng đường có thể thay đổi, bạn vẫn nên chú ý khi đi."
            )

        explanation_elapsed += time.perf_counter() - explain_started
        coverage = "CORRIDOR_DATA_UNAVAILABLE" if camera_count is None else "SPATIALLY_NEAR_UNVERIFIED_VIEW" if camera_count else "NO_VERIFIED_CAMERA_GPS"

        # Multi-criteria ranking cost:
        # Base: estimated_duration_seconds + realistic traffic delay penalty (x0.5 extra) + 7200s per closed road + 3600s per critical hazard + 180s per moderate risk
        ranking_cost = round(
            estimated_duration_seconds
            + (total_traffic_delay * 0.5)
            + (closed_count * 7200.0)
            + (critical_count * 3600.0)
            + (moderate_count * 180.0),
            2,
        )

        responses.append(SafeRouteResponse(
            route_id=route_id,
            total_distance_km=total_distance_km,
            estimated_time_mins=estimated_time_mins,
            osrm_duration_seconds=osrm_duration_seconds,
            duration_seconds=osrm_duration_seconds,
            baseline_duration_seconds=baseline_duration_seconds,
            duration_in_traffic_seconds=duration_in_traffic_seconds,
            estimated_duration_seconds=estimated_duration_seconds,
            traffic_adjusted_eta_seconds=traffic_adjusted_eta_seconds,
            transport_mode=mode_enum,
            eta_source=eta_calc["eta_source"],
            is_live_traffic=eta_calc["is_live_traffic"],
            traffic_status=eta_calc["traffic_status"],
            data_freshness=eta_calc["data_freshness"],
            eta_breakdown=eta_calc["eta_breakdown"],
            traffic_eta_status=traffic_eta_status,
            traffic_eta_source=traffic_eta_source,
            traffic_delay_seconds=round(total_traffic_delay, 1),
            traffic_coverage_ratio=traffic_coverage_ratio,
            ranking_cost=ranking_cost,
            overall_risk=overall_risk,
            route_status=route_status,
            evidence_coverage=coverage,
            route_ai_status=("EVIDENCE_AVAILABLE" if any(c.evidence_eligibility == EvidenceEligibility.ROUTING_ELIGIBLE for segment in segments for c in segment.evidence_cameras) else "BLOCKED_BY_EVIDENCE"),
            critical_segments_count=critical_count,
            moderate_segments_count=moderate_count,
            unknown_segments_count=unknown_count,
            geojson_path=route["geometry"],
            segments=segments,
            ai_explanation=explanation,
        ))

    if not responses:
        raise RoutingError("ROUTING_PROVIDER_UNAVAILABLE", 503, "OSRM returned no usable step geometry.")

    # Safe routes outrank hazardous routes
    responses.sort(key=lambda r: (
        bool(r.critical_segments_count or any(s.is_closed or s.traffic_status == TrafficStatus.CLOSED for s in r.segments)),
        r.ranking_cost if r.ranking_cost is not None else float("inf"),
        r.estimated_time_mins, json.dumps(r.geojson_path, sort_keys=True)))

    # B07: If ALL candidate routes traverse CRITICAL flood hazards or CLOSED roads, mark NO_SAFE_ROUTE explicitly
    all_routes_hazardous = all(
        r.overall_risk == RiskLevel.CRITICAL
        or r.critical_segments_count > 0
        or any(s.traffic_status == TrafficStatus.CLOSED or s.is_closed for s in r.segments)
        for r in responses
    )
    if all_routes_hazardous:
        for r in responses:
            r.route_status = "NO_SAFE_ROUTE"
            if not r.ai_explanation.startswith("Chưa tìm được tuyến tránh nguy hiểm."):
                r.ai_explanation = (
                    "Chưa tìm được tuyến tránh nguy hiểm. Các lựa chọn đều có cảnh báo hoặc đoạn bị chặn; bạn nên cân nhắc đổi đường hoặc đi vào lúc khác. "
                    + r.ai_explanation
                )

    # Authoritative assignment: lowest ranking_cost is recommended by safety engine
    responses[0].is_recommended = not all_routes_hazardous

    # Identify fastest route by travel time
    fastest_idx = min(
        range(len(responses)),
        key=lambda i: (responses[i].estimated_time_mins, responses[i].osrm_duration_seconds or 0)
    )
    responses[fastest_idx].is_fastest = True

    for idx, r in enumerate(responses):
        if r.is_recommended and r.is_fastest:
            r.route_type = "RECOMMENDED_AND_FASTEST"
        elif r.is_recommended:
            r.route_type = "RECOMMENDED_SAFE"
        elif r.is_fastest:
            r.route_type = "FASTEST_ALTERNATIVE"
        else:
            r.route_type = f"ALTERNATIVE_{idx}"
    completed_at = time.perf_counter()
    logger.info(
        "route_timing request_id=%s osrm_ms=%.1f db_ms=%.1f risk_ms=%.1f explanation_ms=%.1f osrm_cache_hit=%s",
        request_id or "none", (osrm_done_at - started_at) * 1000,
        (db_done_at - osrm_done_at) * 1000,
        max(0.0, completed_at - db_done_at - explanation_elapsed) * 1000,
        explanation_elapsed * 1000, cache_hit,
    )
    return responses
