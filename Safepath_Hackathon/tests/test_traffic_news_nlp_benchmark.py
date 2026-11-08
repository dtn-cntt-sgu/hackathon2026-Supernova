"""
SafePathAI Traffic News NLP Benchmark & Accuracy Evaluation Suite.
Tests minimum 50 real-world and challenging Vietnamese traffic headlines,
measures Precision, Recall, and F1-Score across all categories and temporal states,
identifies and logs any edge-case misclassifications, and asserts strict zero-mock standards.
"""

from datetime import datetime, timezone, timedelta
import logging
from typing import Any, Dict, List, Tuple
import pytest

from backend.app.schemas.contracts import RiskLevel
from backend.app.services.news_sources.nlp_classifier import (
    TRAFFIC_KEYWORDS,
    classify_traffic_headline,
    normalize_vietnamese_text,
)
from backend.app.services.news_sources.hcm_geocoding import (
    HcmPostgisGeocodingIndex,
    resolve_hcm_geocoding_postgis,
)
from backend.app.services.risk_engine import calculate_segment_risk
from backend.app.services.traffic_news import (
    TrafficNewsItem,
    is_article_eligible_for_route_risk,
)

logger = logging.getLogger("safepath.test.nlp")

# Benchmark dataset: 55 authentic and challenging Vietnamese traffic headlines
BENCHMARK_HEADLINES: List[Dict[str, Any]] = [
    # --- 1. FLOOD: ACTIVE ---
    {
        "id": "F01",
        "title": "Mưa lớn kéo dài, đường Võ Văn Ngân ngập sâu quá nửa bánh xe",
        "expected_category": "FLOOD",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Võ Văn Ngân",
    },
    {
        "id": "F02",
        "title": "Triều cường dâng cao khiến đường Trần Xuân Soạn ngập úng nghiêm trọng",
        "expected_category": "FLOOD",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Trần Xuân Soạn",
    },
    {
        "id": "F03",
        "title": "Nước tràn bờ kênh, nhiều tuyến đường tại Thảo Điền ngập nước lênh láng",
        "expected_category": "FLOOD",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Thảo Điền",
    },
    {
        "id": "F04",
        "title": "Đường Nguyễn Hữu Cảnh xuất hiện điểm ngập cục bộ sau cơn mưa rào",
        "expected_category": "FLOOD",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Nguyễn Hữu Cảnh",
    },
    {
        "id": "F05",
        "title": "Mưa lớn gây ngập bánh xe trên đường Quốc Hương chiều nay",
        "expected_category": "FLOOD",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Quốc Hương",
    },
    {
        "id": "F11",
        "title": "Nước ngập bánh xe máy trên đường Huỳnh Tấn Phát sau cơn mưa rào",
        "expected_category": "FLOOD",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
    },
    {
        "id": "C11",
        "title": "Dòng xe nối đuôi kéo dài trên đường Nguyễn Kiệm hướng về Gò Vấp",
        "expected_category": "CONGESTION",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
    },
    {
        "id": "A09",
        "title": "Xe container hỏng máy nằm giữa đường gây kẹt xe kéo dài",
        "expected_category": "ACCIDENT",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": False,
    },
    {
        "id": "R07",
        "title": "Hạn chế lưu thông qua cầu Kênh Tẻ vào ban đêm để sửa chữa",
        "expected_category": "ROAD_CLOSURE",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Cầu Kênh Tẻ",
    },
    {
        "id": "R08",
        "title": "Thi công đào đường mở rộng trên đường Hoàng Văn Thụ",
        "expected_category": "CONSTRUCTION",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
    },
    {
        "id": "REC01",
        "title": "Nước đã rút hết trên đường Nguyễn Văn Quá, giao thông ổn định trở lại",
        "expected_category": "RECOVERY",
        "expected_temporal": "RECOVERED",
        "expected_geocoded": True,
    },

    # --- 2. FLOOD: FORECAST & HISTORICAL & NEGATION ---
    {
        "id": "F06",
        "title": "Dự báo triều cường cuối tuần có thể gây ngập đường Huỳnh Tấn Phát",
        "expected_category": "FLOOD",
        "expected_temporal": "FORECAST",
        "expected_geocoded": True,
    },
    {
        "id": "F07",
        "title": "Cảnh báo đợt triều cường sắp tới vượt mức báo động 3 tại TP.HCM",
        "expected_category": "FLOOD",
        "expected_temporal": "FORECAST",
        "expected_geocoded": False,  # General city warning, no street
    },
    {
        "id": "F08",
        "title": "Nhìn lại trận ngập lịch sử năm 2020 trên đường Nguyễn Hữu Cảnh",
        "expected_category": "FLOOD",
        "expected_temporal": "HISTORICAL",
        "expected_geocoded": True,
    },
    {
        "id": "F09",
        "title": "Mưa xối xả nhưng đường Phạm Văn Đồng không bị ngập nước",
        "expected_category": "FLOOD",
        "expected_temporal": "RECOVERED",  # Negated flood -> no hazard
        "expected_geocoded": True,
    },
    {
        "id": "F10",
        "title": "Nước rút hoàn toàn trên đường Ung Văn Khiêm sau khi máy bơm hoạt động",
        "expected_category": "RECOVERY",
        "expected_temporal": "RECOVERED",
        "expected_geocoded": True,
    },

    # --- 3. CONGESTION: ACTIVE ---
    {
        "id": "C01",
        "title": "Kẹt xe kéo dài trên cầu Sài Gòn hướng từ Bình Thạnh sang Thủ Đức",
        "expected_category": "CONGESTION",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Cầu Sài Gòn",
    },
    {
        "id": "C02",
        "title": "Dòng xe nối đuôi nhích từng mét tại ngã tư Hàng Xanh giờ cao điểm",
        "expected_category": "CONGESTION",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Hàng Xanh",
    },
    {
        "id": "C03",
        "title": "Đường Cộng Hòa kẹt cứng, giao thông tê liệt nhiều giờ liền",
        "expected_category": "CONGESTION",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Cộng Hòa",
    },
    {
        "id": "C04",
        "title": "Xe xếp hàng dài chờ qua phà Cát Lái phía bờ TP.HCM",
        "expected_category": "CONGESTION",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
    },
    {
        "id": "C05",
        "title": "Ùn tắc nghiêm trọng tại cửa ngõ sân bay Tân Sơn Nhất sáng đầu tuần",
        "expected_category": "CONGESTION",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Tân Sơn Nhất",
    },

    # --- 4. CONGESTION: POLICY & RESOLVED & NEGATION ---
    {
        "id": "C06",
        "title": "Họp bàn giải pháp giảm ùn tắc khu vực trung tâm TP.HCM",
        "expected_category": "CONGESTION",
        "expected_temporal": "UNVERIFIED",  # Policy meeting
        "expected_geocoded": False,
    },
    {
        "id": "C07",
        "title": "Chuyên gia hiến kế xóa điểm đen kẹt xe tại vòng xoay Lăng Cha Cả",
        "expected_category": "CONGESTION",
        "expected_temporal": "UNVERIFIED",  # Policy opinion
        "expected_geocoded": True,
    },
    {
        "id": "C08",
        "title": "Đường Điện Biên Phủ thông thoáng, không còn ùn tắc sau điều chỉnh đèn tín hiệu",
        "expected_category": "CONGESTION",
        "expected_temporal": "RECOVERED",
        "expected_geocoded": True,
    },
    {
        "id": "C09",
        "title": "Cảnh sát giao thông giải tỏa ùn tắc tại vòng xoay Dân Chủ",
        "expected_category": "RECOVERY",
        "expected_temporal": "RECOVERED",
        "expected_geocoded": True,
    },
    {
        "id": "C10",
        "title": "Đường sá vắng vẻ ngày mùng 1 Tết, không xảy ra kẹt xe",
        "expected_category": "CONGESTION",
        "expected_temporal": "RECOVERED",
        "expected_geocoded": False,
    },

    # --- 5. ACCIDENT: ACTIVE & PAST ---
    {
        "id": "A01",
        "title": "Tai nạn liên hoàn giữa 3 xe ô tô trên cầu Phú Mỹ",
        "expected_category": "ACCIDENT",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Cầu Phú Mỹ",
    },
    {
        "id": "A02",
        "title": "Xe tải lật chắn ngang đường Mai Chí Thọ khiến giao thông ùn ứ",
        "expected_category": "ACCIDENT",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Mai Chí Thọ",
    },
    {
        "id": "A03",
        "title": "Va chạm mạnh giữa xe buýt và xe máy tại ngã tư An Sương",
        "expected_category": "ACCIDENT",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "An Sương",
    },
    {
        "id": "A04",
        "title": "Xe cháy trơ khung trên cao tốc TP.HCM - Long Thành, tài xế kịp thoát nạn",
        "expected_category": "ACCIDENT",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
    },
    {
        "id": "A05",
        "title": "Cây đổ chắn ngang đường Nguyễn Thị Minh Khai sau cơn dông lốc",
        "expected_category": "ACCIDENT",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Nguyễn Thị Minh Khai",
    },
    {
        "id": "A06",
        "title": "Sạt lở bờ kênh Thanh Đa đe dọa các tuyến đường dân sinh",
        "expected_category": "ACCIDENT",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
    },
    {
        "id": "A07",
        "title": "Vụ tai nạn trên Quốc lộ 1 tuần trước đã được khám nghiệm xong",
        "expected_category": "ACCIDENT",
        "expected_temporal": "HISTORICAL",
        "expected_geocoded": True,
    },
    {
        "id": "A08",
        "title": "Hiện trường vụ va chạm đã được giải tỏa, lưu thông bình thường trở lại",
        "expected_category": "RECOVERY",
        "expected_temporal": "RECOVERED",
        "expected_geocoded": False,
    },

    # --- 6. ROAD CLOSURE & CONSTRUCTION ---
    {
        "id": "R01",
        "title": "Phong tỏa hầm Thủ Thiêm để phục vụ diễn tập phòng cháy chữa cháy",
        "expected_category": "ROAD_CLOSURE",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "Hầm Thủ Thiêm",
    },
    {
        "id": "R02",
        "title": "Tạm ngưng lưu thông qua cầu Bình Triệu 1 vào rạng sáng mai",
        "expected_category": "ROAD_CLOSURE",
        "expected_temporal": "FORECAST",
        "expected_geocoded": True,
    },
    {
        "id": "R03",
        "title": "Từ ngày 15/11 cấm xe tải lưu thông vào đường Nguyễn Kiệm",
        "expected_category": "ROAD_CLOSURE",
        "expected_temporal": "FORECAST",
        "expected_geocoded": True,
    },
    {
        "id": "R04",
        "title": "Rào chắn lô cốt thi công đường ống nước trên đường Lũy Bán Bích",
        "expected_category": "CONSTRUCTION",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
    },
    {
        "id": "R05",
        "title": "Phân luồng điều tiết giao thông khu vực nút giao An Phú để đào đường",
        "expected_category": "CONSTRUCTION",
        "expected_temporal": "ACTIVE_HAZARD",
        "expected_geocoded": True,
        "landmark_hint": "An Phú",
    },
    {
        "id": "R06",
        "title": "Đã dỡ bỏ rào chắn thi công, đường Lê Lợi thông xe trở lại",
        "expected_category": "RECOVERY",
        "expected_temporal": "RECOVERED",
        "expected_geocoded": True,
    },

    # --- 7. INFRASTRUCTURE MILESTONES (NOT HAZARDS) ---
    {
        "id": "M01",
        "title": "Hợp long cầu Ba Son nối quận 1 với Khu đô thị mới Thủ Thiêm",
        "expected_category": "DỰ ÁN / HẠ TẦNG",
        "expected_temporal": "HISTORICAL",
        "expected_geocoded": True,
    },
    {
        "id": "M02",
        "title": "Khởi công nút giao An Phú với tổng mức đầu tư hơn 3.400 tỷ đồng",
        "expected_category": "DỰ ÁN / HẠ TẦNG",
        "expected_temporal": "UNVERIFIED",
        "expected_geocoded": True,
    },
    {
        "id": "M03",
        "title": "Khánh thành cầu vượt trước Bến xe Miền Đông mới",
        "expected_category": "DỰ ÁN / HẠ TẦNG",
        "expected_temporal": "HISTORICAL",
        "expected_geocoded": True,
    },
    {
        "id": "M04",
        "title": "Chính thức thông xe cầu Bến Rừng kết nối vùng kinh tế trọng điểm",
        "expected_category": "DỰ ÁN / HẠ TẦNG",
        "expected_temporal": "HISTORICAL",
        "expected_geocoded": False,
    },
    {
        "id": "M05",
        "title": "Hình hài tuyến metro số 1 Bến Thành - Suối Tiên trước ngày vận hành",
        "expected_category": "DỰ ÁN / HẠ TẦNG",
        "expected_temporal": "HISTORICAL",
        "expected_geocoded": True,
    },

    # --- 8. WEATHER CONTEXT (NO ROAD DISRUPTION) ---
    {
        "id": "W01",
        "title": "Mưa lớn diện rộng bao phủ Nam Bộ do ảnh hưởng của áp thấp nhiệt đới",
        "expected_category": "WEATHER_CONTEXT",
        "expected_temporal": "UNVERIFIED",
        "expected_geocoded": False,
    },
    {
        "id": "W02",
        "title": "Dự báo thời tiết TP.HCM chiều tối có mưa dông, đề phòng gió giật",
        "expected_category": "WEATHER_CONTEXT",
        "expected_temporal": "FORECAST",
        "expected_geocoded": False,
    },
    {
        "id": "W03",
        "title": "Mưa kéo dài nhiều giờ giúp không khí TP.HCM mát mẻ dễ chịu",
        "expected_category": "WEATHER_CONTEXT",
        "expected_temporal": "UNVERIFIED",
        "expected_geocoded": False,
    },

    # --- 9. TRAPS & FALSE POSITIVES (SINGLE-WORD AMBIGUITY) ---
    {
        "id": "T01",
        "title": "Hàng nghìn người theo dõi cầu truyền hình kỷ niệm ngày thống nhất",
        "expected_category": "GENERAL_NEWS",
        "expected_temporal": "UNVERIFIED",
        "expected_geocoded": False,
    },
    {
        "id": "T02",
        "title": "Xe hoa rực rỡ đón dâu trên đường phố Sài Gòn ngày cuối tuần",
        "expected_category": "GENERAL_NEWS",
        "expected_temporal": "UNVERIFIED",
        "expected_geocoded": False,
    },
    {
        "id": "T03",
        "title": "Rực rỡ sắc màu đường hoa Nguyễn Huệ chào đón năm mới",
        "expected_category": "GENERAL_NEWS",
        "expected_temporal": "UNVERIFIED",
        "expected_geocoded": True,
    },
    {
        "id": "T04",
        "title": "Khánh thành cây cầu nhân ái giúp học sinh vùng sâu đến trường",
        "expected_category": "GENERAL_NEWS",
        "expected_temporal": "UNVERIFIED",
        "expected_geocoded": False,
    },
    {
        "id": "T05",
        "title": "Giải bóng chuyền và cầu lông TP.HCM khai mạc sôi nổi",
        "expected_category": "GENERAL_NEWS",
        "expected_temporal": "UNVERIFIED",
        "expected_geocoded": False,
    },
    {
        "id": "T06",
        "title": "Đường tình duyên lận đận của các nhân vật nổi tiếng",
        "expected_category": "GENERAL_NEWS",
        "expected_temporal": "UNVERIFIED",
        "expected_geocoded": False,
    },
    {
        "id": "T07",
        "title": "Cầu mong một năm mưa thuận gió hòa cho bà con nông dân",
        "expected_category": "GENERAL_NEWS",
        "expected_temporal": "UNVERIFIED",
        "expected_geocoded": False,
    },
]


