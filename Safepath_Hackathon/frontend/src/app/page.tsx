"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useCinematicScene } from "../hooks/useCinematicScene";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  Navigation,
  Camera,
  Car,
  Waves,
  CloudRain,
  ShieldCheck,
  CheckCircle,
  AlertTriangle,
  RefreshCw,
  Eye,
  Sparkles,
  MapPin,
  Clock,
  Compass,
  Newspaper,
  ExternalLink,
} from "lucide-react";
import { AnimatedCounter } from "../components/cinematic/AnimatedCounter";
import { LiquidGlassCard } from "../components/ui/LiquidGlassCard";
import { LiquidGlass } from "../components/ui/LiquidGlass";
import { AuroraBackground } from "../components/ui/AuroraBackground";
import { CardContainer, CardBody, CardItem } from "../components/ui/ThreeDCard";
import { ObservationImage } from "../components/spatial/ObservationImage";
import { useLiveObservations } from "../hooks/useLiveObservations";
import { currentRain, currentTide, observationTime } from "../lib/observations";
import { prepareCameraAnalysis, cameraAnalysisImageUrl, type CameraViewAnalysis } from "../services/api";
import { CameraProxySnapshot, cameraSourceLabel } from "../components/CameraProxySnapshot";
import { RoutingLaunchPanel } from "../components/cinematic/RoutingLaunchPanel";
import { NewsEditorialCards } from "../components/cinematic/NewsEditorialCards";

const chapters = [
  "Thành phố chuyển động",
  "Nguy cơ tiềm ẩn",
  "Bản tin giao thông",
  "Định tuyến thông minh",
];

