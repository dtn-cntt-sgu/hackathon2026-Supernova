"""
Risk Engine for OpenStreetMap Road Segments (Zero-Mock Runtime).
Calculates deterministic multi-criteria risk scores based strictly on:
1. Verified, fresh camera observations showing the exact road segment.
2. Official historical flood points combined with real-time precipitation and tidal alerts.
3. Strict Zero-Mock: Without verified evidence, roads are marked UNKNOWN, never defaulted to SAFE.
"""

from datetime import datetime, timezone
import json
import logging
import math
import re
from typing import Any, Dict, List, Optional, Tuple, Union
from redis.asyncio import Redis

from backend.app.db.models import RoadEdge, RoadSegment
from backend.app.db.session import get_redis_client
from backend.app.schemas.contracts import (
    CameraEvidence,
    DataSourceStatus,
    EvidenceEligibility,
    RiskLevel,
    RouteSegmentRisk,
    TrafficStatus,
    WeatherTideSignal,
)

logger = logging.getLogger(__name__)

# Redis key prefix for segment risk caching
REDIS_SEGMENT_RISK_PREFIX = "road:risk:"

# Risk Level Score Boundaries
CRITICAL_RISK_THRESHOLD = 65.0
MODERATE_RISK_THRESHOLD = 30.0

# Critical Camera Flood Threshold (>= 35% road water segmentation triggers automatic CRITICAL)
AUTO_CRITICAL_FLOOD_RATIO = 0.35

# Rain Intensity Thresholds (mm/h)
HEAVY_RAIN_THRESHOLD_MM_H = 30.0
MODERATE_RAIN_THRESHOLD_MM_H = 10.0

# Maximum spatial distance (meters) between a geocoded news hazard and a segment with geometry (C01)
MAX_NEWS_SEGMENT_DISTANCE_METERS = 1500.0


