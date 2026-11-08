"use client";
import { recommendationLabel } from "../lib/route-status";

import React, { useState } from "react";
import { CameraEvidence, RiskLevel, SafeRouteResponse, TrafficStatus } from "../types/contracts";
import { Clock, ChevronDown, ChevronUp, AlertTriangle, Navigation2, Camera, ShieldCheck, Zap, Activity } from "lucide-react";

interface Props {
  selected: SafeRouteResponse;
  alternatives: SafeRouteResponse[];
  selectedStepIndex: number | null;
  onSelect: (route: SafeRouteResponse) => void;
  onSelectStep: (index: number | null) => void;
  onSelectCamera: (camera: CameraEvidence) => void;
}

const hasRiskEvidence = (route: SafeRouteResponse) =>
  route.segments.some(
    (s) =>
      s.risk_level !== RiskLevel.UNKNOWN &&
      s.risk_level !== RiskLevel.INSUFFICIENT_EVIDENCE &&
      (s.historical_flood_prone === true || s.evidence_cameras.length > 0)
  );

const riskCost = (route: SafeRouteResponse) =>
  (route.ranking_cost !== undefined && route.ranking_cost !== null)
    ? route.ranking_cost
    : (route.critical_segments_count || 0) * 10000 +
      (route.moderate_segments_count || 0) * 1000 +
      (route.unknown_segments_count || 0);

const allUnknown = (route: SafeRouteResponse) =>
  !route.segments.length ||
  route.segments.every(
    (s) => s.risk_level === RiskLevel.UNKNOWN || s.risk_level === RiskLevel.INSUFFICIENT_EVIDENCE
  );