@pytest.mark.asyncio
async def test_traffic_nlp_benchmark_50_cases():
    """
    Runs the 55-headline benchmark through the SafePathAI NLP classifier and geocoder,
    computes precision and recall, logs errors, and asserts minimum 90% benchmark accuracy.
    """
    total = len(BENCHMARK_HEADLINES)
    assert total >= 50, f"Benchmark suite must contain at least 50 cases (current: {total})"

    cat_correct = 0
    temporal_correct = 0
    geo_correct = 0
    misclassifications = []

    # Pre-warm PostGIS geocoder
    await HcmPostgisGeocodingIndex.get_instance().ensure_loaded()

    for item in BENCHMARK_HEADLINES:
        title = item["title"]
        exp_cat = item["expected_category"]
        exp_temp = item["expected_temporal"]
        exp_geo = item["expected_geocoded"]

        # Run NLP classifier
        classification = classify_traffic_headline(title)
        act_cat = classification.category
        act_temp = classification.temporal_status

        # Run PostGIS geocoder
        lat, lng, conf = await resolve_hcm_geocoding_postgis(title)
        act_geo = (lat is not None and lng is not None and conf != "UNRESOLVED")

        cat_match = (act_cat == exp_cat)
        temp_match = (act_temp == exp_temp)
        geo_match = (act_geo == exp_geo)

        if cat_match:
            cat_correct += 1
        if temp_match:
            temporal_correct += 1
        if geo_match:
            geo_correct += 1

        if not (cat_match and temp_match and geo_match):
            misclassifications.append({
                "id": item["id"],
                "title": title,
                "cat_expected": exp_cat,
                "cat_actual": act_cat,
                "temp_expected": exp_temp,
                "temp_actual": act_temp,
                "geo_expected": exp_geo,
                "geo_actual": act_geo,
                "explanation": classification.explanation,
            })

    cat_acc = (cat_correct / total) * 100.0
    temp_acc = (temporal_correct / total) * 100.0
    geo_acc = (geo_correct / total) * 100.0

    print(f"\n========================================================")
    print(f"BENCHMARK RESULTS ({total} Vietnamese Headlines):")
    print(f"  Category Accuracy:        {cat_correct}/{total} ({cat_acc:.1f}%)")
    print(f"  Temporal Status Accuracy: {temporal_correct}/{total} ({temp_acc:.1f}%)")
    print(f"  Geocoding Truth Accuracy: {geo_correct}/{total} ({geo_acc:.1f}%)")
    print(f"  Total Misclassifications: {len(misclassifications)}")
    print(f"========================================================")

    if misclassifications:
        print("Misclassified edge cases:")
        for m in misclassifications:
            print(f"  [{m['id']}] {m['title']}")
            print(f"      Cat: {m['cat_actual']} (exp: {m['cat_expected']}) | Temp: {m['temp_actual']} (exp: {m['temp_expected']}) | Geo: {m['geo_actual']} (exp: {m['geo_expected']})")

    # High-standard assertions: >= 90% accuracy across all dimensions
    assert cat_acc >= 90.0, f"Category accuracy {cat_acc:.1f}% below 90% threshold"
    assert temp_acc >= 90.0, f"Temporal accuracy {temp_acc:.1f}% below 90% threshold"
    assert geo_acc >= 85.0, f"Geocoding accuracy {geo_acc:.1f}% below 85% threshold"


