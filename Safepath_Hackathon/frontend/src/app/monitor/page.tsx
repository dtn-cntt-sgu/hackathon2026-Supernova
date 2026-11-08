"use client";

import React, { useState, useEffect, useCallback } from "react";
import { AppPageHeader } from "../../components/ui/AppPageHeader";
import { fetchCameras, fetchCameraSummary } from "../../services/api";
import { CameraEvidence, CameraSummary } from "../../types/contracts";
import { CameraProxyModal } from "../../components/CameraProxyModal";
import { CameraProxySnapshot } from "../../components/CameraProxySnapshot";
import { Camera, MapPin, Search, Eye, Radio, RefreshCw, CheckCircle, Clock } from "lucide-react";
import { GlassBadge, GlassInput } from "../../components/Glass";

export default function CameraMonitorPage() {
  const [cameras, setCameras] = useState<CameraEvidence[]>([]);
  const [summary, setSummary] = useState<CameraSummary | null>(null);
  const [selectedCamera, setSelectedCamera] = useState<CameraEvidence | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [districtFilter, setDistrictFilter] = useState<string>("ALL");
  const [onlyWithImage, setOnlyWithImage] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshMs, setRefreshMs] = useState(30000);
  const [revision, setRevision] = useState(0);

  const loadCameras = useCallback(async () => {
    setIsLoading(true);
    try {
      const [cameraList, summaryData] = await Promise.all([
        fetchCameras(),
        fetchCameraSummary().catch(() => null),
      ]);
      setCameras(cameraList);
      if (summaryData) setSummary(summaryData);
    } catch (e) {
      console.warn("Failed to load cameras for monitor:", e);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    setRevision(value => value + 1);
    try {
      const [cameraList, summaryData] = await Promise.all([
        fetchCameras(),
        fetchCameraSummary().catch(() => null),
      ]);
      setCameras(cameraList);
      if (summaryData) setSummary(summaryData);
    } catch (e) {
      console.warn("Refresh failed:", e);
    } finally {
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    loadCameras();
    const interval = setInterval(async () => {
      if (document.hidden || refreshMs === 0) return;
      try {
        const [sum, cameraList] = await Promise.all([
          fetchCameraSummary(),
          fetchCameras(),
        ]);
        setSummary(sum);
        setCameras(cameraList);
      } catch {}
    }, Math.max(30000, refreshMs));
    return () => clearInterval(interval);
  }, [loadCameras, refreshMs]);

  // Calculate camera count by district
  const districtCounts = React.useMemo(() => {
    const counts: Record<string, number> = {};
    cameras.forEach((c) => {
      const d = c.district || "UNKNOWN_DISTRICT";
      counts[d] = (counts[d] || 0) + 1;
    });
    return counts;
  }, [cameras]);

  // Known HCMC districts sorted naturally
  const knownDistricts = React.useMemo(() => {
    return Array.from(
      new Set(
        cameras
          .map((c) => c.district)
          .filter((d): d is string => !!d && d !== "UNKNOWN_DISTRICT")
      )
    ).sort((a, b) => a.localeCompare(b, "vi", { numeric: true }));
  }, [cameras]);

  const unknownDistrictCount = (districtCounts["UNKNOWN_DISTRICT"] || 0) + (districtCounts[""] || 0);

  const filteredCameras = cameras.filter((cam) => {
    if (onlyWithImage && !cam.has_image) return false;
    if (districtFilter === "UNKNOWN_DISTRICT") {
      if (cam.district && cam.district !== "UNKNOWN_DISTRICT") return false;
    } else if (districtFilter !== "ALL" && cam.district !== districtFilter) {
      return false;
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchName = cam.name.toLowerCase().includes(q);
      const matchCode = (cam.code || "").toLowerCase().includes(q);
      const districtLabel = (
        cam.district && cam.district !== "UNKNOWN_DISTRICT"
          ? cam.district
          : "chưa xác định chưa xác định quận huyện unknown"
      ).toLowerCase();
      const matchDistrict = districtLabel.includes(q);
      if (!matchName && !matchCode && !matchDistrict) return false;
    }
    return true;
  });

  return (
    <div className="spatial-aux flex flex-col min-h-screen text-ink-900 relative selection:bg-indigo-600 selection:text-white pb-16">
      {/* Background aurora mist */}
      <div className="fixed top-[-10%] left-[-5%] w-[50vw] h-[50vw] rounded-full bg-gradient-to-br from-indigo-200/35 via-ice-200/25 to-transparent blur-3xl pointer-events-none -z-10" />
      <div className="fixed bottom-[-10%] right-[-5%] w-[45vw] h-[45vw] rounded-full bg-gradient-to-tl from-lavender-200/35 via-sky-200/25 to-transparent blur-3xl pointer-events-none -z-10" />

      {/* Floating Header Capsule */}
      <AppPageHeader
        title="Trung tâm Giám sát Camera"
        description="Quan trắc ảnh camera gốc qua proxy · nguồn hiển thị trên từng ảnh"
        badge={summary ? `${summary.total_registered} camera` : undefined}
      />

      {/* Main Content Area */}
      <main className="flex-1 p-4 sm:p-6 max-w-7xl mx-auto w-full space-y-6 mt-2">
        <p className="text-xs text-ink-500">Thống kê bên dưới thuộc kho ảnh thu thập nền TP.HCM. Nguồn ảnh proxy và trạng thái tải hiện tại được ghi trên từng camera.</p>
        {/* Real Network Telemetry Summary (4 Glass Metrics) */}
        {summary && (
          <div data-testid="monitor-telemetry-summary" className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
            {/* Metric 1: Camera đã đăng ký */}
            <div className="liquid-glass-surface rounded-3xl p-4 sm:p-5 flex flex-col justify-between space-y-3 group hover:border-[#168BD2]/40 transition-colors">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-ink-700 uppercase tracking-wider">Tổng camera hệ thống</span>
                <div className="p-2.5 rounded-2xl bg-indigo-50/90 border border-indigo-100 text-[#168BD2] shadow-glass-sm group-hover:scale-105 transition-transform">
                  <Camera className="w-4 h-4" />
                </div>
              </div>
              <div>
                <div className="text-2xl sm:text-3xl font-black text-ink-950 font-mono tracking-tight">
                  {summary.total_registered}
                </div>
                <div className="mt-1 flex items-center gap-1.5 text-[11px] text-emerald-700 font-semibold">
                  <CheckCircle className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                  <span>{summary.valid_gps_count} camera có tọa độ GPS</span>
                </div>
              </div>
            </div>

            {/* Metric 2: Camera đã kiểm tra trong chu kỳ 10 phút (600s) */}
            <div className="liquid-glass-surface rounded-3xl p-4 sm:p-5 flex flex-col justify-between space-y-3 group hover:border-[#168BD2]/40 transition-colors">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-ink-700 uppercase tracking-wider">Tiến độ chu kỳ 10 phút (600s)</span>
                <div className="p-2.5 rounded-2xl bg-blue-50/90 border border-blue-100 text-blue-600 shadow-glass-sm group-hover:scale-105 transition-transform">
                  <Radio className="w-4 h-4" />
                </div>
              </div>
              <div>
                <div className="text-2xl sm:text-3xl font-black text-ink-950 font-mono tracking-tight">
                  {summary.cycle_checked_count ?? summary.checked_count}
                </div>
                <div className="mt-1 text-[11px] text-ink-500 font-medium">
                  {summary.cycle_pending_count !== undefined && summary.cycle_pending_count !== null
                    ? `Chu kỳ rà soát 600s • Còn chờ ${summary.cycle_pending_count} camera`
                    : `trên tổng số ${summary.total_registered} camera toàn thành phố`}
                </div>
              </div>
            </div>

            {/* Metric 3: Camera có ảnh mới gần đây */}
            <div className="liquid-glass-surface rounded-3xl p-4 sm:p-5 flex flex-col justify-between space-y-3 group hover:border-[#18B6AD]/40 transition-colors">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-ink-700 uppercase tracking-wider">Snapshot hợp lệ gần đây</span>
                <div className="p-2.5 rounded-2xl bg-cyan-50/90 border border-cyan-100 text-[#18B6AD] shadow-glass-sm group-hover:scale-105 transition-transform">
                  <Eye className="w-4 h-4" />
                </div>
              </div>
              <div>
                <div className="text-2xl sm:text-3xl font-black text-[#168BD2] font-mono tracking-tight">
                  {summary.valid_images_count}
                </div>
                <div className="mt-1 text-[11px] text-ink-500 font-medium">
                  {summary.circuit_breaker_open ? "Đang điều tiết tải kết nối" : "camera có ảnh nhận thành công gần nhất"}
                </div>
              </div>
            </div>

            {/* Metric 4: Camera có dữ liệu cũ */}
            <div className="liquid-glass-surface rounded-3xl p-4 sm:p-5 flex flex-col justify-between space-y-3 group hover:border-amber-300/40 transition-colors">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-ink-700 uppercase tracking-wider">Camera có ảnh lưu cũ</span>
                <div className="p-2.5 rounded-2xl bg-amber-50/90 border border-amber-100 text-amber-600 shadow-glass-sm group-hover:scale-105 transition-transform">
                  <Clock className="w-4 h-4" />
                </div>
              </div>
              <div>
                <div className="text-2xl sm:text-3xl font-black text-amber-800 font-mono tracking-tight">
                  {summary.stale_count ?? "—"}
                </div>
                <div className="mt-1 text-[11px] text-ink-500 font-medium">
                  không dùng ảnh cũ để xác nhận hiện trạng
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Section F Granular Telemetry Breakdown Strip */}
        {summary && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5 text-xs">
            <div className="p-3 rounded-2xl bg-white/70 border border-slate-200/80 flex flex-col justify-between">
              <span className="text-[11px] text-ink-500 font-medium">Nguồn khả dụng</span>
              <div className="text-lg font-bold font-mono text-emerald-700 mt-1">
                {summary.reachable_count ?? summary.valid_images_count}
              </div>
            </div>
            <div className="p-3 rounded-2xl bg-white/70 border border-slate-200/80 flex flex-col justify-between">
              <span className="text-[11px] text-ink-500 font-medium">Mới nhận gần đây</span>
              <div className="text-lg font-bold font-mono text-sky-700 mt-1">
                {summary.fetched_recently_count ?? summary.valid_images_count}
              </div>
            </div>
            <div className="p-3 rounded-2xl bg-white/70 border border-slate-200/80 flex flex-col justify-between">
              <span className="text-[11px] text-ink-500 font-medium">Live xác minh</span>
              <div className="text-lg font-bold font-mono text-emerald-700 mt-1">
                {summary.fresh_verified_count ?? 0}
              </div>
            </div>
            <div className="p-3 rounded-2xl bg-white/70 border border-slate-200/80 flex flex-col justify-between">
              <span className="text-[11px] text-ink-500 font-medium">Lưu cũ (Stale)</span>
              <div className="text-lg font-bold font-mono text-amber-700 mt-1">
                {summary.stale_count ?? summary.stale_images_count}
              </div>
            </div>
            <div className="p-3 rounded-2xl bg-white/70 border border-slate-200/80 flex flex-col justify-between">
              <span className="text-[11px] text-ink-500 font-medium">Lỗi tải (Failed)</span>
              <div className="text-lg font-bold font-mono text-rose-700 mt-1">
                {summary.fetch_failed_count ?? summary.unavailable_count}
              </div>
            </div>
            <div className="p-3 rounded-2xl bg-white/70 border border-slate-200/80 flex flex-col justify-between">
              <div className="text-lg font-bold font-mono text-slate-700 mt-1">
                {summary.capture_time_unknown_count ?? "—"}
              </div>
            </div>
          </div>
        )}

        {/* Data Provenance & Caution Banner */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 px-4 py-3 rounded-2xl bg-white/70 border border-white/90 text-xs text-ink-600 shadow-glass-sm">
          <div className="flex items-center gap-2">
            <Clock className="w-4 h-4 text-[#168BD2] shrink-0" />
            <span>
              Cập nhật gần nhất: <strong>{summary?.last_scheduler_cycle ? new Date(summary.last_scheduler_cycle).toLocaleTimeString("vi-VN") : "Đang đồng bộ..."}</strong> · Danh mục và kho ảnh nền: Cổng TT Giao thông TP.HCM
            </span>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-ink-500">
            <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span>Ảnh đang hiển thị: <strong>{refreshMs ? `mỗi ${refreshMs / 1000} giây` : "tạm dừng tự làm mới"}</strong></span>
          </div>
        </div>

        {/* Filter Toolbar (Floating Glass Surface) */}
        <div className="liquid-glass-surface rounded-3xl p-4 sm:p-5 border border-white/95 shadow-glass space-y-3">
          <div className="flex flex-col md:flex-row items-stretch md:items-center gap-3 justify-between">
            {/* Search input */}
            <div className="w-full md:w-96">
              <GlassInput
                placeholder="Tìm camera theo tên đường, mã hoặc quận..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onClear={() => setSearchQuery("")}
                leftIcon={<Search className="w-4 h-4" />}
              />
            </div>

            {/* Filters and Actions */}
            <div className="flex flex-wrap items-center gap-2.5 justify-start md:justify-end">
              {/* District Filter Dropdown */}
              <select
                value={districtFilter}
                onChange={(e) => setDistrictFilter(e.target.value)}
                aria-label="Lọc theo quận huyện"
                className="px-3.5 py-2.5 rounded-2xl bg-white/90 hover:bg-white text-ink-900 text-xs font-bold border border-indigo-100/90 shadow-glass-sm outline-none cursor-pointer focus:ring-4 focus:ring-indigo-400/20 transition"
              >
                <option value="ALL">Tất cả quận / huyện ({cameras.length})</option>
                {knownDistricts.map((d) => (
                  <option key={d} value={d}>
                    {d} ({districtCounts[d] || 0})
                  </option>
                ))}
                {unknownDistrictCount > 0 && (
                  <option value="UNKNOWN_DISTRICT">
                    Chưa xác định quận/huyện ({unknownDistrictCount})
                  </option>
                )}
              </select>

              {/* Only with image toggle */}
              <button
                type="button"
                onClick={() => setOnlyWithImage((v) => !v)}
                className={`px-3.5 py-2.5 rounded-2xl text-xs font-bold border transition-all duration-200 cursor-pointer flex items-center gap-1.5 shadow-glass-sm select-none ${
                  onlyWithImage
                    ? "bg-indigo-50/95 border-indigo-300 text-indigo-700 shadow-sm ring-2 ring-indigo-400/20"
                    : "bg-white/90 border-white/95 text-ink-700 hover:text-ink-950 hover:bg-white"
                }`}
              >
                <Eye className="w-3.5 h-3.5 text-indigo-600" />
                <span>Chỉ camera có ảnh lưu</span>
              </button>

              <select aria-label="Chu kỳ cập nhật ảnh" value={refreshMs} onChange={event => setRefreshMs(Number(event.target.value))} className="px-3 py-2.5 rounded-2xl bg-white border text-xs focus:ring-2">
                <option value={30000}>Mỗi 30 giây</option><option value={60000}>Mỗi 60 giây</option><option value={0}>Tạm dừng</option>
              </select>
              {/* Refresh Button */}
              <button
                type="button"
                onClick={handleRefresh}
                disabled={isRefreshing}
                className="p-2.5 rounded-2xl bg-white/90 hover:bg-white border border-white/95 text-ink-700 hover:text-indigo-600 shadow-glass-sm transition cursor-pointer disabled:opacity-50"
                aria-label="Làm mới camera"
                title={isRefreshing ? "Đang đồng bộ dữ liệu snapshot..." : "Làm mới dữ liệu snapshot camera"}
              >
                <RefreshCw className={`w-4 h-4 ${isRefreshing ? "animate-spin text-indigo-600" : ""}`} />
              </button>

              <GlassBadge variant="indigo" size="md">
                {filteredCameras.length} camera
              </GlassBadge>
            </div>
          </div>
        </div>

        {/* Camera Gallery Grid View */}
        {isLoading ? (
          <div className="flex flex-col items-center justify-center p-20 space-y-3">
            <div className="w-9 h-9 border-3 border-indigo-600 border-t-transparent rounded-full animate-spin" />
            <p className="text-xs font-bold text-ink-700">Đang nạp thư viện camera TP.HCM...</p>
          </div>
        ) : filteredCameras.length === 0 ? (
          <div className="liquid-glass-surface rounded-3xl p-16 text-center border border-white/95 shadow-glass space-y-3">
            <div className="w-12 h-12 rounded-3xl bg-indigo-50 border border-indigo-100/80 text-indigo-600 flex items-center justify-center mx-auto shadow-sm">
              <Camera className="w-6 h-6 stroke-1.5" />
            </div>
            <h3 className="text-sm font-bold text-ink-950">Không tìm thấy camera phù hợp</h3>
            <p className="text-xs text-ink-500 max-w-sm mx-auto">
              Hãy thử đổi từ khóa tìm kiếm hoặc chọn &quot;Tất cả quận / huyện&quot; để hiển thị toàn bộ camera trong danh sách.
            </p>
          </div>
        ) : (
          <div
            data-testid="camera-monitor-grid"
            className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 sm:gap-5"
          >
            {filteredCameras.map((cam) => {

              return (
                <div
                  key={cam.cam_id}
                  data-testid="camera-card"
                  role="button"
                  tabIndex={0}
                  aria-label={`Xem chi tiết ${cam.name}`}
                  onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); setSelectedCamera(cam); } }}
                  onClick={() => setSelectedCamera(cam)}
                  className="group relative rounded-3xl overflow-hidden glass-interactive shadow-glass hover:shadow-glass-elevated transition-all duration-300 hover:-translate-y-1 cursor-pointer flex flex-col"
                >
                  {/* Camera Snapshot / Placeholder View */}
                  <div className="relative aspect-video bg-gradient-to-br from-slate-100 to-indigo-50/40 overflow-hidden flex items-center justify-center border-b border-slate-100/80">
                    <CameraProxySnapshot camId={cam.cam_id} name={cam.name} refreshMs={refreshMs} revision={revision} />

                    {/* Hover CTA Pill */}
                    <div className="absolute inset-0 bg-indigo-950/20 opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex items-center justify-center backdrop-blur-[2px]">
                      <span className="px-3.5 py-1.5 rounded-full bg-white/95 text-indigo-700 font-bold text-xs shadow-md border border-white/90 flex items-center gap-1.5 transform translate-y-2 group-hover:translate-y-0 transition-transform">
                        <Eye className="w-3.5 h-3.5" />
                        <span>Xem chi tiết</span>
                      </span>
                    </div>

                    {/* Camera code */}
                    <div className="absolute top-2.5 left-2.5 flex items-center gap-1.5">
                      <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono font-bold bg-white/95 text-indigo-950 border border-white/90 backdrop-blur-md shadow-sm">
                        {cam.code || "CAM"}
                      </span>
                    </div>


                  </div>

                  {/* Camera Meta Body */}
                  <div className="p-4 flex-1 flex flex-col justify-between space-y-2.5">
                    <div>
                      <h4 className="text-xs font-bold text-ink-950 line-clamp-1 group-hover:text-indigo-600 transition">
                        {cam.name}
                      </h4>
                      <p className="text-[11px] text-ink-500 font-medium flex items-center gap-1 mt-1">
                        <MapPin className="w-3 h-3 text-indigo-500 shrink-0" />
                        <span className="truncate">
                          {cam.district && cam.district !== "UNKNOWN_DISTRICT"
                            ? cam.district
                            : "Chưa xác định quận/huyện"}
                        </span>
                      </p>
                    </div>

                    <p className="text-[11px] text-ink-500">{cam.lat}, {cam.lng}</p>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>

      {/* Original snapshots only; route evidence retains its own modal. */}
      <CameraProxyModal
        camera={selectedCamera}
        refreshMs={refreshMs}
        onClose={() => setSelectedCamera(null)}
      />
    </div>
  );
}
