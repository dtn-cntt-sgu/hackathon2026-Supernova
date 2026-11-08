"use client";

import { useEffect, useRef, useState } from "react";
import { getCameraProxyUrl } from "../services/api";

// Share a small request budget across cards and the modal.
let active = 0;
const waiting: (() => void)[] = [];
async function bounded<T>(work: () => Promise<T>): Promise<T> {
  await new Promise<void>((resolve) => {
    const start = () => { active++; resolve(); };
    if (active < 4) start(); else waiting.push(start);
  });
  try { return await work(); }
  finally { active--; waiting.shift()?.(); }
}

export function cameraSourceLabel(provider?: string | null): string {
  return provider === "vietmap" ? "Vietmap CDN" : provider === "hcmc" ? "Cổng Giao thông TP.HCM" : "Đang xác định";
}

export type CameraSnapshotFrame = { snapshotId: string; retrievedAt: string | null; provider: string | null };

export function CameraProxySnapshot({ camId, name, refreshMs = 30000, revision = 0, showMetadata = true, onFrame }: {
  camId: string; name: string; refreshMs?: number; revision?: number;
  showMetadata?: boolean; onFrame?: (frame: CameraSnapshotFrame) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);
  const [source, setSource] = useState<string | null>(null);
  const [status, setStatus] = useState("Chưa tải ảnh");
  const frameCallback = useRef(onFrame);
  frameCallback.current = onFrame;
  const [provider, setProvider] = useState<string | null>(null);
  const [received, setReceived] = useState<string | null>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    if (container.current) observer.observe(container.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible) return;
    setSource(null);
    setReceived(null);
    setStatus("Đang tải ảnh");
    let stopped = false;
    let running = false;
    let objectUrl: string | null = null;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      if (stopped || running || document.hidden) return;
      running = true;
      if (timer) clearTimeout(timer);
      controller = new AbortController();
      const signal = controller.signal;
      const timeout = setTimeout(() => controller?.abort(), 15000);
      try {
        await bounded(async () => {
          if (signal.aborted) return;
          const url = getCameraProxyUrl(camId);
          if (!url) throw new Error("INVALID_CAMERA_ID");
          const response = await fetch(`${url}?t=${Date.now()}`, { signal, cache: "no-store" });
          if (!response.ok) {
            const error = await response.json().catch(() => null);
            throw new Error(response.headers.get("X-Camera-Source-Status") || error?.detail?.code || "FETCH_FAILED");
          }
          const blob = await response.blob();
          if (!blob.type.startsWith("image/")) throw new Error("FETCH_FAILED");
          if (stopped || signal.aborted) return;
          const next = URL.createObjectURL(blob);
          if (objectUrl) URL.revokeObjectURL(objectUrl);
          objectUrl = next;
          setSource(next);
          setStatus(response.headers.get("X-Camera-Source-Status") || "RECENTLY_RETRIEVED_CAPTURE_UNKNOWN");
          setReceived(response.headers.get("X-Retrieved-At"));
          setProvider(response.headers.get("X-Camera-Provider"));
          const snapshotId = response.headers.get("X-Snapshot-ID");
          if (snapshotId) frameCallback.current?.({ snapshotId, retrievedAt: response.headers.get("X-Retrieved-At"), provider: response.headers.get("X-Camera-Provider") });
        });
      } catch (error) {
        if (!stopped) {
          // A retained frame is old evidence after a failed refresh.
          setStatus(objectUrl ? "STALE" : error instanceof Error && error.name !== "AbortError" ? error.message : "FETCH_FAILED");
        }
      } finally {
        clearTimeout(timeout);
        running = false;
        if (!stopped && refreshMs > 0) timer = setTimeout(refresh, Math.max(30000, refreshMs));
      }
    };
    const visibility = () => {
      if (document.hidden) { controller?.abort(); if (timer) clearTimeout(timer); }
      else if (refreshMs > 0 || !objectUrl) void refresh();
    };
    void refresh();
    document.addEventListener("visibilitychange", visibility);
    return () => {
      stopped = true;
      controller?.abort();
      if (timer) clearTimeout(timer);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [camId, visible, refreshMs, revision]);

  const message = status === "LIVE_VERIFIED" ? "Ảnh có giờ chụp đã xác minh"
    : status === "STALE" ? null
    : status === "RESTRICTED" ? "Nguồn đang hạn chế truy cập"
    : status === "OFFLINE" ? "Camera tạm mất kết nối"
    : status === "PLACEHOLDER" ? "Nguồn chưa có ảnh camera"
    : status === "RECENTLY_RETRIEVED_CAPTURE_UNKNOWN" ? null
    : status === "Đang tải ảnh" || status === "Chưa tải ảnh" ? status
    : "Chưa tải được ảnh";

  return <div ref={container} className="camera-proxy-snapshot w-full h-full min-h-32 bg-slate-100 flex flex-col">
    <div className="min-h-0 flex-1 flex items-center justify-center overflow-hidden">
      {!source && message && <span role="status" className="p-4 text-sm text-slate-600">{message}</span>}
      {/* Preserve remote source bytes without the image optimization proxy. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {source && <img src={source} alt={`Ảnh gốc camera ${name}`} className="w-full h-full object-contain" onError={() => { setSource(null); setStatus("FETCH_FAILED"); }} />}
    </div>
    {showMetadata && <div role="status" className="shrink-0 border-t border-slate-200 bg-white/95 text-ink-700 px-3 py-2 text-[10px] leading-relaxed">
      <span className="block">Nguồn: {cameraSourceLabel(provider)}</span>
      {received && <span className="block">Thời gian ảnh (nhận lúc): {new Date(received).toLocaleString("vi-VN")}</span>}
    </div>}
  </div>;
}
