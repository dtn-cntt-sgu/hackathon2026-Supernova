"""
HERE Traffic Flow Provider Adapter for SafePathAI.
Queries HERE Traffic Flow v7 along route corridor with Redis caching, true unit conversions (m/s -> km/h),
bearing verification, and strict zero-mock.
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



class HereTrafficProvider(BaseTrafficProvider):
    name = "here"
    BASE_URL = "https://data.traffic.hereapi.com/v7/flow"
    _circuit_open_until = 0.0

    def is_configured(self) -> bool:
        return bool(settings.HERE_API_KEY and settings.HERE_API_KEY.strip())

    async def get_corridor_traffic(
        self,
        route_coordinates: List[List[float]],
        segments: List[Dict[str, Any]],
        redis_client: Optional[Any] = None,
    ) -> Dict[int, SegmentTrafficFlow]:
        results: Dict[int, SegmentTrafficFlow] = {}
        now = datetime.now(timezone.utc)

        if not self.is_configured():
            logger.info("TrafficProvider[here]: Not configured (no HERE_API_KEY provided); fail-closed to UNKNOWN.")
            return results

        now_ts = now.timestamp()
        if now_ts < self._circuit_open_until:
            logger.warning("TrafficProvider[here]: Circuit breaker open until %s; skipping queries.", self._circuit_open_until)
            return results

        api_key = settings.HERE_API_KEY.strip()
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

        # Diagnostic counters
        requests_total = 0
        requests_success = 0
        requests_failure = 0
        cell_data_map: Dict[str, Tuple[Optional[Dict[str, Any]], Optional[datetime]]] = {}

        # 1. Check Redis Cache
        if redis_client is not None:
            for cell_key in list(query_tasks.keys()):
                cache_key = f"traffic:here:{cell_key}"
                try:
                    cached_raw = await redis_client.get(cache_key)
                    if cached_raw:
                        cached = cached_record(json.loads(cached_raw), now, cache_ttl)
                        if cached is not None:
                            cell_data_map[cell_key] = cached
                except Exception as cache_err:
                    logger.debug("Redis read error for %s: %s", cache_key, cache_err)

        # 2. Fetch missing cells with bounded concurrency (max 5)
        needed_cells = {k: v for k, v in query_tasks.items() if k not in cell_data_map}
        sem = asyncio.Semaphore(5)

        async with httpx.AsyncClient(timeout=timeout) as client:
            async def fetch_cell(cell_k: str, lat_val: float, lng_val: float):
                nonlocal requests_total, requests_success, requests_failure
                async with sem:
                    requests_total += 1
                    url = f"{self.BASE_URL}?in=circle:{lat_val:.5f},{lng_val:.5f};r=80&locationReferencing=shape&apiKey={api_key}"
                    try:
                        resp = await get_json_response(client, url, operation="traffic", budget_seconds=3)
                        if resp.status_code == 200:
                            payload = resp.json()
                            requests_success += 1
                            cached_at_now = datetime.now(timezone.utc)
                            cell_data_map[cell_k] = (payload, cached_at_now)
                            if redis_client is not None:
                                try:
                                    cache_record = {
                                        "payload": payload,
                                        "cached_at": cached_at_now.isoformat(),
                                    }
                                    await redis_client.set(
                                        f"traffic:here:{cell_k}",
                                        json.dumps(cache_record),
                                        ex=cache_ttl,
                                    )
                                except Exception:
                                    pass
                        elif resp.status_code in (401, 403, 429):
                            requests_failure += 1
                            logger.warning(
                                "TrafficProvider[here]: HTTP %s (Auth/Quota/RateLimit). Opening circuit breaker for 60s.",
                                resp.status_code
                            )
                            self._circuit_open_until = datetime.now(timezone.utc).timestamp() + 60.0
                        else:
                            requests_failure += 1
                            logger.debug("TrafficProvider[here]: Non-200 (%s) for cell %s", resp.status_code, cell_k)
                    except (httpx.TimeoutException, httpx.RequestError) as net_err:
                        requests_failure += 1
                        logger.debug("TrafficProvider[here]: Request error for %s: %s", cell_k, net_err)

            tasks = [fetch_cell(k, v[0], v[1]) for k, v in needed_cells.items()]
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        # 3. Match each segment with retrieved candidate flow
        matched_count = 0
        for idx, seg in enumerate(segments):
            cell_k = segment_keys.get(idx)
            if not cell_k or cell_k not in cell_data_map:
                continue

            payload, observed_at = cell_data_map[cell_k]
            if not payload or not isinstance(payload, dict):
                continue

            results_list = payload.get("results", [])
            if not results_list:
                continue

            length = float(seg.get("length_meters") or 0.0)
            geo = seg.get("geojson_path", {})
            coords = geo.get("coordinates") if isinstance(geo, dict) else None
            if not coords or len(coords) < 2:
                continue

            best_candidate = None
            best_coverage = 0.0
            best_record = None
            ambiguous = False
            for candidate in results_list:
                if not isinstance(candidate, dict):
                    continue
                flow = candidate.get("currentFlow", {})
                if not isinstance(flow, dict) or valid_confidence(flow.get("confidence")) is None:
                    continue
                location = candidate.get("location", {})
                links = location.get("shape", {}).get("links", []) if isinstance(location, dict) and isinstance(location.get("shape"), dict) else []
                try:
                    # Do not bridge disconnected HERE links or accept a street-name-only match.
                    source_lines = [[[point["lng"], point["lat"]] for point in link["points"]] for link in links]
                    coverage = observed_fraction(coords, source_lines)
                except (KeyError, TypeError):
                    continue
                if coverage > best_coverage:
                    best_candidate, best_coverage, best_record = flow, coverage, candidate
                    ambiguous = False
                elif coverage > 0 and abs(coverage - best_coverage) < 1e-6 and candidate != best_record:
                    ambiguous = True
            if best_candidate is None or best_coverage <= 0 or ambiguous:
                continue
            observed_length = length * best_coverage
            traversability = str(best_candidate.get("traversability") or "open").lower()
            try:
                curr_speed_mps = 0.0 if traversability == "closed" else float(best_candidate.get("speed"))
                ff_speed_mps = float(best_candidate["freeFlow"]) if best_candidate.get("freeFlow") is not None else None
                jam_factor = float(best_candidate.get("jamFactor") or 0.0)
            except (TypeError, ValueError):
                continue
            traversability = str(best_candidate.get("traversability") or "open").lower()
            confidence = valid_confidence(best_candidate.get("confidence"))

            # CRITICAL UNIT CONVERSION: HERE speeds are in m/s. Convert to km/h!
            is_closed = traversability == "closed"
            curr_speed_kmh = 0.0 if is_closed else round(curr_speed_mps * 3.6, 1)
            ff_speed_kmh = round(ff_speed_mps * 3.6, 1) if ff_speed_mps is not None else None

            if (
                not math.isfinite(curr_speed_kmh)
                or curr_speed_kmh < 0.0
                or curr_speed_kmh > 160.0
                or (ff_speed_kmh is not None and (not math.isfinite(ff_speed_kmh) or not 0 < ff_speed_kmh <= 160))
                or (not is_closed and ff_speed_kmh is None)
            ):
                continue

            # Classify status based on speed km/h, jam factor, and B06 road closure
            if is_closed:
                status = TrafficStatus.CLOSED
            elif jam_factor >= 8.0 or curr_speed_kmh < 12.0:
                status = TrafficStatus.CONGESTED
            elif jam_factor >= 4.0 or curr_speed_kmh < (0.65 * ff_speed_kmh):
                status = TrafficStatus.SLOW
            else:
                status = TrafficStatus.FREE_FLOW

            # Delay calculation using exact m/s travel time difference
            delay_s = (max(0.0, round(observed_length / curr_speed_mps - observed_length / ff_speed_mps, 1))
                       if curr_speed_mps > 0 and ff_speed_mps is not None else 0.0)

            freshness_sec = (datetime.now(timezone.utc) - observed_at).total_seconds() if observed_at else None

            results[idx] = SegmentTrafficFlow(
                traffic_status=status,
                is_closed=is_closed,
                current_speed_kmh=curr_speed_kmh,
                free_flow_speed_kmh=ff_speed_kmh,
                traffic_delay_seconds=delay_s,
                observed_length_meters=observed_length,
                confidence=confidence,
                source="here_traffic_flow",
                freshness_seconds=round(freshness_sec, 1) if freshness_sec is not None else None,
                observed_at=observed_at,
                match_status="CORRIDOR_MATCHED",
                raw_payload=best_candidate,
            )
            matched_count += 1

        logger.info(
            "TrafficProvider[here]: Configured=True, RequestsTotal=%d, Success=%d, Fail=%d, MatchedSegments=%d/%d",
            requests_total, requests_success, requests_failure, matched_count, len(segments)
        )
        return results
