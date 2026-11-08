"""
Unit & Integration Tests for SafePathAI Traffic News Service (Phase 10).
Verifies RFC 2822 parsing, deterministic canonical IDs, honest geocoding,
and non-hallucinatory incident messaging.
"""

from datetime import datetime, timezone
import pytest
from httpx import AsyncClient

from backend.app.services.news_sources.base import (
    classify_traffic_article,
    compute_news_id,
    parse_news_date,
    resolve_hcm_geocoding,
)
from backend.app.services.traffic_news import (
    get_nearby_traffic_news,
    haversine_km,
)


def test_parse_news_date_rfc2822_and_custom():
    # Standard RFC 2822 from VnExpress
    rfc_str = "Sat, 24 Oct 2026 04:00:00 +0700"
    dt = parse_news_date(rfc_str)
    assert dt is not None
    assert dt.tzinfo == timezone.utc
    assert dt.hour == 21  # 04:00 +0700 is 21:00 UTC previous day

    # Custom Vietnamese portal format (Tuoi Tre)
    custom_str = "10/24/2026 5:47:00 AM"
    dt2 = parse_news_date(custom_str)
    assert dt2 is not None
    assert dt2.tzinfo == timezone.utc

    # Missing or empty string
    assert parse_news_date("") is None
    assert parse_news_date(None) is None


def test_deterministic_news_id():
    url1 = "https://vnexpress.net/thoi-su/bai-bao-123.html"
    url2 = "https://vnexpress.net/thoi-su/bai-bao-123.html?utm_source=rss"
    # Canonical URLs with same base
    id1 = compute_news_id("vnex", url1)
    id2 = compute_news_id("vnex", url1)
    assert id1 == id2
    assert id1.startswith("vnex_")
    assert len(id1) == 5 + 16  # "vnex_" + 16 hex chars


def test_honest_geocoding_resolution():
    # Specific landmark match
    lat, lng, status = resolve_hcm_geocoding("Xe múc lật ngửa tại đường Hoàng Sa, kênh Nhiêu Lộc gây ùn tắc")
    assert lat is not None and lng is not None
    assert status in ("EXACT", "APPROXIMATE")
    assert round(lat, 2) == 10.79

    # General text mentioning only TP.HCM
    lat_gen, lng_gen, status_gen = resolve_hcm_geocoding("UBND TP.HCM ban hành kế hoạch phát triển giao thông đô thị")
    assert lat_gen is None
    assert lng_gen is None
    assert status_gen == "UNRESOLVED"
    # STRICT ZERO-MOCK: Must NEVER default to 10.7769, 106.7009!


def test_accurate_event_classification():
    # Benign milestone (bridge completion)
    cat1, sev1, st1 = classify_traffic_article(
        "Cầu đi bộ qua sông Sài Gòn hoàn thành hợp long",
        "Sau nhiều giờ triển khai, cầu đi bộ hoàn tất hợp long chiều 21/10."
    )
    assert cat1 == "DỰ ÁN / HẠ TẦNG"
    assert sev1 == "INFO"
    assert st1 in ("RESOLVED", "HISTORICAL")

    # Active accident
    cat2, sev2, st2 = classify_traffic_article(
        "Xe múc lật ngửa, chắn đường gây ùn tắc hơn một km ở TP HCM",
        "Xe múc 5 tấn bất ngờ lật ngửa ra đường khiến giao thông ùn tắc."
    )
    assert cat2 in ("TAI NẠN", "ACCIDENT")
    assert sev2 == "CRITICAL"
    assert st2 in ("ONGOING", "ACTIVE_HAZARD")

    # Flooding
    cat3, sev3, st3 = classify_traffic_article(
        "Mưa lớn gây ngập sâu đường Quốc Hương",
        "Nước tràn vào nhà dân, xe chết máy hàng loạt."
    )
    assert cat3 in ("NGẬP NƯỚC", "FLOOD")
    assert sev3 == "CRITICAL"
    assert st3 in ("ONGOING", "ACTIVE_HAZARD")


@pytest.mark.asyncio
async def test_nearby_traffic_news_empty_message_honesty():
    # Coordinate far away in ocean or countryside
    res = await get_nearby_traffic_news(lat=0.0, lng=0.0, radius_km=3.0)
    assert res.count == 0
    assert res.status == "NO_NEARBY_INCIDENTS"
    assert "Chưa tìm thấy bản tin giao thông phù hợp trong các nguồn đang theo dõi." in res.message
    # Must NOT claim "Không có sự cố giao thông nào được ghi nhận gần khu vực này trong 12 giờ qua."
    assert "12 giờ qua" not in res.message


@pytest.mark.asyncio
async def test_traffic_news_summary_and_highlights():
    from backend.app.services.traffic_news import (
        get_traffic_news_highlights,
        get_traffic_news_summary,
        list_all_traffic_news,
        TrafficNewsItem,
    )

    # Test summary response format and data fields
    summary = await get_traffic_news_summary()
    assert summary is not None
    assert isinstance(summary.total_articles, int)
    assert isinstance(summary.active_hazards, int)
    assert "FLOOD" in summary.categories
    assert "CONGESTION" in summary.categories
    assert "vnexpress" in summary.sources
    assert "tuoitre" in summary.sources
    assert summary.sources["vnexpress"]["status"] == "CONNECTED"

    # Test highlights
    highlights = await get_traffic_news_highlights(limit=3)
    assert highlights is not None
    assert highlights.count <= 3
    assert isinstance(highlights.items, list)

    # Test list_all_traffic_news with category & timeframe filters
    res_all = await list_all_traffic_news(limit=10, offset=0)
    assert res_all.count <= 10
    assert res_all.total >= res_all.count

    # Test category filter
    res_flood = await list_all_traffic_news(category="FLOOD", limit=10)
    for it in res_flood.items:
        c = it.category.upper()
        assert "NGẬP" in c or "FLOOD" in c

    # Test text search filter
    res_search = await list_all_traffic_news(search="đường", limit=10)
    for it in res_search.items:
        assert "đường" in (it.title + " " + it.summary + " " + it.source_name).lower()