def _haversine_meters_point(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _extract_segment_spatial_context(
    segment: Union[RoadEdge, RoadSegment, Dict[str, Any]]
) -> Tuple[List[Tuple[float, float]], Optional[str]]:
    """Extracts (lat, lng) coordinate points and optional district from a segment if available (C01)."""
    points: List[Tuple[float, float]] = []
    district: Optional[str] = None

    if isinstance(segment, dict):
        district = segment.get("district")
        lat = segment.get("lat")
        lng = segment.get("lng")
        if lat is not None and lng is not None:
            try:
                points.append((float(lat), float(lng)))
            except (TypeError, ValueError):
                pass
        geojson = segment.get("geojson_path")
        if isinstance(geojson, dict):
            coords = geojson.get("coordinates") or []
            for pt in coords:
                if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                    try:
                        points.append((float(pt[1]), float(pt[0])))
                    except (TypeError, ValueError):
                        pass
    else:
        district = getattr(segment, "district", None)
        lat = getattr(segment, "lat", None)
        lng = getattr(segment, "lng", None)
        if lat is not None and lng is not None:
            try:
                points.append((float(lat), float(lng)))
            except (TypeError, ValueError):
                pass
    return points, district


def _news_article_matches_segment(
    art: Any,
    street_name: Optional[str],
    seg_points: List[Tuple[float, float]],
    seg_district: Optional[str],
) -> bool:
    """
    Verifies whether an eligible traffic news hazard applies to this specific segment (C01):
    1. Whole-phrase street name match in title/summary.
    2. If segment district is known and article explicitly names a different district, reject.
    3. If both segment coordinates and article coordinates exist, require proximity <= 1500m.
    """
    norm_street = (street_name or "").strip().lower()
    if len(norm_street) < 3:
        return False

    art_title = (getattr(art, "title", "") or "").lower()
    art_summary = (getattr(art, "summary", "") or "").lower()
    combined_text = f"{art_title} {art_summary}"

    pattern = r"(?<!\w)" + re.escape(norm_street) + r"(?!\w)"
    if not re.search(pattern, combined_text):
        return False

    if seg_district:
        norm_seg_dist = seg_district.strip().lower()
        mentioned_districts = re.findall(
            r"quận\s+(?:10|11|12|[1-9]|bình\s+thạnh|tân\s+bình|tân\s+phú|phú\s+nhuận|gò\s+vấp|bình\s+tân|thủ\s+đức)",
            combined_text,
        )
        if mentioned_districts and not any(d in norm_seg_dist or norm_seg_dist in d for d in mentioned_districts):
            return False

    if seg_points:
        art_lat = getattr(art, "lat", None) if getattr(art, "lat", None) is not None else getattr(art, "latitude", None)
        art_lng = getattr(art, "lng", None) if getattr(art, "lng", None) is not None else getattr(art, "longitude", None)
        if art_lat is not None and art_lng is not None:
            try:
                alat, alng = float(art_lat), float(art_lng)
                min_dist = min(_haversine_meters_point(alat, alng, plat, plng) for plat, plng in seg_points)
                if min_dist > MAX_NEWS_SEGMENT_DISTANCE_METERS:
                    return False
            except (TypeError, ValueError):
                pass

    return True


def calculate_segment_risk(
    segment: Union[RoadEdge, RoadSegment, Dict[str, Any]],
    camera_evidences: List[CameraEvidence],
    weather_tide: Optional[WeatherTideSignal] = None,
    traffic_news: Optional[List[Any]] = None,
    community_incidents: Optional[List[dict]] = None,
) -> RouteSegmentRisk:
    """
    Calculates the multi-criteria risk assessment for a specific OSM road segment or edge.
    
    Zero-Mock Principles:
    - Only cameras with OBSERVED_SEGMENT_VERIFIED and fresh LIVE status can provide camera scoring.
      Spatially near cameras without verified view orientation cannot score the road.
    - Historical flood points and regional weather are context, not a current
      measurement of water on this exact road segment.
    - Traffic news: Only fresh (< 3h), geocoded, verified ACTIVE_HAZARD articles can influence risk.
      Historical, forecast, recovered, or unlocated articles are strictly filtered out (Rule 6).
    - If a segment has no verified camera observations and is not flood-prone:
        - Returns RiskLevel.UNKNOWN with risk_score = None.
    """
    # Extract segment properties
    if isinstance(segment, RoadEdge):
        osm_way_id = segment.osm_way_id
        edge_index = segment.edge_index
        street_name = segment.way.street_name if segment.way else None
        length_meters = segment.length_meters
        source_url = segment.way.source_url if segment.way else None
        is_flood_prone_history = getattr(segment.way, "is_flood_prone_history", None) if segment.way else None
    elif isinstance(segment, RoadSegment):
        osm_way_id = segment.osm_way_id
        edge_index = None
        street_name = segment.street_name
        length_meters = segment.length_meters
        source_url = segment.source_url
        is_flood_prone_history = segment.is_flood_prone_history
    elif isinstance(segment, dict):
        osm_way_id = segment.get("osm_way_id")
        edge_index = segment.get("edge_index", segment.get("osm_edge_index"))
        street_name = segment.get("street_name")
        length_meters = segment.get("length_meters")
        source_url = segment.get("source_url")
        is_flood_prone_history = segment.get("is_flood_prone_history", segment.get("historical_flood_prone"))
    else:
        osm_way_id = getattr(segment, "osm_way_id", None)
        edge_index = getattr(segment, "edge_index", getattr(segment, "osm_edge_index", None))
        street_name = getattr(segment, "street_name", None)
        length_meters = getattr(segment, "length_meters", None)
        source_url = getattr(segment, "source_url", None)
        is_flood_prone_history = getattr(segment, "is_flood_prone_history", getattr(segment, "historical_flood_prone", None))

    try:
        measured_length = float(length_meters)
    except (TypeError, ValueError):
        measured_length = 0.0

    if (not osm_way_id or not math.isfinite(measured_length) or measured_length <= 0):
        raise ValueError("Risk scoring requires a valid OSM way and positive measured length")

    now = datetime.now(timezone.utc)

    # 1. Filter strictly verified camera observations
    verified_cams = [
        cam for cam in camera_evidences
        if cam.spatial_match_status == "OBSERVED_SEGMENT_VERIFIED"
        and cam.observed_osm_way_id == osm_way_id
        and (edge_index is None or cam.observed_edge_index == edge_index)
        and cam.coordinate_source_url
        and cam.view_verification_source_url
        and cam.line_of_sight_verified
        and cam.evidence_eligibility == EvidenceEligibility.ROUTING_ELIGIBLE
        and (cam.source_status == DataSourceStatus.LIVE or cam.source_status.value == "LIVE")
        and cam.updated_at.tzinfo is not None
        and 0 <= (now - cam.updated_at).total_seconds() <= 120
    ]

    camera_risk_score: Optional[float] = None
    severe_camera_flood = False
    freshness_seconds: Optional[float] = None

    # B03: Evaluate flood camera evidence independently from traffic_density_score so:
    # 1) A camera with valid flood_ratio and traffic_density_score=None is never dropped.
    # 2) High traffic_density_score on a dry road (flood_ratio < 0.12) never inflates flood risk_level.
    cams_with_flood = [
        c for c in verified_cams
        if c.flood_ratio is not None
        and math.isfinite(c.flood_ratio)
        and 0.0 <= c.flood_ratio <= 1.0
    ]
    if cams_with_flood:
        max_flood = max(cam.flood_ratio for cam in cams_with_flood)
        severe_camera_flood = max_flood >= AUTO_CRITICAL_FLOOD_RATIO
        if max_flood >= 0.12:
            flood_scores: List[float] = []
            for cam in cams_with_flood:
                if cam.flood_ratio < 0.12:
                    continue
                if (
                    cam.traffic_density_score is not None
                    and math.isfinite(cam.traffic_density_score)
                    and 0.0 <= cam.traffic_density_score <= 1.0
                ):
                    flood_scores.append(min(100.0, cam.flood_ratio * 150.0 + cam.traffic_density_score * 15.0))
                else:
                    flood_scores.append(min(100.0, cam.flood_ratio * 200.0))
            if flood_scores:
                camera_risk_score = round(max(flood_scores), 2)
        else:
            camera_risk_score = round(max_flood * 100.0, 2)

    if verified_cams:
        freshness_seconds = min((now - cam.updated_at).total_seconds() for cam in verified_cams)

    # 2. Evaluate Weather & Tide inputs
    weather_risk: Optional[str] = None
    rain_mm: Optional[float] = None
    tide_alert: Optional[bool] = None

    if weather_tide is not None:
        rain_observed = weather_tide.rain_observed_at
        rain_fresh = (
            weather_tide.rain_status == "LIVE" and weather_tide.source_url
            and rain_observed is not None and rain_observed.tzinfo is not None
            and 0 <= (now - rain_observed).total_seconds() <= 900
        )
        rain_mm = weather_tide.rain_mm_per_hour if rain_fresh else None
        tide_observed = weather_tide.timestamp
        tide_fresh = (
            weather_tide.tide_status == "LIVE" and weather_tide.source_url
            and tide_observed is not None and tide_observed.tzinfo is not None
            and 0 <= (now - tide_observed).total_seconds() <= 10800
        )
        tide_alert = weather_tide.is_high_tide_alert if tide_fresh else None

        if rain_mm is not None:
            if rain_mm >= HEAVY_RAIN_THRESHOLD_MM_H:
                weather_risk = "HEAVY_RAIN"
            elif rain_mm >= MODERATE_RAIN_THRESHOLD_MM_H:
                weather_risk = "MODERATE_RAIN"
            elif rain_mm > 0.0:
                weather_risk = "LIGHT_RAIN"
            else:
                weather_risk = "CLEAR"
        else:
            weather_risk = "UNKNOWN"

        if freshness_seconds is None and rain_fresh:
            freshness_seconds = (now - rain_observed).total_seconds()

    # 2.5 Evaluate Traffic News Hazards (Rule 6: Zero-Mock & Strict Disqualification + C01 Spatial Verification)
    eligible_news_category: Optional[str] = None
    news_freshness_sec: Optional[float] = None
    seg_points, seg_district = _extract_segment_spatial_context(segment)
    if traffic_news:
        from backend.app.services.traffic_news import is_article_eligible_for_route_risk
        # A benign or duplicate article must never hide a stronger incident.
        priorities = {"ROAD_CLOSURE": 4, "CẤM ĐƯỜNG": 4, "FLOOD": 3, "NGẬP NƯỚC": 3,
                      "ACCIDENT": 2, "TAI NẠN": 2, "CONGESTION": 1, "ÙN TẮC": 1}
        seen = set()
        for art in traffic_news:
            if not is_article_eligible_for_route_risk(art, now=now):
                continue
            category = (getattr(art, "category", "") or "").upper()
            identity = (getattr(art, "source_url", None), getattr(art, "title", None), category)
            if identity in seen or not _news_article_matches_segment(art, street_name, seg_points, seg_district):
                continue
            seen.add(identity)
            if priorities.get(category, 0) > priorities.get(eligible_news_category, 0):
                eligible_news_category = category
                art_pub = getattr(art, "published_at", None)
                if art_pub and getattr(art_pub, "tzinfo", None) is not None:
                    news_freshness_sec = max(0.0, (now - art_pub).total_seconds())

    # 3. Dedicated Traffic Intelligence Evaluation (Separated from Flood Risk)
    traffic_status = TrafficStatus.UNKNOWN
    is_closed = False
    traffic_density_val: Optional[float] = None
    traffic_source: Optional[str] = None
    traffic_confidence: Optional[float] = None
    traffic_freshness: Optional[float] = None
    traffic_estimation_method: Optional[str] = "UNREPRESENTED"
    traffic_segment_match_status: Optional[str] = "NO_OBSERVATION"
    traffic_delay_seconds: Optional[float] = None
    observed_speed_kmh: Optional[float] = None

    cams_with_density = [
        c for c in verified_cams
        if c.traffic_density_score is not None
        and math.isfinite(c.traffic_density_score)
        and 0.0 <= c.traffic_density_score <= 1.0
    ]
    if cams_with_density and eligible_news_category not in ("ROAD_CLOSURE", "CẤM ĐƯỜNG"):
        traffic_density_val = max(c.traffic_density_score for c in cams_with_density)
        traffic_freshness = min((now - c.updated_at).total_seconds() for c in cams_with_density)
        traffic_source = f"camera_vision:{cams_with_density[0].cam_id}"
        traffic_segment_match_status = "OBSERVED_SEGMENT_VERIFIED"
        traffic_confidence = 0.90
        traffic_estimation_method = "CAMERA_VIEW_OCCUPANCY"

        # Calibrated HCMC urban corridor thresholds
        # Baseline free flow speed in urban HCMC: 35.0 km/h (9.72 m/s)
        # Slowed speed: 20.0 km/h (5.56 m/s)
        # Congested crawl speed: 10.0 km/h (2.78 m/s)
        baseline_speed_mps = 35.0 / 3.6
        if traffic_density_val >= 0.70:
            traffic_status = TrafficStatus.CONGESTED
            crawl_speed_mps = 10.0 / 3.6
            traffic_delay_seconds = round(max(0.0, (measured_length / crawl_speed_mps) - (measured_length / baseline_speed_mps)), 1)
        elif traffic_density_val >= 0.40:
            traffic_status = TrafficStatus.SLOW
            slow_speed_mps = 20.0 / 3.6
            traffic_delay_seconds = round(max(0.0, (measured_length / slow_speed_mps) - (measured_length / baseline_speed_mps)), 1)
        else:
            traffic_status = TrafficStatus.FREE_FLOW
            traffic_delay_seconds = 0.0

    elif eligible_news_category in ("CONGESTION", "ÙN TẮC"):
        traffic_status = TrafficStatus.CONGESTED
        traffic_source = "traffic_news:verified"
        traffic_confidence = 0.85
        traffic_freshness = news_freshness_sec
        traffic_segment_match_status = "STREET_NAME_GEOCODED"
        traffic_estimation_method = "NLP_EVENT_GEOCODED"
        crawl_speed_mps = 8.0 / 3.6
        baseline_speed_mps = 35.0 / 3.6
        traffic_delay_seconds = round(max(0.0, (measured_length / crawl_speed_mps) - (measured_length / baseline_speed_mps)), 1)

    elif eligible_news_category in ("ROAD_CLOSURE", "CẤM ĐƯỜNG"):
        traffic_status = TrafficStatus.CLOSED
        is_closed = True
        observed_speed_kmh = 0.0
        traffic_source = "traffic_news:verified"
        traffic_confidence = 0.90
        traffic_freshness = news_freshness_sec
        traffic_segment_match_status = "STREET_NAME_GEOCODED"
        traffic_estimation_method = "NLP_EVENT_GEOCODED"
        blockage_speed_mps = 2.0 / 3.6
        baseline_speed_mps = 35.0 / 3.6
        traffic_delay_seconds = round(max(0.0, (measured_length / blockage_speed_mps) - (measured_length / baseline_speed_mps)), 1)

    elif eligible_news_category in ("ACCIDENT", "TAI NẠN"):
        traffic_status = TrafficStatus.CONGESTED
        traffic_source = "traffic_news:verified"
        traffic_confidence = 0.90
        traffic_freshness = news_freshness_sec
        traffic_segment_match_status = "STREET_NAME_GEOCODED"
        traffic_estimation_method = "NLP_EVENT_GEOCODED"
        blockage_speed_mps = 5.0 / 3.6
        baseline_speed_mps = 35.0 / 3.6
        traffic_delay_seconds = round(max(0.0, (measured_length / blockage_speed_mps) - (measured_length / baseline_speed_mps)), 1)

    # 4. Determine Flood & Physical Hazard Risk Level (B04: evaluate camera & news independently without masking)
    cam_hazard_level = RiskLevel.UNKNOWN
    cam_hazard_score: Optional[float] = None

    if severe_camera_flood:
        cam_hazard_level = RiskLevel.CRITICAL
        cam_hazard_score = max(camera_risk_score or 0.0, 75.0)
    elif camera_risk_score is not None:
        if camera_risk_score >= CRITICAL_RISK_THRESHOLD:
            cam_hazard_level = RiskLevel.CRITICAL
            cam_hazard_score = camera_risk_score
        elif camera_risk_score >= MODERATE_RISK_THRESHOLD:
            cam_hazard_level = RiskLevel.MODERATE
            cam_hazard_score = camera_risk_score

    news_hazard_level = RiskLevel.UNKNOWN
    news_hazard_score: Optional[float] = None
    if eligible_news_category in ("FLOOD", "NGẬP NƯỚC", "ROAD_CLOSURE", "CẤM ĐƯỜNG"):
        news_hazard_level = RiskLevel.CRITICAL
        news_hazard_score = 80.0
    elif eligible_news_category in ("ACCIDENT", "TAI NẠN"):
        news_hazard_level = RiskLevel.MODERATE
        news_hazard_score = 55.0

    severity_rank = {
        RiskLevel.UNKNOWN: 0,
        RiskLevel.INSUFFICIENT_EVIDENCE: 0,
        RiskLevel.SAFE: 1,
        RiskLevel.MODERATE: 2,
        RiskLevel.CRITICAL: 3,
    }
    if severity_rank[news_hazard_level] > severity_rank[cam_hazard_level]:
        risk_level = news_hazard_level
    else:
        risk_level = cam_hazard_level

    valid_scores = [s for s in (cam_hazard_score, news_hazard_score) if s is not None]
    final_score: Optional[float] = max(valid_scores) if valid_scores else None

    # Independently reviewed community observations apply only to their exact edge.
    seen_incidents = set()
    for incident in community_incidents or []:
        identity = incident.get("incident_id", incident.get("id"))
        observed, expiry = incident.get("observed_at"), incident.get("expires_at")
        if (identity is None or identity in seen_incidents or incident.get("status") != "VERIFIED"
                or incident.get("osm_way_id") != osm_way_id or incident.get("edge_index") != edge_index
                or edge_index is None or not incident.get("evidence_url")
                or not isinstance(observed, datetime) or observed.tzinfo is None
                or not isinstance(expiry, datetime) or expiry.tzinfo is None
                or not 0 <= (now - observed).total_seconds() <= 10800 or expiry <= now
                or not isinstance(incident.get("confidence"), (int, float))
                or not .7 <= incident["confidence"] <= 1):
            continue
        seen_incidents.add(identity)
        category = incident.get("category")
        if category not in ("BLOCKED", "FLOOD", "ACCIDENT", "OTHER"):
            continue
        community_level = RiskLevel.CRITICAL if category == "BLOCKED" else RiskLevel.MODERATE
        if severity_rank[community_level] > severity_rank[risk_level]:
            risk_level = community_level
        final_score = max(final_score or 0, 95.0 if category == "BLOCKED" else 55.0)
        if category == "BLOCKED":
            is_closed, traffic_status = True, TrafficStatus.CLOSED
            traffic_source = "community:independently_verified"
            traffic_estimation_method = "VERIFIED_INCIDENT"
            traffic_segment_match_status = "EXACT_OSM_EDGE"
            traffic_confidence = incident["confidence"]
            traffic_freshness = (now - observed).total_seconds()
            observed_speed_kmh = 0.0
            traffic_delay_seconds = max(traffic_delay_seconds or 0,
                round(measured_length / (2.0 / 3.6) - measured_length / (35.0 / 3.6), 1))

    # Determine evidence coverage description
    if verified_cams:
        evidence_coverage = "OBSERVED_SEGMENT_VERIFIED"
    elif camera_evidences:
        evidence_coverage = "SPATIALLY_NEAR_UNVERIFIED_VIEW"
    else:
        evidence_coverage = "NO_VERIFIED_OBSERVATIONS"

    return RouteSegmentRisk(
        osm_way_id=osm_way_id,
        osm_edge_index=edge_index,
        street_name=street_name,
        length_meters=measured_length,
        risk_score=final_score,
        risk_level=risk_level,
        historical_flood_prone=is_flood_prone_history,
        historical_flood_cause=(
            "TIDAL_AND_HEAVY_RAIN" if is_flood_prone_history and tide_alert and weather_risk == "HEAVY_RAIN"
            else "HIGH_TIDE" if is_flood_prone_history and tide_alert
            else "HEAVY_RAIN" if is_flood_prone_history and weather_risk == "HEAVY_RAIN"
            else None
        ),
        weather_risk=weather_risk,
        evidence_coverage=evidence_coverage,
        evidence_cameras=verified_cams,
        freshness_seconds=freshness_seconds,
        traffic_status=traffic_status,
        traffic_observed_length_meters=(measured_length if traffic_status in
            (TrafficStatus.FREE_FLOW,TrafficStatus.SLOW,TrafficStatus.CONGESTED) else 0.0),
        is_closed=is_closed,
        observed_speed_kmh=observed_speed_kmh,
        traffic_density_score=traffic_density_val,
        traffic_confidence=traffic_confidence,
        traffic_freshness_seconds=traffic_freshness,
        traffic_source=traffic_source,
        traffic_estimation_method=traffic_estimation_method,
        traffic_segment_match_status=traffic_segment_match_status,
        traffic_delay_seconds=traffic_delay_seconds,
    )


async def save_segment_risk_to_redis(
    segment_risk: RouteSegmentRisk,
    redis_client: Optional[Redis] = None,
    ttl_seconds: int = 600,
) -> None:
    """
    Caches verified segment risk under road:risk:{osm_way_id}:{edge_index or 'all'}.
    """
    close_redis = False
    if segment_risk.osm_way_id is None:
        return
    if redis_client is None:
        redis_client = get_redis_client()
        close_redis = True

    try:
        edge_sub = segment_risk.osm_edge_index if segment_risk.osm_edge_index is not None else "all"
        key = f"{REDIS_SEGMENT_RISK_PREFIX}{segment_risk.osm_way_id}:{edge_sub}"
        payload = segment_risk.model_dump_json()
        await redis_client.set(key, payload, ex=ttl_seconds)
    except Exception as exc:
        logger.warning("Failed to cache road segment risk for %s in Redis: %s", segment_risk.osm_way_id, exc)
    finally:
        if close_redis:
            await redis_client.aclose()


async def get_cached_segment_risk(
    osm_way_id: int,
    redis_client: Optional[Redis] = None,
    edge_index: Optional[int] = None,
) -> Optional[RouteSegmentRisk]:
    """
    Retrieves cached RouteSegmentRisk from Redis.
    """
    close_redis = False
    if redis_client is None:
        redis_client = get_redis_client()
        close_redis = True

    try:
        edge_sub = edge_index if edge_index is not None else "all"
        key = f"{REDIS_SEGMENT_RISK_PREFIX}{osm_way_id}:{edge_sub}"
        raw_val = await redis_client.get(key)
        if not raw_val:
            return None
        data = json.loads(raw_val)
        return RouteSegmentRisk.model_validate(data)
    except Exception as exc:
        logger.warning("Failed to get cached segment risk for %s: %s", osm_way_id, exc)
        return None
    finally:
        if close_redis:
            await redis_client.aclose()


def aggregate_edge_risks(risks: List[RouteSegmentRisk]) -> RouteSegmentRisk:
    """Preserve every edge hazard; add delays once per edge, never pick a camera's way."""
    if not risks:
        raise ValueError("Cannot aggregate no edges")
    severity = {RiskLevel.CRITICAL: 3, RiskLevel.MODERATE: 2, RiskLevel.SAFE: 1}
    traffic = {TrafficStatus.CLOSED: 4, TrafficStatus.CONGESTED: 3, TrafficStatus.SLOW: 2,
               TrafficStatus.FREE_FLOW: 1}
    worst = max(risks, key=lambda r: (severity.get(r.risk_level, 0), r.risk_score or 0))
    flow = max(risks, key=lambda r: traffic.get(r.traffic_status, 0))
    result = worst.model_copy(deep=True)
    result.length_meters = sum(r.length_meters for r in risks)
    if (result.risk_level not in (RiskLevel.CRITICAL, RiskLevel.MODERATE)
            and any(r.risk_level in (RiskLevel.UNKNOWN, RiskLevel.INSUFFICIENT_EVIDENCE) for r in risks)):
        result.risk_level = RiskLevel.UNKNOWN
        result.risk_score = None
    result.traffic_observed_length_meters = sum(
        min(r.length_meters, r.traffic_observed_length_meters if r.traffic_observed_length_meters is not None else r.length_meters)
        for r in risks if r.traffic_status in (TrafficStatus.FREE_FLOW, TrafficStatus.SLOW, TrafficStatus.CONGESTED))
    result.is_closed = any(r.is_closed for r in risks)
    result.traffic_delay_seconds = sum(r.traffic_delay_seconds or 0 for r in risks)
    for field in ("traffic_status", "traffic_source", "traffic_confidence", "traffic_freshness_seconds",
                  "traffic_estimation_method", "traffic_segment_match_status", "traffic_density_score", "observed_speed_kmh"):
        setattr(result, field, getattr(flow, field))
    result.evidence_cameras = list({c.cam_id: c for r in risks for c in r.evidence_cameras}.values())
    # Partial camera coverage cannot be presented as full-step observation.
    result.evidence_coverage = ("OBSERVED_SEGMENT_VERIFIED" if all(r.evidence_coverage == "OBSERVED_SEGMENT_VERIFIED" for r in risks)
                                else "PARTIAL_VERIFIED_EDGE_OBSERVATIONS" if result.evidence_cameras else worst.evidence_coverage)
    if len(risks) > 1:
        result.osm_way_id = None
        result.osm_edge_index = None
    return result