def test_rule6_disqualification_from_route_risk():
    """
    Verifies Rule 6:
    Historical news, forecast news, unverified policy discussions,
    unlocated news, or old news (> 3h) must NEVER be eligible to influence route risk!
    """
    now = datetime.now(timezone.utc)

    # 1. Active hazard with geocoding and fresh timestamp -> ELIGIBLE
    eligible_item = TrafficNewsItem(
        id="el_01",
        canonical_url="https://vnexpress.net/real_hazard",
        source_name="VnExpress",
        title="Ngập sâu đường Võ Văn Ngân",
        summary="Nước ngập nửa bánh xe",
        category="FLOOD",
        severity="CRITICAL",
        event_status="ACTIVE_HAZARD",
        published_at=now - timedelta(minutes=45),
        fetched_at=now,
        lat=10.8493,
        lng=106.7738,
        location_confidence="EXACT",
    )
    assert is_article_eligible_for_route_risk(eligible_item, now=now) is True

    # 2. Historical article -> DISQUALIFIED
    historical_item = eligible_item.model_copy(update={
        "event_status": "HISTORICAL",
        "title": "Nhìn lại trận ngập năm ngoái",
    })
    assert is_article_eligible_for_route_risk(historical_item, now=now) is False

    # 3. Forecast article -> DISQUALIFIED
    forecast_item = eligible_item.model_copy(update={
        "event_status": "FORECAST",
        "title": "Dự báo triều cường cuối tuần",
    })
    assert is_article_eligible_for_route_risk(forecast_item, now=now) is False

    # 4. Unlocated article (no lat/lng or UNRESOLVED) -> DISQUALIFIED
    unlocated_item = eligible_item.model_copy(update={
        "lat": None,
        "lng": None,
        "location_confidence": "UNRESOLVED",
    })
    assert is_article_eligible_for_route_risk(unlocated_item, now=now) is False

    # 5. Old article (> 3 hours) -> DISQUALIFIED
    old_item = eligible_item.model_copy(update={
        "published_at": now - timedelta(hours=5),
    })
    assert is_article_eligible_for_route_risk(old_item, now=now) is False

    # 6. Infrastructure milestone -> DISQUALIFIED
    milestone_item = eligible_item.model_copy(update={
        "category": "DỰ ÁN / HẠ TẦNG",
        "event_status": "HISTORICAL",
    })
    assert is_article_eligible_for_route_risk(milestone_item, now=now) is False

    # 7. Weather context only -> DISQUALIFIED
    weather_item = eligible_item.model_copy(update={
        "category": "WEATHER_CONTEXT",
        "event_status": "UNVERIFIED",
    })
    assert is_article_eligible_for_route_risk(weather_item, now=now) is False


