"""
SafePathAI Traffic News NLP Classifier (Zero-Mock Runtime).
Implements phrase-based matching across 7 traffic keyword groups, Vietnamese normalization,
negation detection, temporal status extraction (ACTIVE_HAZARD, FORECAST, HISTORICAL, RECOVERED, UNVERIFIED),
and infrastructure milestone filtering without hallucinations or false positives.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("safepath.news.classifier")

# 1. Official Standard Traffic Keywords Groups
TRAFFIC_KEYWORDS: Dict[str, List[str]] = {
    "FLOOD": [
        "ngập nước", "ngập sâu", "ngập cục bộ",
        "ngập úng", "đường ngập", "triều cường",
        "nước dâng", "nước tràn", "ngập bánh xe",
        "điểm ngập", "thoát nước chậm",
        "trận ngập", "ngập nặng", "ngập lịch sử",
    ],
    "CONGESTION": [
        "kẹt xe", "ùn tắc", "ùn ứ", "tắc đường",
        "kẹt cứng", "dòng xe nối đuôi",
        "xe xếp hàng dài", "giao thông tê liệt",
        "lưu thông chậm", "kẹt xe kéo dài",
    ],
    "ACCIDENT": [
        "tai nạn giao thông", "va chạm",
        "tai nạn liên hoàn", "xe lật",
        "xe cháy", "xe chết máy", "xe hỏng",
        "chướng ngại vật", "cây đổ",
        "sụt lún", "sạt lở",
        "xe tải lật", "xe múc lật", "lật ngửa", "lật xe",
        "hỏng máy", "chết máy", "vụ tai nạn", "tai nạn",
    ],
    "ROAD_CLOSURE": [
        "cấm đường", "phong tỏa",
        "đóng cầu", "hạn chế lưu thông",
        "tạm ngưng lưu thông", "cấm xe",
    ],
    "CONSTRUCTION": [
        "thi công", "rào chắn", "lô cốt",
        "đào đường", "sửa đường",
        "phân luồng", "điều tiết giao thông",
    ],
    "WEATHER_CONTEXT": [
        "mưa lớn", "mưa kéo dài",
        "mưa dông", "mưa cực đoan",
        "áp thấp nhiệt đới",
    ],
    "RECOVERY": [
        "nước rút", "hết ngập",
        "thông xe trở lại", "thông đường",
        "giải tỏa ùn tắc", "lưu thông bình thường",
    ],
}

# 2. Negation patterns (must precede or directly qualify keyword phrases)
NEGATION_WORDS: List[str] = [
    "không", "chưa", "chẳng", "không còn", "không bị", "không có", "không xảy ra",
    "hết", "chấm dứt", "đã rút", "tránh", "ngăn ngừa", "phòng ngừa", "chống",
    "bớt", "hạn chế tối đa",
]

# 3. Infrastructure Milestones & Benign Civil Works (NOT active disruption hazards)
INFRASTRUCTURE_MILESTONES: List[str] = [
    "hợp long", "khánh thành", "khởi công", "thông xe cầu", "thông xe hầm",
    "hoàn thành", "vốn đầu tư", "hình hài", "thiết kế dự án", "đề xuất xây",
    "chuẩn bị thông xe", "đẩy nhanh tiến độ", "về đích", "công trình trọng điểm",
    "nghiệm thu", "chính thức thông xe", "thông xe",
]

# 4. Temporal Classification Markers
FORECAST_MARKERS: List[str] = [
    "dự báo", "dự kiến", "khả năng sẽ", "có thể xảy ra", "có thể ngập",
    "cảnh báo đợt triều cường", "sắp có", "từ ngày mai", "vào cuối tuần",
    "trong những ngày tới", "chuẩn bị đón", "dự báo thời tiết", "kịch bản",
    "dự kiến từ", "sẽ có mưa", "nguy cơ ngập", "chuẩn bị phân luồng",
    "rạng sáng mai", "sáng mai", "ngày mai", "từ ngày", "vào ngày", "sắp tới",
]

HISTORICAL_MARKERS: List[str] = [
    "từng ngập", "trước đây", "hồi năm", "năm ngoái", "vừa qua", "đã từng",
    "tháng trước", "hồi tháng", "quá khứ", "lịch sử", "nhìn lại", "đã xảy ra vào",
    "hôm qua đã", "tuần trước", "vụ việc xảy ra", "sau khi xảy ra",
    "năm 2020", "năm 2021", "năm 2022", "năm 2023", "trước ngày", "ngập lịch sử",
]

RECOVERY_MARKERS: List[str] = [
    "nước rút", "hết ngập", "thông xe trở lại", "thông đường", "giải tỏa ùn tắc",
    "lưu thông bình thường", "lưu thông ổn định", "đã dỡ bỏ rào chắn",
    "đã khắc phục xong", "trở lại bình thường", "đã thông tuyến", "không còn ngập",
    "nước đã rút", "được kéo đi", "đã giải tỏa",
]

UNVERIFIED_POLICY_MARKERS: List[str] = [
    "đề xuất", "nghiên cứu", "họp bàn", "kiến nghị", "chuyên gia hiến kế",
    "thí điểm", "lấy ý kiến", "băn khoăn", "kêu gọi", "bàn giải pháp",
    "bài toán", "hội thảo", "kinh nghiệm", "nhận định",
]

# 5. Trap phrases that contain words like "cầu", "xe", "đường" but are NOT traffic incidents
FALSE_POSITIVE_TRAPS: List[str] = [
    "cầu truyền hình", "cầu lông", "cầu nối", "cầu khỉ", "cầu mong", "cầu nguyện",
    "xe hoa", "xe cứu thương làm nhiệm vụ", "đường hoa", "đường sách",
    "con đường âm nhạc", "đường tình", "đường dây", "đường biên",
    "cây cầu nhân ái", "cây cầu ước mơ",
]


@dataclass
class ArticleClassification:
    category: str  # FLOOD, CONGESTION, ACCIDENT, ROAD_CLOSURE, CONSTRUCTION, WEATHER_CONTEXT, RECOVERY, DỰ ÁN / HẠ TẦNG, GENERAL_NEWS
    temporal_status: str  # ACTIVE_HAZARD, FORECAST, HISTORICAL, RECOVERED, UNVERIFIED
    severity: str  # INFO, WARNING, CRITICAL
    primary_keyword: Optional[str] = None
    matched_keywords: List[str] = field(default_factory=list)
    is_negated: bool = False
    is_milestone: bool = False
    is_forecast: bool = False
    is_historical: bool = False
    is_recovery: bool = False
    is_trap: bool = False
    confidence: float = 0.0
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "temporal_status": self.temporal_status,
            "severity": self.severity,
            "primary_keyword": self.primary_keyword,
            "matched_keywords": self.matched_keywords,
            "is_negated": self.is_negated,
            "is_milestone": self.is_milestone,
            "is_forecast": self.is_forecast,
            "is_historical": self.is_historical,
            "is_recovery": self.is_recovery,
            "confidence": self.confidence,
            "explanation": self.explanation,
        }


def normalize_vietnamese_text(text: str) -> str:
    """
    Normalizes Vietnamese unicode into NFC form, converts to lower case,
    and replaces extraneous punctuation/whitespaces while preserving word breaks.
    """
    if not text:
        return ""
    # NFC normalization
    nfc_text = unicodedata.normalize("NFC", text.strip())
    # Lowercase
    lowered = nfc_text.lower()
    # Normalize hyphens and dashes
    cleaned = re.sub(r"[\u2010-\u2015\u2212]", "-", lowered)
    # Remove multiple spaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def is_phrase_negated(text: str, phrase: str, window_words: int = 4) -> bool:
    """
    Checks if a matched keyword phrase is preceded by a negation word
    within a small word window in the same sentence or clause.
    """
    idx = text.find(phrase)
    if idx == -1:
        return False

    prefix = text[:idx].strip()
    if not prefix:
        return False

    # Stop at clause boundaries like comma, semicolon, period, or dash
    last_punct = max(
        prefix.rfind(","),
        prefix.rfind(";"),
        prefix.rfind("."),
        prefix.rfind("-"),
        prefix.rfind("!"),
    )
    if last_punct != -1:
        prefix = prefix[last_punct + 1:].strip()

    tokens = prefix.split()
    preceding_words = tokens[-window_words:] if len(tokens) >= window_words else tokens
    preceding_phrase = " ".join(preceding_words)

    for neg in NEGATION_WORDS:
        # Check if negation appears at the end of preceding words
        if preceding_phrase.endswith(neg) or f" {neg} " in f" {preceding_phrase} ":
            return True

    return False


def classify_traffic_headline(
    title: str,
    description: str = "",
    published_at: Optional[datetime] = None,
) -> ArticleClassification:
    """
    Accurately classifies a Vietnamese traffic news title and summary into
    category, temporal status, and severity according to SafePathAI Zero-Mock rules.
    """
    norm_title = normalize_vietnamese_text(title)
    norm_desc = normalize_vietnamese_text(description)
    full_text = f"{norm_title} {norm_desc}".strip()

    # Rule 2 check: Check for non-traffic trap phrases (e.g. "cầu truyền hình", "xe hoa", "đường hoa")
    for trap in FALSE_POSITIVE_TRAPS:
        if trap in full_text:
            return ArticleClassification(
                category="GENERAL_NEWS",
                temporal_status="UNVERIFIED",
                severity="INFO",
                is_trap=True,
                confidence=0.95,
                explanation=f"Tiêu đề chứa cụm từ phi giao thông: '{trap}'.",
            )

    # Check for Infrastructure milestones (e.g. "hợp long", "khánh thành", "khởi công")
    # Exception: "thông xe trở lại" is a recovery marker, not a new milestone
    milestone_matches = [m for m in INFRASTRUCTURE_MILESTONES if m in full_text and "thông xe trở lại" not in full_text]
    if milestone_matches:
        # Check if it also specifically mentions a severe current accident/collapse
        if not any(acc in full_text for acc in ["sập cầu", "cháy xe", "tai nạn chết người"]):
            is_hist = any(h in full_text for h in ["hoàn thành", "khánh thành", "hợp long", "thông xe", "hình hài", "nghiệm thu", "chính thức thông xe"])
            return ArticleClassification(
                category="DỰ ÁN / HẠ TẦNG",
                temporal_status="HISTORICAL" if is_hist else "UNVERIFIED",
                severity="INFO",
                is_milestone=True,
                primary_keyword=milestone_matches[0],
                matched_keywords=milestone_matches,
                confidence=0.95,
                explanation=f"Sự kiện hạ tầng/cột mốc dự án: '{milestone_matches[0]}'. Không phải sự cố giao thông.",
            )

    # Check for Recovery markers (e.g. "nước rút", "hết ngập", "thông xe trở lại")
    recovery_matches = [r for r in RECOVERY_MARKERS if r in full_text]

    # Check for Forecast markers (e.g. "dự báo", "dự kiến", "cảnh báo triều cường")
    forecast_matches = [f for f in FORECAST_MARKERS if f in full_text]

    # Check for Historical markers (e.g. "từng ngập", "năm ngoái", "trước đây")
    historical_matches = [h for h in HISTORICAL_MARKERS if h in full_text]

    # Check for Policy / Academic / Proposal discussions
    policy_matches = [p for p in UNVERIFIED_POLICY_MARKERS if p in full_text]

    # Keyword Group Matching across TRAFFIC_KEYWORDS
    group_hits: Dict[str, List[str]] = {}
    negated_hits: Dict[str, List[str]] = {}

    for group, keywords in TRAFFIC_KEYWORDS.items():
        for kw in keywords:
            if kw in full_text:
                if is_phrase_negated(full_text, kw):
                    negated_hits.setdefault(group, []).append(kw)
                else:
                    group_hits.setdefault(group, []).append(kw)

    # If recovery keywords matched without active hazard or if active hazard is negated into recovery
    if "RECOVERY" in group_hits or recovery_matches:
        active_rec = group_hits.get("RECOVERY", []) or recovery_matches
        return ArticleClassification(
            category="RECOVERY",
            temporal_status="RECOVERED",
            severity="INFO",
            is_recovery=True,
            primary_keyword=active_rec[0],
            matched_keywords=active_rec,
            confidence=0.92,
            explanation=f"Tình trạng đã giải tỏa/hồi phục bình thường: '{active_rec[0]}'.",
        )

    # If all matches were negated (e.g. "không ngập", "không có ùn tắc", "chưa xảy ra tai nạn")
    if negated_hits and not group_hits:
        first_group = list(negated_hits.keys())[0]
        first_kw = negated_hits[first_group][0]
        return ArticleClassification(
            category=first_group,
            temporal_status="RECOVERED",
            severity="INFO",
            is_negated=True,
            primary_keyword=first_kw,
            matched_keywords=negated_hits[first_group],
            confidence=0.90,
            explanation=f"Hiện tượng bị phủ định: 'không/chưa {first_kw}'. Không có sự cố.",
        )

    # Determine primary category based on priority: FLOOD > ACCIDENT > ROAD_CLOSURE > CONGESTION > CONSTRUCTION > WEATHER_CONTEXT
    priority_order = ["FLOOD", "ACCIDENT", "ROAD_CLOSURE", "CONGESTION", "CONSTRUCTION", "WEATHER_CONTEXT"]
    primary_category = "TIN GIAO THÔNG CHUNG"
    matched_kws: List[str] = []

    for cat in priority_order:
        if cat in group_hits:
            primary_category = cat
            matched_kws = group_hits[cat]
            break

    # If no traffic keywords matched at all
    if primary_category == "TIN GIAO THÔNG CHUNG":
        return ArticleClassification(
            category="TIN GIAO THÔNG CHUNG",
            temporal_status="UNVERIFIED",
            severity="INFO",
            confidence=0.75,
            explanation="Không phát hiện cụm từ sự cố giao thông cụ thể.",
        )

    # Determine Temporal Status
    # 1. Forecast priority
    if forecast_matches and not any(now_marker in full_text for now_marker in ["đang ngập", "đang kẹt cứng", "vừa xảy ra"]):
        return ArticleClassification(
            category=primary_category,
            temporal_status="FORECAST",
            severity="WARNING" if primary_category in ("FLOOD", "ROAD_CLOSURE") else "INFO",
            primary_keyword=matched_kws[0],
            matched_keywords=matched_kws,
            is_forecast=True,
            confidence=0.92,
            explanation=f"Tin dự báo/cảnh báo tương lai: '{forecast_matches[0]}'.",
        )

    # 2. Historical priority
    if historical_matches and not any(now_marker in full_text for now_marker in ["đang", "hiện nay", "lúc này"]):
        return ArticleClassification(
            category=primary_category,
            temporal_status="HISTORICAL",
            severity="INFO",
            primary_keyword=matched_kws[0],
            matched_keywords=matched_kws,
            is_historical=True,
            confidence=0.90,
            explanation=f"Tin lịch sử/hồi tưởng quá khứ: '{historical_matches[0]}'.",
        )

    # 3. Policy / General discussion priority
    if policy_matches and not any(now_marker in full_text for now_marker in ["đang kẹt", "đang ngập", "tê liệt"]):
        return ArticleClassification(
            category=primary_category,
            temporal_status="UNVERIFIED",
            severity="INFO",
            primary_keyword=matched_kws[0],
            matched_keywords=matched_kws,
            confidence=0.88,
            explanation=f"Thảo luận/đề xuất giải pháp chính sách: '{policy_matches[0]}'.",
        )

    # 4. Pure Weather Context without road hazard
    if primary_category == "WEATHER_CONTEXT":
        return ArticleClassification(
            category="WEATHER_CONTEXT",
            temporal_status="UNVERIFIED",
            severity="INFO",
            primary_keyword=matched_kws[0],
            matched_keywords=matched_kws,
            confidence=0.85,
            explanation="Thông tin bối cảnh thời tiết chung, chưa ghi nhận ngập hoặc tai nạn cụ thể.",
        )

    # 5. Active Hazard (Verified Ongoing Event)
    severity = "CRITICAL" if primary_category in ("FLOOD", "ACCIDENT") else "WARNING"
    return ArticleClassification(
        category=primary_category,
        temporal_status="ACTIVE_HAZARD",
        severity=severity,
        primary_keyword=matched_kws[0],
        matched_keywords=matched_kws,
        confidence=0.94,
        explanation=f"Sự cố giao thông đang diễn ra: '{matched_kws[0]}'.",
    )