export default function LandingPage() {
  const { track, scene, jump } = useCinematicScene();
  const [selectedId, setSelectedId] = useState("");
  const live = useLiveObservations();
  const [analysis, setAnalysis] = useState<CameraViewAnalysis | null>(null);
  const pendingAnalysis = useRef<AbortController | null>(null);
  useEffect(() => () => pendingAnalysis.current?.abort(), []);
  const inspectCamera = async (camId: string) => {
    setSelectedId(camId);
    pendingAnalysis.current?.abort();
    const controller = new AbortController(); pendingAnalysis.current = controller;
    setAnalysis({ status: "PREPARING" });
    try {
      const result = await prepareCameraAnalysis(camId, controller.signal);
      if (!controller.signal.aborted) setAnalysis(result);
    } catch (error) {
      if (!controller.signal.aborted) setAnalysis({ status: "UNAVAILABLE", reason: error instanceof Error ? error.message : "Không tải được phân tích camera." });
    }
  };


  const camera =
    live.cameras.find((c) => c.cam_id === selectedId) ||
    live.cameras.find((c) => c.has_image && c.model_status === "INFERENCE_COMPLETED") ||
    live.cameras.find((c) => c.has_image) ||
    live.cameras[0] ||
    null;

  const hasAnalysis = analysis?.status === "READY" && Boolean(analysis.image_url && analysis.overlay_url);
  const rain = currentRain(live.weather, live.now);
  const tide = currentTide(live.weather, live.now);
  const rainLabel = rain !== null ? `${rain.toFixed(1)} mm/h` : live.weather?.rain_status === "STALE" || (live.weather?.rain_status === "LIVE" && live.weather?.rain_observed_at) ? "Dữ liệu cũ" : "Chưa có dữ liệu";

  const timestamp = live.summary?.last_scheduler_cycle;

  const snapshot = hasAnalysis ? cameraAnalysisImageUrl(analysis!.image_url!) : null;
  const analyzed = hasAnalysis ? cameraAnalysisImageUrl(analysis!.overlay_url!) : null;

  return (
    <main className="spatial-landing real-observatory relative selection:bg-indigo-600 selection:text-white">
      {/* Aceternity UI Aurora Background — Light Cinematic Liquid Glass Edition (Single persistent instance across all 4 ACTs) */}
      <AuroraBackground
        className="fixed inset-0 pointer-events-none -z-10 overflow-hidden"
        showRadialGradient={true}
      />

      {/* Primary Navigation Pill — Glass Static (Zero Refraction Jank) */}
      <LiquidGlass
        as="nav"
        variant="pill"
        glassLevel="static"
        interactive={false}
        className="landing-nav"
        aria-label="Điều hướng chính"
      >
        <Link className="spatial-brand" href="/">
          <div className="p-1.5 bg-gradient-to-tr from-indigo-600 via-blue-600 to-sky-500 rounded-xl shadow-md text-white">
            <Navigation size={18} />
          </div>
          <span className="font-black text-ink-950">
            SafePath<span className="text-indigo-600">AI</span>
          </span>
        </Link>
        <span className="nav-live">
          TP.HCM · <span data-testid="network-count" className="font-bold text-ink-900">{live.summary?.total_registered ?? "—"}</span> CAMERA GIÁM SÁT
        </span>
        <div className="nav-links">
          <button onClick={() => jump(0)} className={scene === 0 ? "active" : ""}>01 Đô thị 3D</button>
          <button onClick={() => jump(1)} className={scene === 1 ? "active" : ""}>02 Nguy cơ ngập</button>
          <button onClick={() => jump(2)} className={scene === 2 ? "active" : ""}>03 Bản tin</button>
          <button onClick={() => jump(3)} className={scene === 3 ? "active" : ""}>04 Điều hướng</button>
        </div>
        <Link href="/map" className="nav-cta">
          Bắt đầu ngay <ArrowUpRight size={16} />
        </Link>
      </LiquidGlass>

      {/* Story Track with 4 Scenes */}
      <div className="story-track" ref={track}>
        <div className="story-viewport" data-scene={scene}>
          <div className="scene-coordinate">
            TP. HỒ CHÍ MINH
            <span>MẠNG LƯỚI ĐIỀU HƯỚNG TRÁNH NGẬP THỰC TẾ</span>
          </div>

          {live.errors.length > 0 && (
            <div className="observatory-error liquid-island" role="alert">
              Không tải được: {live.errors.join(", ")}.
              <button onClick={live.refresh}>Thử lại</button>
            </div>
          )}

          {/* SCENE 0: Act 1 — The Living City */}
          <section
            className={`story-scene hero-scene ${scene === 0 ? "is-active" : ""}`}
            id="city"
          >
            <div className="hero-copy">
              {/* Aceternity Style Floating Status Pill */}
              <div className="mb-4 inline-flex">
                <LiquidGlass
                  variant="pill"
                  glassLevel="static"
                  interactive={false}
                  className="inline-flex items-center gap-2 px-3 py-1.5 border border-white/80 shadow-xs"
                >
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-50 text-indigo-700 border border-indigo-200/70 tracking-wider">
                    SAFEPATH 3.1
                  </span>
                  <span className="text-xs font-semibold text-ink-700">
                    {live.summary?.total_registered ?? "796"} Camera quan trắc thực tế TP.HCM
                  </span>
                  <Sparkles size={13} className="text-indigo-600" />
                </LiquidGlass>
              </div>

              <h1>
                ĐIỀU HƯỚNG THÔNG MINH.
                <br />
                <span>CHỦ ĐỘNG TRÁNH NGẬP.</span>
              </h1>
              <p>
                Khám phá giao thông TP.HCM qua dữ liệu camera hiện trường, mô hình AI nhận diện nước ngập và thuật toán định tuyến an toàn trước mọi cơn mưa & triều cường.
              </p>
              <div className="flex flex-wrap items-center gap-3 my-5">
                <Link className="primary-spatial group" href="/map">
                  <span>Tìm lộ trình tránh ngập</span>
                  <ArrowUpRight size={18} className="group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition" />
                </Link>
                <Link
                  className="px-5 py-3 rounded-full text-xs font-bold text-ink-700 bg-white/85 hover:bg-white border border-white/90 shadow-glass-sm hover:shadow-glass transition"
                  href="/monitor"
                >
                  Thư viện camera trực tiếp
                </Link>
              </div>
              <div className="hero-trust">
                <ShieldCheck size={16} className="text-emerald-600 shrink-0" />
                <span>Dữ liệu thực địa từ Cổng giao thông TP.HCM & Open-Meteo · Nhãn xác minh minh bạch</span>
              </div>
            <div className="hero-bottom">
              <span>
                <b><AnimatedCounter value={live.summary?.valid_gps_count} /></b>
                Camera có tọa độ
              </span>
              <span>
                <b>{live.health?.osrm === "available" ? "Sẵn sàng" : "Đang kiểm tra"}</b>
                Dịch vụ định tuyến OSRM
              </span>
              <span>
                <b>{rainLabel}</b>
                Mưa thời gian thực
              </span>
            </div>
            </div>

            <CardContainer maxTilt={2} className="w-full">
              <CardBody className="w-full">
                <LiquidGlassCard className="hero-signal">
                  <div className="signal-top">
                    <CardItem translateZ={2}>
                      <span className="font-bold flex items-center gap-1.5 text-xs text-ink-800">
                        <Camera size={16} className="text-indigo-600" /> MẠNG LƯỚI CAMERA TP.HCM
                      </span>
                    </CardItem>
                    <button
                      onClick={live.refresh}
                      aria-label="Cập nhật dữ liệu"
                      className="p-1 hover:bg-slate-100 rounded-lg transition"
                    >
                      <RefreshCw size={13} className="text-slate-500" />
                    </button>
                  </div>

                  <div className="signal-metrics">
                    <CardItem translateZ={4}>
                      <strong data-testid="recent-image-count" className="text-3xl font-black text-ink-950">
                        <AnimatedCounter value={live.summary?.valid_images_count} />
                      </strong>
                      <small className="text-[11px] text-ink-500 font-medium block">Ảnh nhận gần đây theo backend</small>
                    </CardItem>
                  </div>
                  <p className="text-[10px] text-ink-400 mt-2">Ảnh nhận được không đồng nghĩa với thời điểm chụp đã xác minh.</p>
                  <hr className="my-3 border-slate-200" />
                  <CardItem translateZ={8} className="w-full">
                    <div className="live-stat-row">
                      <span>Camera đã quét</span>
                      <b>{live.summary?.checked_count ?? "—"}</b>
                    </div>
                    <div className="live-stat-row">
                      <span>Đã phân tích xe & lưu thông</span>
                      <b>{live.summary?.analyzed_count ?? "—"}</b>
                    </div>
                  </CardItem>
                  <p className="text-[10px] text-ink-400 mt-2">
                    Chu kỳ cập nhật gần nhất: {observationTime(timestamp)}
                  </p>
                  <CardItem translateZ={12}>
                    <Link className="observation-link" href="/monitor">
                      Mở thư viện camera <ArrowUpRight size={13} />
                    </Link>
                  </CardItem>
                </LiquidGlassCard>
              </CardBody>
            </CardContainer>


          </section>

          {/* SCENE 1: Act 2 — The Invisible Danger */}
          <section
            className={`story-scene vision-scene ${scene === 1 ? "is-active" : ""}`}
            id="vision"
          >
            <div className="scene-heading">
              <span className="eyebrow">02 / NGUY CƠ TIỀM ẨN DƯỚI MƯA & THỦY TRIỀU</span>
              <h2>
                Trời chuyển mưa ngập.
                <br />
                <span>SafePath Vision AI phân tích trực quan.</span>
              </h2>
              <label className="camera-selector">
                Chọn camera kiểm tra:
                <select
                  aria-label="Chọn camera quan trắc"
                  value={camera?.cam_id || ""}
                  onChange={(e) => void inspectCamera(e.target.value)}
                  disabled={!live.cameras.length}
                >
                  {!live.cameras.length && <option value="">Đang tải danh sách camera...</option>}
                  {live.cameras.map((c) => (
                    <option key={c.cam_id} value={c.cam_id}>
                      {c.name} {c.has_image ? "• Có ảnh" : ""}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="vision-cards">
              {/* Card 1: Ảnh gốc */}
              <LiquidGlassCard className="vision-card flex flex-col justify-between h-full p-5 sm:p-6">
                <div className="signal-top">
                  <span className="font-bold flex items-center gap-1.5 text-xs text-ink-800">
                    <Camera size={16} className="text-indigo-600" /> ẢNH CAMERA GỐC
                  </span>

                </div>
                {hasAnalysis ? <>
                  <ObservationImage src={snapshot} alt={`Ảnh gốc ${camera?.name || "camera"}`} empty="Đang tải ảnh camera" />
                  <div className="pt-2 mt-auto text-[11px] text-ink-600 space-y-1">
                    <p>Nguồn: {cameraSourceLabel(analysis?.provider)}</p>
                    <p>Thời gian ảnh (nhận lúc): {observationTime(analysis?.retrieved_at)}</p>
                  </div>
                </> : camera ? <div className="snapshot-frame !h-auto !min-h-48"><CameraProxySnapshot key={camera.cam_id} camId={camera.cam_id} name={camera.name} refreshMs={0} /></div> : <p role="status">Đang tải danh sách camera…</p>}

              </LiquidGlassCard>

              {/* Card 2: AI nhận diện phương tiện */}
              <LiquidGlassCard className="vision-card flex flex-col justify-between h-full p-5 sm:p-6">
                <div className="signal-top">
                  <span className="font-bold flex items-center gap-1.5 text-xs text-ink-800">
                    <Car size={16} className="text-emerald-600" /> PHÁT HIỆN PHƯƠNG TIỆN
                  </span>
                  <span className="tiny-badge font-bold text-emerald-700 bg-emerald-50">
                    SafePath Vision AI
                  </span>
                </div>
                <ObservationImage
                  src={analyzed}
                  alt={`Phân tích phương tiện ${camera?.name || "camera"}`}
                  empty={analysis?.status === "PREPARING" ? "AI đang nhận diện ảnh camera…" : analysis?.reason || "Chọn camera để bắt đầu phân tích"}
                />
                <div className="pt-2 mt-auto space-y-1" aria-busy={analysis?.status === "PREPARING"}>
                  {camera && <button className="rounded-xl border px-3 py-2 text-xs disabled:opacity-50" disabled={analysis?.status === "PREPARING"} onClick={() => void inspectCamera(camera.cam_id)}>{analysis?.status === "PREPARING" ? "Đang phân tích…" : "Phân tích camera đã chọn"}</button>}
                  <div className="vision-number">
                    <strong data-testid="observed-vehicle-count">
                      {hasAnalysis ? analysis?.vehicle_count ?? "—" : "—"} <small>xe quan sát được</small>
                    </strong>
                    <b className="text-xs font-semibold text-emerald-700">Ô tô & Xe máy</b>
                  </div>
                  <p className="text-[10px] text-ink-500 mt-1">
                    {hasAnalysis ? `Trạng thái: ${analysis?.model_status || "Đã phân tích"}` : "Phân tích ảnh khi bạn chọn camera"}
                  </p>
                </div>
              </LiquidGlassCard>

              {/* Card 3: Mức độ lưu thông & cảnh báo ngập */}
              <CardContainer maxTilt={2} className="h-full" containerClassName="h-full">
                <CardBody className="h-full">
                  <LiquidGlassCard className="vision-card flex flex-col justify-between h-full p-5 sm:p-6">
                    <div className="signal-top">
                      <CardItem translateZ={2}>
                        <span className="font-bold flex items-center gap-1.5 text-xs text-ink-800">
                          <Waves size={16} className="text-sky-600" /> ĐÁNH GIÁ LƯU THÔNG
                        </span>
                      </CardItem>
                    </div>
                    <CardItem translateZ={4} className="w-full my-auto">
                      <div className="actual-water-status">
                        <Eye size={36} className="text-indigo-500" />
                        <strong className="text-lg font-bold text-ink-950">
                          Chưa xác minh rủi ro tuyến đường
                        </strong>
                        <small className="text-xs text-ink-500">
                          Vùng nước trên ảnh: {hasAnalysis && analysis?.flood_ratio != null ? `${Math.round(analysis.flood_ratio * 100)}%` : "Chưa có dữ liệu"}
                        </small>
                      </div>
                    </CardItem>
                    <p className="text-[10px] text-ink-500 mt-auto pt-2">
                      Kết quả trên ảnh không tự chứng minh tình trạng toàn tuyến.
                    </p>
                  </LiquidGlassCard>
                </CardBody>
              </CardContainer>
            </div>

            <span className="scene-note">
              {camera?.name || "Điểm quan sát giao thông"} · Kết quả nhận diện trên khung hình đã chọn
            </span>
          </section>

          {/* SCENE 2: Act 3 — Bản tin giao thông & Tình hình hiện trường */}
          <section
            className={`story-scene fusion-scene ${scene === 2 ? "is-active" : ""}`}
            id="news"
          >
            <div className="scene-heading">
              <span className="eyebrow">03 / BẢN TIN GIAO THÔNG THÀNH PHỐ</span>
              <h2>
                Biết trước những gì đang diễn ra.
                <br />
                <span>Cập nhật giao thông trước mỗi hành trình.</span>
              </h2>
              <p className="text-xs text-ink-600 max-w-lg mx-auto">
                Tổng hợp sự cố giao thông, ngập úng và các điểm thi công từ VnExpress, Tuổi Trẻ và Cổng thông tin giao thông TP.HCM.
              </p>
            </div>

            <NewsEditorialCards />

            <div className="act03-action-bar">
              <Link href="/news" className="act03-cta-btn primary-spatial group shadow-glass">
                <Newspaper size={18} />
                <span>Khám phá bản tin giao thông</span>
                <ArrowUpRight size={18} className="group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition" />
              </Link>

              <div className="act03-weather-card">
                <div className="act03-weather-pill">
                  <ShieldCheck size={16} className="text-indigo-600 shrink-0" />
                  <span className="font-semibold text-xs text-ink-900">
                    Mưa {rainLabel} · Triều {tide === null ? "Chưa có dữ liệu" : `${tide.toFixed(2)} m`}
                  </span>
                </div>
                <p className="act03-weather-provenance">
                  TP.HCM · {observationTime(live.weather?.rain_observed_at)}{" "}
                  {live.weather?.source_url && (
                    <a
                      href={live.weather.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline hover:text-indigo-600 transition"
                    >
                      Nguồn thời tiết
                    </a>
                  )}
                </p>
              </div>
            </div>
          </section>

          {/* SCENE 3: Lộ trình thông minh */}
          <section
            className={`story-scene route-scene ${scene === 3 ? "is-active" : ""}`}
            id="routing"
          >
            <RoutingLaunchPanel />
          </section>

          {/* Bottom Chapter Navigation — Glass Static (Zero Refraction Jank) */}
          <LiquidGlass
            variant="pill"
            glassLevel="static"
            interactive={false}
            className="story-bottom"
          >
            {scene < 3 ? (
              <button className="scroll-invite" onClick={() => jump(scene + 1)}>
                <ArrowDown size={14} />
                <span>Cuộn để khám phá tiếp</span>
              </button>
            ) : (
              <button className="scroll-invite" onClick={() => jump(0)}>
                <ArrowUp size={14} />
                <span>Về đầu trang</span>
              </button>
            )}
            <div className="chapter-nav" aria-label="Phân cảnh">
              {chapters.map((label, i) => (
                <button
                  key={label}
                  onClick={() => jump(i)}
                  aria-label={label}
                  aria-current={scene === i ? "step" : undefined}
                >
                  <span>0{i + 1}</span>
                  <i className={scene === i ? "active" : ""} />
                </button>
              ))}
            </div>
            <span className="story-caption">{chapters[scene]}</span>
          </LiquidGlass>

          {/* Progress bar at bottom */}
          <div className="story-progress" aria-hidden="true" />
        </div>
      </div>

      {/* Modern Footer */}
      <footer className="spatial-footer">
        <Link className="spatial-brand" href="/">
          <div className="p-1 bg-gradient-to-tr from-indigo-600 via-blue-600 to-sky-500 rounded-lg text-white">
            <Navigation size={14} />
          </div>
          <span className="font-bold text-ink-950">SafePathAI</span>
        </Link>
        <span>Ứng dụng hỗ trợ điều hướng tránh ngập & theo dõi giao thông TP.HCM</span>
        <Link href="/map" className="font-semibold text-indigo-600 hover:underline flex items-center gap-1">
          Bản đồ trực tiếp <ArrowUpRight size={14} />
        </Link>
      </footer>
    </main>
  );
}
