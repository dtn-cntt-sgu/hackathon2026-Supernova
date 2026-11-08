"use client";
import { useState } from "react";
import { CameraOff } from "lucide-react";

export function ObservationImage({ src, alt, empty }: { src: string | null; alt: string; empty: string }) {
  const [failed, setFailed] = useState<string | null>(null);
  return <div className="snapshot-frame">{src && failed !== src ? (
    // Source snapshots bypass optimization to preserve evidence bytes.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} onError={() => setFailed(src)} />
  ) : <div className="snapshot-empty"><CameraOff size={28}/><span>{src ? "Không tải được ảnh từ backend" : empty}</span></div>}
  </div>;
}
