"use client";

import React, { useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { SafeRouteResponse, WebSocketAlertMessage } from "../types/contracts";
import { distanceMeters, instructionForStep, isVerifiedRouteAlert, type TrackedPosition } from "../lib/navigation";
import { Navigation, Pause, Play, RotateCcw, Square, Volume2, VolumeX } from "lucide-react";

export type GuidanceState = "idle" | "route_preview" | "navigating" | "paused" | "ended";

export interface NavigationGuidanceHandle {
  start: () => void;
  pause: () => void;
  stop: () => void;
  toggleVoice: () => void;
  getState: () => GuidanceState;
}

export interface NavigationGuidanceProps {
  route: SafeRouteResponse | null;
  explanation: string;
  latestAlert: WebSocketAlertMessage | null;
  onPositionUpdate: (position: TrackedPosition) => void;
  onStateChange?: (state: GuidanceState) => void;
  onInstructionChange?: (instruction: string, stepIndex: number, totalSteps: number) => void;
}

export const NavigationGuidance = React.forwardRef<NavigationGuidanceHandle, NavigationGuidanceProps>((
  {
    route,
    explanation,
    latestAlert,
    onPositionUpdate,
    onStateChange,
    onInstructionChange,
  },
  ref
) => {
  const [state, setState] = useState<GuidanceState>(route ? "route_preview" : "idle");
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [trackingEnabled, setTrackingEnabled] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const speakingRef = useRef(false);
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const stateRef = useRef(state);
  const voiceRef = useRef(voiceEnabled);
  const routeRef = useRef(route);
  const stepIndexRef = useRef(stepIndex);
  const lastStepAtRef = useRef(0);
  const lastAlertAtRef = useRef(0);
  const seenAlertsRef = useRef(new Set<string>());
  const utteranceTokenRef = useRef(0);
  stateRef.current = state;
  voiceRef.current = voiceEnabled;
  routeRef.current = route;
  stepIndexRef.current = stepIndex;

  const cancelSpeech = useCallback(() => {
    utteranceTokenRef.current++;
    if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
    speakingRef.current = false;
  }, []);

  const speak = useCallback(
    (message: string, replace = true) => {
      if (
        stateRef.current !== "navigating" ||
        !voiceRef.current ||
        document.visibilityState !== "visible" ||
        !("speechSynthesis" in window) ||
        !("SpeechSynthesisUtterance" in window)
      )
        return false;
      if (!replace && (window.speechSynthesis.speaking || speakingRef.current)) return false;
      if (replace) cancelSpeech();
      const token = ++utteranceTokenRef.current;
      const utterance = new SpeechSynthesisUtterance(message);
      utterance.lang = "vi-VN";
      utterance.rate = 1;
      const vietnamese = window.speechSynthesis.getVoices().find((voice) => voice.lang.toLowerCase().startsWith("vi"));
      if (vietnamese) utterance.voice = vietnamese;
      utterance.onstart = () => {
        if (utteranceTokenRef.current === token) speakingRef.current = true;
      };
      utterance.onend = utterance.onerror = () => {
        if (utteranceTokenRef.current === token) speakingRef.current = false;
      };
      speakingRef.current = true;
      try {
        window.speechSynthesis.speak(utterance);
      } catch {
        speakingRef.current = false;
        return false;
      }
      return true;
    },
    [cancelSpeech]
  );

  useEffect(() => {
    cancelSpeech();
    stateRef.current = route?.route_id ? "route_preview" : "idle";
    voiceRef.current = false;
    setState(route?.route_id ? "route_preview" : "idle");
    setVoiceEnabled(false);
    setTrackingEnabled(false);
    setStepIndex(0);
    setTrackingError(null);
    seenAlertsRef.current.clear();
    lastStepAtRef.current = 0;
    lastAlertAtRef.current = 0;
  }, [route?.route_id, cancelSpeech]);

  useEffect(() => {
    const utteranceCounter = utteranceTokenRef;
    const onVisibility = () => {
      cancelSpeech();
      if (document.visibilityState !== "visible" && stateRef.current === "navigating") {
        stateRef.current = "paused";
        setState("paused");
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      utteranceCounter.current++;
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    };
  }, [cancelSpeech]);

  useEffect(() => {
    if (state !== "navigating" || !trackingEnabled) return;
    if (!("geolocation" in navigator)) {
      setTrackingError("Thiết bị không hỗ trợ theo dõi vị trí.");
      setTrackingEnabled(false);
      return;
    }
    const watchId = navigator.geolocation.watchPosition(
      (position) => {
        const current = {
          lat: position.coords.latitude,
          lng: position.coords.longitude,
          accuracy: position.coords.accuracy,
        };
        onPositionUpdate(current);
        const activeRoute = routeRef.current;
        if (
          !activeRoute ||
          stateRef.current !== "navigating" ||
          !Number.isFinite(current.accuracy) ||
          current.accuracy! > 100
        )
          return;
        const nextIndex = activeRoute.segments.findIndex(
          (step, index) =>
            index > stepIndexRef.current && step.maneuver_type && step.maneuver_location?.length === 2
        );
        if (nextIndex < 0) return;
        const next = activeRoute.segments[nextIndex];
        const [lng, lat] = next.maneuver_location!;
        if (!Number.isFinite(lng) || !Number.isFinite(lat)) return;
        const threshold = Math.max(45, Math.min(110, current.accuracy! + 40));
        const now = Date.now();
        if (distanceMeters(current, lng, lat) <= threshold && now - lastStepAtRef.current >= 7000) {
          stepIndexRef.current = nextIndex;
          setStepIndex(nextIndex);
          lastStepAtRef.current = now;
          if (next.maneuver_type === "arrive") {
            stateRef.current = "ended";
            setState("ended");
            cancelSpeech();
            return;
          }
          const instruction = instructionForStep(next);
          if (instruction) speak(instruction);
        }
      },
      (error) => {
        setTrackingError(
          error.code === 1 ? "Chưa được cấp quyền theo dõi vị trí." : "Không thể cập nhật vị trí hiện tại."
        );
        setTrackingEnabled(false);
      },
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 10000 }
    );
    return () => navigator.geolocation.clearWatch(watchId);
  }, [state, trackingEnabled, onPositionUpdate, speak, cancelSpeech]);

  useEffect(() => {
    if (!latestAlert?.event_id || seenAlertsRef.current.has(latestAlert.event_id)) return;
    if (seenAlertsRef.current.size >= 100) seenAlertsRef.current.delete(seenAlertsRef.current.values().next().value!);
    seenAlertsRef.current.add(latestAlert.event_id);
    const activeRoute = routeRef.current;
    const now = Date.now();
    if (
      state !== "navigating" ||
      !voiceEnabled ||
      !activeRoute ||
      now - lastAlertAtRef.current < 60000 ||
      !isVerifiedRouteAlert(latestAlert, activeRoute, now, stepIndexRef.current)
    )
      return;
    lastAlertAtRef.current = now;
    speak(`Cảnh báo trên tuyến đang đi. ${latestAlert.message}`, false);
  }, [latestAlert, state, voiceEnabled, speak]);

  const instructions = React.useMemo(() => route?.segments.map(instructionForStep) || [], [route]);
  const canNavigate = instructions.some(Boolean);
  const currentInstruction = instructions[stepIndex] || "Chưa có hướng rẽ từ nhà cung cấp định tuyến.";

  const start = useCallback(() => {
    if (!route || !canNavigate) return;
    seenAlertsRef.current.add(latestAlert?.event_id || "");
    const firstIndex = instructions.findIndex(Boolean);
    stepIndexRef.current = firstIndex;
    setStepIndex(firstIndex);
    stateRef.current = "navigating";
    setState("navigating");
    const first = instructions[firstIndex];
    if (voiceEnabled && first) speak(first);
  }, [route, canNavigate, latestAlert?.event_id, instructions, voiceEnabled, speak]);

  const pause = useCallback(() => {
    stateRef.current = "paused";
    setState("paused");
    cancelSpeech();
  }, [cancelSpeech]);

  const stop = useCallback(() => {
    stateRef.current = "ended";
    setState("ended");
    setTrackingEnabled(false);
    setVoiceEnabled(false);
    cancelSpeech();
  }, [cancelSpeech]);

  const toggleVoice = useCallback(() => {
    if (voiceEnabled) {
      setVoiceEnabled(false);
      voiceRef.current = false;
      cancelSpeech();
    } else {
      setVoiceEnabled(true);
      voiceRef.current = true;
    }
  }, [voiceEnabled, cancelSpeech]);

  useImperativeHandle(
    ref,
    () => ({
      start,
      pause,
      stop,
      toggleVoice,
      getState: () => stateRef.current,
    }),
    [start, pause, stop, toggleVoice]
  );

  useEffect(() => {
    onStateChange?.(state);
  }, [state, onStateChange]);

  useEffect(() => {
    onInstructionChange?.(currentInstruction, stepIndex, instructions.length);
  }, [currentInstruction, stepIndex, instructions.length, onInstructionChange]);

  const label: Record<GuidanceState, string> = {
    idle: "Chưa có tuyến",
    route_preview: "Xem trước tuyến",
    navigating: "Đang chỉ đường",
    paused: "Đã tạm dừng",
    ended: "Đã kết thúc",
  };

  return (
    <section
      className="rounded-3xl bg-gradient-to-br from-white/95 via-indigo-50/20 to-white/90 p-4 text-xs text-ink-900 border border-white/95 shadow-glass backdrop-blur-xl"
      aria-label="Hướng dẫn hành trình"
      data-navigation-state={state}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 font-black text-ink-950 text-xs sm:text-sm tracking-tight">
          <Navigation className="h-4 w-4 text-indigo-600" />
          <span>Hướng dẫn bằng giọng nói</span>
        </h3>
        <span
          className={`text-[11px] px-3 py-0.5 rounded-full border shadow-glass-sm tracking-tight font-bold select-none ${
            state === "idle"
              ? "bg-slate-100/90 text-ink-900 border-slate-300"
              : "bg-indigo-50/90 text-indigo-700 border-indigo-200"
          }`}
        >
          {label[state]}
        </span>
      </div>

      {route ? (
        <>
          {state === "route_preview" && (
            <p data-testid="route-explanation" className="mt-2.5 text-xs leading-relaxed text-ink-600 font-medium">
              {explanation}
            </p>
          )}

          {(state === "navigating" || state === "paused") && (
            <p
              aria-live="polite"
              className="mt-2.5 rounded-2xl glass-panel-elevated p-3.5 text-xs sm:text-sm font-bold text-ink-950 border border-indigo-200/80 shadow-glass-sm"
            >
              {currentInstruction}
            </p>
          )}

          {state === "ended" && (
            <p className="mt-2.5 text-xs text-ink-500 font-medium">
              Hướng dẫn đã dừng. Bạn có thể bắt đầu lại khi sẵn sàng.
            </p>
          )}

          {(state === "route_preview" || state === "ended") && (
            <div className="mt-3.5 space-y-2 text-xs text-ink-700">
              <label className="flex min-h-8 cursor-pointer items-center gap-2.5 hover:text-ink-950 transition">
                <input
                  type="checkbox"
                  checked={voiceEnabled}
                  onChange={(event) => setVoiceEnabled(event.target.checked)}
                  className="h-4 w-4 rounded accent-indigo-600 cursor-pointer"
                />
                <span className="font-semibold">Bật giọng hướng dẫn khi bắt đầu</span>
              </label>
              <label className="flex min-h-8 cursor-pointer items-center gap-2.5 hover:text-ink-950 transition">
                <input
                  type="checkbox"
                  checked={trackingEnabled}
                  onChange={(event) => setTrackingEnabled(event.target.checked)}
                  className="h-4 w-4 rounded accent-indigo-600 cursor-pointer"
                />
                <span className="font-semibold">Theo dõi vị trí của tôi khi đi</span>
              </label>
              <p className="text-[11px] text-ink-500">
                Chỉ xin quyền vị trí khi bạn bật theo dõi và bắt đầu.
              </p>
            </div>
          )}

          {trackingError && (
            <p role="alert" className="mt-2 text-xs text-amber-700 font-medium">
              {trackingError}
            </p>
          )}

          <div className="mt-3.5 flex flex-wrap gap-2">
            {(state === "route_preview" || state === "ended") && (
              <button
                type="button"
                onClick={start}
                disabled={!canNavigate}
                className="aurora-btn-primary flex min-h-10 items-center gap-1.5 rounded-2xl px-4 text-xs font-bold disabled:opacity-40 cursor-pointer shadow-md"
              >
                <Play className="h-4 w-4" />
                <span>Bắt đầu chỉ đường</span>
              </button>
            )}
            {state === "navigating" && (
              <button
                type="button"
                onClick={pause}
                className="bg-white/85 hover:bg-white text-ink-800 hover:text-ink-950 border border-white/90 shadow-glass-sm flex min-h-10 items-center gap-1.5 rounded-2xl px-3.5 text-xs font-bold transition cursor-pointer"
              >
                <Pause className="h-4 w-4 text-ink-600" />
                <span>Tạm dừng</span>
              </button>
            )}
            {state === "paused" && (
              <button
                type="button"
                onClick={() => {
                  stateRef.current = "navigating";
                  setState("navigating");
                }}
                className="aurora-btn-primary flex min-h-10 items-center gap-1.5 rounded-2xl px-4 text-xs font-bold cursor-pointer shadow-md"
              >
                <Play className="h-4 w-4" />
                <span>Tiếp tục</span>
              </button>
            )}
            {(state === "navigating" || state === "paused") && (
              <button
                type="button"
                onClick={stop}
                className="bg-white/85 hover:bg-white text-ink-800 hover:text-ink-950 border border-white/90 shadow-glass-sm flex min-h-10 items-center gap-1.5 rounded-2xl px-3.5 text-xs font-bold transition cursor-pointer"
              >
                <Square className="h-4 w-4 text-ink-600" />
                <span>Dừng chỉ đường</span>
              </button>
            )}
            {state === "navigating" && (
              <>
                <button
                  type="button"
                  onClick={toggleVoice}
                  className="bg-white/85 hover:bg-white text-ink-800 hover:text-ink-950 border border-white/90 shadow-glass-sm flex min-h-10 items-center gap-1.5 rounded-2xl px-3.5 text-xs font-bold transition cursor-pointer"
                >
                  {voiceEnabled ? (
                    <VolumeX className="h-4 w-4 text-rose-500" />
                  ) : (
                    <Volume2 className="h-4 w-4 text-indigo-600" />
                  )}
                  <span>{voiceEnabled ? "Tắt tiếng" : "Bật tiếng"}</span>
                </button>
                <button
                  type="button"
                  onClick={() => speak(currentInstruction)}
                  disabled={!voiceEnabled || !instructions[stepIndex]}
                  className="bg-white/85 hover:bg-white text-ink-800 hover:text-ink-950 border border-white/90 shadow-glass-sm flex min-h-10 items-center gap-1.5 rounded-2xl px-3.5 text-xs font-bold transition disabled:opacity-40 cursor-pointer"
                >
                  <RotateCcw className="h-4 w-4 text-ink-600" />
                  <span>Đọc lại</span>
                </button>
              </>
            )}
          </div>

          {!canNavigate && (
            <p className="mt-2 text-xs text-amber-600">
              Chưa có hướng rẽ chi tiết cho tuyến này; chưa thể phát chỉ đường.
            </p>
          )}
        </>
      ) : (
        <p className="mt-2 text-xs text-ink-500">
          Tìm tuyến đường để xem trước và bắt đầu chỉ đường.
        </p>
      )}
    </section>
  );
});

NavigationGuidance.displayName = "NavigationGuidance";
