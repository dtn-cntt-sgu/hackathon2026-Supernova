"""Arithmetic regressions with labelled fixtures; no Google accuracy or production data claim."""
from datetime import datetime, timezone
import pytest
from backend.app.schemas.contracts import RouteSegmentRisk, RiskLevel, TrafficStatus
from backend.app.services.routing import calculate_hcmc_route_eta

NIGHT = datetime(2026, 11, 9, 16, 0, tzinfo=timezone.utc)  # 23:00 ICT
PEAK = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)  # 17:00 ICT


def speed_segment(speed=60., length=1000., covered=1000., **changes):
    values = dict(length_meters=length, osrm_duration_seconds=120., risk_level=RiskLevel.UNKNOWN,
                  traffic_status=TrafficStatus.FREE_FLOW, traffic_observed_length_meters=covered,
                  observed_speed_kmh=speed, free_flow_speed_kmh=60., traffic_confidence=.9,
                  traffic_freshness_seconds=20., traffic_segment_match_status="CORRIDOR_MATCHED",
                  traffic_delay_seconds=9999., maneuver_type="turn")
    values.update(changes)
    return RouteSegmentRisk(**values)


def eta(segments, distance=1000., duration=120., when=NIGHT, mode="CAR"):
    return calculate_hcmc_route_eta(segments, distance, duration, mode, departure_dt=when,
                                  has_live_corridor_provider=True, provider_name="test_provider")


@pytest.mark.parametrize("mode", ["CAR", "MOTORCYCLE"])
@pytest.mark.parametrize("speed,seconds", [(60.,60.), (30.,120.), (1.,3600.), (120.,30.)])
def test_covered_time_is_actual_distance_over_speed_without_penalties_or_clamps(mode, speed, seconds):
    result = eta([speed_segment(speed)], mode=mode, when=PEAK)
    assert result["estimated_duration_seconds"] == seconds
    assert result["covered_distance_m"] == 1000
    assert result["is_live_traffic"]
    assert result["eta_breakdown"].intersection_delay_seconds == 0
    assert result["eta_breakdown"].environmental_delay_seconds == 0
    assert result["estimated_duration_seconds"] == pytest.approx(result["baseline_duration_seconds"] + result["traffic_delay_seconds"])


def test_partial_speed_replaces_only_covered_osrm_time_and_peak_applies_only_to_rest():
    result = eta([speed_segment(60., covered=500.)], when=PEAK)
    assert result["estimated_duration_seconds"] == pytest.approx(30 + 60 * 1.64)
    assert result["covered_distance_m"] == 500
    assert result["eta_breakdown"].confidence == pytest.approx(.45)
    assert result["eta_source"].endswith("PARTIAL")


@pytest.mark.parametrize("changes", [
    {"observed_speed_kmh":0}, {"observed_speed_kmh":float("nan")}, {"observed_speed_kmh":161},
    {"traffic_confidence":None}, {"traffic_confidence":.29}, {"traffic_freshness_seconds":None},
    {"traffic_freshness_seconds":301}, {"traffic_freshness_seconds":-1},
    {"traffic_segment_match_status":"UNMATCHED"}, {"traffic_observed_length_meters":None},
    {"is_closed":True}, {"traffic_status":TrafficStatus.CLOSED},
])
def test_invalid_speed_support_falls_back_without_claiming_live_eta(changes):
    result = eta([speed_segment(**changes)])
    assert result["estimated_duration_seconds"] == 120
    assert not result["is_live_traffic"]
    assert result["covered_distance_m"] == 0
    assert result["duration_in_traffic_seconds"] is None
    assert result["eta_breakdown"].confidence == 0


def test_density_only_camera_does_not_manufacture_speed_or_live_eta():
    result = eta([speed_segment(observed_speed_kmh=None, traffic_status=TrafficStatus.CONGESTED,
                               traffic_estimation_method="CAMERA_VIEW_OCCUPANCY")])
    assert result["estimated_duration_seconds"] == 120
    assert result["traffic_status"] == TrafficStatus.CONGESTED  # Warning is preserved.
    assert not result["is_live_traffic"]


def test_risk_and_signal_counts_cannot_change_measured_eta():
    normal = eta([speed_segment()])
    hazard = eta([speed_segment(risk_level=RiskLevel.CRITICAL)])
    assert hazard["estimated_duration_seconds"] == normal["estimated_duration_seconds"] == 60


def test_uncovered_baseline_responds_to_osrm_and_preserves_relative_step_duration():
    segments = [speed_segment(60., length=500., covered=500., osrm_duration_seconds=30.),
                speed_segment(length=500., covered=0., osrm_duration_seconds=90.)]
    assert eta(segments)["estimated_duration_seconds"] == 120  # 30 measured + 90 uncovered
    assert eta(segments, duration=240.)["estimated_duration_seconds"] == 210  # 30 + 180


def test_motorized_flow_does_not_affect_walking_or_claim_walk_traffic_coverage():
    result = eta([speed_segment()], mode="WALKING", when=PEAK)
    assert result["estimated_duration_seconds"] == 750
    assert not result["is_live_traffic"] and result["covered_distance_m"] == 0
    assert result["eta_source"] == "WALKING_DISTANCE_ESTIMATE"


def test_empty_segment_and_zero_distance_baselines_stay_finite():
    assert eta([], distance=0, duration=0)["estimated_duration_seconds"] == 0
    assert eta([])["estimated_duration_seconds"] == 120
