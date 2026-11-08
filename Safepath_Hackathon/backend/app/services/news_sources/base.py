"""
SafePathAI Traffic News Sources Base Infrastructure.
Provides robust date parsing, deterministic ID generation, HCMC geocoding resolution,
and accurate event classification without hallucinations.
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from backend.app.services.news_sources.nlp_classifier import (
    TRAFFIC_KEYWORDS,
    ArticleClassification,
    classify_traffic_headline,
    normalize_vietnamese_text,
)
from backend.app.services.news_sources.hcm_geocoding import (
    GeocodingMatch,
    HcmPostgisGeocodingIndex,
    resolve_hcm_geocoding_postgis,
)

logger = logging.getLogger("safepath.news")

VN_TIMEZONE = timezone(timedelta(hours=7))


@dataclass
class NewsItemData:
    id: str
    canonical_url: str
    source_name: str
    title: str
    summary: str
    category: str  # NGẬP NƯỚC, ÙN TẮC, TAI NẠN, THI CÔNG, CẤM ĐƯỜNG, TIN GIAO THÔNG CHUNG, HỢP LONG / DỰ ÁN
    severity: str  # INFO, WARNING, CRITICAL
    event_status: str  # ONGOING, UPCOMING, RESOLVED, GENERAL_NEWS
    published_at: Optional[datetime]
    fetched_at: datetime
    event_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_confidence: str = "UNRESOLVED"  # EXACT, APPROXIMATE, UNRESOLVED
    geocoding_status: str = "UNRESOLVED"  # EXACT, APPROXIMATE, UNRESOLVED
    verification_status: str = "VERIFIED_SOURCE"
    image_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "canonical_url": self.canonical_url,
            "source_name": self.source_name,
            "title": self.title,
            "summary": self.summary,
            "category": self.category,
            "severity": self.severity,
            "event_status": self.event_status,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "fetched_at": self.fetched_at.isoformat(),
            "event_at": self.event_at.isoformat() if self.event_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "lat": self.latitude,
            "lng": self.longitude,
            "location_confidence": self.location_confidence,
            "geocoding_status": self.geocoding_status,
            "verification_status": self.verification_status,
            "image_url": self.image_url,
            "link": self.canonical_url,
        }


def compute_news_id(source_prefix: str, url: str) -> str:
    """Generates a stable, process-independent deterministic ID from the canonical URL."""
    cleaned = (url or "").strip().lower()
    h = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
    return f"{source_prefix}_{h}"


def parse_news_date(date_str: Optional[str]) -> Optional[datetime]:
    """
    Parses RFC 2822 or Vietnamese news portal date strings into timezone-aware UTC datetime.
    Never hallucinates or replaces missing dates with current time.
    """
    if not date_str or not date_str.strip():
        return None
    s = date_str.strip()

    # 1. Standard RFC 2822
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=VN_TIMEZONE)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    # 2. Formats with possible non-breaking spaces or localized AM/PM
    s_clean = re.sub(r"\s+", " ", s)
    formats = [
        "%m/%d/%Y %I:%M:%S %p",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(s_clean, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=VN_TIMEZONE)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue

    logger.debug("Unparseable news date string: %s", date_str)
    return None


# Verified HCMC geographic focal traffic nodes with exact coordinates
HCMC_GEO_NODES: List[Dict[str, Any]] = [
    {"name": "Cầu Sài Gòn", "lat": 10.7997, "lng": 106.7235, "keywords": ["cầu sài gòn", "điện biên phủ", "xa lộ hà nội", "võ nguyên giáp"]},
    {"name": "Ngã tư Hàng Xanh", "lat": 10.8016, "lng": 106.7118, "keywords": ["hàng xanh", "xô viết nghệ tĩnh", "bạch đằng", "đinh bộ lĩnh"]},
    {"name": "Hầm Thủ Thiêm", "lat": 10.7672, "lng": 106.7056, "keywords": ["hầm thủ thiêm", "hầm sông sài gòn", "mai chí thọ"]},
    {"name": "Cầu Bình Triệu", "lat": 10.8242, "lng": 106.7136, "keywords": ["cầu bình triệu", "quốc lộ 13", "bến xe miền đông cũ"]},
    {"name": "Vòng xoay Dân Chủ", "lat": 10.7787, "lng": 106.6811, "keywords": ["vòng xoay dân chủ", "cách mạng tháng tám", "ba tháng hai", "nguyễn thị minh khai"]},
    {"name": "Ngã 6 Phù Đổng", "lat": 10.7717, "lng": 106.6925, "keywords": ["ngã 6 phù đổng", "ngã sáu phù đổng", "nguyễn trãi", "lý tự trọng"]},
    {"name": "Cầu Kênh Tẻ", "lat": 10.7547, "lng": 106.6989, "keywords": ["cầu kênh tẻ", "khánh hội", "nguyễn hữu thọ"]},
    {"name": "Cầu Phú Mỹ", "lat": 10.7423, "lng": 106.7441, "keywords": ["cầu phú mỹ", "huỳnh tấn phát", "võ chí công"]},
    {"name": "Đường Nguyễn Hữu Cảnh", "lat": 10.7905, "lng": 106.7176, "keywords": ["nguyễn hữu cảnh", "tòa nhà landmark 81", "vinhomes central park"]},
    {"name": "Sân bay Tân Sơn Nhất", "lat": 10.8184, "lng": 106.6588, "keywords": ["sân bay tân sơn nhất", "tân sơn nhất", "đường trường sơn", "hoàng văn thụ"]},
    {"name": "Ngã tư An Sương", "lat": 10.8465, "lng": 106.6186, "keywords": ["ngã tư an sương", "an sương", "quốc lộ 22", "trường chinh"]},
    {"name": "Cầu Chữ Y", "lat": 10.7525, "lng": 106.6841, "keywords": ["cầu chữ y", "nguyễn biểu", "dương bá trạc"]},
    {"name": "Vòng xoay Lăng Cha Cả", "lat": 10.7986, "lng": 106.6612, "keywords": ["lăng cha cả", "cộng hòa", "hoàng văn thụ"]},
    {"name": "Đường Hoàng Sa / Nhiêu Lộc", "lat": 10.7890, "lng": 106.6870, "keywords": ["đường hoàng sa", "đường trường sa", "kênh nhiêu lộc"]},
    {"name": "Nút giao An Phú", "lat": 10.7950, "lng": 106.7550, "keywords": ["nút giao an phú", "cao tốc tp.hcm - long thành", "lương định của"]},
    {"name": "Đường Võ Văn Kiệt", "lat": 10.7580, "lng": 106.6800, "keywords": ["võ văn kiệt", "đại lộ đông tây"]},
]


def resolve_hcm_geocoding(text: str) -> Tuple[Optional[float], Optional[float], str]:
    """
    Resolves geographic coordinates from HCMC PostGIS road segments, camera intersections,
    and verified landmarks.
    STRICT ZERO-MOCK RULE: If no specific landmark or street is verified, returns
    (None, None, 'UNRESOLVED'). NEVER fabricates central city coordinates!
    """
    if not text or not text.strip():
        return None, None, "UNRESOLVED"

    # Use PostGIS geocoding index synchronous resolver
    match = HcmPostgisGeocodingIndex.get_instance().resolve_sync(text)
    if match.confidence != "UNRESOLVED" and match.lat is not None and match.lng is not None:
        return match.lat, match.lng, match.confidence

    # Secondary check against HCMC_GEO_NODES for fast fallback
    text_lower = text.lower()
    for node in HCMC_GEO_NODES:
        if any(kw in text_lower for kw in node["keywords"]):
            return node["lat"], node["lng"], "APPROXIMATE"

    return None, None, "UNRESOLVED"


def classify_traffic_article(title: str, description: str = "") -> Tuple[str, str, str]:
    """
    Accurately classifies news articles into category, severity, and temporal event_status
    using phrase-based multi-keyword matching, Vietnamese normalization, and negation detection.
    Prevents benign milestones or non-traffic phrases from being misclassified as active hazards.
    """
    res = classify_traffic_headline(title, description)
    return res.category, res.severity, res.temporal_status

