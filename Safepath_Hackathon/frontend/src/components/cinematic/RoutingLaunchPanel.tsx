"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Navigation, ArrowUpRight, Sparkles, AlertCircle, CheckCircle2 } from "lucide-react";
import { LiquidGlassCard } from "../ui/LiquidGlassCard";
import { PlaceSearchCombobox } from "../PlaceSearchCombobox";
import type { PlaceResult } from "../../types/contracts";

interface RoutePreset {
  label: string;
  origin: PlaceResult;
  destination: PlaceResult;
}

const PRESETS: RoutePreset[] = [
  {
    label: "Bến Thành → Landmark 81",
    origin: {
      id: "preset_ben_thanh",
      name: "Chợ Bến Thành",
      display_name: "Chợ Bến Thành, Quận 1, TP.HCM",
      lat: 10.7725,
      lng: 106.6980,
      type: "landmark",
      city: "TP. Hồ Chí Minh",
      provenance: "osm.hcm_preset",
    },
    destination: {
      id: "preset_landmark_81",
      name: "Landmark 81",
      display_name: "Tòa nhà Landmark 81, Bình Thạnh, TP.HCM",
      lat: 10.7950,
      lng: 106.7218,
      type: "landmark",
      city: "TP. Hồ Chí Minh",
      provenance: "osm.hcm_preset",
    },
  },
  {
    label: "Sân bay TSN → Quận 1",
    origin: {
      id: "preset_tan_son_nhat",
      name: "Sân bay Tân Sơn Nhất",
      display_name: "Cảng hàng không QT Tân Sơn Nhất, Tân Bình, TP.HCM",
      lat: 10.8185,
      lng: 106.6588,
      type: "airport",
      city: "TP. Hồ Chí Minh",
      provenance: "osm.hcm_preset",
    },
    destination: {
      id: "preset_duc_ba",
      name: "Nhà thờ Đức Bà",
      display_name: "Nhà thờ Đức Bà, Quận 1, TP.HCM",
      lat: 10.7798,
      lng: 106.6990,
      type: "landmark",
      city: "TP. Hồ Chí Minh",
      provenance: "osm.hcm_preset",
    },
  },
  {
    label: "Hàng Xanh → Bến Thành",
    origin: {
      id: "preset_hang_xanh",
      name: "Ngã tư Hàng Xanh",
      display_name: "Ngã tư Hàng Xanh, Bình Thạnh, TP.HCM",
      lat: 10.8012,
      lng: 106.7115,
      type: "intersection",
      city: "TP. Hồ Chí Minh",
      provenance: "osm.hcm_preset",
    },
    destination: {
      id: "preset_ben_thanh",
      name: "Chợ Bến Thành",
      display_name: "Chợ Bến Thành, Quận 1, TP.HCM",
      lat: 10.7725,
      lng: 106.6980,
      type: "landmark",
      city: "TP. Hồ Chí Minh",
      provenance: "osm.hcm_preset",
    },
  },
];

