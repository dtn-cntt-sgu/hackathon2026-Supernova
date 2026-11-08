"use client";

import { useState } from "react";
import type { HydrologyBulletin, HydrologyBulletinEvent } from "../types/contracts";

const zone = "Asia/Ho_Chi_Minh";
const stationIds = ["tram_phu_an", "tram_nha_be"];
const stationNames: Record<string, string> = { tram_phu_an: "Phú An", tram_nha_be: "Nhà Bè" };
function timestamp(value?: string | null): string {
  return value ? new Date(value).toLocaleString("vi-VN", { timeZone: zone, hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit", year: "numeric" }) : "Chưa xác minh";
}
function day(value: string): string { return value.split("-").reverse().join("/"); }
function clock(value: string | null): string {
  return value ? new Date(value).toLocaleTimeString("vi-VN", { timeZone: zone, hour: "2-digit", minute: "2-digit" }) : "Không có giờ";
}
function eventClock(event: HydrologyBulletinEvent): string {
  if (!event.event_time) return "Không có giờ";
  const actualDay = new Date(event.event_time).toLocaleDateString("en-CA", { timeZone: zone });
  return `${clock(event.event_time)}${actualDay !== event.event_date ? ` (${day(actualDay)})` : ""}`;
}
function EventRows({ events }: { events: HydrologyBulletinEvent[] }) {
  return <ul className="space-y-1.5 mt-2">
    {events.map((event, index) => <li key={`${event.data_type}-${event.event_date}-${event.event_kind}-${index}`} className="flex flex-wrap justify-between gap-x-2 gap-y-0.5 text-[11px]" data-type={event.data_type}>
      <span className="text-ink-600">{event.event_kind === "HIGH_TIDE" ? "Đỉnh" : "Chân"} · {eventClock(event)}</span>
      <strong className="text-ink-900">{event.water_level_m === null ? `Chưa có số liệu${event.source_value ? ` (${event.source_value})` : ""}` : `${event.water_level_m.toFixed(2)} m`}</strong>
    </li>)}
  </ul>;
}

export function HydrologyBulletinPanel({ bulletin }: { bulletin: HydrologyBulletin | null }) {
  const [selectedDay, setSelectedDay] = useState("");
  const events = bulletin?.events || [];
  const forecasts = events.filter(event => event.data_type === "FORECAST");
  const dates = Array.from(new Set(forecasts.map(event => event.event_date))).sort();
  const today = new Date().toLocaleDateString("en-CA", { timeZone: zone });
  const activeDay = dates.includes(selectedDay) ? selectedDay : dates.find(date => date >= today) || dates[dates.length - 1] || "";
  const hasData = bulletin?.source_url && events.length > 0;
  if (!hasData) return <section data-testid="hydrology-bulletin" className="rounded-2xl border border-slate-200 bg-white/70 p-3 text-xs space-y-1">
    <h3 className="font-bold text-ink-900">Bản tin thủy triều ngày</h3>
    <p className="text-ink-500">Chưa tải được bản tin chính thức. Không có số đo tức thời để thay thế.</p>
  </section>;
  return <section data-testid="hydrology-bulletin" className="min-w-0 rounded-2xl border border-cyan-100 bg-white/90 p-3 space-y-2 text-xs">
    <div className="flex flex-wrap justify-between items-start gap-1">
      <h3 className="font-bold text-ink-900">Bản tin thủy triều {bulletin.bulletin_number || "ngày"}</h3>
      <span className={bulletin.status === "STALE" ? "text-amber-700 font-bold" : "text-ink-500"}>{bulletin.status === "STALE" ? "Bản tin cũ (STALE)" : "Cập nhật theo bản tin ngày"}</span>
    </div>
    <p className="text-ink-600">Phát hành: <strong>{timestamp(bulletin.issued_at)}</strong> · giờ TP.HCM</p>
    {activeDay && <div className="rounded-xl bg-cyan-50 p-2 space-y-1">
      <p className="font-semibold text-cyan-900">Dự báo đỉnh ngày {day(activeDay)}{bulletin.status === "STALE" ? " · từ bản tin cũ" : ""}</p>
      {stationIds.map(id => {
        const highs = forecasts.filter(event => event.station_id === id && event.event_date === activeDay && event.event_kind === "HIGH_TIDE" && event.water_level_m !== null && event.event_time !== null && event.quality_status !== "UNAVAILABLE");
        const highest = highs.reduce<HydrologyBulletinEvent | null>((best, event) => !best || event.water_level_m! > best.water_level_m! ? event : best, null);
        return <p key={id} className="flex flex-wrap justify-between gap-1"><span>{stationNames[id]}</span><strong>{highest ? `${highest.water_level_m!.toFixed(2)} m · ${eventClock(highest)}` : "Chưa có số liệu"}</strong></p>;
      })}
    </div>}
    <p className="text-[11px] text-ink-600">Đỉnh/chân triều theo ngày, không phải mực nước hiện tại. Không xác nhận ngập đường.</p>
    <details>
      <summary className="cursor-pointer font-semibold text-cyan-800 py-2 min-h-10 flex items-center">Xem thực đo và dự báo riêng</summary>
      <div className="space-y-3 pt-1">
        <div><h4 className="font-bold text-ink-900">Thực đo · số liệu lịch sử</h4>
          {stationIds.map(id => {
            const observed = events.filter(event => event.station_id === id && event.data_type === "OBSERVED");
            return <div key={id} className="rounded-xl border border-slate-200 p-2 mt-2"><h5 className="font-semibold">{stationNames[id]}{observed[0] ? ` · ${day(observed[0].event_date)}` : ""}</h5><EventRows events={observed} /></div>;
          })}
        </div>
        <div><label className="flex flex-wrap items-center justify-between gap-2 font-bold">Dự báo · chọn ngày
          <select aria-label="Ngày dự báo thủy triều" value={activeDay} onChange={event => setSelectedDay(event.target.value)} className="max-w-full rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs font-normal">{dates.map(date => <option key={date} value={date}>{day(date)}</option>)}</select>
        </label>
          {stationIds.map(id => <div key={id} className="rounded-xl border border-cyan-100 p-2 mt-2"><h5 className="font-semibold">{stationNames[id]} · dự báo{activeDay < today ? " đã qua" : ""}</h5><EventRows events={forecasts.filter(event => event.station_id === id && event.event_date === activeDay)} /></div>)}
        </div>
      </div>
    </details>
    <p className="text-[10px] text-ink-500">Đơn vị nguồn: {bulletin.source_unit || "chưa xác minh"}. Mốc cao độ: {bulletin.vertical_datum && bulletin.vertical_datum !== "UNSPECIFIED_IN_BULLETIN" ? bulletin.vertical_datum : "PDF không nêu riêng cho Phú An/Nhà Bè"}.</p>
    <a href="https://www.nchmf.gov.vn/kttv/vi-VN/1/ban-tin-du-bao-thuy-trieu-10-ngay-toi-tu-ngay-29-10-den-ngay-07-11-2026-post54291.html" target="_blank" rel="noreferrer" className="block text-[11px] text-ink-500 underline">Dự báo thủy triều quốc gia · tham khảo, không thay số liệu hai trạm</a>
    <a href={bulletin.source_url!} target="_blank" rel="noreferrer" className="block break-words text-[11px] font-semibold text-cyan-800 underline py-1">PDF chính thức · Đài KTTV Nam Bộ / Ban Chỉ huy TP.HCM</a>
  </section>;
}
