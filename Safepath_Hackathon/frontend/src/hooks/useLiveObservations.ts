"use client";
import { useEffect, useRef, useState } from "react";
import { fetchCameras, fetchCameraSummary, fetchHealth, fetchModelStatus, fetchWeatherTide, fetchHydrologyBulletin } from "../services/api";
import type { CameraEvidence, CameraSummary, ModelStatusResponse, WeatherTideSignal, HydrologyBulletin } from "../types/contracts";

function areCamerasEqual(prev: CameraEvidence[], next: CameraEvidence[]): boolean {
  if (prev === next) return true;
  if (prev.length !== next.length) return false;
  for (let i = 0; i < prev.length; i++) {
    const p = prev[i];
    const n = next[i];
    if (
      p.cam_id !== n.cam_id ||
      p.source_status !== n.source_status ||
      p.has_image !== n.has_image ||
      p.snapshot_id !== n.snapshot_id ||
      p.frame_sha256 !== n.frame_sha256 ||
      p.updated_at !== n.updated_at ||
      p.vehicle_count !== n.vehicle_count ||
      p.flood_ratio !== n.flood_ratio
    ) {
      return false;
    }
  }
  return true;
}

export function useLiveObservations() {
  const [cameras, setCameras] = useState<CameraEvidence[]>([]);
  const [summary, setSummary] = useState<CameraSummary | null>(null);
  const [weather, setWeather] = useState<WeatherTideSignal | null>(null);
  const [hydrology, setHydrology] = useState<HydrologyBulletin | null>(null);
  const [models, setModels] = useState<ModelStatusResponse | null>(null);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(0);
  const [revision, setRevision] = useState(0);

  const prevLastCycleRef = useRef<string | null>(null);
  const prevCamerasRef = useRef<CameraEvidence[]>([]);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let refreshing = false;
    let fetchRegistry = true;

    async function refresh() {
      if (!active || refreshing) return;
      clearTimeout(timer);
      if (typeof document !== "undefined" && document.visibilityState === "hidden") {
        timer = setTimeout(refresh, 30000);
        return;
      }

      refreshing = true;
      try {
      // Fetch cameras on initial load or manual refresh
      const shouldFetchCameras = prevCamerasRef.current.length === 0 || fetchRegistry;

      fetchRegistry = false;
      const promises = [
        shouldFetchCameras ? fetchCameras() : Promise.resolve(null),
        fetchCameraSummary(),
        fetchWeatherTide(),
        fetchModelStatus(),
        fetchHealth(),
        fetchHydrologyBulletin(),
      ] as const;

      const results = await Promise.allSettled(promises);
      if (!active) return;

      const [c, s, w, m, h, b] = results;

      // Update Summary
      if (s.status === "fulfilled" && s.value) {
        setSummary(s.value);
        const lastCycle = s.value.last_scheduler_cycle;
        // If scheduler advanced to a new cycle and we didn't fetch cameras above, fetch them on next sweep
        if (lastCycle && lastCycle !== prevLastCycleRef.current && prevCamerasRef.current.length > 0 && !shouldFetchCameras) {
          prevLastCycleRef.current = lastCycle;
          await fetchCameras().then((latestCams) => {
            if (!active) return;
            const filtered = latestCams;
            if (!areCamerasEqual(prevCamerasRef.current, filtered)) {
              prevCamerasRef.current = filtered;
              setCameras(filtered);
            }
          }).catch(() => {});
        } else if (lastCycle) {
          prevLastCycleRef.current = lastCycle;
        }
      }

      // Update Cameras on explicit fetch
      if (c.status === "fulfilled" && c.value !== null) {
        const filtered = c.value;
        if (!areCamerasEqual(prevCamerasRef.current, filtered)) {
          prevCamerasRef.current = filtered;
          setCameras(filtered);
        }
      }

      setWeather(w.status === "fulfilled" ? w.value : null);
      setModels(m.status === "fulfilled" ? m.value : null);
      setHealth(h.status === "fulfilled" ? h.value : null);
      setHydrology(b.status === "fulfilled" ? b.value : null);

      const names = ["camera", "thống kê mạng lưới", "thời tiết / triều", "trạng thái mô hình", "hạ tầng", "bản tin thủy văn"];
      setErrors(results.flatMap((r, i) => (r.status === "rejected" ? [names[i]] : [])));
      setNow(Date.now());
      setLoading(false);

      } finally {
        refreshing = false;
        if (active) timer = setTimeout(refresh, 30000);
      }
    }

    const onVisibilityChange = () => {
      if (typeof document !== "undefined" && document.visibilityState === "visible" && active) {
        clearTimeout(timer);
        void refresh();
      }
    };

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibilityChange);
    }

    void refresh();
    const clock = setInterval(() => setNow(Date.now()), 30000);

    return () => {
      active = false;
      clearTimeout(timer);
      clearInterval(clock);
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibilityChange);
      }
    };
  }, [revision]);

  return {
    cameras,
    summary,
    weather,
    hydrology,
    models,
    health,
    errors,
    loading,
    now,
    refresh: () => setRevision((value) => value + 1),
  };
}
