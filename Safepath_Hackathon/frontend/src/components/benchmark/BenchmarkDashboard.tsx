"use client";

import { useEffect, useState } from "react";
import { Activity, ArrowDownToLine, ArrowUpRight, Camera, Car, CheckCircle2, Cpu, FileCheck2, FlaskConical, Route, Waves } from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import { GlassCard } from "../Glass/GlassCard";

const SECTIONS = [
  { key: "flood", title: "Phân đoạn nước", icon: Waves, description: "So sánh vùng nước dự đoán với nhãn độc lập." },
  { key: "vehicle", title: "Nhận diện phương tiện", icon: Car, description: "Đánh giá đúng lớp, vị trí và các xe bị bỏ sót." },
  { key: "inference", title: "Hiệu năng suy luận", icon: Cpu, description: "Thời gian đo trên phần cứng và provider thực tế." },
  { key: "routing", title: "Tuyến đường & rủi ro", icon: Route, description: "Kiểm tra kịch bản và các ràng buộc an toàn." },
  { key: "camera", title: "Độ tin cậy camera", icon: Camera, description: "Phân biệt camera đăng ký, có ảnh và đủ bằng chứng." },
  { key: "load", title: "Khả năng phục vụ", icon: Activity, description: "Độ trễ và lỗi dưới tải local có giới hạn." },
] as const;

type RecordValue = Record<string, unknown>;
type Summary = {
  schema_version: number;
  run_id?: string;
  generated_at?: string;
  commit_sha?: string;
  dirty_worktree?: boolean;
  mode?: string;
  sections: Record<string, RecordValue>;
  artifacts?: { name: string; href: string }[];
  disclaimer?: string;
  models?: Record<string, RecordValue>;
};

const STATES: Record<string, { label: string; style: string }> = {
  VERIFIED: { label: "Đã đo và kiểm tra", style: "bg-emerald-50 text-emerald-800 border-emerald-200" },
  LIMITED: { label: "Có giới hạn", style: "bg-amber-50 text-amber-900 border-amber-200" },
  "NOT EVALUATED": { label: "Chưa đánh giá", style: "bg-slate-100 text-slate-700 border-slate-200" },
  BLOCKED: { label: "Chưa thể thực hiện", style: "bg-orange-50 text-orange-900 border-orange-200" },
  FAILED: { label: "Không đạt / có lỗi", style: "bg-rose-50 text-rose-800 border-rose-200" },
};

