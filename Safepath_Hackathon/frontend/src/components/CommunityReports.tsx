"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useAuth } from "../context/AuthContext";
import { PlaceSearchCombobox } from "./PlaceSearchCombobox";
import type { PlaceResult } from "../types/contracts";
import { GlassButton } from "./Glass";

type Incident = {
  id: string; incident_type: string; description: string;
  lat: number; lng: number; observed_at: string;
  status: "PENDING" | "VERIFIED" | "REJECTED" | "EXPIRED";
  moderation_note: string | null;
};
const statuses = { PENDING: "Chờ xác minh", VERIFIED: "Đã xác minh", REJECTED: "Từ chối", EXPIRED: "Hết hiệu lực" };

export function CommunityReports() {
  const { user, isAuthenticated, loginWithGoogle } = useAuth();
  const [items, setItems] = useState<Incident[]>([]);
  const [query, setQuery] = useState("");
  const [place, setPlace] = useState<PlaceResult | null>(null);
  const [category, setCategory] = useState("FLOOD");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const userId = user?.id;
  const token = user?.sessionToken;
  useEffect(() => {
    setItems([]);
    if (!userId) return;
    const controller = new AbortController();
    setLoading(true);
    fetch("/api/v1/user/incidents", {
      headers: { "X-User-Id": userId, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      signal: controller.signal, cache: "no-store",
    }).then(async response => {
      if (!response.ok) throw new Error("Không tải được báo cáo đã gửi.");
      setItems(await response.json());
    }).catch(reason => { if (!controller.signal.aborted) setError(String(reason.message)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [userId, token]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!userId || !place || busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await fetch("/api/v1/user/incidents", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-User-Id": userId, ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ incident_type: category, description: description.trim(), lat: place.lat, lng: place.lng, observed_at: new Date().toISOString() }),
      });
      if (!response.ok) throw new Error(response.status === 409 ? "Bạn đã báo cáo sự cố này gần đây." : response.status === 429 ? "Bạn đã gửi quá nhiều báo cáo. Vui lòng thử lại sau." : "Không gửi được báo cáo. Vui lòng thử lại.");
      const item: Incident = await response.json();
      setItems(previous => [item, ...previous]); setDescription("");
      setMessage("Đã lưu báo cáo, đang chờ kiểm duyệt. Báo cáo chưa xác minh không tự động chặn tuyến.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Không gửi được báo cáo."); }
    finally { setBusy(false); }
  }

  return <section className="glass-panel rounded-3xl p-5 sm:p-6 space-y-4" aria-labelledby="community-title">
    <h2 id="community-title" className="font-semibold">Báo cáo cộng đồng</h2>
    <p className="text-sm text-ink-600">Phản ánh sự cố bạn đang quan sát tại TP.HCM. Báo cáo cần được kiểm duyệt và có hiệu lực tối đa 6 giờ; không thay thế hướng dẫn của cơ quan chức năng.</p>
    {!isAuthenticated ? <GlassButton onClick={() => void loginWithGoogle()}>Đăng nhập Google để gửi báo cáo</GlassButton> : <form onSubmit={submit} className="space-y-3 max-w-2xl">
      <PlaceSearchCombobox label="Vị trí sự cố" ariaLabel="Vị trí sự cố" placeholder="Tìm địa chỉ hoặc địa danh" color="emerald" value={query}
        onChangeText={value => { setQuery(value); setPlace(null); }} onSelectPlace={setPlace}
        selectedCoordinates={place ? { lat: place.lat, lng: place.lng } : null} />
      {place && <p className="text-xs">Tọa độ: {place.lat.toFixed(5)}, {place.lng.toFixed(5)}</p>}
      <label className="block text-sm">Loại sự cố<select className="block w-full rounded-xl border p-3 mt-1 bg-white" value={category} onChange={event => setCategory(event.target.value)}>
        <option value="FLOOD">Ngập nước</option><option value="ACCIDENT">Tai nạn</option><option value="BLOCKED">Đường bị chặn</option><option value="OTHER">Nguy hiểm khác</option>
      </select></label>
      <label className="block text-sm">Mô tả quan sát hiện tại<textarea className="block w-full rounded-xl border p-3 mt-1" minLength={10} maxLength={2000} required value={description} onChange={event => setDescription(event.target.value)} /></label>
      <GlassButton type="submit" disabled={!place || description.trim().length < 10 || busy}>{busy ? "Đang gửi…" : "Gửi báo cáo"}</GlassButton>
    </form>}
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {message && <p role="status" className="text-sm text-emerald-800">{message}</p>}
    {loading && <p role="status">Đang tải báo cáo…</p>}
    {isAuthenticated && !loading && !items.length && <p className="text-sm text-ink-600">Bạn chưa có báo cáo nào.</p>}
    <ul className="space-y-3">{items.map(item => <li key={item.id} className="rounded-xl border p-3 space-y-1">
      <p className="font-semibold text-sm">{statuses[item.status]}</p><p className="text-sm break-words">{item.description}</p>
      <p className="text-xs text-ink-600">{item.lat.toFixed(5)}, {item.lng.toFixed(5)} · {new Date(item.observed_at).toLocaleString("vi-VN")}</p>
      {item.moderation_note && <p className="text-sm">Kiểm duyệt: {item.moderation_note}</p>}
    </li>)}</ul>
  </section>;
}
