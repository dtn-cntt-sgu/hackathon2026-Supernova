import test from "node:test";
import assert from "node:assert/strict";
import { instructionForStep, isVerifiedRouteAlert } from "../src/lib/navigation.ts";

test("OSRM maneuver text retains direction and measured step distance", () => {
  assert.equal(instructionForStep({ maneuver_type: "turn", maneuver_modifier: "right", street_name: "Điện Biên Phủ", length_meters: 152.2 }), "Rẽ phải vào Điện Biên Phủ, đi 152 m.");
  assert.equal(instructionForStep({ maneuver_type: "unknown", maneuver_modifier: "right", length_meters: 100 }), null);
});

test("spoken alerts require fresh confirmed evidence on an unpassed route step", () => {
  const now = Date.now();
  const camera = {
    cam_id: "verified-1", source_status: "LIVE", risk_level: "CRITICAL",
    evidence_eligibility: "ROUTING_ELIGIBLE", spatial_match_status: "OBSERVED_SEGMENT_VERIFIED",
    line_of_sight_verified: true, coordinate_source_url: "https://example.com/gps",
    view_verification_source_url: "https://example.com/view", observed_osm_way_id: 42,
    updated_at: new Date(now - 30000).toISOString(),
  };
  const route = { segments: [{ evidence_cameras: [camera] }, { evidence_cameras: [] }] };
  const alert = {
    event_id: "event-1", type: "CRITICAL_FLOOD_ALERT", severity: "CRITICAL",
    source: "camera_vision:ONNX", cam_id: "verified-1", risk_level: "CRITICAL",
    observed_at: new Date(now - 10000).toISOString(), expiry: new Date(now + 60000).toISOString(), message: "Ngập trên tuyến",
  };
  assert.equal(isVerifiedRouteAlert(alert, route, now), true);
  assert.equal(isVerifiedRouteAlert(alert, route, now, 1), false);
  assert.equal(isVerifiedRouteAlert({ ...alert, cam_id: "other-camera" }, route, now), false);
  assert.equal(isVerifiedRouteAlert({ ...alert, observed_at: new Date(now - 121000).toISOString() }, route, now), false);
  assert.equal(isVerifiedRouteAlert({ ...alert, expiry: new Date(now - 1).toISOString() }, route, now), false);
  assert.equal(isVerifiedRouteAlert({ ...alert, source: "unverified" }, route, now), false);
  assert.equal(isVerifiedRouteAlert(alert, { segments: [{ evidence_cameras: [{ ...camera, evidence_eligibility: "NOT_VERIFIED_FOR_ROUTING" }] }] }, now), false);
  assert.equal(isVerifiedRouteAlert(alert, { segments: [{ evidence_cameras: [{ ...camera, source_status: "STALE" }] }] }, now), false);
});
