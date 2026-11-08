"""
Geocoding and Place Search Adapter (Zero-Mock Runtime).
Provides address, street, and POI search for TP. Hồ Chí Minh using Photon (Komoot OSM)
with local PostGIS road_segments fallback, coordinate parsing, and Redis caching.
Complies strictly with OpenStreetMap and service provider usage policies.
"""

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.schemas.contracts import PlaceResult, PlaceSearchResponse

logger = logging.getLogger("safepath.geocoding")

# Bounding box for TP. Hồ Chí Minh and surrounding urban area (WGS84 minLng, minLat, maxLng, maxLat)
HCMC_BBOX = "106.3,10.3,107.1,11.2"
HCMC_CENTER_LAT = 10.7769
HCMC_CENTER_LNG = 106.7009

# Regex to detect coordinate input "lat, lng" or "lat,lng"
COORDINATE_REGEX = re.compile(
    r"^\s*(?P<lat>[+-]?[0-9]+(?:\.[0-9]+)?)\s*,\s*(?P<lng>[+-]?[0-9]+(?:\.[0-9]+)?)\s*$"
)

PHOTON_SEARCH_URL = "https://photon.komoot.io/api/"
PHOTON_REVERSE_URL = "https://photon.komoot.io/reverse"
DEFAULT_USER_AGENT = "SafePathAI/1.0 (https://github.com/giakhoi0123/SafePathAI)"
CACHE_TTL_SECONDS = 3600  # 1 hour cache for places


def _parse_coordinates(q: str) -> Optional[tuple[float, float]]:
    """Detects if query is a raw coordinate pair (lat, lng)."""
    match = COORDINATE_REGEX.match(q.strip())
    if not match:
        return None
    try:
        lat = float(match.group("lat"))
        lng = float(match.group("lng"))
        if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
            return (lat, lng)
    except ValueError:
        pass
    return None


def _format_photon_display_name(props: Dict[str, Any]) -> str:
    """Constructs a clean, human-readable address line from Photon properties."""
    parts = []
    name = props.get("name")
    housenumber = props.get("housenumber")
    street = props.get("street")
    locality = props.get("locality") or props.get("suburb")
    district = props.get("district")
    city = props.get("city") or props.get("state")

    if housenumber and street:
        parts.append(f"{housenumber} {street}")
    elif name:
        parts.append(name)
        if street and street != name:
            parts.append(street)
    elif street:
        parts.append(street)

    if locality and locality not in parts:
        parts.append(locality)
    if district and district not in parts:
        parts.append(district)
    if city and city not in parts:
        parts.append(city)

    if not parts:
        return name or "Địa điểm tại TP.HCM"
    return ", ".join(parts)