function record(value: unknown): value is RecordValue {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function status(value: unknown) {
  return typeof value === "string" && Object.hasOwn(STATES, value) ? value : "NOT EVALUATED";
}

function StatusBadge({ value }: { value: unknown }) {
  const key = status(value);
  return <span className={`inline-flex max-w-full flex-wrap gap-x-1.5 rounded-full border px-3 py-1.5 text-xs font-bold ${STATES[key].style}`}><span>{key}</span><span className="font-medium">· {STATES[key].label}</span></span>;
}

const LABELS: Record<string, string> = {
  model_version: "Phiên bản model", model_sha256: "SHA-256 model", sha256: "SHA-256", sample_count: "Số mẫu",
  samples: "Mẫu", dataset: "Dataset", dataset_name: "Dataset", provider: "Provider", actual_providers: "Provider thực tế",
  p50_ms: "p50 (ms)", p95_ms: "p95 (ms)", p99_ms: "p99 (ms)", mean_ms: "Trung bình (ms)", std_ms: "Độ lệch chuẩn (ms)",
  global_iou: "IoU toàn bộ pixel", mean_iou: "IoU trung bình mỗi ảnh", dice: "Dice", f1: "F1", precision: "Precision", recall: "Recall",
  ap50: "AP50", ap50_95: "AP50:95", passed: "Kịch bản đạt", total: "Tổng kịch bản", iterations: "Lượt đo", runs: "Số lần chạy độc lập",
};

function label(key: string) { return LABELS[key] || key.replaceAll("_", " "); }

function valueText(value: unknown): string {
  if (value === null || value === undefined) return "Chưa có số đo";
  if (typeof value === "number") return Number.isFinite(value) ? value.toLocaleString("vi-VN", { maximumFractionDigits: 4 }) : "Chưa có số đo";
  if (typeof value === "boolean") return value ? "Có" : "Không";
  if (Array.isArray(value)) return value.length === 0 ? "Không có mẫu" : value.every(v => !record(v)) ? value.map(valueText).join(", ") : `${value.length} mục · xem báo cáo JSON`;
  return String(value);
}

function Measurements({ data, depth = 0 }: { data: RecordValue; depth?: number }) {
  const entries = Object.entries(data).filter(([key]) => !["status", "reason", "artifacts", "examples"].includes(key));
  if (!entries.length) return <p className="text-sm text-slate-600">Chưa có số đo để hiển thị.</p>;
  return <dl className="space-y-3">{entries.map(([key, value]) => <div key={key} className="min-w-0 border-t border-slate-200/70 pt-3 first:border-0 first:pt-0">
    <dt className="text-xs font-semibold text-slate-600 break-words">{label(key)}</dt>
    <dd className="mt-1 break-words text-sm text-slate-900 [overflow-wrap:anywhere]">{record(value) && depth < 3 ? <Measurements data={value} depth={depth + 1} /> : record(value) ? "Xem chi tiết trong báo cáo JSON" : valueText(value)}</dd>
  </div>)}</dl>;
}

function latencyGroups(data: RecordValue, path = ""): { name: string; values: [string, number][] }[] {
  if (record(data.timings) && record(data.timings.pipeline_file)) {
    return latencyGroups(data.timings.pipeline_file, `${path} / pipeline đầy đủ (đọc file)`);
  }
  const values = ["p50_ms", "p95_ms", "p99_ms"].flatMap(key => typeof data[key] === "number" && Number.isFinite(data[key]) && (data[key] as number) >= 0 ? [[key, data[key]] as [string, number]] : []);
  const nested = Object.entries(data).flatMap(([key, child]) => {
    if (key === "raw_samples_ms") return [];
    const name = path ? `${path} / ${label(key)}` : label(key);
    if (record(child)) return latencyGroups(child, name);
    if (Array.isArray(child)) return child.flatMap((item, index) => record(item) ? latencyGroups(item, `${name} ${valueText(item.concurrent_users ?? item.run ?? index + 1)}`) : []);
    return [];
  });
  return [...(values.length ? [{ name: path || "Suy luận", values }] : []), ...nested];
}

function ModelTable({ models, inference }: { models: RecordValue; inference: RecordValue }) {
  const entries = Object.entries(models).filter(([, model]) => record(model));
  if (!entries.length) return null;
  const measured = record(inference.models) ? inference.models : {};
  return <GlassCard className="space-y-4 p-5 sm:p-6"><h2 className="text-xl font-extrabold">Model trong lần đánh giá</h2><p className="text-sm text-slate-600">Hash xác định đúng weights đã dùng. Độ trễ pipeline gồm các bước được mô tả trong phương pháp đo; không phải độ chính xác.</p><div className="overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-600" tabIndex={0} role="region" aria-label="Bảng model; cuộn ngang để xem đầy đủ"><table className="w-full min-w-[540px] text-left text-sm"><caption className="sr-only">Kiến trúc, phiên bản model và độ trễ pipeline đo được</caption><thead className="border-b border-slate-200 text-xs text-slate-600"><tr>{["Model / kiến trúc", "Phiên bản", "SHA-256", "Pipeline p95 (ms)"].map(title => <th key={title} scope="col" className="px-3 py-3 first:pl-0">{title}</th>)}</tr></thead><tbody>{entries.map(([key, value]) => {
    const model = value as RecordValue;
    const metrics = record(measured[key]) ? measured[key] : {};
    return <tr key={key} className="border-b border-slate-100"><th scope="row" className="max-w-52 py-4 pr-3 align-top font-semibold [overflow-wrap:anywhere]">{key}<span className="mt-1 block text-xs font-normal text-slate-600">{valueText(model.architecture ?? model.model_type ?? model.type)}</span></th><td className="max-w-40 px-3 py-4 align-top [overflow-wrap:anywhere]">{valueText(model.version ?? model.model_version)}</td><td className="max-w-56 px-3 py-4 align-top font-mono text-xs [overflow-wrap:anywhere]">{valueText(model.sha256 ?? model.model_sha256)}</td><td className="px-3 py-4 align-top tabular-nums">{valueText(metrics.pipeline_p95_ms)}</td></tr>;
  })}</tbody></table></div></GlassCard>;
}

function LatencyChart({ data }: { data: RecordValue }) {
  const groups = latencyGroups(data);
  if (!groups.length) return null;
  return <figure className="mt-5 rounded-2xl bg-sky-50/70 p-4" aria-label="Biểu đồ các phân vị độ trễ đã đo">
    <figcaption className="mb-4 text-sm font-bold text-slate-900">Độ trễ đã đo · ms</figcaption>
    {groups.map(group => {
      const max = Math.max(...group.values.map(([, value]) => value), 1);
      return <div key={group.name} className="mb-5 last:mb-0"><p className="mb-2 break-words text-xs font-semibold text-slate-700">{group.name}</p>
        {group.values.map(([key, value]) => <div key={key} className="mb-2 grid grid-cols-[2rem_1fr_4rem] items-center gap-2 text-xs"><span>{key.slice(0, 3)}</span><div className="h-2 rounded-full bg-slate-200" aria-hidden="true"><div className="h-2 rounded-full bg-gradient-to-r from-sky-600 to-teal-500" style={{ width: `${value / max * 100}%` }} /></div><span className="text-right tabular-nums">{valueText(value)}</span></div>)}
      </div>;
    })}
    <p className="mt-3 text-xs text-slate-600">Mỗi nhóm dùng thang đo riêng; số nhỏ hơn nghĩa là xử lý nhanh hơn.</p>
  </figure>;
}

const DOWNLOAD_NAMES = /^(summary|commands|environment|flood_metrics|vehicle_metrics|inference_metrics|routing_metrics|camera_metrics|load_test_metrics)\.json$|^(benchmark_results\.csv|flood_predictions\.csv|vehicle_predictions\.csv|benchmark_report\.md|methodology\.md|limitations\.md|inference_latency\.png|flood_confusion_matrix\.png|vehicle_confusion_matrix\.png)$/;
function safeArtifacts(summary: Summary) {
  return (summary.artifacts || []).filter(item => record(item) && typeof item.name === "string" && typeof item.href === "string" && DOWNLOAD_NAMES.test(item.name) && item.href === `/benchmark/${item.name}`);
}

function AuthorizedExamples({ section, data, summary }: { section: string; data: RecordValue; summary: Summary }) {
  if (!["flood", "vehicle"].includes(section) || !record(data.dataset) || data.dataset.public_examples_authorized !== true) return null;
  const name = `${section}_examples.png`;
  const href = `/benchmark/${name}`;
  if (!(summary.artifacts || []).some(item => record(item) && item.name === name && item.href === href)) return null;
  return <figure className="space-y-3 rounded-2xl border border-slate-200 bg-white p-3">
    <figcaption className="text-sm font-bold text-slate-800">{section === "flood" ? "Ảnh gốc · Nhãn chuẩn · Dự đoán · Vùng sai lệch" : "Đối chiếu nhãn chuẩn và phát hiện phương tiện"}</figcaption>
    <a href={href} target="_blank" rel="noopener noreferrer" className="block rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-600" aria-label="Mở ảnh đối chiếu đã được phép công bố">
      <Image src={href} alt={section === "flood" ? "Đối chiếu ảnh gốc, ground truth, dự đoán phân đoạn nước và lỗi" : "Đối chiếu ground truth và bounding box phương tiện dự đoán"} width={1600} height={600} unoptimized className="h-auto w-full rounded-lg" />
    </a>
    <p className="text-xs leading-relaxed text-slate-600">Mẫu thuộc dataset cho phép công bố. Mở ảnh để xem rõ nhãn và dự đoán; các ảnh minh họa không thay thế kết quả trên toàn bộ tập đánh giá.</p>
  </figure>;
}

export function BenchmarkDashboard() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    fetch("/benchmark/summary.json", { signal: controller.signal, cache: "no-store" })
      .then(async response => {
        if (!response.ok) throw new Error("missing");
        const data: unknown = await response.json();
        if (!record(data) || data.schema_version !== 1 || !record(data.sections) || (data.artifacts !== undefined && !Array.isArray(data.artifacts))) throw new Error("invalid");
        for (const value of Object.values(data.sections)) if (!record(value)) throw new Error("invalid");
        if (active) setSummary(data as Summary);
      }).catch(() => { if (active) setError("Chưa tải được báo cáo benchmark hợp lệ. Các mục dưới đây chưa được đánh giá; không có số liệu thay thế."); })
      .finally(() => { window.clearTimeout(timeout); if (active) setLoading(false); });
    return () => { active = false; window.clearTimeout(timeout); controller.abort(); };
  }, []);

  const downloads = summary ? safeArtifacts(summary) : [];
  const measured = SECTIONS.filter(section => ["VERIFIED", "LIMITED"].includes(status(summary?.sections[section.key]?.status))).length;
  return <div className="min-h-screen bg-gradient-to-br from-slate-50 via-sky-50 to-teal-50 text-slate-900">
    <header className="border-b border-white bg-white/85 backdrop-blur-xl"><div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-5 py-4 sm:px-8">
      <Link href="/" className="flex min-h-11 items-center gap-2 font-black text-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-600"><FlaskConical className="h-6 w-6 text-sky-600" aria-hidden="true" />SafePath<span className="text-teal-700">AI</span></Link>
      <Link href="/di-duong" className="flex min-h-11 items-center gap-2 rounded-full border border-slate-200 bg-white px-4 text-sm font-semibold hover:bg-sky-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-600">Về bản đồ<ArrowUpRight className="h-4 w-4" aria-hidden="true" /></Link>
    </div></header>
    <main className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-8 sm:py-12">
      <section className="grid gap-6 lg:grid-cols-[1.6fr_1fr]" aria-labelledby="benchmark-title">
        <div className="space-y-4"><p className="flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-teal-800"><FileCheck2 className="h-4 w-4" aria-hidden="true" />Benchmark & evaluation</p>
          <h1 id="benchmark-title" className="max-w-2xl text-3xl font-black tracking-tight sm:text-5xl">AI làm được gì?<br /><span className="aurora-gradient-text">Xem bằng số đo.</span></h1>
          <p className="max-w-2xl text-base leading-relaxed text-slate-600">Kết quả từ một lần chạy có thể kiểm tra lại. Độ chính xác model, tốc độ xử lý và kiểm tra an toàn được trình bày riêng, cùng nguồn dữ liệu và giới hạn.</p>
          <nav aria-label="Các phần benchmark" className="flex flex-wrap gap-2">{SECTIONS.map(section => <a key={section.key} href={`#${section.key}`} className="inline-flex min-h-11 items-center rounded-full border border-white bg-white/80 px-3 text-xs font-semibold text-slate-700 hover:bg-sky-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-600">{section.title}</a>)}</nav>
        </div>
        <GlassCard variant="elevated" className="space-y-4 p-5 sm:p-6"><div className="flex items-center gap-2 text-sm font-bold"><CheckCircle2 className="h-5 w-5 text-teal-700" aria-hidden="true" />Hồ sơ lần chạy</div>
          <p className="text-3xl font-black tabular-nums">{loading ? "—" : measured}<span className="ml-2 text-sm font-medium text-slate-600">/ {SECTIONS.length} mục có kết quả đo</span></p>
          <dl className="space-y-3 text-sm">{[["Thời điểm (nguồn)", summary?.generated_at], ["Chế độ", summary?.mode], ["Run ID", summary?.run_id], ["Commit", summary?.commit_sha], ["Working tree có thay đổi", summary?.dirty_worktree]].map(([key, value]) => <div key={String(key)} className="grid grid-cols-[1fr_1.3fr] gap-3"><dt className="text-slate-600">{key}</dt><dd className="min-w-0 break-all font-mono text-xs">{valueText(value)}</dd></div>)}</dl>
        </GlassCard>
      </section>
      <div role="status" className="rounded-2xl border border-sky-200 bg-white/90 p-4 text-sm leading-relaxed text-slate-700">{loading ? "Đang đọc báo cáo đã xuất…" : error || (typeof summary?.disclaimer === "string" ? summary.disclaimer : "") || "Kết quả benchmark chỉ có giá trị trong phạm vi dataset, cấu hình và phần cứng đã ghi nhận. Chưa có nhãn độc lập thì chưa kết luận độ chính xác ngoài thực địa."}</div>
      {summary && record(summary.models) && <ModelTable models={summary.models} inference={summary.sections.inference || {}} />}
      <section aria-label="Kết quả theo phân hệ" className="grid items-start gap-5 md:grid-cols-2 xl:grid-cols-3">{SECTIONS.map(({ key, title, icon: Icon, description }) => {
        const data = summary?.sections[key] || {};
        return <GlassCard key={key} id={key} className="min-w-0 scroll-mt-6 space-y-4 p-5 sm:p-6"><div className="flex items-center gap-3"><div className="rounded-2xl border border-sky-100 bg-sky-50 p-3"><Icon className="h-5 w-5 text-sky-700" aria-hidden="true" /></div><h2 className="text-lg font-extrabold">{title}</h2></div><StatusBadge value={data.status} /><p className="text-sm leading-relaxed text-slate-600">{description}</p>
          {typeof data.reason === "string" && <p className="rounded-xl bg-slate-50 p-3 text-sm leading-relaxed text-slate-700 break-words">{data.reason}</p>}
          <Measurements data={data} />
          <LatencyChart data={data} />
          {summary && <AuthorizedExamples section={key} data={data} summary={summary} />}
        </GlassCard>;
      })}</section>
      <GlassCard variant="elevated" className="space-y-5 p-5 sm:p-7"><div><h2 className="text-xl font-extrabold">Dữ liệu & cách đo</h2><p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-600">Tải báo cáo để xem model, SHA-256, dataset, phần cứng, lệnh chạy và các phép đo chi tiết. Bộ dữ liệu tĩnh này xem được khi không có kết nối đến backend; không khởi chạy tác vụ AI từ trang công khai.</p></div>
        {downloads.some(item => item.name === "methodology.md") && <a href="/benchmark/methodology.md" className="inline-flex min-h-11 items-center gap-2 rounded-full border border-sky-200 bg-sky-50 px-4 text-sm font-bold text-sky-800 hover:bg-sky-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-600">Xem phương pháp đo<ArrowUpRight className="h-4 w-4" aria-hidden="true" /></a>}
        {downloads.length ? <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{downloads.map(item => <li key={item.name}><a href={item.href} download className="flex min-h-12 items-center gap-3 rounded-xl border border-slate-200 bg-white/90 p-3 text-sm font-semibold hover:border-sky-400 hover:bg-sky-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-600"><ArrowDownToLine className="h-4 w-4 shrink-0 text-sky-700" aria-hidden="true" /><span className="break-all">{item.name}</span></a></li>)}</ul> : <p className="text-sm text-slate-600">Chưa có tệp kết quả được công bố.</p>}
      </GlassCard>
      <footer className="border-t border-slate-200 pt-5 text-xs leading-relaxed text-slate-600">VERIFIED: đã đo trong phạm vi ghi nhận · LIMITED: có kết quả nhưng còn giới hạn · NOT EVALUATED: chưa đánh giá · BLOCKED: thiếu điều kiện · FAILED: phép chạy hoặc kiểm tra thất bại. Kiểm tra kịch bản đạt không chứng minh độ chính xác ngoài thực địa; chưa có dữ liệu hành trình thực thì chưa đánh giá độ chính xác ETA.</footer>
    </main>
  </div>;
}
