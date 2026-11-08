/**
 * Presentation helpers for timestamped observations.
 *
 * Safety rules:
 * - Never manufacture rainfall, tidal levels, camera frames, or water evidence.
 * - "LIVE" requires a real, fresh, source-verified capture timestamp.
 * - A cached or inaccessible frame is not proof of current road safety.
 */
import type {
  CameraEvidence,
  WeatherTideSignal,
} from "../types/contracts";

const CAMERA_TTL_MS = 10 * 60 * 1000; // Backend CAMERA_IMAGE_TTL_SECONDS = 600 (10 minutes target cycle)
const CLOCK_SKEW_MS = 60 * 1000;

function epoch(value?: string | null): number | null {
  if (!value) return null;
  const milliseconds = Date.parse(value);
  return Number.isFinite(milliseconds) ? milliseconds : null;
}

/** Format a provider timestamp in Vietnam local time, or show unknown explicitly. */
export function observationTime(value?: string | null): string {
  const at = epoch(value);
  if (at === null) return "—";
  return new Intl.DateTimeFormat("vi-VN", {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(at));
}

/** Only return measured, currently available rain rates; never substitute zero. */
export function currentRain(
  weather: WeatherTideSignal | null | undefined,
  now: number = Date.now()
): number | null {
  if (weather?.rain_status !== "LIVE") return null;
  const value = weather.rain_mm_per_hour;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
  const observed = epoch(weather.rain_observed_at);
  if (observed === null || !weather.source_url || observed > now + CLOCK_SKEW_MS || now - observed > 15 * 60 * 1000) return null;
  return value;
}

/** Tide is unknown until the source publishes a verified current bulletin. */
export function currentTide(
  weather: WeatherTideSignal | null | undefined,
  now: number = Date.now()
): number | null {
  if (weather?.tide_status !== "LIVE") return null;
  const value = weather.tide_level_meters;
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const observed = epoch(weather.tide_observed_at);
  if (observed === null || !weather.tide_source_url || observed > now + CLOCK_SKEW_MS || now - observed > 4 * 60 * 60 * 1000) return null;
  return value;
}

export type CameraObservationStatus =
  | "LIVE_VERIFIED"
  | "RECENTLY_RETRIEVED_CAPTURE_UNKNOWN"
  | "STALE"
  | "OFFLINE"
  | "RESTRICTED"
  | "PLACEHOLDER"
  | "UNAVAILABLE";

/**
 * Derives true provenance & freshness lifecycle.
 * Safety Rule: Never use LIVE if captured_at is unverified!
 */
export function cameraObservationStatus(
  camera: CameraEvidence | null | undefined,
  now: number = Date.now()
): CameraObservationStatus {
  if (camera?.source_status === "SIMULATED") {
    return "UNAVAILABLE";
  }
  if (!camera?.has_image) {
    if (camera?.image_access_status === "EXTERNAL_ACCESS_RESTRICTED" || camera?.freshness_status === "RESTRICTED") {
      return "RESTRICTED";
    }
    if (camera?.image_status_reason?.includes("PLACEHOLDER") || camera?.freshness_status === "PLACEHOLDER") {
      return "PLACEHOLDER";
    }
    return "OFFLINE";
  }

  // Explicit freshness status from backend
  if (camera.freshness_status) {
    if (camera.freshness_status === "LIVE_VERIFIED") return "LIVE_VERIFIED";
    if (camera.freshness_status === "RECENTLY_RETRIEVED_CAPTURE_UNKNOWN") return "RECENTLY_RETRIEVED_CAPTURE_UNKNOWN";
    if (camera.freshness_status === "RESTRICTED") return "RESTRICTED";
    if (camera.freshness_status === "PLACEHOLDER") return "PLACEHOLDER";
    if (camera.freshness_status === "STALE") return "STALE";
    if (camera.freshness_status === "OFFLINE") return "OFFLINE";
  }

  const captured = epoch(camera.captured_at);
  if (captured !== null) {
    if (captured > now + CLOCK_SKEW_MS || now - captured > CAMERA_TTL_MS) {
      return "STALE";
    }
    return "LIVE_VERIFIED";
  }

  // Freshly retrieved within TTL, but capture timestamp is unverified
  const retrieved = epoch(camera.retrieved_at);
  if (retrieved !== null && now - retrieved <= CAMERA_TTL_MS) {
    return "RECENTLY_RETRIEVED_CAPTURE_UNKNOWN";
  }

  return "STALE";
}

/** Water map points need actual ONNX segmentation and routing-grade spatial evidence. */
export function hasVerifiedFloodObservation(
  camera: CameraEvidence,
  now: number = Date.now()
): boolean {
  return (
    cameraObservationStatus(camera, now) === "LIVE_VERIFIED" &&
    camera.evidence_eligibility === "ROUTING_ELIGIBLE" &&
    camera.line_of_sight_verified === true &&
    camera.flood_model_status === "VERIFIED_ONNX_INFERENCE" &&
    typeof camera.flood_ratio === "number" &&
    Number.isFinite(camera.flood_ratio) &&
    camera.flood_ratio >= 0 &&
    camera.flood_ratio <= 1
  );
}
