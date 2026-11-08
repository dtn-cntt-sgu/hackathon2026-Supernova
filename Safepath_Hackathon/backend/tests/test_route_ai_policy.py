import importlib.util
from pathlib import Path
import sys

MODULE = Path(__file__).resolve().parents[1] / "app/services/route_ai_policy.py"
spec = importlib.util.spec_from_file_location("route_ai_policy_starter", MODULE)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def admitted(**kwargs):
    data = dict(
        enabled=True,
        ingestion_permitted=True,
        routing_evidence_permitted=True,
        active_route_expiry_epoch=1200,
        image_valid=True,
        image_retrieved_epoch=990,
        image_hash="hash-current",
        last_analyzed_image_hash="hash-prior",
        line_of_sight_verified=True,
        observed_way_matches_route=True,
    )
    data.update(kwargs)
    return module.route_ai_admission_reason(module.RouteAIAdmission(**data), now_epoch=1000)


def test_verified_active_route_allowed():
    assert admitted() == "ALLOW"


def test_monitor_never_triggers_inference_without_route_lease():
    assert admitted(active_route_expiry_epoch=None) == "NOT_ACTIVE_ROUTE_CAMERA"


def test_expired_route_lease_fails_closed():
    assert admitted(active_route_expiry_epoch=999) == "NOT_ACTIVE_ROUTE_CAMERA"


def test_permission_and_feature_flag_fail_closed():
    assert admitted(routing_evidence_permitted=False) == "EVIDENCE_PERMISSION_NOT_GRANTED"
    assert admitted(enabled=False) == "ROUTE_AI_DISABLED"


def test_dont_analyze_duplicate_or_bad_snapshot():
    assert admitted(last_analyzed_image_hash="hash-current") == "ALREADY_ANALYZED"
    assert admitted(image_retrieved_epoch=800) == "STALE_OR_UNKNOWN_IMAGE"
    assert admitted(image_valid=False) == "NO_VALID_IMAGE"


def test_unverified_camera_way_match_not_eligible():
    assert admitted(line_of_sight_verified=False) == "CAMERA_ROUTE_MATCH_UNVERIFIED"
    assert admitted(observed_way_matches_route=False) == "CAMERA_ROUTE_MATCH_UNVERIFIED"