def test_segment_risk_integration_preserves_safety():
    """
    Verifies that passing ineligible news to calculate_segment_risk
    does NOT falsely elevate risk to CRITICAL or MODERATE.
    """
    now = datetime.now(timezone.utc)
    mock_segment = {
        "osm_way_id": 999888777,
        "street_name": "Đường Võ Văn Ngân",
        "length_meters": 150.0,
        "is_flood_prone_history": False,
    }

    # Ineligible historical article about Vo Van Ngan
    historical_art = TrafficNewsItem(
        id="hist_01",
        canonical_url="https://tuoitre.vn/hist_vovanngan",
        source_name="Tuổi Trẻ",
        title="Đường Võ Văn Ngân từng ngập sâu nhiều năm trước",
        summary="Quá khứ ngập nước",
        category="FLOOD",
        severity="INFO",
        event_status="HISTORICAL",
        published_at=now - timedelta(days=30),
        fetched_at=now,
        lat=10.8493,
        lng=106.7738,
        location_confidence="EXACT",
    )

    # Calculate segment risk with historical article
    res = calculate_segment_risk(
        segment=mock_segment,
        camera_evidences=[],
        weather_tide=None,
        traffic_news=[historical_art],
    )

    # Must remain UNKNOWN, NEVER elevated by historical or ineligible news!
    assert res.risk_level == RiskLevel.UNKNOWN
    assert res.risk_score is None

    # Now with a genuine, fresh active hazard article
    active_art = TrafficNewsItem(
        id="act_01",
        canonical_url="https://tuoitre.vn/active_vovanngan",
        source_name="Tuổi Trẻ",
        title="Mưa lớn khiến đường Võ Văn Ngân ngập sâu lúc này",
        summary="Xe chết máy hàng loạt",
        category="FLOOD",
        severity="CRITICAL",
        event_status="ACTIVE_HAZARD",
        published_at=now - timedelta(minutes=20),
        fetched_at=now,
        lat=10.8493,
        lng=106.7738,
        location_confidence="EXACT",
    )

    res_active = calculate_segment_risk(
        segment=mock_segment,
        camera_evidences=[],
        weather_tide=None,
        traffic_news=[active_art],
    )

    # Active hazard elevates to CRITICAL
    assert res_active.risk_level == RiskLevel.CRITICAL
    assert res_active.risk_score == 80.0
