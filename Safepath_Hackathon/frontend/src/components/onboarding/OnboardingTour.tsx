"use client";

import React, { useEffect, useRef, useState, useCallback } from "react";
import { usePathname } from "next/navigation";
import { driver, Driver } from "driver.js";
import "driver.js/dist/driver.css";
import "../../styles/onboarding.css";
import { useOnboarding } from "./OnboardingProvider";
import { MAP_TOUR_STEPS, NEWS_TOUR_STEPS } from "../../lib/onboarding/tourSteps";
import {
  Navigation,
  Compass,
  Sparkles,
  ArrowRight,
  X,
  ShieldCheck,
  CheckCircle,
} from "lucide-react";

export function OnboardingTour() {
  const pathname = usePathname();
  const {
    activeTour,
    welcomeOpen,
    startTour,
    stopTour,
    skipTour,
    completeTour,
    closeWelcomeModal,
  } = useOnboarding();

  const driverInstanceRef = useRef<Driver | null>(null);
  const [pointerPos, setPointerPos] = useState<{
    top: number;
    left: number;
    width: number;
    height: number;
    visible: boolean;
  }>({ top: 0, left: 0, width: 0, height: 0, visible: false });

  // Update hand pointer position to match highlighted element
  const updatePointerPosition = useCallback((element: Element | null) => {
    if (!element) {
      setPointerPos((prev) => ({ ...prev, visible: false }));
      return;
    }
    const rect = element.getBoundingClientRect();
    setPointerPos({
      top: rect.top,
      left: rect.left,
      width: rect.width,
      height: rect.height,
      visible: true,
    });
  }, []);

  // Cleanup driver on unmount or route change
  useEffect(() => {
    return () => {
      if (driverInstanceRef.current) {
        driverInstanceRef.current.destroy();
        driverInstanceRef.current = null;
      }
      setPointerPos((prev) => ({ ...prev, visible: false }));
    };
  }, [pathname]);

  // Launch Driver.js when activeTour is set
  useEffect(() => {
    if (!activeTour) {
      if (driverInstanceRef.current) {
        driverInstanceRef.current.destroy();
        driverInstanceRef.current = null;
      }
      setPointerPos((prev) => ({ ...prev, visible: false }));
      return;
    }

    const steps = activeTour === "map" ? MAP_TOUR_STEPS : NEWS_TOUR_STEPS;

    // Filter available elements on page (safety check & mobile visibility check)
    const availableSteps = steps.filter((step) => {
      let el: Element | null = null;
      if (typeof step.element === "string") {
        el = document.querySelector(step.element);
      } else if (step.element instanceof Element) {
        el = step.element;
      }
      if (!el) return false;
      const style = window.getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden") {
        return false;
      }
      return true;
    });

    if (availableSteps.length === 0) {
      console.warn("No tour target elements found on page for", activeTour);
      stopTour();
      return;
    }

    const d = driver({
      showProgress: true,
      animate: true,
      smoothScroll: true,
      allowClose: true,
      allowKeyboardControl: true,
      stagePadding: 6,
      stageRadius: 14,
      popoverOffset: 12,
      progressText: "{{current}} / {{total}}",
      nextBtnText: "Tiếp tục →",
      prevBtnText: "← Quay lại",
      doneBtnText: "Hoàn tất ✓",
      steps: availableSteps,
      onHighlightStarted: (element) => {
        if (element) {
          element.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
          updatePointerPosition(element);
        }
      },
      onHighlighted: (element) => {
        if (element) {
          updatePointerPosition(element);
        }
      },
      onPopoverRender: (popover, opts) => {
        if (opts.config.steps && opts.index !== undefined && opts.index < opts.config.steps.length - 1) {
          let skipBtn = popover.footer.querySelector<HTMLButtonElement>(".driver-popover-skip-btn");
          if (!skipBtn) {
            skipBtn = document.createElement("button");
            skipBtn.className = "driver-popover-skip-btn";
            skipBtn.innerText = "Bỏ qua";
            skipBtn.setAttribute("type", "button");
            skipBtn.setAttribute("aria-label", "Bỏ qua hướng dẫn");
            skipBtn.addEventListener("click", () => {
              skipTour();
              opts.driver.destroy();
            });
            popover.footer.insertBefore(skipBtn, popover.footerButtons);
          }
        }
      },
      onDoneClick: () => {
        setPointerPos((prev) => ({ ...prev, visible: false }));
        if (activeTour) {
          completeTour(activeTour);
        }
        if (driverInstanceRef.current) {
          driverInstanceRef.current.destroy();
          driverInstanceRef.current = null;
        }
      },
      onCloseClick: () => {
        setPointerPos((prev) => ({ ...prev, visible: false }));
        skipTour();
        if (driverInstanceRef.current) {
          driverInstanceRef.current.destroy();
          driverInstanceRef.current = null;
        }
      },
      onDestroyed: () => {
        setPointerPos((prev) => ({ ...prev, visible: false }));
        driverInstanceRef.current = null;
        stopTour();
      },
    });

    driverInstanceRef.current = d;
    d.drive();

    return () => {
      if (driverInstanceRef.current) {
        driverInstanceRef.current.destroy();
        driverInstanceRef.current = null;
      }
    };
  }, [activeTour, completeTour, skipTour, stopTour, updatePointerPosition]);

  // Keep spotlight and hand pointer aligned on resize and scroll
  useEffect(() => {
    const handleReposition = () => {
      if (!driverInstanceRef.current?.isActive()) return;
      const activeEl = document.querySelector(".driver-active-element");
      if (activeEl) {
        updatePointerPosition(activeEl);
      }
    };
    window.addEventListener("scroll", handleReposition, { passive: true });
    window.addEventListener("resize", handleReposition, { passive: true });
    return () => {
      window.removeEventListener("scroll", handleReposition);
      window.removeEventListener("resize", handleReposition);
    };
  }, [updatePointerPosition]);

  return (
    <>
      {/* Interactive Hand Pointer & Pulse Ripple Overlay */}
      {pointerPos.visible && activeTour && (
        <>
          {/* Target Pulse Ripple */}
          <div
            className="safepath-tour-target-ripple"
            style={{
              top: `${Math.max(4, pointerPos.top - 4)}px`,
              left: `${Math.max(4, pointerPos.left - 4)}px`,
              width: `${pointerPos.width + 8}px`,
              height: `${pointerPos.height + 8}px`,
            }}
          />

          {/* Hand Pointer */}
          <div
            className="safepath-tour-hand-pointer"
            style={{
              top: `${Math.max(8, pointerPos.top + pointerPos.height * 0.4)}px`,
              left: `${Math.max(8, pointerPos.left + pointerPos.width - 12)}px`,
            }}
          >
            {/* Soft SVG Hand Cursor */}
            <svg
              className="safepath-tour-hand-icon"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                d="M10 2L10 11M10 11V6.5C10 5.67 9.33 5 8.5 5C7.67 5 7 5.67 7 6.5V13M10 11V8.5C10 7.67 10.67 7 11.5 7C12.33 7 13 7.67 13 8.5V11M10 11V9.5C10 8.67 10.67 8 11.5 8C12.33 8 13 8.67 13 9.5V12M13 11V10.5C13 9.67 13.67 9 14.5 9C15.33 9 16 9.67 16 10.5V14C16 17.87 12.87 21 9 21C5.13 21 2 17.87 2 14V11.5C2 10.67 2.67 10 3.5 10C4.33 10 5 10.67 5 11.5V14"
                stroke="#4338ca"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="#ffffff"
              />
            </svg>
          </div>
        </>
      )}

      {/* Welcome Popover Dialog (First-time user onboarding) - Soft backdrop without blurring entire page */}
      {welcomeOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="onboarding-welcome-title"
          className="fixed inset-0 z-[100002] flex items-center justify-center p-4 bg-slate-900/28 animate-fadeIn"
        >
          <div className="w-full max-w-md rounded-3xl glass-panel-elevated p-6 sm:p-7 border border-white/95 shadow-glass-elevated space-y-5 animate-scaleUp relative">
            {/* Close Button */}
            <button
              onClick={() => closeWelcomeModal(true)}
              className="absolute top-5 right-5 p-1.5 rounded-full text-ink-400 hover:text-ink-900 hover:bg-slate-100 transition"
              aria-label="Đóng hướng dẫn"
            >
              <X className="w-4 h-4" />
            </button>

            {/* Header Badge */}
            <div className="flex items-center gap-3">
              <div className="p-3 rounded-2xl bg-gradient-to-tr from-indigo-600 via-blue-600 to-sky-500 text-white shadow-md shadow-indigo-500/25">
                <Sparkles className="w-6 h-6 animate-pulse" />
              </div>
              <div>
                <span className="text-[10px] font-bold tracking-wider uppercase text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded-full border border-indigo-200/80">
                  Chào mừng bạn
                </span>
                <h3
                  id="onboarding-welcome-title"
                  className="text-lg font-black text-ink-950 tracking-tight mt-0.5"
                >
                  Chào mừng bạn đến SafePathAI!
                </h3>
              </div>
            </div>

            {/* Description */}
            <p className="text-xs sm:text-sm text-ink-600 leading-relaxed">
              Chúng tôi sẽ hướng dẫn bạn tìm đường tránh ngập, quan sát camera thực tế và cập nhật tin tức giao thông chỉ trong vài bước đơn giản.
            </p>

            {/* Feature Highlights */}
            <div className="space-y-2 py-1 text-xs text-ink-700">
              <div className="flex items-center gap-2">
                <CheckCircle className="w-4 h-4 text-emerald-500 shrink-0" />
                <span>Tìm lộ trình thông minh tránh ngập úng</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle className="w-4 h-4 text-emerald-500 shrink-0" />
                <span>Quan sát hình ảnh từ 796 camera giao thông</span>
              </div>
              <div className="flex items-center gap-2">
                <CheckCircle className="w-4 h-4 text-emerald-500 shrink-0" />
                <span>Bản tin giao thông cập nhật hằng ngày</span>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="pt-2 flex flex-col sm:flex-row items-center gap-2.5">
              <button
                type="button"
                onClick={() => {
                  const tour = pathname.startsWith("/news") ? "news" : "map";
                  startTour(tour);
                }}
                className="aurora-btn-primary w-full py-3 px-4 rounded-2xl font-bold text-xs flex items-center justify-center gap-2 shadow-md cursor-pointer"
              >
                <span>Bắt đầu hướng dẫn</span>
                <ArrowRight className="w-4 h-4" />
              </button>

              <button
                type="button"
                onClick={skipTour}
                className="w-full sm:w-auto py-3 px-4 rounded-2xl text-xs font-semibold text-ink-600 hover:text-ink-950 hover:bg-white/80 transition cursor-pointer text-center"
              >
                Bỏ qua
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
