"use client";

import React, { useState } from "react";
import { CommunityReports } from "../../components/CommunityReports";
import Link from "next/link";
import { AppPageHeader } from "../../components/ui/AppPageHeader";
import {
  ArrowLeft,
  ArrowRight,
  Bookmark,
  Clock,
  MapPin,
  Plus,
  Trash2,
  Navigation,
  Camera,
  Car,
  CloudRain,
  Waves,
  ShieldAlert,
  ShieldCheck,
  CheckCircle,
  AlertTriangle,
  RefreshCw,
  Send,
  User,
  ExternalLink,
  Radio,
  Eye,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { useLiveObservations } from "../../hooks/useLiveObservations";
import { GlassCard, GlassButton, GlassBadge } from "../../components/Glass";
import { PlaceSearchCombobox } from "../../components/PlaceSearchCombobox";
import { CameraEvidenceModal } from "../../components/CameraEvidenceModal";
import { observationTime, currentRain, currentTide } from "../../lib/observations";
import { getCameraImageUrl } from "../../services/api";
import type { PlaceResult, CameraEvidence } from "../../types/contracts";

export default function UserDashboardPage() {
  const { user, isAuthenticated, isLoading, savePlace, removeSavedPlace } = useAuth();
  const live = useLiveObservations();

  const [showAdd, setShowAdd] = useState(false);
  const [query, setQuery] = useState("");
  const [place, setPlace] = useState<PlaceResult | null>(null);
  const [label, setLabel] = useState("Nhà");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedCamera, setSelectedCamera] = useState<CameraEvidence | null>(null);

  const rain = currentRain(live.weather, live.now);
  const tide = currentTide(live.weather, live.now);

  // Cameras near user / with valid images
  const nearbyCameras = live.cameras.filter((c) => c.has_image).slice(0, 4);

  async function createPlace(event: React.FormEvent) {
    event.preventDefault();
    if (!place || !isAuthenticated || busy) return;
    setBusy(true);
    setError(null);
    try {
      await savePlace({
        name: place.name,
        address: place.display_name,
        lat: place.lat,
        lng: place.lng,
        label,
      });
      setShowAdd(false);
      setQuery("");
      setPlace(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Không lưu được địa điểm.");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setError(null);
    try {
      await removeSavedPlace(id);
    } catch {
      setError("Không xóa được địa điểm. Vui lòng thử lại.");
    }
  }

  return (
    <div className="flex flex-col min-h-screen bg-gradient-to-b from-pearl-50 via-ice-50 to-pearl-100 text-ink-900 relative selection:bg-indigo-600 selection:text-white pb-16">
      {/* Background Aurora Orbs (Fixed to viewport to prevent scroll cutoff) */}
      <div className="fixed top-[-10%] left-[-5%] w-[50vw] h-[50vw] rounded-full bg-gradient-to-br from-indigo-200/30 via-ice-200/25 to-transparent blur-3xl pointer-events-none -z-10" />
      <div className="fixed bottom-[-10%] right-[-5%] w-[45vw] h-[45vw] rounded-full bg-gradient-to-tl from-lavender-200/30 via-sky-200/25 to-transparent blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <AppPageHeader title="Bảng điều khiển" description="Hành trình và thông tin giao thông của bạn" badge="Hành trình" />

      {/* Main Content */}
      <main className="mx-auto max-w-6xl w-full p-4 sm:p-6 md:p-8 space-y-6">
        {/* Welcome Greeting Banner */}
        <GlassCard variant="elevated" className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-5 sm:p-6">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="text-xl sm:text-2xl font-black text-ink-950 tracking-tight">
                {user ? `Chào buổi sáng, ${user.name}` : "Chào bạn! Hôm nay đi làm an toàn nhé."}
              </span>
              <GlassBadge variant="indigo" size="sm">TP.HCM</GlassBadge>
            </div>
            <p className="text-xs sm:text-sm text-ink-600">
              {isLoading
                ? "Đang nạp dữ liệu hồ sơ..."
                : user
                ? "Dữ liệu hành trình & địa điểm đã lưu được đồng bộ an toàn qua tài khoản Google."
                : "Hệ thống đang hoạt động ở Chế độ Khách bảo mật. Đăng nhập Google để lưu lộ trình thường nhật."}
            </p>
          </div>

          <div className="flex items-center gap-2.5 shrink-0">
            <Link
              href="/di-duong"
              className="px-4 py-2.5 rounded-2xl bg-gradient-to-r from-[#168BD2] to-[#18B6AD] hover:opacity-95 text-white font-bold text-xs flex items-center gap-1.5 shadow-md transition"
            >
              <Navigation className="w-4 h-4" />
              <span>Tìm tuyến đường</span>
            </Link>
          </div>
        </GlassCard>

        {/* SECTION 1: Nhịp đập thành phố (City Pulse) */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-black text-xs uppercase tracking-wider text-ink-800">
              <Radio className="w-4 h-4 text-indigo-600 animate-pulse" />
              <span>Nhịp đập thành phố (City Pulse)</span>
            </div>
            <span className="text-[11px] text-ink-500 font-mono">
              Cập nhật chu kỳ: {observationTime(live.summary?.last_scheduler_cycle)}
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {/* KPI 1 */}
            <GlassCard className="p-4 space-y-1">
              <div className="flex items-center justify-between text-xs text-ink-500">
                <span>Camera đăng ký</span>
                <Camera className="w-4 h-4 text-indigo-600" />
              </div>
              <div className="text-2xl font-black text-ink-950">
                {live.summary?.total_registered ?? "—"}{" "}
                <small className="text-xs font-normal text-ink-500">trạm</small>
              </div>
              <p className="text-[10px] text-emerald-700 font-semibold flex items-center gap-1">
                <CheckCircle className="w-3 h-3" /> Tọa độ: {live.summary?.valid_gps_count ?? "—"} camera
              </p>
            </GlassCard>

            {/* KPI 2 */}
            <GlassCard className="p-4 space-y-1">
              <div className="flex items-center justify-between text-xs text-ink-500">
                <span>Lượng mưa hiện tại</span>
                <CloudRain className="w-4 h-4 text-sky-600" />
              </div>
              <div className="text-2xl font-black text-ink-950">
                {rain === null ? "—" : rain.toFixed(1)}{" "}
                <small className="text-xs font-normal text-ink-500">mm/h</small>
              </div>
              <p className="text-[10px] text-ink-500">
                {rain === null ? "Chưa có dữ liệu đủ mới" : `Cập nhật: ${observationTime(live.weather?.rain_observed_at)}`}
              </p>
            </GlassCard>

            {/* KPI 3 */}
            <GlassCard className="p-4 space-y-1">
              <div className="flex items-center justify-between text-xs text-ink-500">
                <span>Mực triều</span>
                <Waves className="w-4 h-4 text-indigo-600" />
              </div>
              <div className="text-2xl font-black text-ink-950">
                {tide === null ? "—" : tide.toFixed(2)}{" "}
                <small className="text-xs font-normal text-ink-500">m</small>
              </div>
              <p className="text-[10px] text-ink-500">
                {live.weather?.tide_datum || "Chưa xác minh hệ mốc"}
              </p>
            </GlassCard>

            {/* KPI 4 */}
            <GlassCard className="p-4 space-y-1">
              <div className="flex items-center justify-between text-xs text-ink-500">
                <span>Dịch vụ định tuyến</span>
                <Navigation className="w-4 h-4 text-emerald-600" />
              </div>
              <div className="text-2xl font-black text-emerald-700">
                {live.health?.osrm === "available" ? "Sẵn sàng" : "Chưa khả dụng"}
              </div>
              <p className="text-[10px] text-ink-500">
                Tuyến đường theo kết quả dịch vụ OSRM
              </p>
            </GlassCard>
          </div>
        </section>

        {/* SECTION 2 & 3: Hành trình của tôi + Giao thông quanh tôi */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* LEFT: Hành trình của tôi (7 cols) */}
          <section className="lg:col-span-7 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-black text-xs uppercase tracking-wider text-ink-800">
                <Bookmark className="w-4 h-4 text-indigo-600" />
                <span>Hành trình thường nhật của tôi</span>
              </div>
              {isAuthenticated && (
                <GlassButton
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowAdd(!showAdd)}
                  className="text-indigo-600 hover:text-indigo-700"
                >
                  <Plus className="w-3.5 h-3.5 mr-1" />
                  Thêm địa điểm
                </GlassButton>
              )}
            </div>

            {/* Add Place Form */}
            {showAdd && (
              <GlassCard className="p-4 space-y-3 animate-fadeIn">
                <div className="font-bold text-xs text-ink-800">Lưu địa điểm mới:</div>
                <form onSubmit={createPlace} className="space-y-3">
                  <div className="flex items-center gap-3 text-xs">
                    <span className="font-semibold text-ink-700">Loại địa điểm:</span>
                    <select
                      value={label}
                      onChange={(e) => setLabel(e.target.value)}
                      className="rounded-xl border border-slate-300 p-1.5 text-xs bg-white text-ink-900"
                    >
                      <option>Nhà</option>
                      <option>Cơ quan</option>
                      <option>Trường học</option>
                      <option>Khác</option>
                    </select>
                  </div>

                  <PlaceSearchCombobox
                    label="Tìm địa chỉ lưu"
                    placeholder="Nhập tên đường, địa chỉ hoặc địa danh..."
                    color="emerald"
                    value={query}
                    onChangeText={(t) => {
                      setQuery(t);
                      setPlace(null);
                    }}
                    selectedCoordinates={place ? { lat: place.lat, lng: place.lng } : null}
                    onSelectPlace={setPlace}
                    ariaLabel="Địa chỉ cần lưu"
                  />

                  {place && (
                    <p className="text-[11px] text-ink-500 font-mono">
                      {place.display_name} • {place.lat.toFixed(4)}, {place.lng.toFixed(4)}
                    </p>
                  )}

                  <div className="flex justify-end gap-2 pt-1">
                    <GlassButton
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowAdd(false)}
                    >
                      Hủy
                    </GlassButton>
                    <GlassButton
                      type="submit"
                      variant="primary"
                      size="sm"
                      disabled={!place || busy}
                    >
                      {busy ? "Đang lưu..." : "Lưu địa điểm"}
                    </GlassButton>
                  </div>
                </form>
              </GlassCard>
            )}

            {/* Saved Places List */}
            <div className="grid gap-3 sm:grid-cols-2">
              {(user?.savedPlaces || []).map((item) => (
                <GlassCard key={item.id} className="p-3.5 flex items-center justify-between gap-2 text-xs">
                  <div className="space-y-1 min-w-0">
                    <div className="flex items-center gap-1.5 font-bold text-ink-900">
                      <MapPin className="w-3.5 h-3.5 text-indigo-600 shrink-0" />
                      <span className="truncate">{item.name}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-slate-100 text-ink-500 font-normal">
                        {item.label}
                      </span>
                    </div>
                    <p className="text-[11px] text-ink-500 truncate">{item.address}</p>
                  </div>

                  <div className="flex items-center gap-1 shrink-0">
                    <Link
                      href={`/di-duong?origin=${item.lat},${item.lng}`}
                      className="p-2 hover:bg-indigo-50 rounded-xl text-indigo-600 transition"
                      title="Tìm tuyến từ đây"
                    >
                      <ArrowRight className="w-4 h-4" />
                    </Link>
                    <button
                      onClick={() => remove(item.id)}
                      className="p-2 hover:bg-rose-50 rounded-xl text-slate-400 hover:text-rose-600 transition"
                      title="Xóa địa điểm"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </GlassCard>
              ))}
            </div>

            {!user?.savedPlaces?.length && (
              <div className="p-4 text-center rounded-2xl border border-slate-200/80 bg-white/60 text-xs text-ink-500">
                Chưa có địa điểm đã lưu. {isAuthenticated ? "Nhấn 'Thêm địa điểm' ở trên để lưu Nhà hoặc Cơ quan." : "Đăng nhập Google để quản lý các địa điểm thường đi."}
              </div>
            )}

            {/* Lịch sử tìm đường */}
            <div className="space-y-2 pt-1">
              <div className="flex items-center gap-1.5 font-bold text-xs text-ink-700">
                <Clock className="w-3.5 h-3.5 text-indigo-500" />
                <span>Lịch sử tìm đường</span>
              </div>
              {user?.history?.length ? user.history.map(item => (
                <GlassCard key={item.id} className="space-y-2">
                  <p className="text-sm font-semibold">{item.originName} → {item.destName}</p>
                  <p className="text-xs text-ink-600">{item.distanceKm.toFixed(1)} km · {Math.round(item.durationMins)} phút · {observationTime(item.timestamp)}</p>
                  <p className="text-xs text-ink-500">Kết quả đã lưu; cần tính lại trước khi khởi hành.</p>
                </GlassCard>
              )) : <div className="p-3 text-center rounded-2xl border border-slate-200/80 bg-white/60 text-xs text-ink-500">
                Chưa có lịch sử tìm đường. Các lộ trình vừa tra cứu sẽ xuất hiện tại đây.
              </div>}
            </div>
          </section>

          {/* RIGHT: Giao thông quanh tôi (5 cols) */}
          <section className="lg:col-span-5 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-black text-xs uppercase tracking-wider text-ink-800">
                <Camera className="w-4 h-4 text-indigo-600" />
                <span>Giao thông quanh tôi (Camera trực tiếp)</span>
              </div>
              <Link href="/monitor" className="text-xs text-indigo-600 hover:underline font-semibold">
                Xem tất cả ↗
              </Link>
            </div>

            <div className="grid grid-cols-2 gap-3">
              {nearbyCameras.map((cam) => {
                const imgUrl = getCameraImageUrl(cam.cam_id);
                return (
                  <GlassCard
                    key={cam.cam_id}
                    onClick={() => setSelectedCamera(cam)}
                    className="p-2.5 space-y-2 cursor-pointer hover:border-indigo-300 transition group"
                  >
                    <div className="h-24 w-full bg-slate-100 rounded-xl overflow-hidden relative border border-slate-200">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={imgUrl}
                        alt={cam.name}
                        className="w-full h-full object-cover group-hover:scale-105 transition duration-300"
                        onError={(e) => {
                          e.currentTarget.style.display = "none";
                        }}
                      />
                      <span className="absolute bottom-1.5 left-1.5 px-1.5 py-0.5 rounded-md bg-black/70 text-white font-mono text-[9px]">
                        {cam.vehicle_count !== null ? `${cam.vehicle_count} xe` : "Trực tiếp"}
                      </span>
                    </div>

                    <div className="space-y-0.5">
                      <p className="text-[11px] font-bold text-ink-900 line-clamp-1 leading-snug">
                        {cam.name}
                      </p>
                      <p className="text-[10px] text-ink-500 flex items-center justify-between">
                        <span>{observationTime(cam.retrieved_at)}</span>
                        <span className="text-indigo-600 font-semibold group-hover:underline">Chi tiết</span>
                      </p>
                    </div>
                  </GlassCard>
                );
              })}
            </div>

            {nearbyCameras.length === 0 && (
              <div className="p-6 text-center rounded-2xl border border-slate-200/80 bg-white/60 text-xs text-ink-400">
                {live.loading ? "Đang tải camera…" : "Chưa có ảnh camera khả dụng"}
              </div>
            )}
          </section>
        </div>

        <CommunityReports />
      </main>

      {/* Camera Evidence Modal on click */}
      <CameraEvidenceModal
        camera={selectedCamera}
        onClose={() => setSelectedCamera(null)}
      />
    </div>
  );
}
