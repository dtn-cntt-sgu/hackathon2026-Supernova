"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CameraEvidence } from "../types/contracts";
import { CameraProxySnapshot, cameraSourceLabel, type CameraSnapshotFrame } from "./CameraProxySnapshot";
import { prepareCameraAnalysis, cameraAnalysisImageUrl, type CameraViewAnalysis } from "../services/api";

type CameraModalProps = { camera: CameraEvidence | null; onClose: () => void; refreshMs?: number };
export function CameraProxyModal(props: CameraModalProps) {
  return props.camera ? <CameraViewer key={props.camera.cam_id} {...props} camera={props.camera} /> : null;
}

function CameraViewer({ camera, onClose, refreshMs = 30000 }: CameraModalProps & { camera: CameraEvidence }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const pending = useRef<AbortController | null>(null);
  const [revision, setRevision] = useState(0);
  const [frame, setFrame] = useState<CameraSnapshotFrame | null>(null);
  const [analysis, setAnalysis] = useState<CameraViewAnalysis | null>(null);
  const [view, setView] = useState<"original" | "overlay">("original");
  const rememberFrame = useCallback((value: CameraSnapshotFrame) => setFrame(value), []);
  useEffect(() => {
    pending.current?.abort();
    setFrame(null); setAnalysis(null); setView("original"); setRevision(0);
    if (!camera?.cam_id || !dialog.current) return;
    const previous = document.activeElement as HTMLElement | null;
    const element = dialog.current;
    element.showModal();
    return () => { pending.current?.abort(); element.close(); previous?.focus(); };
  }, [camera?.cam_id]);
  if (!camera) return null;

  const ready = analysis?.status === "READY" && analysis.image_url && analysis.overlay_url;
  const refresh = () => {
    pending.current?.abort(); setFrame(null); setAnalysis(null); setView("original"); setRevision(value => value + 1);
  };
  const analyze = async () => {
    if (!frame || analysis?.status === "PREPARING") return;
    setView("overlay");
    if (ready) return;
    pending.current?.abort();
    const controller = new AbortController(); pending.current = controller;
    setAnalysis({ status: "PREPARING" });
    try {
      const result = await prepareCameraAnalysis(camera.cam_id, controller.signal, frame.snapshotId);
      if (!controller.signal.aborted) setAnalysis(result);
    } catch (error) {
      if (!controller.signal.aborted) setAnalysis({ status: "UNAVAILABLE", reason: error instanceof Error ? error.message : "Không tải được kết quả phân tích." });
    }
  };
  const received = ready ? analysis.retrieved_at : frame?.retrievedAt;
  return <dialog ref={dialog} onCancel={(event) => { event.preventDefault(); onClose(); }}
    aria-labelledby="proxy-camera-title" data-testid="camera-proxy-modal"
    className="w-[min(95vw,900px)] max-h-[90vh] overflow-y-auto rounded-3xl p-5 bg-white text-ink-900 backdrop:bg-slate-950/60">
    <div className="flex items-start justify-between gap-3 mb-4">
      <div><h2 id="proxy-camera-title" className="font-bold">{camera.name}</h2><p className="text-sm">{camera.district || "Camera giao thông"}</p></div>
      <button type="button" onClick={onClose} aria-label="Đóng chi tiết camera" className="rounded-xl p-3 focus:ring-2">Đóng</button>
    </div>
    <div role="tablist" aria-label="Chế độ xem camera" className="flex flex-wrap gap-2 mb-3">
      <button role="tab" aria-selected={view === "original"} onClick={() => setView("original")} className={`rounded-xl px-4 py-3 focus:ring-2 ${view === "original" ? "bg-indigo-600 text-white" : "bg-slate-100"}`}>Ảnh gốc (Nguồn)</button>
      <button role="tab" aria-selected={view === "overlay"} disabled={!frame || analysis?.status === "PREPARING"} onClick={() => void analyze()} className={`rounded-xl px-4 py-3 focus:ring-2 disabled:opacity-50 ${view === "overlay" ? "bg-teal-600 text-white" : "bg-slate-100"}`}>Phát hiện AI (Overlay)</button>
    </div>
    <div className="aspect-video min-h-44 bg-slate-100 rounded-xl overflow-hidden" aria-busy={analysis?.status === "PREPARING"}>
      {/* Preserve remote source bytes without the image optimization proxy. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      {ready ? <img src={cameraAnalysisImageUrl(view === "overlay" ? analysis.overlay_url! : analysis.image_url!)} alt={`${view === "overlay" ? "Phát hiện AI" : "Ảnh gốc"} camera ${camera.name}`} className="h-full w-full object-contain" />
        : view === "original" ? <CameraProxySnapshot key={camera.cam_id} camId={camera.cam_id} name={camera.name} refreshMs={refreshMs} revision={revision} showMetadata={false} onFrame={rememberFrame} />
        : <div role="status" className="h-full flex flex-col items-center justify-center gap-3 p-6 text-center">
          <strong>{analysis?.status === "PREPARING" ? "AI đang nhận diện ảnh camera…" : analysis?.status === "PENDING" ? "AI đang xử lý ảnh này" : "Phân tích chưa hoàn tất"}</strong>
          {analysis?.reason && <p className="text-sm text-ink-600">{analysis.reason}</p>}
          {analysis?.status !== "PREPARING" && <button className="rounded-xl border px-4 py-3" onClick={() => analysis?.status === "FRAME_CHANGED" ? refresh() : void analyze()}>{analysis?.status === "FRAME_CHANGED" ? "Lấy ảnh mới" : "Phân tích lại"}</button>}
        </div>}
    </div>
    <div className="text-sm mt-3 space-y-2" role="status">
      <p>Nguồn: {cameraSourceLabel(ready ? analysis.provider : frame?.provider)}</p>
      {received && <p>Thời gian ảnh (nhận lúc): {new Date(received).toLocaleString("vi-VN")}</p>}
      {view === "overlay" && ready && <p><strong>{analysis.vehicle_count ?? "—"}</strong> xe được nhận diện trên ảnh này{analysis.flood_ratio != null ? ` · Diện tích nước: ${Math.round(analysis.flood_ratio * 100)}%` : ""}.</p>}
      <p>Tọa độ: {camera.lat}, {camera.lng}</p>
      <button type="button" onClick={refresh} className="rounded-xl border px-4 py-3 focus:ring-2">Tải lại ảnh</button>
    </div>
  </dialog>;
}
