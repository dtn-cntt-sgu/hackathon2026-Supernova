import type { CameraEvidence, RouteSegmentRisk, SafeRouteResponse, WebSocketAlertMessage } from "../types/contracts";

export type TrackedPosition = { lat: number; lng: number; accuracy?: number };

export const distanceMeters = (a: TrackedPosition, lng: number, lat: number) => {
  const r = 6371000;
  const deltaLat = (lat - a.lat) * Math.PI / 180;
  const deltaLng = (lng - a.lng) * Math.PI / 180;
  const h = Math.sin(deltaLat / 2) ** 2 + Math.cos(a.lat * Math.PI / 180) * Math.cos(lat * Math.PI / 180) * Math.sin(deltaLng / 2) ** 2;
  return 2 * r * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
};
const lengthText = (meters: number) => meters >= 1000 ? `${(meters / 1000).toFixed(1)} km` : `${Math.round(meters)} m`;
const direction = (modifier?: string | null) => ({
  left: "trái", right: "phải", "slight left": "chếch trái", "slight right": "chếch phải",
  "sharp left": "ngoặt gấp trái", "sharp right": "ngoặt gấp phải", straight: "thẳng", uturn: "quay đầu",
}[modifier || ""] || null);

/** Uses only maneuver and distance values returned by OSRM. Unknown maneuvers are silent. */
export const instructionForStep = (step: RouteSegmentRisk): string | null => {
  const type = step.maneuver_type;
  if (!type || !Number.isFinite(step.length_meters)) return null;
  const road = step.street_name ? ` vào ${step.street_name}` : "";
  const travel = step.length_meters > 0 ? `, đi ${lengthText(step.length_meters)}` : "";
  const turn = direction(step.maneuver_modifier);
  switch (type) {
    case "depart": return `Bắt đầu${step.street_name ? ` trên ${step.street_name}` : ""}${travel}.`;
    case "turn": return turn ? `${turn === "quay đầu" ? "Quay đầu" : `Rẽ ${turn}`}${road}${travel}.` : null;
    case "continue": return `Tiếp tục ${turn === "thẳng" ? "đi thẳng" : turn ? `về ${turn}` : "theo đường"}${road}${travel}.`;
    case "new name": return `Tiếp tục${road}${travel}.`;
    case "merge": return `Nhập làn${turn ? ` về ${turn}` : ""}${road}${travel}.`;
    case "fork": return `Đi theo nhánh ${turn || "phía trước"}${road}${travel}.`;
    case "on ramp": return `Vào đường dẫn${road}${travel}.`;
    case "off ramp": return `Ra khỏi đường chính${road}${travel}.`;
    case "end of road": return turn ? `Cuối đường rẽ ${turn}${road}${travel}.` : null;
    case "roundabout":
    case "rotary": return `Vào vòng xoay${step.maneuver_exit ? `, ra lối thứ ${step.maneuver_exit}` : ""}${road}${travel}.`;
    case "exit roundabout": return `Ra khỏi vòng xoay${road}${travel}.`;
    case "arrive": return "Đã đến nơi.";
    default: return null;
  }
};

/** An alert needs recent, route-matched, routing-eligible camera evidence. */
export const isVerifiedRouteAlert = (alert: WebSocketAlertMessage, route: SafeRouteResponse, now = Date.now(), fromStepIndex = 0) => {
  if (alert.type !== "CRITICAL_FLOOD_ALERT" || alert.severity !== "CRITICAL" ||
      alert.risk_level !== "CRITICAL" || !alert.cam_id || !alert.event_id ||
      typeof alert.source !== "string" || !alert.source.startsWith("camera_vision:")) return false;
  const observed = Date.parse(alert.observed_at);
  const expires = alert.expiry ? Date.parse(alert.expiry) : now + 1;
  if (!Number.isFinite(observed) || !Number.isFinite(expires) || now - observed < -30000 || now - observed > 120000 || expires <= now) return false;
  return route.segments.some((segment, index) => index >= fromStepIndex && segment.evidence_cameras.some((camera: CameraEvidence) => {
    const updated = Date.parse(camera.updated_at);
    return camera.cam_id === alert.cam_id &&
      camera.source_status === "LIVE" &&
      camera.risk_level === "CRITICAL" &&
      camera.evidence_eligibility === "ROUTING_ELIGIBLE" &&
      camera.spatial_match_status === "OBSERVED_SEGMENT_VERIFIED" &&
      camera.line_of_sight_verified === true &&
      Boolean(camera.coordinate_source_url && camera.view_verification_source_url && camera.observed_osm_way_id) &&
      Number.isFinite(updated) && now - updated >= 0 && now - updated <= 120000;
  }));
};

