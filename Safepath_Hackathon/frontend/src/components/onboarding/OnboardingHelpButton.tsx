"use client";

import React from "react";
import { HelpCircle, Sparkles } from "lucide-react";
import { useOnboarding } from "./OnboardingProvider";
import { usePathname } from "next/navigation";

interface OnboardingHelpButtonProps {
  className?: string;
  variant?: "pill" | "icon" | "minimal";
}

export function OnboardingHelpButton({
  className = "",
  variant = "pill",
}: OnboardingHelpButtonProps) {
  const { startTour, openWelcomeModal } = useOnboarding();
  const pathname = usePathname();

  const handleClick = () => {
    if (pathname.startsWith("/news")) {
      startTour("news");
    } else {
      startTour("map");
    }
  };

  if (variant === "icon") {
    return (
      <button
        type="button"
        onClick={handleClick}
        className={`p-2 rounded-full glass-pill border border-white/90 text-ink-700 hover:text-indigo-600 hover:bg-white shadow-glass-sm transition cursor-pointer ${className}`}
        title="Hướng dẫn sử dụng SafePathAI"
        aria-label="Hướng dẫn sử dụng"
      >
        <HelpCircle className="w-4 h-4 text-indigo-600" />
      </button>
    );
  }

  if (variant === "minimal") {
    return (
      <button
        type="button"
        onClick={handleClick}
        className={`text-xs font-semibold text-indigo-700 hover:text-indigo-900 transition flex items-center gap-1 cursor-pointer ${className}`}
        aria-label="Xem hướng dẫn sử dụng"
      >
        <HelpCircle className="w-3.5 h-3.5" />
        <span>Hướng dẫn</span>
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      className={`glass-pill px-3 py-1.5 rounded-full text-xs font-semibold text-ink-800 hover:text-indigo-700 bg-white/80 hover:bg-white border border-white/90 shadow-glass-sm transition flex items-center gap-1.5 cursor-pointer ${className}`}
      title="Khám phá các bước hướng dẫn sử dụng"
      aria-label="Hướng dẫn sử dụng"
    >
      <Sparkles className="w-3.5 h-3.5 text-indigo-600 animate-pulse" />
      <span className="hidden sm:inline">Hướng dẫn sử dụng</span>
    </button>
  );
}

