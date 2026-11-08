"""
AI Explanation and FastMCP Tool Provider for SafePathAI.
Provides:
- FastMCP tools for route evidence summary and hydrometeorological context.
- Mathematical-data-grounded route explanations (2-3 concise sentences in Vietnamese).
- Smart Template Fallback with sub-millisecond execution when LLM_API_KEY is not set or times out.
- LLM Integration (Gemini / OpenAI) strictly constrained to explaining computed facts (Rule #2).
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional
import httpx
from mcp.server.fastmcp import FastMCP

from backend.app.core.config import settings
from backend.app.db.session import get_redis_client
from backend.app.schemas.contracts import (
    CameraEvidence,
    RiskLevel,
    SafeRouteResponse,
    WeatherTideSignal,
)
from backend.app.services.weather_tide import get_cached_weather_tide

logger = logging.getLogger(__name__)

# Initialize FastMCP Server for SafePathAI
mcp_server = FastMCP("SafePathAI-Evidence-Explainer")


def extract_route_evidence_summary(route: SafeRouteResponse) -> Dict[str, Any]:
    """
    Synchronous helper to extract structured evidence from a SafeRouteResponse.
    """
    critical_segments = []
    moderate_segments = []
    all_cameras: Dict[str, Dict[str, Any]] = {}

    for seg in route.segments:
        seg_data = {
            "osm_way_id": seg.osm_way_id,
            "street_name": seg.street_name or "Đoạn đường đô thị",
            "risk_score": seg.risk_score,
            "risk_level": seg.risk_level.value,
        }
        if seg.risk_level == RiskLevel.CRITICAL:
            critical_segments.append(seg_data)
        elif seg.risk_level == RiskLevel.MODERATE:
            moderate_segments.append(seg_data)

        for cam in seg.evidence_cameras:
            if cam.cam_id not in all_cameras:
                all_cameras[cam.cam_id] = {
                    "cam_id": cam.cam_id,
                    "code": cam.code or "CAM",
                    "name": cam.name,
                    "district": cam.district or "",
                    "flood_ratio": cam.flood_ratio,
                    "traffic_density_score": cam.traffic_density_score,
                    "vehicle_count": cam.vehicle_count,
                    "risk_level": cam.risk_level.value,
                    "source_status": cam.source_status.value,
                }

    return {
        "route_id": route.route_id,
        "total_distance_km": route.total_distance_km,
        "estimated_time_mins": route.estimated_time_mins,
        "overall_risk": route.overall_risk.value,
        "critical_segment_count": len(critical_segments),
        "critical_segments": critical_segments,
        "moderate_segment_count": len(moderate_segments),
        "cameras": list(all_cameras.values()),
    }


@mcp_server.tool()
async def get_route_evidence_summary(route_id: str, total_distance_km: float, overall_risk: str) -> Dict[str, Any]:
    """
    MCP Tool: Returns high-level metadata and evidence status for a computed route.
    """
    return {
        "route_id": route_id,
        "total_distance_km": total_distance_km,
        "overall_risk": overall_risk,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@mcp_server.tool()
async def get_weather_tide_context() -> Dict[str, Any]:
    """
    MCP Tool: Retrieves current rainfall and tide levels in Ho Chi Minh City from cache.
    """
    redis_client = get_redis_client()
    try:
        cached_signal = await get_cached_weather_tide(redis_client=redis_client)
        if cached_signal:
            return cached_signal.model_dump(mode="json")
        return {
            "rain_mm_per_hour": None,
            "rain_status": "WEATHER_UNAVAILABLE",
            "rain_observed_at": None,
            "tide_level_meters": None,
            "tide_status": "TIDE_UNAVAILABLE",
            "is_high_tide_alert": None,
            "timestamp": None,
            "source_url": None,
        }
    finally:
        await redis_client.aclose()


def build_template_explanation(
    recommended_route: SafeRouteResponse,
    alternative_routes: List[SafeRouteResponse],
    weather: Optional[WeatherTideSignal] = None,
) -> str:
    """Explain only OSRM metrics and validated, fresh observations."""
    street = next((s.street_name for s in recommended_route.segments if s.street_name), "tuyến đã chọn")
    sentences = [
        f"Tuyến qua {street} dài {recommended_route.total_distance_km:.1f} km, "
        f"thời gian OSRM ước tính {recommended_route.estimated_time_mins:.0f} phút."
    ]
    if recommended_route.overall_risk == RiskLevel.UNKNOWN:
        sentences.append("Chưa có đủ quan trắc đã xác minh cho toàn tuyến; mức rủi ro hiện chưa xác định.")
    elif recommended_route.overall_risk in (RiskLevel.MODERATE, RiskLevel.CRITICAL):
        sentences.append("Một số đoạn có tín hiệu rủi ro đã ghi nhận; hãy xem chi tiết từng đoạn trước khi đi.")
    else:
        sentences.append("Các quan trắc hiện có cho thấy rủi ro thấp tại những đoạn đã kiểm định; điều kiện có thể thay đổi.")

    now = datetime.now(timezone.utc)
    for alt in alternative_routes:
        for segment in alt.segments:
            for cam in segment.evidence_cameras:
                age = (now - cam.updated_at).total_seconds() if cam.updated_at.tzinfo else float("inf")
                if (
                    cam.flood_ratio is not None and cam.flood_ratio > 0
                    and cam.evidence_eligibility == "ROUTING_ELIGIBLE"
                    and cam.source_status == "LIVE" and 0 <= age <= 120
                    and cam.spatial_match_status == "OBSERVED_SEGMENT_VERIFIED"
                ):
                    code = cam.code or cam.name
                    sentences.append(f"Camera {code} trên đường khác ghi nhận {round(cam.flood_ratio * 100)}% pixel vùng đường nghi là nước; tỷ lệ này không cho biết độ sâu.")
                    return " ".join(sentences)

    if weather and weather.rain_status == "LIVE" and weather.rain_observed_at and weather.source_url:
        observed = weather.rain_observed_at
        if observed.tzinfo and 0 <= (now - observed).total_seconds() <= 900 and weather.rain_mm_per_hour is not None:
            sentences.append(f"Bản tin mưa gần nhất: {weather.rain_mm_per_hour:.1f} mm/giờ.")
    return " ".join(sentences)


async def _call_llm_for_explanation(
    prompt_payload: Dict[str, Any],
    api_key: str,
    timeout_sec: float = 2.5,
) -> Optional[str]:
    """
    Calls Gemini API (or OpenAI API if key starts with sk-) to synthesize 2-3 sentences.
    Enforces a strict timeout of 2.5 seconds.
    """
    system_instruction = (
        "Bạn là trợ lý AI định hướng an toàn giao thông SafePathAI tại TP.HCM. "
        "Nhiệm vụ của bạn là viết đúng 2 đến 3 câu ngắn gọn, súc tích bằng tiếng Việt cho người lái xe. "
        "Tuyệt đối KHÔNG thay đổi lộ trình. Chỉ giải thích lý do thuật toán chọn tuyến đường dựa trên "
        "các số liệu thực tế được cung cấp (tên đường, khoảng cách, % ngập nước, số xe đếm được tại mã camera)."
    )
    user_content = json.dumps(prompt_payload, ensure_ascii=False)

    async with httpx.AsyncClient(timeout=timeout_sec) as client:
        # 1. Google Gemini API
        if api_key.startswith("AIza") or len(api_key) == 39:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
            body = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {"text": f"{system_instruction}\n\nDữ liệu quan trắc thực tế:\n{user_content}"}
                        ],
                    }
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 256,
                },
            }
            resp = await client.post(url, json=body)
            if resp.status_code == 200:
                data = resp.json()
                text = (
                    data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                    .strip()
                )
                if text:
                    return text

        # 2. OpenAI API
        elif api_key.startswith("sk-"):
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}"}
            body = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": f"Dữ liệu quan trắc thực tế:\n{user_content}"},
                ],
                "temperature": 0.2,
                "max_tokens": 256,
            }
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code == 200:
                data = resp.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if text:
                    return text

    return None


async def generate_route_explanation(
    recommended_route: SafeRouteResponse,
    alternative_routes: List[SafeRouteResponse],
    weather: Optional[WeatherTideSignal] = None,
) -> str:
    """
    Main entrypoint for generating route explanations.
    Combines:
    1. Deterministic template generation (Baseline & Fast Fallback).
    2. Optional LLM refinement if LLM_API_KEY is configured and responds within 2.5 seconds.
    """
    # 1. Compute baseline factual explanation
    baseline_explanation = build_template_explanation(
        recommended_route=recommended_route,
        alternative_routes=alternative_routes,
        weather=weather,
    )

    # Free-form LLM output cannot be proven to preserve these evidence boundaries.
    # Keep route explanations deterministic until a claim-level verifier is available.
    return baseline_explanation

