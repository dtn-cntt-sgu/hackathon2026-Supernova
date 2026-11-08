import test from "node:test";
import assert from "node:assert/strict";
import { cameraObservationStatus, currentRain, currentTide, hasVerifiedFloodObservation } from "../src/lib/observations.ts";

const now = Date.parse("2026-10-24T02:00:00+07:00");
const recent = new Date(now - 60000).toISOString();
test("a recent download without capture time is never a live observation", () => {
  const camera = { has_image: true, source_status: "LIVE", retrieved_at: recent, updated_at: recent };
  assert.equal(cameraObservationStatus(camera, now), "RECENTLY_RETRIEVED_CAPTURE_UNKNOWN");
  assert.equal(cameraObservationStatus({ ...camera, captured_at: recent }, now), "LIVE_VERIFIED");
  assert.equal(cameraObservationStatus({ ...camera, captured_at: recent }, now + 1800000), "STALE");
  assert.equal(cameraObservationStatus({ ...camera, has_image: false }, now), "OFFLINE");
  assert.equal(cameraObservationStatus({ ...camera, source_status: "SIMULATED" }, now), "UNAVAILABLE");
});
test("missing and expired weather cannot become zero or borrow another signal's timestamp", () => {
  assert.equal(currentRain(null, now), null);
  const weather = { rain_status: "LIVE", rain_mm_per_hour: 0, rain_observed_at: recent, source_url: "https://api.open-meteo.com/v1/forecast", tide_status: "LIVE", tide_level_meters: 1.5, timestamp: recent };
  assert.equal(currentRain(weather, now), 0);
  assert.equal(currentRain(weather, now + 900000), null);
  assert.equal(currentTide(weather, now), null);
  assert.equal(currentTide({ ...weather, tide_observed_at: recent, tide_source_url: "https://example.org/bulletin" }, now), 1.5);
});
test("water layer rejects a ratio without fresh, model-verified, road-matched evidence", () => {
  const camera = { has_image: true, source_status: "LIVE", captured_at: recent, flood_ratio: .4 };
  assert.equal(hasVerifiedFloodObservation(camera, now), false);
  const verified = { ...camera, flood_model_status: "VERIFIED_ONNX_INFERENCE", evidence_eligibility: "ROUTING_ELIGIBLE", spatial_match_status: "OBSERVED_SEGMENT_VERIFIED", line_of_sight_verified: true, coordinate_source_url: "https://example.org/gps", view_verification_source_url: "https://example.org/view" };
  assert.equal(hasVerifiedFloodObservation(verified, now), true);
  assert.equal(hasVerifiedFloodObservation({ ...verified, captured_at: null }, now), false);
  assert.equal(hasVerifiedFloodObservation({ ...verified, flood_ratio: null }, now), false);
});
