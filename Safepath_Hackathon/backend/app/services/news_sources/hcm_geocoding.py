"""
SafePathAI HCMC PostGIS Geocoding Engine for Traffic News (Zero-Mock Runtime).
Resolves real geographic coordinates for Ho Chi Minh City traffic incidents by dynamically querying:
1. Real OpenStreetMap road segments (`road_segments` table) with PostGIS geometries and centroids.
2. Verified camera intersection nodes (`traffic_cameras` table) with exact GPS coordinates.
3. Renowned bridges, tunnels, and key expressways in TP.HCM.

STRICT ZERO-MOCK RULE:
If no street, intersection, or landmark is verified in the news article,
returns (None, None, 'UNRESOLVED'). NEVER fabricates central city coordinates!
"""

from dataclasses import dataclass
import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import text

from backend.app.db.session import AsyncSessionLocal

logger = logging.getLogger("safepath.news.geocoding")

# Verified HCMC prominent landmarks, bridges, and express gateways
HCMC_KNOWN_LANDMARKS: List[Dict[str, Any]] = [
    {"name": "Cầu Sài Gòn", "lat": 10.7997, "lng": 106.7235, "aliases": ["cầu sài gòn", "cau sai gon"]},
    {"name": "Ngã tư Hàng Xanh", "lat": 10.8016, "lng": 106.7118, "aliases": ["ngã tư hàng xanh", "hàng xanh", "nga tu hang xanh"]},
    {"name": "Hầm Thủ Thiêm", "lat": 10.7672, "lng": 106.7056, "aliases": ["hầm thủ thiêm", "hầm vượt sông sài gòn", "ham thu thiem"]},
    {"name": "Cầu Ba Son (Thủ Thiêm 2)", "lat": 10.7785, "lng": 106.7115, "aliases": ["cầu ba son", "cầu thủ thiêm 2", "cau ba son", "cau thu thiem 2"]},
    {"name": "Cầu Thủ Thiêm", "lat": 10.7892, "lng": 106.7208, "aliases": ["cầu thủ thiêm 1", "cầu thủ thiêm", "cau thu thiem"]},
    {"name": "Cầu Bình Triệu", "lat": 10.8242, "lng": 106.7136, "aliases": ["cầu bình triệu", "cau binh trieu"]},
    {"name": "Cầu Kênh Tẻ", "lat": 10.7547, "lng": 106.6989, "aliases": ["cầu kênh tẻ", "cau kenh te"]},
    {"name": "Cầu Phú Mỹ", "lat": 10.7423, "lng": 106.7441, "aliases": ["cầu phú mỹ", "cau phu my"]},
    {"name": "Cầu Chữ Y", "lat": 10.7525, "lng": 106.6841, "aliases": ["cầu chữ y", "cau chu y"]},
    {"name": "Cầu Rạch Chiếc", "lat": 10.8214, "lng": 106.7621, "aliases": ["cầu rạch chiếc", "cau rach chiec"]},
    {"name": "Cầu Chà Và", "lat": 10.7490, "lng": 106.6620, "aliases": ["cầu chà và", "cau cha va"]},
    {"name": "Cầu Ông Lãnh", "lat": 10.7635, "lng": 106.6975, "aliases": ["cầu ông lãnh", "cau ong lanh"]},
    {"name": "Cầu Calmette", "lat": 10.7665, "lng": 106.7015, "aliases": ["cầu calmette", "cau calmette"]},
    {"name": "Cầu Bình Lợi", "lat": 10.8260, "lng": 106.7150, "aliases": ["cầu bình lợi", "cau binh loi"]},
    {"name": "Cầu Vàm Thuật", "lat": 10.8385, "lng": 106.7030, "aliases": ["cầu vàm thuật", "cau vam thuat"]},
    {"name": "Sân bay Tân Sơn Nhất", "lat": 10.8184, "lng": 106.6588, "aliases": ["sân bay tân sơn nhất", "tân sơn nhất", "san bay tan son nhat"]},
    {"name": "Vòng xoay Dân Chủ", "lat": 10.7787, "lng": 106.6811, "aliases": ["vòng xoay dân chủ", "ngã sáu dân chủ", "vong xoay dan chu"]},
    {"name": "Vòng xoay Lăng Cha Cả", "lat": 10.7986, "lng": 106.6612, "aliases": ["vòng xoay lăng cha cả", "lăng cha cả", "lang cha ca"]},
    {"name": "Ngã 6 Phù Đổng", "lat": 10.7717, "lng": 106.6925, "aliases": ["ngã 6 phù đổng", "ngã sáu phù đổng", "nga sau phu dong"]},
    {"name": "Nút giao An Phú", "lat": 10.7950, "lng": 106.7550, "aliases": ["nút giao an phú", "nut giao an phu"]},
    {"name": "Ngã tư An Sương", "lat": 10.8465, "lng": 106.6186, "aliases": ["ngã tư an sương", "an sương", "nga tu an suong"]},
    {"name": "Ngã tư Thủ Đức", "lat": 10.8493, "lng": 106.7738, "aliases": ["ngã tư thủ đức", "nút giao thủ đức", "nga tu thu duc"]},
    {"name": "Bến xe Miền Đông (cũ)", "lat": 10.8142, "lng": 106.7125, "aliases": ["bến xe miền đông cũ", "bến xe miền đông quận bình thạnh"]},
    {"name": "Bến xe Miền Tây", "lat": 10.7410, "lng": 106.6178, "aliases": ["bến xe miền tây", "ben xe mien tay"]},
    {"name": "Kênh Nhiêu Lộc - Hoàng Sa", "lat": 10.7890, "lng": 106.6870, "aliases": ["kênh nhiêu lộc", "nhiêu lộc", "đường hoàng sa", "đường trường sa"]},
    {"name": "Bến xe Miền Đông mới", "lat": 10.8750, "lng": 106.8250, "aliases": ["bến xe miền đông mới", "bxmd mới"]},
    {"name": "Phà Cát Lái", "lat": 10.7602, "lng": 106.7925, "aliases": ["phà cát lái", "pha cat lai"]},
    {"name": "Cao tốc TP.HCM - Long Thành", "lat": 10.7950, "lng": 106.7750, "aliases": ["cao tốc tp.hcm - long thành", "cao tốc long thành", "cao toc long thanh"]},
    {"name": "Đường hoa Nguyễn Huệ", "lat": 10.7745, "lng": 106.7035, "aliases": ["đường hoa nguyễn huệ", "nguyễn huệ", "duong nguyen hue"]},
    {"name": "Tuyến Metro số 1 Bến Thành - Suối Tiên", "lat": 10.7725, "lng": 106.6980, "aliases": ["metro số 1", "tuyến metro số 1", "bến thành - suối tiên"]},
]

