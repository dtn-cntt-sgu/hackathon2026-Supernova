"use client";

import React, { useState, useRef, useEffect } from "react";
import { Camera, ChevronDown, Check, Layers, Image as ImageIcon, Route as RouteIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type CameraFilterMode = "ALL" | "ON_ROUTE" | "HAS_IMAGE";

interface GlassToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  disabled?: boolean;
  cameraCount?: { active: number; total: number };
  filter?: CameraFilterMode;
  onFilterChange?: (filter: CameraFilterMode) => void;
}

export default function GlassToggle({
  checked,
  onChange,
  label = "Hiển thị camera",
  disabled = false,
  cameraCount,
  filter = "ALL",
  onFilterChange,
}: GlassToggleProps) {
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Click / touch outside to close dropdown
  useEffect(() => {
    const handleOutside = (e: MouseEvent | TouchEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("touchstart", handleOutside);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("touchstart", handleOutside);
    };
  }, []);

  return (
    <div ref={containerRef} className="relative inline-flex items-center gap-1.5 select-none text-ink-900">
      {/* Main Switch Button — Constant Width, Zero Refraction Jank */}
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn(
          "cursor-pointer flex items-center justify-between gap-2 px-3 py-1.5 rounded-full text-xs font-semibold select-none",
          "min-w-[150px] sm:min-w-[160px] min-h-[44px] shadow-glass-sm glass-surface transition-all duration-200",
          checked
            ? "bg-gradient-to-r from-indigo-50/90 to-sky-50/80 border-indigo-300/80 text-indigo-800 ring-2 ring-indigo-400/20"
            : "text-ink-700 hover:text-ink-950 hover:border-white",
          disabled && "opacity-50 cursor-not-allowed"
        )}
        title={checked ? "Ẩn camera quan sát" : "Hiện camera quan sát"}
      >
        <div className="flex items-center gap-2">
          <div
            className={`p-1 rounded-full ${
              checked ? "bg-indigo-100 text-indigo-600" : "bg-slate-100 text-ink-500"
            }`}
          >
            <Camera className="w-3.5 h-3.5" />
          </div>
          <span className="font-medium">{label}</span>
        </div>
        <span
          className={`inline-flex items-center justify-center min-w-[32px] px-2 py-0.5 rounded-full text-[10px] font-bold tracking-wider ${
            checked ? "bg-indigo-600 text-white" : "bg-slate-200 text-ink-600"
          }`}
        >
          {checked ? "Bật" : "Tắt"}
        </span>
      </button>

      {/* Popover Filter Trigger when checked and onFilterChange provided */}
      {checked && onFilterChange && (
        <div className="relative">
          <button
            type="button"
            onClick={() => setDropdownOpen((v) => !v)}
            aria-label="Lọc loại camera"
            aria-expanded={dropdownOpen}
            className="flex items-center gap-1.5 px-2.5 py-1.5 min-h-[44px] min-w-[44px] rounded-full text-xs font-semibold glass-surface border border-white/90 shadow-glass-sm text-ink-700 hover:text-ink-950 cursor-pointer transition-all duration-200"
            title="Lọc loại camera"
          >
            {cameraCount && (
              <span className="text-[11px] font-mono font-bold text-indigo-600">
                {cameraCount.active}
              </span>
            )}
            <ChevronDown className={`w-3.5 h-3.5 text-ink-500 transition-transform ${dropdownOpen ? "rotate-180" : ""}`} />
          </button>

          {dropdownOpen && (
            <div
              role="menu"
              className="absolute right-0 top-full mt-2 w-52 max-w-[calc(100vw-32px)] z-30 animate-fadeIn text-xs rounded-2xl glass-panel-elevated border border-white/90 shadow-2xl p-1.5 space-y-1"
            >
              <div className="px-3 py-1.5 text-[10px] font-bold text-ink-400 uppercase tracking-wider border-b border-slate-100">
                {cameraCount ? `Đang hiện ${cameraCount.active}/${cameraCount.total} camera` : "Bộ lọc camera"}
              </div>

              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  onFilterChange("ALL");
                  setDropdownOpen(false);
                }}
                className={`w-full flex items-center justify-between px-3 py-2 min-h-[40px] rounded-xl text-left transition cursor-pointer ${
                  filter === "ALL" ? "bg-indigo-50/90 text-indigo-700 font-bold" : "text-ink-700 hover:bg-slate-100/80"
                }`}
              >
                <div className="flex items-center gap-2">
                  <Layers className="w-3.5 h-3.5 text-indigo-500 shrink-0" />
                  <span>Tất cả camera</span>
                </div>
                {filter === "ALL" && <Check className="w-3.5 h-3.5 shrink-0" />}
              </button>

              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  onFilterChange("ON_ROUTE");
                  setDropdownOpen(false);
                }}
                className={`w-full flex items-center justify-between px-3 py-2 min-h-[40px] rounded-xl text-left transition cursor-pointer ${
                  filter === "ON_ROUTE" ? "bg-indigo-50/90 text-indigo-700 font-bold" : "text-ink-700 hover:bg-slate-100/80"
                }`}
              >
                <div className="flex items-center gap-2">
                  <RouteIcon className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                  <span>Trên lộ trình</span>
                </div>
                {filter === "ON_ROUTE" && <Check className="w-3.5 h-3.5 shrink-0" />}
              </button>

              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  onFilterChange("HAS_IMAGE");
                  setDropdownOpen(false);
                }}
                className={`w-full flex items-center justify-between px-3 py-2 min-h-[40px] rounded-xl text-left transition cursor-pointer ${
                  filter === "HAS_IMAGE" ? "bg-indigo-50/90 text-indigo-700 font-bold" : "text-ink-700 hover:bg-slate-100/80"
                }`}
              >
                <div className="flex items-center gap-2">
                  <ImageIcon className="w-3.5 h-3.5 text-cyan-500 shrink-0" />
                  <span>Có ảnh trực tiếp</span>
                </div>
                {filter === "HAS_IMAGE" && <Check className="w-3.5 h-3.5 shrink-0" />}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
