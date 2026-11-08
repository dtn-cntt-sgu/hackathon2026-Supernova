"""Fail-closed admission policy for on-demand camera AI in SafePath routing.

This is a policy helper, not a replacement for the existing vision worker.
It must be integrated at BOTH the enqueue and worker-consume boundaries.
Actual risk eligibility is stricter and belongs to SafePath's risk engine.
"""
from dataclasses import dataclass
from typing import Optional
import time


@dataclass(frozen=True)
class RouteAIAdmission:
    enabled: bool
    ingestion_permitted: bool
    routing_evidence_permitted: bool
    active_route_expiry_epoch: Optional[float]
    image_valid: bool
    image_retrieved_epoch: Optional[float]
    image_hash: Optional[str]
    last_analyzed_image_hash: Optional[str]
    line_of_sight_verified: bool
    observed_way_matches_route: bool


def route_ai_admission_reason(
    camera: RouteAIAdmission,
    *,
    now_epoch: Optional[float] = None,
    max_frame_age_seconds: float = 120.0,
) -> str:
    """Return ALLOW or a reason why inference must not be scheduled.

    A retrieved image is not enough to claim capture-time freshness or SAFE risk.
    The downstream risk engine must independently verify evidence eligibility.
    """
    now = time.time() if now_epoch is None else now_epoch
    if not camera.enabled:
        return "ROUTE_AI_DISABLED"
    if not (camera.ingestion_permitted and camera.routing_evidence_permitted):
        return "EVIDENCE_PERMISSION_NOT_GRANTED"
    if camera.active_route_expiry_epoch is None or camera.active_route_expiry_epoch <= now:
        return "NOT_ACTIVE_ROUTE_CAMERA"
    if not (camera.line_of_sight_verified and camera.observed_way_matches_route):
        return "CAMERA_ROUTE_MATCH_UNVERIFIED"
    if not camera.image_valid or not camera.image_hash:
        return "NO_VALID_IMAGE"
    age = None if camera.image_retrieved_epoch is None else now - camera.image_retrieved_epoch
    if age is None or not 0 <= age <= max_frame_age_seconds:
        return "STALE_OR_UNKNOWN_IMAGE"
    if camera.image_hash == camera.last_analyzed_image_hash:
        return "ALREADY_ANALYZED"
    return "ALLOW"
