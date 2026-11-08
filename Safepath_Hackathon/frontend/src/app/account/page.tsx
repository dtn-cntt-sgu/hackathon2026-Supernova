"use client";

import React, { useState } from "react";
import Link from "next/link";
import { PlaceSearchCombobox } from "../../components/PlaceSearchCombobox";
import type { PlaceResult } from "../../types/contracts";
import { AppPageHeader } from "../../components/ui/AppPageHeader";
import { useAuth } from "../../context/AuthContext";
import {
  User,
  ArrowLeft,
  Bike,
  Car,
  CheckCircle,
  AlertCircle,
  Key,
  LogOut,
  LogIn,
  MapPin,
  Clock,
  Trash2,
  Plus,
  Shield,
  ShieldAlert,
} from "lucide-react";
import { GlassCard, GlassButton, GlassBadge } from "../../components/Glass";

export default function AccountPage() {
  const {
    user,
    isAuthenticated,
    isConfigured,
    oauthStatus,
    loginWithGoogle,
    logout,
    updateVehicle,
    savePlace,
    removeSavedPlace,
  } = useAuth();

  const [saveToast, setSaveToast] = useState<string | null>(null);
  const [showAddPlace, setShowAddPlace] = useState(false);
  const [newPlaceName, setNewPlaceName] = useState("");
  const [newPlaceAddress, setNewPlaceAddress] = useState("");
  const [selectedPlace, setSelectedPlace] = useState<PlaceResult | null>(null);
  const [savingPlace, setSavingPlace] = useState(false);
  const [newPlaceCategory, setNewPlaceCategory] = useState("favorite");

  const handleVehicleChange = async (v: "motorcycle" | "car") => {
    if (!isAuthenticated) {
      setSaveToast("Vui lòng đăng nhập để lưu phương tiện mặc định vào tài khoản.");
      setTimeout(() => setSaveToast(null), 3000);
      return;
    }
    await updateVehicle(v);
    setSaveToast("Đã cập nhật phương tiện di chuyển chính vào cơ sở dữ liệu!");
    setTimeout(() => setSaveToast(null), 3000);
  };

  const handleAddPlaceSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newPlaceName.trim() || !selectedPlace || !isAuthenticated || savingPlace) return;
    setSavingPlace(true);
    try {
      await savePlace({ name: newPlaceName.trim(), address: selectedPlace.display_name, lat: selectedPlace.lat, lng: selectedPlace.lng, label: newPlaceCategory });
      setNewPlaceName(""); setNewPlaceAddress(""); setSelectedPlace(null); setShowAddPlace(false);
      setSaveToast("Đã lưu địa điểm mới thành công!");
    } catch { setSaveToast("Không lưu được địa điểm. Vui lòng thử lại."); }
    finally { setSavingPlace(false); }

  };

  return (
    <div className="flex flex-col min-h-screen max-w-full overflow-x-hidden bg-gradient-to-b from-pearl-50 via-ice-50 to-pearl-100 text-ink-900 relative selection:bg-indigo-600 selection:text-white">
      {/* Background aurora mist (fixed to viewport so it gracefully covers full document scroll) */}
      <div className="fixed top-[-10%] left-[-5%] w-[50vw] h-[50vw] rounded-full bg-gradient-to-br from-indigo-200/30 via-ice-200/25 to-transparent blur-3xl pointer-events-none -z-10" />
      <div className="fixed bottom-[-10%] right-[-5%] w-[45vw] h-[45vw] rounded-full bg-gradient-to-tl from-lavender-200/30 via-soft-cyan/25 to-transparent blur-3xl pointer-events-none -z-10" />

      {/* Header */}
      <AppPageHeader title="Tài khoản & Cài đặt" description="Hồ sơ, phương tiện và địa điểm của bạn" badge="Hồ sơ" />

      {/* Main Workspace */}
      <main className="flex-1 p-5 pb-16 max-w-4xl mx-auto w-full space-y-6">
        {saveToast && (
          <div className="p-3 bg-emerald-50 border border-emerald-300 rounded-2xl text-emerald-800 text-xs font-bold flex items-center gap-2 shadow-sm animate-fadeIn">
            <CheckCircle className="w-4 h-4 text-emerald-600" />
            <span>{saveToast}</span>
          </div>
        )}

        {/* Profile Card */}
        <GlassCard variant="elevated" className="space-y-4">
          <div className="flex flex-col sm:flex-row items-center gap-4 justify-between">
            <div className="flex items-center gap-4">
              <div className="w-16 h-16 rounded-full overflow-hidden border-2 border-indigo-200 shadow-glass bg-indigo-50 flex items-center justify-center shrink-0">
                {user?.avatar ? (
                  // Preserve remote source bytes without the image optimization proxy.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={user.avatar}
                    alt={user.name}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <User className="w-8 h-8 text-indigo-400" />
                )}
              </div>
              <div>
                <h3 className="text-base font-black text-ink-950">
                  {isAuthenticated && user ? user.name : "Bạn chưa đăng nhập"}
                </h3>
                <p className="text-xs text-ink-500">
                  {isAuthenticated && user ? user.email : "Đăng nhập Google để lưu địa điểm và lịch sử tuyến đường"}
                </p>
                <div className="mt-1 flex items-center gap-2">
                  <GlassBadge variant={isAuthenticated ? "emerald" : "slate"} size="sm">
                    {isAuthenticated ? "Đã xác thực Google" : "Khách (Chưa đăng nhập)"}
                  </GlassBadge>
                </div>
              </div>
            </div>

            <div>
              {isAuthenticated ? (
                <GlassButton variant="danger" size="sm" onClick={logout}>
                  <LogOut className="w-3.5 h-3.5 mr-1.5" />
                  <span>Đăng xuất</span>
                </GlassButton>
              ) : (
                <GlassButton
                  variant="primary"
                  size="md"
                  onClick={loginWithGoogle}
                  disabled={!isConfigured}
                  title={!isConfigured ? "Cần cấu hình AUTH_GOOGLE_ID và AUTH_GOOGLE_SECRET" : "Đăng nhập bằng tài khoản Google"}
                >
                  <LogIn className="w-4 h-4 mr-1.5" />
                  <span>Tiếp tục với Google</span>
                </GlassButton>
              )}
            </div>
          </div>
        </GlassCard>

        {/* Vehicle Selection Card */}
        <GlassCard variant="elevated" className="space-y-4">
          <div className="border-b border-slate-200/70 pb-3">
            <h4 className="text-xs font-bold uppercase tracking-wider text-ink-800 flex items-center gap-2">
              <Car className="w-4 h-4 text-indigo-600" />
              <span>Phương tiện di chuyển chính</span>
            </h4>
            <p className="text-xs text-ink-500 mt-1">
              Hệ thống SafePathAI điều chỉnh ngưỡng cảnh báo ngập nước dựa trên độ cao gầm xe của bạn.
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Motorcycle option */}
            <div
              onClick={() => handleVehicleChange("motorcycle")}
              className={`p-4 rounded-3xl border transition cursor-pointer flex items-center gap-4 ${
                (user?.vehicle || "motorcycle") === "motorcycle"
                  ? "bg-white border-indigo-300 shadow-glass-elevated ring-2 ring-indigo-400/25"
                  : "bg-white/70 border-slate-200/80 hover:bg-white"
              }`}
            >
              <div className="p-3 bg-indigo-50 border border-indigo-100 rounded-2xl text-indigo-600">
                <Bike className="w-6 h-6" />
              </div>
              <div className="space-y-0.5">
                <div className="text-sm font-bold text-ink-950 flex items-center gap-1.5">
                  <span>Xe máy (2 bánh)</span>
                  {(user?.vehicle || "motorcycle") === "motorcycle" && (
                    <CheckCircle className="w-4 h-4 text-indigo-600" />
                  )}
                </div>
                <p className="text-[11px] text-ink-500 leading-snug">
                  Cảnh báo rủi ro khi mực nước vượt quá 15 - 20cm (tránh ngập ống xả & lọc gió).
                </p>
              </div>
            </div>

            {/* Car option */}
            <div
              onClick={() => handleVehicleChange("car")}
              className={`p-4 rounded-3xl border transition cursor-pointer flex items-center gap-4 ${
                user?.vehicle === "car"
                  ? "bg-white border-indigo-300 shadow-glass-elevated ring-2 ring-indigo-400/25"
                  : "bg-white/70 border-slate-200/80 hover:bg-white"
              }`}
            >
              <div className="p-3 bg-blue-50 border border-blue-100 rounded-2xl text-blue-600">
                <Car className="w-6 h-6" />
              </div>
              <div className="space-y-0.5">
                <div className="text-sm font-bold text-ink-950 flex items-center gap-1.5">
                  <span>Ô tô (4 bánh)</span>
                  {user?.vehicle === "car" && (
                    <CheckCircle className="w-4 h-4 text-indigo-600" />
                  )}
                </div>
                <p className="text-[11px] text-ink-500 leading-snug">
                  Cảnh báo rủi ro khi mực nước vượt quá 25 - 30cm (tránh thủy kích & trôi xe).
                </p>
              </div>
            </div>
          </div>
        </GlassCard>

        {/* Saved Places Card */}
        <GlassCard variant="elevated" className="space-y-4">
          <div className="flex items-center justify-between border-b border-slate-200/70 pb-3">
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-ink-800 flex items-center gap-2">
                <MapPin className="w-4 h-4 text-emerald-600" />
                <span>Địa điểm đã lưu ({user?.savedPlaces?.length || 0})</span>
              </h4>
              <p className="text-xs text-ink-500 mt-1">
                Lưu nhanh các vị trí thường đi để chọn tuyến chỉ với 1 chạm.
              </p>
            </div>
            {isAuthenticated && (
              <GlassButton
                variant="secondary"
                size="sm"
                onClick={() => setShowAddPlace(!showAddPlace)}
              >
                <Plus className="w-3.5 h-3.5 mr-1" />
                <span>{showAddPlace ? "Đóng" : "Thêm mới"}</span>
              </GlassButton>
            )}
          </div>

          {!isAuthenticated ? (
            <div className="p-4 rounded-2xl bg-slate-50 border border-slate-200 text-center text-xs text-ink-500">
              Bạn đang ở chế độ khách. Hãy đăng nhập tài khoản để lưu các địa điểm yêu thích.
            </div>
          ) : (
            <div className="space-y-3">
              {showAddPlace && (
                <form onSubmit={handleAddPlaceSubmit} className="p-3.5 bg-indigo-50/60 rounded-2xl border border-indigo-200/80 space-y-3">
                  <div className="font-bold text-xs text-indigo-950">Thêm địa điểm yêu thích mới</div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    <input
                      type="text"
                      placeholder="Tên gợi nhớ (e.g. Nhà riêng, Cơ quan)"
                      value={newPlaceName}
                      onChange={(e) => setNewPlaceName(e.target.value)}
                      className="px-3 py-1.5 rounded-xl border border-indigo-200 bg-white text-xs text-ink-900 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      required
                    />
                    <PlaceSearchCombobox label="Địa chỉ thực tế" placeholder="Tìm địa chỉ tại TP.HCM" color="emerald"
                      value={newPlaceAddress} onChangeText={text => { setNewPlaceAddress(text); setSelectedPlace(null); }}
                      selectedCoordinates={selectedPlace} onSelectPlace={setSelectedPlace} ariaLabel="Địa chỉ cần lưu" />
                  </div>
                  <div className="flex justify-end gap-2">
                    <GlassButton type="button" variant="ghost" size="sm" onClick={() => setShowAddPlace(false)}>Hủy</GlassButton>
                    <GlassButton disabled={!selectedPlace || savingPlace} type="submit" variant="primary" size="sm">Lưu địa điểm</GlassButton>
                  </div>
                </form>
              )}

              {user?.savedPlaces && user.savedPlaces.length > 0 ? (
                <div className="divide-y divide-slate-100">
                  {user.savedPlaces.map((sp) => (
                    <div key={sp.id} className="py-2.5 flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <div className="p-2 rounded-xl bg-emerald-50 text-emerald-600 border border-emerald-100">
                          <MapPin className="w-4 h-4" />
                        </div>
                        <div>
                          <div className="text-xs font-bold text-ink-950">{sp.name}</div>
                          <div className="text-[11px] text-ink-500">{sp.address || sp.name}</div>
                        </div>
                      </div>
                      <button
                        onClick={() => removeSavedPlace(sp.id)}
                        className="p-1.5 rounded-lg text-rose-500 hover:bg-rose-50 transition"
                        title="Xóa địa điểm"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-3 text-center text-xs text-ink-400">
                  Chưa có địa điểm nào được lưu trong cơ sở dữ liệu.
                </div>
              )}
            </div>
          )}
        </GlassCard>

        {/* Route History Card */}
        <GlassCard variant="elevated" className="space-y-4">
          <div className="border-b border-slate-200/70 pb-3">
            <h4 className="text-xs font-bold uppercase tracking-wider text-ink-800 flex items-center gap-2">
              <Clock className="w-4 h-4 text-blue-600" />
              <span>Lịch sử các tuyến đường đã tìm ({user?.history?.length || 0})</span>
            </h4>
            <p className="text-xs text-ink-500 mt-1">
              Lưu trữ an toàn trên cơ sở dữ liệu PostgreSQL cho tài khoản đã xác thực.
            </p>
          </div>

          {!isAuthenticated ? (
            <div className="p-4 rounded-2xl bg-slate-50 border border-slate-200 text-center text-xs text-ink-500">
              Bạn đang ở chế độ khách. Các tuyến đường tìm kiếm sẽ không được lưu vào tài khoản.
            </div>
          ) : user?.history && user.history.length > 0 ? (
            <div className="divide-y divide-slate-100 max-h-60 overflow-y-auto">
              {user.history.map((h) => (
                <div key={h.id} className="py-2.5 flex items-center justify-between">
                  <div className="space-y-0.5">
                    <div className="text-xs font-bold text-ink-950 flex items-center gap-1.5">
                      <span>{h.originName}</span>
                      <span className="text-slate-400">→</span>
                      <span>{h.destName}</span>
                    </div>
                    <div className="text-[10px] text-ink-400 font-mono">
                      {h.distanceKm.toFixed(1)} km • ~{Math.round(h.durationMins)} phút • {new Date(h.timestamp).toLocaleDateString("vi-VN")}
                    </div>
                  </div>
                  <GlassBadge variant="indigo" size="sm">
                    {Math.round(h.durationMins)}p
                  </GlassBadge>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-3 text-center text-xs text-ink-400">
              Chưa có lịch sử lộ trình nào.
            </div>
          )}
        </GlassCard>

        {/* Bảo mật & Quyền riêng tư */}
        <GlassCard variant="elevated" className="space-y-4">
          <div className="flex items-center gap-2 font-bold text-xs uppercase tracking-wider text-ink-800 border-b border-slate-200/70 pb-3">
            <Shield className="w-4 h-4 text-indigo-600" />
            <span>Bảo mật & Quyền riêng tư</span>
          </div>

          {isAuthenticated ? (
            <div className="p-4 rounded-2xl bg-white/80 border border-emerald-200/60 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs shadow-glass-sm">
              <div className="space-y-1">
                <div className="flex items-center gap-2 text-emerald-800 font-semibold">
                  <CheckCircle className="w-4 h-4 text-emerald-600" />
                  <span>Tài khoản Google đã liên kết</span>
                </div>
                <p className="text-[11px] text-ink-600 font-mono">
                  {user?.email || "Đã đăng nhập bảo mật"}
                </p>
                <p className="text-[11px] text-ink-500">
                  Dữ liệu lộ trình và địa điểm đã lưu được đồng bộ an toàn qua đám mây riêng.
                </p>
              </div>
              <GlassButton
                variant="ghost"
                size="sm"
                onClick={logout}
                className="text-rose-700 hover:text-rose-800 hover:bg-rose-50 self-start sm:self-auto"
              >
                <LogOut className="w-3.5 h-3.5 mr-1.5" />
                Đăng xuất
              </GlassButton>
            </div>
          ) : (
            <div className="p-4 rounded-2xl bg-white/80 border border-slate-200/80 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs shadow-glass-sm">
              <div className="space-y-1">
                <div className="flex items-center gap-2 text-ink-800 font-semibold">
                  <Shield className="w-4 h-4 text-indigo-600" />
                  <span>Chế độ Khách bảo mật</span>
                </div>
                <p className="text-[11px] text-ink-500 leading-relaxed">
                  Dữ liệu lộ trình và tùy chọn lưu cục bộ trên thiết bị của bạn. Đăng nhập Google để đồng bộ lịch sử và cá nhân hóa trải nghiệm.
                </p>
              </div>
              <GlassButton
                variant="primary"
                size="sm"
                onClick={loginWithGoogle}
                className="self-start sm:self-auto shrink-0 shadow-glass-sm"
              >
                <LogIn className="w-3.5 h-3.5 mr-1.5" />
                Đăng nhập Google
              </GlassButton>
            </div>
          )}
        </GlassCard>
      </main>
    </div>
  );
}