export const RouteResults: React.FC<Props> = ({
  selected,
  alternatives,
  selectedStepIndex,
  onSelect,
  onSelectStep,
  onSelectCamera,
}) => {
  const [detailsOpen, setDetailsOpen] = useState(false);
  const routes = [selected, ...alternatives];

  // A reference selection never implies a safe recommendation.
  const recommended = routes.find((r) => r.is_recommended) || routes[0];

  // Fastest route determined by duration/estimated travel time
  const fastest = routes.find((r) => r.is_fastest) || routes.reduce((best, route) =>
    route.estimated_time_mins < best.estimated_time_mins ? route : best
  );

  const evidenced = routes.filter(hasRiskEvidence);
  const leastRisk = evidenced.length
    ? evidenced.reduce((best, route) => (riskCost(route) < riskCost(best) ? route : best))
    : null;

  const otherRoutes = routes.filter(
    (r) => r.route_id !== recommended.route_id && r.route_id !== fastest.route_id && r.route_id !== leastRisk?.route_id
  );

  const getRouteLabel = (route: SafeRouteResponse) => {
    if (route.route_status === "NO_SAFE_ROUTE" || route.overall_risk === RiskLevel.CRITICAL || route.segments.some(segment => segment.is_closed)) {
      return "Có đoạn cần tránh";
    }
    if (route.route_id === recommended.route_id) {
      return recommendationLabel(route);
    }
    if (route.route_id === fastest.route_id) {
      return "Nhanh nhất";
    }
    if (leastRisk && route.route_id === leastRisk.route_id) {
      return "Tuyến khác";
    }
    return "Tuyến thay thế";
  };

  const coverage = allUnknown(selected)
    ? "Chưa rõ tình trạng ngập trên tuyến này. Hãy chú ý quan sát khi đi."
    : selected.unknown_segments_count
    ? `${selected.unknown_segments_count} đoạn chưa có thông tin về tình trạng ngập. Hãy chú ý khi đi qua.`
    : "Thông tin đường đã được cập nhật. Tình trạng thực tế vẫn có thể thay đổi.";

  const renderTrafficBadge = (status?: TrafficStatus | string) => {
    switch (status) {
      case TrafficStatus.FREE_FLOW:
      case "FREE_FLOW":
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            Thông thoáng
          </span>
        );
      case TrafficStatus.SLOW:
      case "SLOW":
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
            Chậm
          </span>
        );
      case TrafficStatus.CONGESTED:
      case "CONGESTED":
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-rose-50 text-rose-700 border border-rose-200">
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
            Ùn tắc
          </span>
        );
      case TrafficStatus.CLOSED:
      case "CLOSED":
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-100 text-red-900 border border-red-300">
            <span className="w-1.5 h-1.5 rounded-full bg-red-800" />
            Phong tỏa
          </span>
        );
      case TrafficStatus.UNKNOWN:
      case "UNKNOWN":
      default:
        return (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-50 text-slate-500 border border-slate-200">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />
            Chưa rõ
          </span>
        );
    }
  };

  return (
    <section className="space-y-3" aria-label="Tuyến đường">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold text-ink-900 flex items-center gap-2">
          <Navigation2 className="w-4 h-4 text-indigo-600" />
          <span>Tuyến đường khả dụng</span>
        </h2>
        <span className="text-[11px] font-medium text-ink-500">
          {routes.length} phương án
        </span>
      </div>

      {/* Authoritative Navigation Tabs */}
      <div role="tablist" aria-label="Chọn tuyến đường" className="flex gap-2 overflow-x-auto pb-1">
        {/* Tab 1: Đề xuất (Backend Authoritative) */}
        <button
          role="tab"
          aria-selected={selected.route_id === recommended.route_id}
          onClick={() => {
            onSelect(recommended);
            setDetailsOpen(false);
          }}
          className="min-h-10 shrink-0 rounded-full px-3.5 py-1.5 text-xs font-semibold transition-all duration-200 border border-slate-200/80 bg-white/80 text-ink-700 hover:bg-white aria-selected:bg-gradient-to-r aria-selected:from-[#168BD2] aria-selected:to-[#18B6AD] aria-selected:border-transparent aria-selected:text-white aria-selected:shadow-md flex items-center gap-1.5"
        >
          <ShieldCheck className="w-3.5 h-3.5" />
          <span>{recommended.is_recommended ? "Đề xuất" : "Cần lưu ý"}</span>
        </button>

        {/* Tab 2: Nhanh nhất (if distinct from recommended) */}
        {fastest.route_id !== recommended.route_id && (
          <button
            role="tab"
            aria-selected={selected.route_id === fastest.route_id}
            onClick={() => {
              onSelect(fastest);
              setDetailsOpen(false);
            }}
            className="min-h-10 shrink-0 rounded-full px-3.5 py-1.5 text-xs font-semibold transition-all duration-200 border border-slate-200/80 bg-white/80 text-ink-700 hover:bg-white aria-selected:bg-gradient-to-r aria-selected:from-[#168BD2] aria-selected:to-[#18B6AD] aria-selected:border-transparent aria-selected:text-white aria-selected:shadow-md flex items-center gap-1.5"
          >
            <Zap className="w-3.5 h-3.5" />
            <span>Nhanh nhất</span>
          </button>
        )}

        {/* Tab 3: Ít rủi ro đã ghi nhận (if distinct and evidenced) */}
        {leastRisk && leastRisk.route_id !== recommended.route_id && leastRisk.route_id !== fastest.route_id && (
          <button
            role="tab"
            aria-selected={selected.route_id === leastRisk.route_id}
            onClick={() => {
              onSelect(leastRisk);
              setDetailsOpen(false);
            }}
            className="min-h-10 shrink-0 rounded-full px-3.5 py-1.5 text-xs font-semibold transition-all duration-200 border border-slate-200/80 bg-white/80 text-ink-700 hover:bg-white aria-selected:bg-gradient-to-r aria-selected:from-[#168BD2] aria-selected:to-[#18B6AD] aria-selected:border-transparent aria-selected:text-white aria-selected:shadow-md flex items-center gap-1.5"
          >
            <Activity className="w-3.5 h-3.5" />
            <span>{getRouteLabel(leastRisk)}</span>
          </button>
        )}

        {/* Tab 4: Other alternatives */}
        {otherRoutes.map((alt, idx) => (
          <button
            key={alt.route_id}
            role="tab"
            aria-selected={selected.route_id === alt.route_id}
            onClick={() => {
              onSelect(alt);
              setDetailsOpen(false);
            }}
            className="min-h-10 shrink-0 rounded-full px-3.5 py-1.5 text-xs font-semibold transition-all duration-200 border border-slate-200/80 bg-white/80 text-ink-700 hover:bg-white aria-selected:bg-gradient-to-r aria-selected:from-[#168BD2] aria-selected:to-[#18B6AD] aria-selected:border-transparent aria-selected:text-white aria-selected:shadow-md"
          >
            Đường khác {idx + 1}
          </button>
        ))}
      </div>

      {/* Route Cards */}
      <div className="space-y-2">
        {routes.map((route) => {
          const isSelected = route.route_id === selected.route_id;
          const isRec = route.route_id === recommended.route_id && route.is_recommended === true;
          const delaySecs = route.traffic_delay_seconds || 0;
          const delayMins = Math.round(delaySecs / 60);

          return (
            <button
              key={route.route_id}
              type="button"
              aria-pressed={isSelected}
              aria-label={`Chọn ${getRouteLabel(route)}, ${route.estimated_time_mins.toFixed(1)} phút, ${route.total_distance_km.toFixed(1)} km`}
              onClick={() => {
                onSelect(route);
                setDetailsOpen(false);
              }}
              className="block w-full min-h-20 rounded-2xl border p-3.5 text-left transition-all duration-200 cursor-pointer bg-white/85 border-slate-200/80 shadow-glass-sm hover:border-[#168BD2]/50 hover:bg-white aria-pressed:border-[#168BD2] aria-pressed:bg-gradient-to-br aria-pressed:from-[#E9F5FF] aria-pressed:to-white aria-pressed:shadow-glass focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#168BD2]"
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-1.5">
                  <span className="font-bold text-ink-900 text-xs sm:text-sm">{getRouteLabel(route)}</span>
                  {isRec && (
                    <span className="rounded-full bg-indigo-50 border border-indigo-200/80 text-indigo-700 px-2 py-0.5 text-[10px] font-bold">
                      Đề xuất SafePath
                    </span>
                  )}
                </div>
                {isSelected && (
                  <span className="rounded-full bg-gradient-to-r from-[#168BD2] to-[#18B6AD] px-2.5 py-0.5 text-[10px] font-bold text-white shadow-sm">
                    Đang chọn
                  </span>
                )}
              </div>

              {/* Time, distance and delay */}
              <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-ink-800">
                <div className="flex items-center gap-1.5">
                  <Clock className="h-4 w-4 text-[#168BD2]" />
                  <strong className="text-ink-950 font-bold">{route.estimated_time_mins.toFixed(1)} phút</strong>
                </div>
                <span className="text-ink-500 font-medium">· {route.total_distance_km.toFixed(1)} km</span>
                {route.transport_mode && (
                  <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-100 text-ink-700 border border-slate-200">
                    {String(route.transport_mode).toUpperCase() === "CAR"
                      ? "Ô tô"
                      : String(route.transport_mode).toUpperCase() === "WALKING"
                      ? "Đi bộ"
                      : "Xe máy"}
                  </span>
                )}
                {delayMins > 0 && (
                  <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
                    Xe đông: +{delayMins} phút
                  </span>
                )}
              </div>

              {/* Realistic ETA status indicator & breakdown */}
              <div className="mt-1.5 space-y-1">
                {route.traffic_eta_status === "TRAFFIC_ADJUSTED" && delayMins > 0 ? (
                  <span className="text-[11px] text-amber-700 font-medium block">
                    Thời gian trên đã tính khoảng {delayMins} phút chậm do xe đông.
                  </span>
                ) : route.traffic_eta_status === "TRAFFIC_VERIFIED_FREE_FLOW" ? (
                  <span className="text-[11px] text-emerald-700 font-medium block">
                    Các đoạn có thông tin giao thông hiện khá thông thoáng.
                  </span>
                ) : route.is_live_traffic ? (
                  <span className="text-[11px] text-slate-600 font-normal block">
                    Thời gian dự kiến đã tính theo tốc độ giao thông cập nhật.
                  </span>
                ) : (
                  <span className="text-[11px] text-slate-600 font-normal block">
                    Đây là thời gian ước tính; chưa có tốc độ giao thông cập nhật trên tuyến.
                  </span>
                )}
                {route.is_live_traffic && (route.traffic_coverage_ratio ?? 0) < 0.999999 && (
                  <p className="text-[11px] text-ink-600">
                    Có thông tin tốc độ trên khoảng {(route.traffic_coverage_ratio ?? 0) < 0.01 ? "dưới 1" : Math.round((route.traffic_coverage_ratio ?? 0) * 100)}% quãng đường; phần còn lại là ước tính.
                  </p>
                )}
              </div>

              {/* Brief honest status */}
              <p className="mt-1 text-xs text-ink-600 line-clamp-1">
                {allUnknown(route)
                  ? "Chưa rõ tình trạng ngập trên tuyến"
                  : route.unknown_segments_count
                  ? `${route.unknown_segments_count} đoạn chưa rõ tình trạng ngập`
                  : "Đã có thông tin đường, bạn vẫn nên chú ý khi đi"}
              </p>
            </button>
          );
        })}
      </div>

      {routes.length === 1 && (
        <p className="text-xs text-ink-500 italic">Chỉ tìm được một tuyến hợp lệ.</p>
      )}

      {/* Caution & Notice Card */}
      <div className="rounded-2xl glass-panel p-3.5 text-xs text-ink-800 border border-slate-200/80">
        <h3 className="font-bold text-ink-900 flex items-center gap-1.5">
          <AlertTriangle className="h-4 w-4 text-amber-500" />
          <span>Lưu ý trên đường</span>
        </h3>
        <p className="mt-1 text-ink-600 leading-relaxed">{coverage}</p>
        {selected.route_status === "NO_SAFE_ROUTE" && (
          <div className="mt-2 rounded-xl bg-red-50 border border-red-200 p-2.5 text-red-900 font-semibold text-xs">
            Chưa tìm được tuyến tránh nguy hiểm. Các lựa chọn đều có cảnh báo hoặc đoạn bị chặn. Bạn nên cân nhắc đổi đường hoặc đi vào lúc khác.
          </div>
        )}
        {selected.segments
          .filter((s) => s.risk_level === RiskLevel.CRITICAL || s.risk_level === RiskLevel.MODERATE || s.traffic_status === TrafficStatus.CONGESTED || s.traffic_status === TrafficStatus.CLOSED || s.is_closed)
          .map((s, i) => (
            <p key={i} className="mt-2 flex items-start gap-1.5 text-amber-800 font-medium">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-500 mt-1.5 shrink-0" />
              <span>
                {s.street_name || "Đoạn đường chưa đặt tên"}:{" "}
                <strong>
                  {s.traffic_status === TrafficStatus.CLOSED || s.is_closed
                    ? "có thông tin đường bị chặn, nên chọn đường khác"
                    : s.risk_level === RiskLevel.CRITICAL
                    ? "có cảnh báo nguy hiểm, nên tránh đi qua"
                    : s.traffic_status === TrafficStatus.CONGESTED
                    ? "ùn tắc giao thông"
                    : "cần đi chậm và chú ý quan sát"}
                </strong>
                {s.traffic_delay_seconds && !s.is_closed && s.traffic_status !== TrafficStatus.CLOSED ? ` · Có thể chậm thêm ${s.traffic_delay_seconds < 60 ? "dưới 1" : Math.round(s.traffic_delay_seconds / 60)} phút` : ""}
              </span>
            </p>
          ))}
      </div>

      {/* Step by Step Details */}
      <div className="rounded-2xl glass-panel p-3 border border-slate-200/80">
        <button
          type="button"
          aria-expanded={detailsOpen}
          onClick={() => setDetailsOpen((v) => !v)}
          className="flex min-h-10 w-full items-center justify-between rounded-xl px-1 py-1 text-left text-xs font-bold text-ink-900 hover:text-indigo-600 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 transition cursor-pointer"
        >
          <span>Xem từng chặng ({selected.segments.length} đoạn)</span>
          {detailsOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </button>
        {detailsOpen && (
          <ol className="mt-2.5 max-h-72 space-y-2 overflow-y-auto border-t border-slate-100 pt-2.5">
            {selected.segments.map((segment, index) => (
              <li key={index} className="space-y-1">
                <button
                  type="button"
                  aria-pressed={selectedStepIndex === index}
                  onClick={() => onSelectStep(selectedStepIndex === index ? null : index)}
                  className="w-full rounded-xl p-2 text-left text-xs font-medium text-ink-800 hover:bg-slate-100/80 aria-pressed:bg-indigo-100/80 aria-pressed:text-indigo-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-500 transition flex items-center justify-between cursor-pointer"
                >
                  <div className="flex-1 min-w-0 pr-2">
                    <span className="font-semibold block truncate">
                      {index + 1}. {segment.street_name || "Tiếp tục theo đường"}
                    </span>
                    <span className="text-[10px] text-ink-500 font-mono">
                      {Math.round(segment.length_meters)} m
                    </span>
                  </div>
                  <div className="shrink-0 flex items-center gap-1.5">
                    {renderTrafficBadge(segment.traffic_status)}
                  </div>
                </button>
                {segment.evidence_cameras.map((camera) => (
                  <button
                    key={camera.cam_id}
                    onClick={() => onSelectCamera(camera)}
                    className="ml-3 inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[11px] font-semibold text-indigo-700 bg-indigo-50 border border-indigo-100 hover:bg-indigo-100 transition cursor-pointer"
                  >
                    <Camera className="w-3 h-3 text-indigo-600" />
                    <span>Xem camera {camera.code || camera.name}</span>
                  </button>
                ))}
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
};
