from backend.app.services.news_sources.base import (
    NewsItemData,
    compute_news_id,
    parse_news_date,
    resolve_hcm_geocoding,
    classify_traffic_article,
)
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
from backend.app.services.news_sources.vnexpress_rss import fetch_vnexpress_news
from backend.app.services.news_sources.tuoitre_rss import fetch_tuoitre_news
from backend.app.services.news_sources.hcm_traffic_portal import fetch_portal_announcements
from backend.app.services.news_sources.official_alerts import generate_official_environmental_alerts

__all__ = [
    "NewsItemData",
    "compute_news_id",
    "parse_news_date",
    "resolve_hcm_geocoding",
    "classify_traffic_article",
    "TRAFFIC_KEYWORDS",
    "ArticleClassification",
    "classify_traffic_headline",
    "normalize_vietnamese_text",
    "GeocodingMatch",
    "HcmPostgisGeocodingIndex",
    "resolve_hcm_geocoding_postgis",
    "fetch_vnexpress_news",
    "fetch_tuoitre_news",
    "fetch_portal_announcements",
    "generate_official_environmental_alerts",
]

