"""
TomTom Traffic Flow Provider Adapter for SafePathAI.
Queries TomTom FlowSegmentData API along the route corridor with Redis caching, shape & bearing matching,
real timestamps, bounded concurrency, and strict zero-mock.
"""

import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from backend.app.core.external_http import get_json_response
import httpx

from backend.app.core.config import settings
from backend.app.schemas.contracts import TrafficStatus
from backend.app.services.traffic_providers.base import BaseTrafficProvider, SegmentTrafficFlow
from backend.app.services.traffic_providers.coverage import cached_record, observed_fraction, valid_confidence

logger = logging.getLogger(__name__)


def _midpoint(coords: List[List[float]]) -> Optional[Tuple[float, float]]:
    """Return (lat, lng) midpoint from a list of [lng, lat] coordinates."""
    if not coords or len(coords) < 2:
        if coords and len(coords) == 1 and len(coords[0]) >= 2:
            return float(coords[0][1]), float(coords[0][0])
        return None
    mid_idx = len(coords) // 2
    pt = coords[mid_idx]
    return float(pt[1]), float(pt[0])



class TomTomTrafficProvider(BaseTrafficProvider):
    name = "tomtom"
    # Zoom level 14 resolves detailed urban road classes (FRC0 through FRC6) in HCMC
    BASE_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/14/json"
    _circuit_open_until = 0.0

    def is_configured(self) -> bool:
        return bool(settings.TOMTOM_API_KEY and settings.TOMTOM_API_KEY.strip())

    async def get_corridor_traffic(
        self,
        route_coordinates: List[List[float]],
        segments: List[Dict[str, Any]],
        redis_client: Optional[Any] = None,
    ) -> Dict[int, SegmentTrafficFlow]:
        results: Dict[int, SegmentTrafficFlow] = {}
        now = datetime.now(timezone.utc)

        if not self.is_configured():
            logger.info("TrafficProvider[tomtom]: Not configured (no TOMTOM_API_KEY provided); fail-closed to UNKNOWN.")
            return results

        now_ts = now.timestamp()
        if now_ts < self._circuit_open_until:
            logger.warning("TrafficProvider[tomtom]: Circuit breaker open until %s; skipping queries.", self._circuit_open_until)
            return results

        api_key = settings.TOMTOM_API_KEY.strip()
        timeout = getattr(settings, "TRAFFIC_REQUEST_TIMEOUT_SECONDS", 3.0)
        cache_ttl = getattr(settings, "TRAFFIC_CACHE_TTL_SECONDS", 180)

        # Deduplicate midpoints along corridor
        query_tasks: Dict[str, Tuple[float, float]] = {}
        segment_keys: Dict[int, str] = {}

        for idx, seg in enumerate(segments):
            length = float(seg.get("length_meters") or 0.0)
            geo = seg.get("geojson_path")
            coords = geo.get("coordinates") if isinstance(geo, dict) else None
            if not coords or length < 40.0:
                continue

            mid = _midpoint(coords)
            if not mid:
                continue
            lat, lng = mid
            cell_key = f"{lat:.4f}:{lng:.4f}"
            segment_keys[idx] = cell_key
            if cell_key not in query_tasks:
                query_tasks[cell_key] = (lat, lng)

        if not query_tasks:
            return results

        requests_total = 0
        requests_success = 0
        requests_failure = 0
        cell_data_map: Dict[str, Tuple[Optional[Dict[str, Any]], Optional[datetime]]] = {}

        # 1. Check Redis Cache
        if redis_client is not None:
            for cell_key in list(query_tasks.keys()):
                cache_key = f"traffic:tomtom:{cell_key}"
                try:
                    cached_raw = await redis_client.get(cache_key)
                    if cached_raw:
                        cached = cached_record(json.loads(cached_raw), now, cache_ttl)
                        if cached is not None:
                            cell_data_map[cell_key] = cached
                except Exception as cache_err:
                    logger.debug("Redis read error for %s: %s", cache_key, cache_err)

        # 2. Fetch missing cells with bounded concurrency (max 5) and max 25 cells per route (C06)
        needed_items = [(k, v) for k, v in query_tasks.items() if k not in cell_data_map]
        if len(needed_items) > 25:
            step_stride = max(1, len(needed_items) // 25)
            needed_items = needed_items[::step_stride][:25]
        needed_cells = dict(needed_items)
        sem = asyncio.Semaphore(5)

        async with httpx.AsyncClient(timeout=timeout) as client:
            async def fetch_cell(cell_k: str, lat_val: float, lng_val: float):
                nonlocal requests_total, requests_success, requests_failure
                async with sem:
                    requests_total += 1
                    url = f"{self.BASE_URL}?point={lat_val:.5f},{lng_val:.5f}&unit=KMPH&key={api_key}"
                    try:
                        resp = await get_json_response(client, url, operation="traffic", budget_seconds=3)
                        if resp.status_code == 200:
                            data = resp.json().get("flowSegmentData")
                            if data and isinstance(data, dict):
                                requests_success += 1
                                cached_at_now = datetime.now(timezone.utc)
                                cell_data_map[cell_k] = (data, cached_at_now)
                                if redis_client is not None:
                                    try:
                                        cache_record = {
                                            "payload": data,
                                            "cached_at": cached_at_now.isoformat(),
                                        }
                                        await redis_client.set(
                                            f"traffic:tomtom:{cell_k}",
                                            json.dumps(cache_record),
                                            ex=cache_ttl,
                                        )
                                    except Exception:
                                        pass
                        elif resp.status_code in (401, 403, 429):
                            requests_failure += 1
                            logger.warning(
                                "TrafficProvider[tomtom]: HTTP %s (Auth/Quota/RateLimit). Opening circuit breaker for 60s.",
                                resp.status_code
                            )
                            self._circuit_open_until = datetime.now(timezone.utc).timestamp() + 60.0
                        else:
                            requests_failure += 1
                            logger.debug("TrafficProvider[tomtom]: Non-200 (%s) for cell %s", resp.status_code, cell_k)
                    except (httpx.TimeoutException, httpx.RequestError) as net_err:
                        requests_failure += 1
                        logger.debug("TrafficProvider[tomtom]: Request error for %s: %s", cell_k, net_err)

            tasks = [fetch_cell(k, v[0], v[1]) for k, v in needed_cells.items()]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        # 3. Match each segment with retrieved candidate flow
        matched_count = 0
        for idx, seg in enumerate(segments):
            cell_k = segment_keys.get(idx)
            if not cell_k or cell_k not in cell_data_map:
                continue

            flow_data, observed_at = cell_data_map[cell_k]
            if not flow_data or not isinstance(flow_data, dict):
                continue

            length = float(seg.get("length_meters") or 0.0)
            geo = seg.get("geojson_path", {})
            coords = geo.get("coordinates") if isinstance(geo, dict) else None
            if not coords or len(coords) < 2:
                continue

            # Only the directed portion actually covered by provider geometry is observed.
            try:
                shape = flow_data.get("coordinates")
                points = shape.get("coordinate", []) if isinstance(shape, dict) else []
                source_line = [[point["longitude"], point["latitude"]] for point in points]
                coverage = observed_fraction(coords, [source_line])
            except (KeyError, TypeError):
                continue
            if coverage <= 0:
                continue
            observed_length = length * coverage

            curr_speed = flow_data.get("currentSpeed")
            ff_speed = flow_data.get("freeFlowSpeed")
            confidence_raw = flow_data.get("confidence")
            confidence = valid_confidence(confidence_raw)
            if confidence is None:
                continue
            is_closed = bool(flow_data.get("roadClosure", False))

            if not is_closed and (curr_speed is None or ff_speed is None):
                continue

            try:
                curr_speed = 0.0 if is_closed else float(curr_speed)
                ff_speed = float(ff_speed) if ff_speed is not None else None
            except (TypeError, ValueError):
                continue

            # C05: Reject non-finite or physically implausible speeds
            if (
                not math.isfinite(curr_speed)
                or curr_speed < 0.0
                or curr_speed > 160.0
                or (ff_speed is not None and (not math.isfinite(ff_speed) or not 0 < ff_speed <= 160))
                or (not is_closed and ff_speed is None)
            ):
                logger.debug("TomTom flow rejected for seg %d: out-of-bounds speed curr=%s ff=%s", idx, curr_speed, ff_speed)
                continue

            # Low confidence check (< 0.30)
            if confidence is not None and confidence < 0.30:
                logger.debug("TomTom flow rejected for seg %d: low confidence %.2f", idx, confidence)
                continue

            # Classify status using standard speed ratio thresholds & B06 roadClosure
            speed_ratio = curr_speed / max(ff_speed or 1.0, 1.0)
            if is_closed:
                status = TrafficStatus.CLOSED
            elif curr_speed < 10.0 or speed_ratio < 0.35:
                status = TrafficStatus.CONGESTED
            elif speed_ratio < 0.75:
                status = TrafficStatus.SLOW
            else:
                status = TrafficStatus.FREE_FLOW

            # Delay calculation relative to free-flow baseline
            delay_s = (max(0.0, round(observed_length / (curr_speed / 3.6) - observed_length / (ff_speed / 3.6), 1))
                       if curr_speed > 0 and ff_speed is not None else 0.0)

            freshness_sec = (datetime.now(timezone.utc) - observed_at).total_seconds() if observed_at else None

            results[idx] = SegmentTrafficFlow(
                traffic_status=status,
                is_closed=is_closed,
                current_speed_kmh=round(curr_speed, 1),
                free_flow_speed_kmh=round(ff_speed, 1) if ff_speed is not None else None,
                traffic_delay_seconds=delay_s,
                observed_length_meters=observed_length,
                confidence=confidence,
                source="tomtom_traffic_flow",
                freshness_seconds=round(freshness_sec, 1) if freshness_sec is not None else None,
                observed_at=observed_at,
                match_status="CORRIDOR_MATCHED",
                raw_payload=flow_data,
            )
            matched_count += 1

        logger.info(
            "TrafficProvider[tomtom]: Configured=True, RequestsTotal=%d, Success=%d, Fail=%d, MatchedSegments=%d/%d",
            requests_total, requests_success, requests_failure, matched_count, len(segments)
        )
        return results