GENERIC_WORDS_REQUIRING_PREFIX = {
    "trung tâm", "thống nhất", "tự do", "hòa bình", "độc lập", "chiến thắng",
    "cách mạng", "nội bộ", "chính", "phụ", "mới", "cũ", "dân sinh",
}


@dataclass
class GeocodingMatch:
    lat: Optional[float]
    lng: Optional[float]
    matched_entity: Optional[str]
    confidence: str  # EXACT, APPROXIMATE, UNRESOLVED
    source: str  # POSTGIS_INTERSECTION, POSTGIS_CAMERA, POSTGIS_ROAD_SEGMENT, KNOWN_LANDMARK, UNRESOLVED


class HcmPostgisGeocodingIndex:
    """
    In-memory accelerated PostGIS cache for HCMC streets and camera intersections.
    Dynamically loads street centroids and camera coordinates on first access,
    and falls back to live PostGIS queries when needed.
    """

    _instance: Optional["HcmPostgisGeocodingIndex"] = None

    def __init__(self):
        self.street_cache: Dict[str, Tuple[float, float, str]] = {}
        self.camera_intersections: List[Dict[str, Any]] = []
        self.is_loaded: bool = False

    @classmethod
    def get_instance(cls) -> "HcmPostgisGeocodingIndex":
        if cls._instance is None:
            cls._instance = HcmPostgisGeocodingIndex()
        return cls._instance

    def _normalize(self, text: str) -> str:
        if not text:
            return ""
        norm = unicodedata.normalize("NFC", text.strip().lower())
        norm = re.sub(r"[\u2010-\u2015\u2212]", "-", norm)
        norm = re.sub(r"\s+", " ", norm)
        return norm

    async def ensure_loaded(self):
        """Loads major street centroids from `road_segments` and camera nodes from `traffic_cameras`."""
        if self.is_loaded:
            return

        try:
            async with AsyncSessionLocal() as session:
                # 1. Load named road segments from PostGIS
                stmt_roads = text(
                    """
                    SELECT street_name,
                           ST_Y(ST_Centroid(ST_Union(geom))) as lat,
                           ST_X(ST_Centroid(ST_Union(geom))) as lng,
                           count(*) as seg_count
                    FROM road_segments
                    WHERE street_name IS NOT NULL
                      AND length(trim(street_name)) >= 3
                      AND street_name NOT ILIKE '%hẻm%'
                      AND street_name NOT ILIKE '%đường số%'
                    GROUP BY street_name
                    HAVING count(*) >= 2
                    ORDER BY seg_count DESC
                    LIMIT 2000;
                    """
                )
                res_roads = await session.execute(stmt_roads)
                for row in res_roads.fetchall():
                    s_name = row[0].strip()
                    norm = self._normalize(s_name)
                    # Strip common prefix like "Đường ", "Đại lộ ", "Phố "
                    clean_norm = re.sub(r"^(đường|đại lộ|phố|tuyến)\s+", "", norm).strip()
                    coords = (float(row[1]), float(row[2]), s_name)
                    self.street_cache[norm] = coords
                    if clean_norm and clean_norm != norm and len(clean_norm) >= 3:
                        self.street_cache[clean_norm] = coords

                # 2. Load camera intersection nodes
                stmt_cams = text(
                    """
                    SELECT name, ST_Y(geom) as lat, ST_X(geom) as lng
                    FROM traffic_cameras
                    WHERE geom IS NOT NULL AND name IS NOT NULL;
                    """
                )
                res_cams = await session.execute(stmt_cams)
                for row in res_cams.fetchall():
                    cam_name = row[0].strip()
                    norm_cam = self._normalize(cam_name)
                    self.camera_intersections.append({
                        "name": cam_name,
                        "norm_name": norm_cam,
                        "lat": float(row[1]),
                        "lng": float(row[2]),
                    })

                self.is_loaded = True
                logger.info(
                    "HcmPostgisGeocodingIndex loaded %d streets and %d camera intersections.",
                    len(self.street_cache),
                    len(self.camera_intersections),
                )
        except Exception as exc:
            logger.warning("Could not pre-load PostGIS street cache (will query on demand): %s", exc)

    def resolve_sync(self, text_input: str) -> GeocodingMatch:
        """
        Synchronous resolution against pre-loaded PostGIS street cache and landmarks.
        Strict Zero-Mock: Returns UNRESOLVED if not found.
        """
        if not text_input or not text_input.strip():
            return GeocodingMatch(None, None, None, "UNRESOLVED", "UNRESOLVED")

        norm_text = self._normalize(text_input)

        # Check non-location trap phrases first
        for trap in [
            "cầu truyền hình", "cây cầu nhân ái", "cầu lông", "xe hoa",
            "con đường âm nhạc", "đường tình", "cầu mong", "cầu nguyện",
        ]:
            if trap in norm_text:
                return GeocodingMatch(None, None, None, "UNRESOLVED", "UNRESOLVED")

        # 1. Check verified landmarks and bridges first
        for lm in HCMC_KNOWN_LANDMARKS:
            for alias in lm["aliases"]:
                if alias in norm_text:
                    return GeocodingMatch(
                        lat=lm["lat"],
                        lng=lm["lng"],
                        matched_entity=lm["name"],
                        confidence="EXACT",
                        source="KNOWN_LANDMARK",
                    )

        # 2. Check camera intersections (e.g. "Điện Biên Phủ - Đinh Tiên Hoàng", "Ngã tư Hàng Xanh")
        for cam in self.camera_intersections:
            norm_name = cam["norm_name"]
            if " - " in norm_name:
                parts = [p.strip() for p in norm_name.split(" - ") if len(p.strip()) >= 3]
                if len(parts) >= 2 and all(p in norm_text for p in parts):
                    return GeocodingMatch(
                        lat=cam["lat"],
                        lng=cam["lng"],
                        matched_entity=cam["name"],
                        confidence="EXACT",
                        source="POSTGIS_CAMERA",
                    )
            elif len(norm_name) >= 6 and norm_name in norm_text:
                return GeocodingMatch(
                    lat=cam["lat"],
                    lng=cam["lng"],
                    matched_entity=cam["name"],
                    confidence="EXACT",
                    source="POSTGIS_CAMERA",
                )

        # 3. Detect two streets crossing in text
        crossing_pattern = re.search(
            r"(?:giao lộ|ngã tư|ngã ba|vòng xoay|nút giao)\s+([A-Za-zÀ-ỹ0-9\s]+?)\s*(?:-|giao|với|và|cắt)\s*([A-Za-zÀ-ỹ0-9\s]+)",
            norm_text,
        )
        if crossing_pattern:
            cand1 = self._normalize(crossing_pattern.group(1))
            cand2 = self._normalize(crossing_pattern.group(2))
            c1_clean = re.sub(r"^(đường|đại lộ|phố|tuyến)\s+", "", cand1).strip()
            c2_clean = re.sub(r"^(đường|đại lộ|phố|tuyến)\s+", "", cand2).strip()

            hit1 = self._find_cached_street(c1_clean) or self._find_cached_street(cand1)
            hit2 = self._find_cached_street(c2_clean) or self._find_cached_street(cand2)

            if hit1 and hit2:
                inter_lat = round((hit1[0] + hit2[0]) / 2.0, 5)
                inter_lng = round((hit1[1] + hit2[1]) / 2.0, 5)
                return GeocodingMatch(
                    lat=inter_lat,
                    lng=inter_lng,
                    matched_entity=f"{hit1[2]} giao {hit2[2]}",
                    confidence="EXACT",
                    source="POSTGIS_INTERSECTION",
                )

        # 4. Search for major street names in text
        sorted_keys = sorted(self.street_cache.keys(), key=lambda k: len(k), reverse=True)
        for key in sorted_keys:
            if len(key) < 4:
                continue
            if key in GENERIC_WORDS_REQUIRING_PREFIX:
                pattern = r"(?:đường|đại lộ|phố|tuyến)\s+" + re.escape(key) + r"(?:$|\s|[,\.-])"
            else:
                pattern = r"(?:^|\s|[,\.-])" + re.escape(key) + r"(?:$|\s|[,\.-])"
            if re.search(pattern, norm_text):
                lat, lng, orig_name = self.street_cache[key]
                return GeocodingMatch(
                    lat=lat,
                    lng=lng,
                    matched_entity=orig_name,
                    confidence="APPROXIMATE",
                    source="POSTGIS_ROAD_SEGMENT",
                )

        # STRICT ZERO-MOCK RULE: If not matched, returns UNRESOLVED with None coordinates!
        return GeocodingMatch(
            lat=None,
            lng=None,
            matched_entity=None,
            confidence="UNRESOLVED",
            source="UNRESOLVED",
        )

    async def resolve(self, text_input: str) -> GeocodingMatch:
        """
        Resolves the geographic coordinates of an HCMC location mentioned in text.
        Returns GeocodingMatch with confidence EXACT, APPROXIMATE, or UNRESOLVED.
        Never fabricates center coordinates.
        """
        if not text_input or not text_input.strip():
            return GeocodingMatch(None, None, None, "UNRESOLVED", "UNRESOLVED")

        await self.ensure_loaded()
        norm_text = self._normalize(text_input)

        # Check non-location trap phrases first
        for trap in [
            "cầu truyền hình", "cây cầu nhân ái", "cầu lông", "xe hoa",
            "con đường âm nhạc", "đường tình", "cầu mong", "cầu nguyện",
        ]:
            if trap in norm_text:
                return GeocodingMatch(None, None, None, "UNRESOLVED", "UNRESOLVED")

        # 1. Check verified landmarks and bridges first
        for lm in HCMC_KNOWN_LANDMARKS:
            for alias in lm["aliases"]:
                if alias in norm_text:
                    return GeocodingMatch(
                        lat=lm["lat"],
                        lng=lm["lng"],
                        matched_entity=lm["name"],
                        confidence="EXACT",
                        source="KNOWN_LANDMARK",
                    )

        # 2. Check camera intersections (e.g. "Điện Biên Phủ - Đinh Tiên Hoàng", "Ngã tư Hàng Xanh")
        for cam in self.camera_intersections:
            norm_name = cam["norm_name"]
            # Check if camera intersection has parts e.g. "a - b"
            if " - " in norm_name:
                parts = [p.strip() for p in norm_name.split(" - ") if len(p.strip()) >= 3]
                if len(parts) >= 2 and all(p in norm_text for p in parts):
                    return GeocodingMatch(
                        lat=cam["lat"],
                        lng=cam["lng"],
                        matched_entity=cam["name"],
                        confidence="EXACT",
                        source="POSTGIS_CAMERA",
                    )
            elif len(norm_name) >= 6 and norm_name in norm_text:
                return GeocodingMatch(
                    lat=cam["lat"],
                    lng=cam["lng"],
                    matched_entity=cam["name"],
                    confidence="EXACT",
                    source="POSTGIS_CAMERA",
                )

        # 3. Detect two streets crossing in text: e.g. "giao lộ A và B", "ngã tư A - B", "A cắt B"
        crossing_pattern = re.search(
            r"(?:giao lộ|ngã tư|ngã ba|vòng xoay|nút giao)\s+([A-Za-zÀ-ỹ0-9\s]+?)\s*(?:-|giao|với|và|cắt)\s*([A-Za-zÀ-ỹ0-9\s]+)",
            norm_text,
        )
        if crossing_pattern:
            cand1 = self._normalize(crossing_pattern.group(1))
            cand2 = self._normalize(crossing_pattern.group(2))
            # Strip prefixes
            c1_clean = re.sub(r"^(đường|đại lộ|phố|tuyến)\s+", "", cand1).strip()
            c2_clean = re.sub(r"^(đường|đại lộ|phố|tuyến)\s+", "", cand2).strip()

            hit1 = self._find_cached_street(c1_clean) or self._find_cached_street(cand1)
            hit2 = self._find_cached_street(c2_clean) or self._find_cached_street(cand2)

            if hit1 and hit2:
                # Average coordinate between the two street centroids
                inter_lat = round((hit1[0] + hit2[0]) / 2.0, 5)
                inter_lng = round((hit1[1] + hit2[1]) / 2.0, 5)
                return GeocodingMatch(
                    lat=inter_lat,
                    lng=inter_lng,
                    matched_entity=f"{hit1[2]} giao {hit2[2]}",
                    confidence="EXACT",
                    source="POSTGIS_INTERSECTION",
                )

        # 4. Search for major street names in text (matching longer names first)
        # Sort candidate keys by descending character length to prefer specific names
        sorted_keys = sorted(self.street_cache.keys(), key=lambda k: len(k), reverse=True)
        for key in sorted_keys:
            if len(key) < 4:
                continue
            # Look for whole phrase occurrence
            if key in GENERIC_WORDS_REQUIRING_PREFIX:
                pattern = r"(?:đường|đại lộ|phố|tuyến)\s+" + re.escape(key) + r"(?:$|\s|[,\.-])"
            else:
                pattern = r"(?:^|\s|[,\.-])" + re.escape(key) + r"(?:$|\s|[,\.-])"
            if re.search(pattern, norm_text):
                lat, lng, orig_name = self.street_cache[key]
                return GeocodingMatch(
                    lat=lat,
                    lng=lng,
                    matched_entity=orig_name,
                    confidence="APPROXIMATE",
                    source="POSTGIS_ROAD_SEGMENT",
                )

        # 5. On-demand live PostGIS query fallback if index didn't match
        try:
            async with AsyncSessionLocal() as session:
                # Extract any word preceded by "đường", "tuyến", "đại lộ", "quốc lộ"
                street_cand = re.search(r"(?:đường|tuyến|đại lộ|quốc lộ|xa lộ)\s+([A-Za-zÀ-ỹ0-9\s]{3,30})", norm_text)
                if street_cand:
                    name_fragment = street_cand.group(1).strip()
                    stmt = text(
                        """
                        SELECT street_name,
                               ST_Y(ST_Centroid(ST_Union(geom))) as lat,
                               ST_X(ST_Centroid(ST_Union(geom))) as lng
                        FROM road_segments
                        WHERE street_name ILIKE :q
                        GROUP BY street_name
                        ORDER BY count(*) DESC
                        LIMIT 1;
                        """
                    )
                    res = await session.execute(stmt, {"q": f"%{name_fragment}%"})
                    row = res.fetchone()
                    if row and row[1] is not None and row[2] is not None:
                        return GeocodingMatch(
                            lat=float(row[1]),
                            lng=float(row[2]),
                            matched_entity=row[0],
                            confidence="APPROXIMATE",
                            source="POSTGIS_ROAD_SEGMENT",
                        )
        except Exception as exc:
            logger.debug("Live PostGIS fallback query error: %s", exc)

        # STRICT ZERO-MOCK RULE: If not matched, returns UNRESOLVED with None coordinates!
        return GeocodingMatch(
            lat=None,
            lng=None,
            matched_entity=None,
            confidence="UNRESOLVED",
            source="UNRESOLVED",
        )

    def _find_cached_street(self, query: str) -> Optional[Tuple[float, float, str]]:
        if not query:
            return None
        norm = self._normalize(query)
        if norm in self.street_cache:
            return self.street_cache[norm]
        for k, v in self.street_cache.items():
            if k in norm or norm in k:
                return v
        return None


# Module-level geocoding entry point
async def resolve_hcm_geocoding_postgis(text_input: str) -> Tuple[Optional[float], Optional[float], str]:
    """
    Asynchronously resolves (lat, lng, confidence) using the PostGIS HCMC index.
    Strict Zero-Mock: Returns (None, None, 'UNRESOLVED') if no location is verified.
    """
    index = HcmPostgisGeocodingIndex.get_instance()
    match = await index.resolve(text_input)
    return match.lat, match.lng, match.confidence