export function RoutingLaunchPanel() {
  const [origin, setOrigin] = useState<PlaceResult | null>(null);
  const [destination, setDestination] = useState<PlaceResult | null>(null);
  const [originText, setOriginText] = useState("");
  const [destinationText, setDestinationText] = useState("");

  const query = new URLSearchParams();
  if (origin) {
    query.set("origin", `${origin.lat},${origin.lng}`);
    query.set("originName", origin.name);
  }
  if (destination) {
    query.set("destination", `${destination.lat},${destination.lng}`);
    query.set("destinationName", destination.name);
  }

  const isOriginUnresolved = originText.trim().length > 0 && !origin;
  const isDestUnresolved = destinationText.trim().length > 0 && !destination;
  const isReady = !!origin && !!destination;

  const handleApplyPreset = (preset: RoutePreset) => {
    setOrigin(preset.origin);
    setOriginText(preset.origin.name);
    setDestination(preset.destination);
    setDestinationText(preset.destination.name);
  };

  return (
    <LiquidGlassCard className="route-ready !max-w-3xl !mx-auto">
      {/* Top Header Badge */}
      <div className="flex items-center justify-center gap-2 mb-2">
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-sky-50 text-[#168BD2] border border-sky-200/80 shadow-xs">
          <Navigation size={13} className="text-[#168BD2]" />
          04 / ĐỊNH TUYẾN THÔNG MINH
        </span>
      </div>

      {/* Main Heading */}
      <h2 className="route-heading text-xl sm:text-2xl md:text-3xl font-extrabold text-[#142A3B] tracking-tight leading-snug my-2">
        HÀNH TRÌNH THÔNG MINH BẮT ĐẦU TỪ ĐÂY.
        <br />
        <span className="bg-gradient-to-r from-[#168BD2] via-[#0284C7] to-[#18B6AD] bg-clip-text text-transparent">
          Chủ động lộ trình an toàn trước ngập nước.
        </span>
      </h2>

      <p className="text-xs sm:text-sm text-slate-600 max-w-xl mx-auto leading-relaxed mb-4">
        Chọn địa điểm thực tế để tính toán lộ trình tối ưu qua OSRM và đối chiếu bằng chứng quan trắc camera thời gian thực.
      </p>

      {/* Quick Preset Route Chips */}
      <div className="flex flex-wrap items-center justify-center gap-2 mb-4">
        <span className="text-[11px] font-semibold text-slate-500 flex items-center gap-1">
          <Sparkles size={12} className="text-amber-500" /> Tuyến gợi ý:
        </span>
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => handleApplyPreset(p)}
            className="text-[11px] font-medium px-2.5 py-1 rounded-full bg-white/90 hover:bg-sky-50 text-slate-700 hover:text-[#168BD2] border border-slate-200/90 hover:border-sky-300 transition-all shadow-2xs"
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Inputs Grid */}
      <div className="routing-launch-inputs grid grid-cols-1 sm:grid-cols-2 gap-3 text-left mb-3">
        <div>
          <PlaceSearchCombobox
            label="Điểm xuất phát"
            placeholder="Tìm địa chỉ xuất phát (ví dụ: Chợ Bến Thành)"
            color="emerald"
            value={originText}
            onChangeText={(text) => {
              setOriginText(text);
              setOrigin(null);
            }}
            selectedCoordinates={origin}
            onSelectPlace={setOrigin}
            ariaLabel="Điểm xuất phát của hành trình"
            testId="landing-origin-combobox"
          />
          {isOriginUnresolved && (
            <p className="text-[11px] text-amber-600 mt-1 flex items-center gap-1">
              <AlertCircle size={12} /> Chọn từ danh sách gợi ý để có tọa độ GPS
            </p>
          )}
          {origin && (
            <p className="text-[11px] text-emerald-600 mt-1 flex items-center gap-1 font-medium">
              <CheckCircle2 size={12} /> Tọa độ: {origin.lat.toFixed(4)}, {origin.lng.toFixed(4)}
            </p>
          )}
        </div>

        <div>
          <PlaceSearchCombobox
            label="Điểm đến"
            placeholder="Bạn muốn đến đâu? (ví dụ: Landmark 81)"
            color="rose"
            value={destinationText}
            onChangeText={(text) => {
              setDestinationText(text);
              setDestination(null);
            }}
            selectedCoordinates={destination}
            onSelectPlace={setDestination}
            ariaLabel="Điểm đến của hành trình"
            testId="landing-destination-combobox"
          />
          {isDestUnresolved && (
            <p className="text-[11px] text-amber-600 mt-1 flex items-center gap-1">
              <AlertCircle size={12} /> Chọn từ danh sách gợi ý để có tọa độ GPS
            </p>
          )}
          {destination && (
            <p className="text-[11px] text-emerald-600 mt-1 flex items-center gap-1 font-medium">
              <CheckCircle2 size={12} /> Tọa độ: {destination.lat.toFixed(4)}, {destination.lng.toFixed(4)}
            </p>
          )}
        </div>
      </div>

      {/* Caution Note */}
      <p className="text-[11px] text-slate-500 max-w-lg mx-auto leading-relaxed mb-4">
        Tuyến đường được tính toán dựa trên mô hình định tuyến OSRM kết hợp dữ liệu ngập nước thực tế. Bạn có thể bật hướng dẫn bằng giọng nói khi di chuyển.
      </p>

      {/* Action CTA */}
      <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
        {isReady ? (
          <Link
            href={`/map?${query.toString()}`}
            className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3 rounded-full font-bold text-sm text-white bg-gradient-to-r from-[#168BD2] to-[#18B6AD] hover:from-[#137BBF] hover:to-[#149E97] shadow-md hover:shadow-lg transition-all transform hover:-translate-y-0.5 active:translate-y-0"
            data-testid="landing-start-routing-btn"
          >
            <span>Mở bản đồ hành trình</span>
            <ArrowUpRight size={18} />
          </Link>
        ) : (
          <Link
            href="/map"
            className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3 rounded-full font-bold text-sm text-white bg-gradient-to-r from-[#168BD2] to-[#18B6AD] hover:from-[#137BBF] hover:to-[#149E97] shadow-md hover:shadow-lg transition-all transform hover:-translate-y-0.5 active:translate-y-0"
            data-testid="landing-start-routing-btn"
          >
            <span>MỞ BẢN ĐỒ ĐIỀU HƯỚNG</span>
            <ArrowUpRight size={18} />
          </Link>
        )}
      </div>
    </LiquidGlassCard>
  );
}
