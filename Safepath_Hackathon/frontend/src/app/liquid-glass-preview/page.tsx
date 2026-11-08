"use client";

import React, { useState } from "react";
import Link from "next/link";
import { LiquidGlass } from "@/components/ui/LiquidGlass";
import { Navigation, ArrowUpRight, Sparkles, Shield, Compass, MapPin } from "lucide-react";

export default function LiquidGlassPreviewPage() {
  const [activeTab, setActiveTab] = useState("all");
  const [sliderAberration, setSliderAberration] = useState(3);
  const [sliderBevel, setSliderBevel] = useState(14);
  const [sliderScale, setSliderScale] = useState(40);

  return (
    <div className="relative min-h-screen bg-gradient-to-br from-slate-100 via-sky-50 to-indigo-100 text-slate-800 p-6 md:p-12 overflow-hidden selection:bg-indigo-600 selection:text-white">
      {/* Dynamic Background Elements to clearly reveal refraction */}
      <div className="fixed -top-24 -left-24 w-96 h-96 rounded-full bg-gradient-to-tr from-blue-500/30 to-indigo-500/20 blur-2xl pointer-events-none" />
      <div className="fixed top-1/3 -right-20 w-80 h-80 rounded-full bg-gradient-to-bl from-teal-400/30 to-cyan-500/20 blur-2xl pointer-events-none" />
      <div className="fixed -bottom-20 left-1/4 w-[36rem] h-72 rounded-full bg-gradient-to-r from-purple-400/20 via-pink-300/20 to-blue-300/20 blur-3xl pointer-events-none" />

      {/* Grid Pattern Behind Glass */}
      <div className="fixed inset-0 bg-[linear-gradient(to_right,#0284c715_1px,transparent_1px),linear-gradient(to_bottom,#0284c715_1px,transparent_1px)] bg-[size:4rem_4rem] pointer-events-none" />

      <header className="relative z-10 max-w-5xl mx-auto mb-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-100 text-indigo-700 text-xs font-bold mb-2">
            <Sparkles size={14} /> Aceternity Liquid Glass V2 Engine
          </div>
          <h1 className="text-3xl md:text-4xl font-extrabold text-[#142A3B] tracking-tight">
            SafePath AI Liquid Glass Laboratory
          </h1>
          <p className="text-sm text-slate-600 mt-1">
            Kiểm thử quang học: khúc xạ Snell&apos;s law, tán sắc chromatic aberration, viền cong phản xạ và chế độ fallback.
          </p>
        </div>
        <Link
          href="/"
          className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/90 text-slate-700 hover:text-indigo-600 font-semibold text-sm border border-slate-200 shadow-sm transition"
        >
          Quay lại Landing <ArrowUpRight size={16} />
        </Link>
      </header>

      {/* Interactive Controls Bar */}
      <div className="relative z-10 max-w-5xl mx-auto mb-8 p-4 rounded-2xl bg-white/70 backdrop-blur-md border border-white/90 shadow-sm flex flex-wrap items-center justify-between gap-4 text-xs font-medium">
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-1.5">
            <span>Tán sắc ({sliderAberration}px):</span>
            <input
              type="range"
              min="0"
              max="8"
              step="0.5"
              value={sliderAberration}
              onChange={(e) => setSliderAberration(parseFloat(e.target.value))}
              className="w-24 accent-indigo-600"
            />
          </label>
          <label className="flex items-center gap-1.5">
            <span>Viền vát ({sliderBevel}px):</span>
            <input
              type="range"
              min="4"
              max="28"
              value={sliderBevel}
              onChange={(e) => setSliderBevel(parseInt(e.target.value))}
              className="w-24 accent-indigo-600"
            />
          </label>
          <label className="flex items-center gap-1.5">
            <span>Cường độ khúc xạ ({sliderScale}px):</span>
            <input
              type="range"
              min="10"
              max="70"
              value={sliderScale}
              onChange={(e) => setSliderScale(parseInt(e.target.value))}
              className="w-24 accent-indigo-600"
            />
          </label>
        </div>

        <div className="flex items-center gap-1 bg-slate-200/60 p-1 rounded-xl">
          {["all", "pill", "button", "panel", "modal"].map((t) => (
            <button
              key={t}
              onClick={() => setActiveTab(t)}
              className={`px-2.5 py-1 rounded-lg capitalize transition ${
                activeTab === t
                  ? "bg-white text-indigo-700 shadow-xs font-bold"
                  : "text-slate-600 hover:text-slate-900"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      <main className="relative z-10 max-w-5xl mx-auto space-y-12">
        {/* VARIANT 1: PILL (Navbar, Segmented Controls) */}
        {(activeTab === "all" || activeTab === "pill") && (
          <section className="space-y-4">
            <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-indigo-600" /> Variant: Pill (Navbar & Segmented Controls)
            </h2>
            <div className="p-8 rounded-3xl bg-gradient-to-r from-blue-600/10 via-teal-500/10 to-indigo-600/10 border border-slate-200 flex flex-col items-center justify-center gap-6">
              {/* Simulated Landing Navbar */}
              <LiquidGlass
                variant="pill"
                scale={sliderScale}
                aberration={sliderAberration}
                bevelDepth={sliderBevel}
                className="w-full max-w-3xl px-5 py-3 flex items-center justify-between"
              >
                <div className="flex items-center gap-2 font-black text-slate-900">
                  <div className="p-1.5 rounded-xl bg-gradient-to-tr from-indigo-600 to-sky-500 text-white shadow-sm">
                    <Navigation size={16} />
                  </div>
                  SafePath<span className="text-indigo-600">AI</span>
                </div>
                <div className="hidden sm:flex items-center gap-6 text-xs font-bold text-slate-700">
                  <span className="text-indigo-600 cursor-pointer">01 Đô thị 3D</span>
                  <span className="hover:text-indigo-600 cursor-pointer">02 Nguy cơ ngập</span>
                  <span className="hover:text-indigo-600 cursor-pointer">03 Bản tin</span>
                  <span className="hover:text-indigo-600 cursor-pointer">04 Điều hướng</span>
                </div>
                <button className="px-4 py-1.5 rounded-full bg-gradient-to-r from-indigo-600 to-sky-500 text-white text-xs font-bold shadow-md hover:brightness-105 transition">
                  Bắt đầu ngay
                </button>
              </LiquidGlass>

              {/* Segmented Chapter Nav Pills */}
              <div className="flex flex-wrap items-center gap-3">
                <LiquidGlass variant="pill" className="px-4 py-2 flex items-center gap-2 text-xs font-semibold text-slate-800">
                  <Compass size={14} className="text-indigo-600" />
                  <span>Khu vực: Quận 1 & Bình Thạnh</span>
                </LiquidGlass>
                <LiquidGlass variant="pill" className="px-4 py-2 flex items-center gap-2 text-xs font-semibold text-slate-800">
                  <Shield size={14} className="text-emerald-600" />
                  <span>796 Camera Đang Giám Sát</span>
                </LiquidGlass>
              </div>
            </div>
          </section>
        )}

        {/* VARIANT 2: BUTTON (Floating Action Buttons) */}
        {(activeTab === "all" || activeTab === "button") && (
          <section className="space-y-4">
            <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-teal-500" /> Variant: Button (Interactive Controls)
            </h2>
            <div className="p-8 rounded-3xl bg-gradient-to-r from-teal-500/10 via-sky-500/10 to-indigo-500/10 border border-slate-200 flex flex-wrap items-center justify-center gap-6">
              <LiquidGlass as="button" variant="button" interactive className="px-6 py-2.5 flex items-center gap-2 text-xs font-bold text-slate-800 hover:text-indigo-600">
                <MapPin size={16} className="text-rose-500" /> Vị trí hiện tại
              </LiquidGlass>

              <LiquidGlass as="button" variant="button" interactive className="px-6 py-2.5 flex items-center gap-2 text-xs font-bold text-indigo-700 bg-white/60">
                <Sparkles size={16} className="text-amber-500" /> Xem 3D Không gian
              </LiquidGlass>

              <LiquidGlass as="button" variant="button" interactive className="px-6 py-2.5 flex items-center gap-2 text-xs font-bold text-slate-800">
                Lọc Camera Ngập Nước (ON_ROUTE)
              </LiquidGlass>
            </div>
          </section>
        )}

        {/* VARIANT 3: PANEL (Route Card & Floating Sidebar) */}
        {(activeTab === "all" || activeTab === "panel") && (
          <section className="space-y-4">
            <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-sky-500" /> Variant: Panel (Floating Cards & Route Panels)
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <LiquidGlass
                variant="panel"
                interactive
                scale={sliderScale * 0.7}
                aberration={sliderAberration * 0.7}
                className="p-6 space-y-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-indigo-600 uppercase tracking-wider">
                    01 / Phân tích rủi ro tuyến đường
                  </span>
                  <span className="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 text-[10px] font-bold">
                    AN TOÀN
                  </span>
                </div>
                <h3 className="text-lg font-bold text-slate-900">
                  Lộ trình: Bến Thành → Landmark 81
                </h3>
                <p className="text-xs text-slate-600 leading-relaxed">
                  Đường đi qua đường Nguyễn Hữu Cảnh và Điện Biên Phủ hiện thông thoáng, không ghi nhận ngập triều hoặc mưa giông.
                </p>
                <div className="pt-2 flex items-center justify-between text-xs font-semibold text-slate-700 border-t border-slate-200/60">
                  <span>Khoảng cách: 5.4 km</span>
                  <span>Thời gian: ~14 phút</span>
                </div>
              </LiquidGlass>

              <LiquidGlass
                variant="panel"
                interactive
                scale={sliderScale * 0.7}
                aberration={sliderAberration * 0.7}
                className="p-6 space-y-3"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-amber-600 uppercase tracking-wider">
                    02 / Quan trắc Thủy văn
                  </span>
                  <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 text-[10px] font-bold">
                    TRIỀU CAO
                  </span>
                </div>
                <h3 className="text-lg font-bold text-slate-900">
                  Trạm Phú An: 1.58m
                </h3>
                <p className="text-xs text-slate-600 leading-relaxed">
                  Mực nước sông Sài Gòn đang ở mức báo động II. Đề xuất xe gầm thấp tránh các đoạn trũng tại Quận 7 và Nhà Bè.
                </p>
                <div className="pt-2 flex items-center justify-between text-xs font-semibold text-slate-700 border-t border-slate-200/60">
                  <span>Dự báo đỉnh triều: 18:30</span>
                  <span className="text-indigo-600 font-bold cursor-pointer">Chi tiết bản đồ →</span>
                </div>
              </LiquidGlass>
            </div>
          </section>
        )}

        {/* VARIANT 4: MODAL SHELL */}
        {(activeTab === "all" || activeTab === "modal") && (
          <section className="space-y-4">
            <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-purple-500" /> Variant: Modal (Popup Shell)
            </h2>
            <div className="p-8 rounded-3xl bg-slate-200/40 border border-slate-200 flex justify-center">
              <LiquidGlass
                variant="modal"
                className="w-full max-w-lg p-6 space-y-4"
              >
                <div className="flex items-center justify-between border-b border-slate-200/80 pb-3">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500" />
                    <h4 className="font-bold text-sm text-slate-900">Camera TTH 1.1 · Mai Chí Thọ</h4>
                  </div>
                  <span className="text-[11px] font-mono text-slate-500">LIVE · 60s Refresh</span>
                </div>

                <div className="aspect-video rounded-2xl bg-slate-900 flex items-center justify-center text-white text-xs font-mono shadow-inner">
                  [Hình ảnh camera và kết quả YOLO giữ sắc nét, không bị filter biến dạng]
                </div>

                <div className="flex items-center justify-between text-xs text-slate-600">
                  <span>Trạng thái: <strong>Không phát hiện ngập</strong></span>
                  <button className="px-3 py-1 rounded-xl bg-slate-900 text-white font-bold text-xs hover:bg-slate-800 transition">
                    Đóng
                  </button>
                </div>
              </LiquidGlass>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

