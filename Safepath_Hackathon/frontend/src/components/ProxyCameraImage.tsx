"use client";

import { useEffect, useState } from "react";
import { getCameraImageUrl } from "../services/api";

type ProxyCameraImageProps = {
  camId: string;
  name: string;
  className?: string;
  refreshMs?: number;
};

/** Monitoring-only view: image requests never invoke AI. */
export function ProxyCameraImage({
  camId,
  name,
  className = "h-full w-full object-cover",
  refreshMs = 30000,
}: ProxyCameraImageProps) {
  const [stamp, setStamp] = useState(() => Date.now());
  const [state, setState] = useState<"loading" | "ready" | "failed">("loading");

  useEffect(() => {
    setState("loading");
    setStamp(Date.now());
    const refresh = () => {
      if (document.hidden) return;
      setState("loading");
      setStamp(Date.now());
    };
    const interval = window.setInterval(refresh, Math.max(10000, refreshMs));
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [camId, refreshMs]);

  const baseUrl = getCameraImageUrl(camId);
  if (!baseUrl) return <span role="status">Mã camera không hợp lệ</span>;
  return (
    <div className="relative h-full w-full bg-slate-900">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`${baseUrl}?t=${stamp}`}
        alt={`Ảnh camera giao thông ${name}`}
        loading="lazy"
        className={className}
        onLoad={() => setState("ready")}
        onError={() => setState("failed")}
      />
      <span
        role="status"
        className="absolute bottom-2 left-2 rounded bg-slate-950/80 px-2 py-1 text-[10px] text-white"
      >
        {state === "ready" ? "Đã nhận ảnh · Chưa xác minh giờ chụp" : state === "failed" ? "Không tải được ảnh" : "Đang tải ảnh"}
      </span>
    </div>
  );
}
