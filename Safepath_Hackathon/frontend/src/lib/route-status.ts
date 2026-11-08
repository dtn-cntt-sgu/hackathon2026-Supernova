import { RiskLevel, type SafeRouteResponse } from "../types/contracts";

export function recommendationLabel(route: SafeRouteResponse): string {
  if (route.route_status === "NO_SAFE_ROUTE" || route.overall_risk === RiskLevel.CRITICAL || (route.critical_segments_count ?? 0) > 0 || route.segments.some(segment => segment.is_closed)) return "Có đoạn cần tránh";
  return "Tuyến đề xuất";
}