async def search_places(
    q: str,
    limit: int = 6,
    session: Optional[AsyncSession] = None,
    redis: Optional[Redis] = None,
) -> PlaceSearchResponse:
    """
    Searches for places, addresses, streets, and POIs in TP. Hồ Chí Minh.
    Supports:
    1. Direct coordinate parsing (e.g. "10.7725, 106.6980")
    2. Primary: Photon geocoder with HCMC bounding box and location bias
    3. Fallback: Local PostGIS road_segments street matching
    Zero-Mock: Returns empty list if no genuine matches found; never fabricates locations.
    """
    clean_q = q.strip()
    if not clean_q:
        return PlaceSearchResponse(query=q, results=[], provider="empty", count=0)

    # 1. Check for raw coordinates
    coords = _parse_coordinates(clean_q)
    if coords:
        lat, lng = coords
        coord_place = PlaceResult(
            id=f"coord_{lat:.5f}_{lng:.5f}",
            name=f"Tọa độ: {lat:.5f}, {lng:.5f}",
            display_name=f"Vị trí tọa độ [{lat:.5f}, {lng:.5f}]",
            lat=lat,
            lng=lng,
            type="coordinate",
            provenance="user_coordinates",
        )
        return PlaceSearchResponse(
            query=clean_q,
            results=[coord_place],
            provider="coordinates",
            count=1,
        )

    # Minimum 3 characters required for text search
    if len(clean_q) < 3:
        return PlaceSearchResponse(
            query=clean_q,
            results=[],
            provider="min_length_not_met",
            count=0,
        )

    # 2. Check Redis cache
    cache_key = f"places:search:{hashlib.sha256(clean_q.lower().encode()).hexdigest()[:16]}:{limit}"
    if redis:
        try:
            cached_data = await redis.get(cache_key)
            if cached_data:
                cached_json = json.loads(cached_data)
                return PlaceSearchResponse(**cached_json)
        except Exception as exc:
            logger.debug("Redis cache get error in search_places: %s", exc)

    # 3. Primary provider: Photon Komoot API
    results: List[PlaceResult] = []
    provider_used = "photon.komoot.io"

    try:
        params = {
            "q": clean_q,
            "lat": HCMC_CENTER_LAT,
            "lon": HCMC_CENTER_LNG,
            "bbox": HCMC_BBOX,
            "limit": limit,
        }
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(PHOTON_SEARCH_URL, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                for idx, feat in enumerate(features):
                    props = feat.get("properties", {})
                    geom = feat.get("geometry", {})
                    coords_arr = geom.get("coordinates", [])
                    if len(coords_arr) >= 2:
                        lng, lat = float(coords_arr[0]), float(coords_arr[1])
                        # Verify coordinate is in reasonable HCMC bounds
                        if 10.1 <= lat <= 11.5 and 106.0 <= lng <= 107.5:
                            name = props.get("name") or props.get("street") or clean_q
                            display = _format_photon_display_name(props)
                            osm_id = props.get("osm_id")
                            place = PlaceResult(
                                id=f"photon_{osm_id or idx}_{lat:.4f}_{lng:.4f}",
                                name=name,
                                display_name=display,
                                lat=lat,
                                lng=lng,
                                osm_type=props.get("osm_type"),
                                osm_id=osm_id,
                                type=props.get("type"),
                                district=props.get("district"),
                                city=props.get("city") or props.get("state"),
                                provenance="photon.komoot.io",
                            )
                            results.append(place)
            elif resp.status_code == 429:
                logger.warning("Photon geocoder rate-limited (HTTP 429). Falling back to PostGIS.")
                provider_used = "postgis_fallback_ratelimited"
            else:
                logger.warning("Photon geocoder returned HTTP %d", resp.status_code)
                provider_used = f"photon_http_{resp.status_code}"
    except (httpx.TimeoutException, httpx.RequestError) as exc:
        logger.warning("Photon geocoder request failed (%s). Falling back to PostGIS.", exc)
        provider_used = "postgis_fallback_timeout"

    # 4. Fallback to PostGIS road_segments if Photon yielded no results
    if not results and session:
        try:
            sql = text(
                """
                SELECT 
                    street_name,
                    ST_Y(ST_Centroid(ST_Union(geom))) AS lat,
                    ST_X(ST_Centroid(ST_Union(geom))) AS lng,
                    COUNT(*) as seg_count
                FROM road_segments
                WHERE street_name IS NOT NULL AND street_name ILIKE :q
                GROUP BY street_name
                ORDER BY seg_count DESC
                LIMIT :limit
                """
            )
            q_param = f"%{clean_q}%"
            res = await session.execute(sql, {"q": q_param, "limit": limit})
            rows = res.fetchall()
            for r in rows:
                if r.lat is not None and r.lng is not None:
                    place = PlaceResult(
                        id=f"postgis_street_{hashlib.md5(r.street_name.encode()).hexdigest()[:8]}",
                        name=r.street_name,
                        display_name=f"Đường {r.street_name}, TP. Hồ Chí Minh",
                        lat=float(r.lat),
                        lng=float(r.lng),
                        type="street",
                        city="Thành phố Hồ Chí Minh",
                        provenance="postgis.osm_road_segments",
                    )
                    results.append(place)
            if results:
                provider_used = "postgis.osm_road_segments"
        except Exception as db_exc:
            logger.error("PostGIS street search error: %s", db_exc)

    response = PlaceSearchResponse(
        query=clean_q,
        results=results,
        provider=provider_used,
        count=len(results),
    )

    # 5. Save to Redis cache if results found
    if redis and results:
        try:
            await redis.set(cache_key, json.dumps(response.model_dump()), ex=CACHE_TTL_SECONDS)
        except Exception as exc:
            logger.debug("Redis cache set error in search_places: %s", exc)

    return response


async def reverse_geocode(
    lat: float,
    lng: float,
    session: Optional[AsyncSession] = None,
    redis: Optional[Redis] = None,
) -> PlaceResult:
    """
    Reverse geocodes a coordinate point (lat, lng) to an address or street name.
    """
    cache_key = f"places:reverse:{lat:.5f}:{lng:.5f}"
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                return PlaceResult(**json.loads(cached))
        except Exception:
            pass

    # 1. Try Photon reverse
    try:
        params = {"lat": lat, "lon": lng}
        headers = {"User-Agent": DEFAULT_USER_AGENT}
        async with httpx.AsyncClient(timeout=2.5) as client:
            resp = await client.get(PHOTON_REVERSE_URL, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                if features:
                    props = features[0].get("properties", {})
                    name = props.get("name") or props.get("street") or f"{lat:.5f}, {lng:.5f}"
                    display = _format_photon_display_name(props)
                    result = PlaceResult(
                        id=f"rev_photon_{lat:.5f}_{lng:.5f}",
                        name=name,
                        display_name=display,
                        lat=lat,
                        lng=lng,
                        osm_type=props.get("osm_type"),
                        osm_id=props.get("osm_id"),
                        type=props.get("type"),
                        district=props.get("district"),
                        city=props.get("city") or props.get("state"),
                        provenance="photon.komoot.io",
                    )
                    if redis:
                        await redis.set(cache_key, json.dumps(result.model_dump()), ex=CACHE_TTL_SECONDS)
                    return result
    except Exception as exc:
        logger.debug("Photon reverse geocode failed: %s", exc)

    # 2. Fallback to PostGIS nearest road
    if session:
        try:
            sql = text(
                """
                SELECT street_name,
                       ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography) as dist
                FROM road_segments
                WHERE street_name IS NOT NULL
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
                LIMIT 1
                """
            )
            res = await session.execute(sql, {"lat": lat, "lng": lng})
            row = res.fetchone()
            if row and row.street_name:
                result = PlaceResult(
                    id=f"rev_postgis_{lat:.5f}_{lng:.5f}",
                    name=f"Gần đường {row.street_name}",
                    display_name=f"Gần đường {row.street_name}, TP. Hồ Chí Minh ({lat:.4f}, {lng:.4f})",
                    lat=lat,
                    lng=lng,
                    type="street",
                    city="Thành phố Hồ Chí Minh",
                    provenance="postgis.osm_road_segments",
                )
                if redis:
                    await redis.set(cache_key, json.dumps(result.model_dump()), ex=CACHE_TTL_SECONDS)
                return result
        except Exception as exc:
            logger.debug("PostGIS reverse nearest road failed: %s", exc)

    # 3. Coordinate fallback
    return PlaceResult(
        id=f"coord_{lat:.5f}_{lng:.5f}",
        name=f"{lat:.5f}, {lng:.5f}",
        display_name=f"Vị trí [{lat:.5f}, {lng:.5f}], TP. Hồ Chí Minh",
        lat=lat,
        lng=lng,
        type="coordinate",
        provenance="coordinate_fallback",
    )

