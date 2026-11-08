/**
 * SafePathAI Frontend API Service (Zero-Mock Runtime).
 * Provides client interfaces for RESTful endpoints and real-time WebSocket connection
 * with automatic reconnection, exponential backoff, and event deduplication.
 */

import {
  ActiveCameraResponse,
  CameraEvidence,
  CameraImageMetadata,
  CameraSummary,
  ModelStatusResponse,
  Coordinates,
  PlaceResult,
  PlaceSearchResponse,
  RouteSearchRequest,
  SafeRouteResponse,
  WeatherTideSignal,
  WebSocketAlertMessage,
  LocationWeatherResponse,
  NearbyTrafficNewsResponse,
  TrafficNewsListResponse,
  TrafficNewsHighlightsResponse,
  TrafficNewsSummaryResponse,
} from "../types/contracts";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || (typeof window !== "undefined" ? window.location.origin : "http://localhost:3000");

/**
 * Resolves the WebSocket base URL safely across local HTTP and production HTTPS environments (B08, R09):
 * - If NEXT_PUBLIC_WS_URL is explicitly configured, upgrades `ws://` to `wss://` when page is served over HTTPS
 *   unless targeting localhost.
 * - Otherwise derives `wss://<host>` on HTTPS or `ws://localhost:8000` on local dev.
 */
export function resolveWsBaseUrl(): string {
  const envWs = (process.env.NEXT_PUBLIC_WS_URL || "").trim();
  if (typeof window !== "undefined") {
    const isHttps = window.location.protocol === "https:";
    const isLocalHost =
      window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    if (envWs) {
      if (isHttps && envWs.startsWith("ws://") && !envWs.includes("localhost") && !envWs.includes("127.0.0.1")) {
        return envWs.replace(/^ws:\/\//i, "wss://").replace(/\/$/, "");
      }
      if (isHttps && !isLocalHost && (envWs.includes("localhost") || envWs.includes("127.0.0.1"))) {
        return `wss://${window.location.host}`;
      }
      return envWs.replace(/\/$/, "");
    }
    if (isHttps) {
      return `wss://${window.location.host}`;
    }
    if (!isLocalHost) {
      return `ws://${window.location.host}`;
    }
  }
  return (envWs || "ws://localhost:8000").replace(/\/$/, "");
}

const WS_BASE_URL = resolveWsBaseUrl();

const SAFE_CAM_ID_REGEX = /^[a-zA-Z0-9_\-]{1,64}$/;

/**
 * Returns full URL to fetch a camera's verified snapshot with path-traversal guard.
 */
export function getCameraImageUrl(camId: string, snapshotId?: string | null): string {
  if (!camId || !SAFE_CAM_ID_REGEX.test(camId)) {
    return "";
  }
  const query = snapshotId ? `?snapshot_id=${encodeURIComponent(snapshotId)}` : "";
  return `${API_BASE_URL}/api/v1/cameras/${encodeURIComponent(camId)}/image${query}`;
}

/** Original source bytes only; this endpoint never requests vision analysis. */
export function getCameraProxyUrl(camId: string): string {
  if (!camId || !SAFE_CAM_ID_REGEX.test(camId)) return "";
  return `${API_BASE_URL}/api/v1/cameras/${encodeURIComponent(camId)}/proxy`;
}

/**
 * Returns full URL to fetch a camera's AI detection overlay frame (with YOLO boxes and water segmentations).
 */
export function getCameraAnalyzedImageUrl(camId: string, snapshotId?: string | null): string {
  if (!camId || !SAFE_CAM_ID_REGEX.test(camId)) {
    return "";
  }
  const snapParam = snapshotId ? `&snapshot_id=${encodeURIComponent(snapshotId)}` : "";
  return `${API_BASE_URL}/api/v1/cameras/${encodeURIComponent(camId)}/image?type=analyzed${snapParam}`;
}

/**
 * Fetches structured technical metadata for a camera snapshot (provenance, eligibility, headers).
 */
export async function fetchCameraMetadata(camId: string): Promise<CameraImageMetadata> {
  if (!camId || !SAFE_CAM_ID_REGEX.test(camId)) {
    throw new Error("Mã định danh camera không hợp lệ.");
  }
  const res = await fetch(`${API_BASE_URL}/api/v1/cameras/${encodeURIComponent(camId)}/metadata`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.detail?.message || `Lỗi tải thông tin camera (${res.status})`);
  }
  return await res.json();
}

/**
 * Triggers an immediate rate-limited fetch for a specific camera snapshot.
 */
export async function triggerCameraRefresh(camId: string): Promise<{
  status: string;
  cam_id?: string;
  is_valid_image?: boolean;
  validation_status?: string;
  source_status?: string;
  image_url?: string | null;
  error_message?: string | null;
  http_status?: number;
} | null> {
  if (!camId || !SAFE_CAM_ID_REGEX.test(camId)) return null;
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/cameras/${encodeURIComponent(camId)}/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.debug("Failed to trigger camera refresh:", err);
    return null;
  }
}

/**
 * Registers one or more cameras as actively viewed (modal open or viewport) for prioritized 60-second refreshes.
 */
export async function registerActiveViewedCameras(camIds: string[], ttlSeconds: number = 90): Promise<ActiveCameraResponse | null> {
  const validIds = camIds.filter(id => id && SAFE_CAM_ID_REGEX.test(id)).slice(0, 50);
  if (validIds.length === 0) return null;
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/cameras/active-view`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cam_ids: validIds, ttl_seconds: ttlSeconds }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.debug("Failed to register active viewed cameras:", err);
    return null;
  }
}

/**
 * Unregisters a camera from active priority when the user closes its modal.
 */
export async function unregisterActiveViewedCamera(camId: string): Promise<void> {
  if (!camId || !SAFE_CAM_ID_REGEX.test(camId)) return;
  try {
    await fetch(`${API_BASE_URL}/api/v1/cameras/${encodeURIComponent(camId)}/active-view`, {
      method: "DELETE",
    });
  } catch (err) {
    console.debug("Failed to unregister active viewed camera:", err);
  }
}

/**
 * Registers cameras along an active navigation route corridor for prioritized 60-second refreshes.
 */
export async function registerActiveRouteCameras(camIds: string[], ttlSeconds: number = 900): Promise<ActiveCameraResponse | null> {
  const validIds = camIds.filter(id => id && SAFE_CAM_ID_REGEX.test(id)).slice(0, 100);
  if (validIds.length === 0) return null;
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/cameras/active-route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cam_ids: validIds, ttl_seconds: ttlSeconds }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    console.debug("Failed to register active route cameras:", err);
    return null;
  }
}

/**
 * Fetches the list of all registered traffic cameras across HCMC with live risk evidence.
 */
export async function fetchCameras(district?: string): Promise<CameraEvidence[]> {
  const url = new URL(`${API_BASE_URL}/api/v1/cameras`);
  if (district) {
    url.searchParams.set("district", district);
  }

  try {
    const res = await fetch(url.toString(), {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    });

    if (!res.ok) {
      throw new Error(`Failed to fetch cameras: ${res.status} ${res.statusText}`);
    }

    return await res.json();
  } catch (error) {
    console.error("Error in fetchCameras:", error);
    throw error;
  }
}

export async function fetchCameraSummary(): Promise<CameraSummary> {
  const url = `${API_BASE_URL}/api/v1/cameras/summary`;
  try {
    const res = await fetch(url, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    });
    if (!res.ok) {
      throw new Error(`Failed to fetch camera summary: ${res.status} ${res.statusText}`);
    }
    return await res.json();
  } catch (error) {
    console.error("Error in fetchCameraSummary:", error);
    throw error;
  }
}

/**
 * Computes an optimal flood-safe route between origin and destination coordinates.
 * Preserves raw OSRM ETA and reranks alternatives using multi-criteria ranking cost.
 */
export async function searchSafeRoute(
  origin: Coordinates,
  destination: Coordinates,
  transportMode: "car" | "motorcycle" | "walking" = "motorcycle"
): Promise<SafeRouteResponse> {
  const url = `${API_BASE_URL}/api/v1/routes/search`;
  const body: RouteSearchRequest = { origin, destination, transport_mode: transportMode };

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const respBody = await res.json().catch(() => null);
      const code = respBody?.detail?.code || (res.status === 503 ? "PROVIDER_DOWN" : "NO_ROUTE");
      const message = respBody?.detail?.message || "Không có tuyến đường khả dụng.";
      throw new Error(`${code}: ${message}`);
    }

    return await res.json();
  } catch (error) {
    console.error("Error in searchSafeRoute:", error);
    throw error;
  }
}

/**
 * Searches places, addresses, streets, and POIs in TP.HCM.
 */
export async function searchPlaces(
  query: string,
  limit: number = 6,
  signal?: AbortSignal
): Promise<PlaceSearchResponse> {
  const url = new URL(`${API_BASE_URL}/api/v1/places/search`);
  url.searchParams.set("q", query);
  url.searchParams.set("limit", String(limit));

  const res = await fetch(url.toString(), {
    method: "GET",
    signal,
    headers: { "Content-Type": "application/json" },
  });

  if (!res.ok) {
    throw new Error(`Failed to search places: ${res.status}`);
  }

  return await res.json();
}

/**
 * Reverse geocodes coordinates to a place name/address.
 */
export async function reverseGeocode(
  lat: number,
  lng: number,
  signal?: AbortSignal
): Promise<PlaceResult> {
  const url = new URL(`${API_BASE_URL}/api/v1/places/reverse`);
  url.searchParams.set("lat", String(lat));
  url.searchParams.set("lng", String(lng));

  const res = await fetch(url.toString(), {
    method: "GET",
    signal,
    headers: { "Content-Type": "application/json" },
  });

  if (!res.ok) {
    throw new Error(`Failed to reverse geocode: ${res.status}`);
  }

  return await res.json();
}

/**
 * Fetches current verified weather and tide conditions.
 */
export async function fetchWeatherTide(): Promise<WeatherTideSignal> {
  const url = `${API_BASE_URL}/api/v1/weather-tide`;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) {
      throw new Error(`Failed to fetch weather/tide: ${res.status}`);
    }
    return await res.json();
  } catch (error) {
    console.error("Error in fetchWeatherTide:", error);
    throw error;
  }
}

/**
 * Fetches system health and backend connectivity metrics.
 */
export async function fetchHealth(): Promise<Record<string, any>> {
  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/health`, { cache: "no-store" });
    if (!res.ok) return { status: "degraded" };
    return await res.json();
  } catch (error) {
    return { status: "offline", error: String(error) };
  }
}

/**
 * Connects to the real-time WebSocket alert stream at /ws/alerts.
 * Includes automatic reconnection with exponential backoff and event deduplication by event_id.
 * Returns a teardown function to close the connection cleanly.
 */
export function connectAlertsWebSocket(
  onMessage: (msg: WebSocketAlertMessage) => void,
  onStatusChange?: (connected: boolean) => void
): () => void {
  let ws: WebSocket | null = null;
  let isClosedManually = false;
  let reconnectAttempts = 0;
  const maxReconnectDelay = 15000;
  const seenEventIds = new Set<string>();
  const MAX_DEDUPE_SIZE = 500;

  function initSocket() {
    if (isClosedManually) return;

    try {
      ws = new WebSocket(`${WS_BASE_URL}/ws/alerts`);

      ws.onopen = () => {
        reconnectAttempts = 0;
        onStatusChange?.(true);
        console.log("[SafePathAI WS] Connected to live alert stream.");
      };

      ws.onmessage = (event) => {
        try {
          const data: WebSocketAlertMessage = JSON.parse(event.data);

          // Deduplicate by event_id if present
          if (data.event_id) {
            if (seenEventIds.has(data.event_id)) {
              return;
            }
            if (seenEventIds.size >= MAX_DEDUPE_SIZE) {
              const first = seenEventIds.values().next().value;
              if (first) seenEventIds.delete(first);
            }
            seenEventIds.add(data.event_id);
          }

          onMessage(data);
        } catch (e) {
          console.warn("[SafePathAI WS] Failed parsing message:", event.data);
        }
      };

      ws.onerror = (err) => {
        console.warn("[SafePathAI WS] Connection error:", err);
      };

      ws.onclose = () => {
        onStatusChange?.(false);
        if (!isClosedManually) {
          reconnectAttempts++;
          const delay = Math.min(1000 * Math.pow(1.5, reconnectAttempts), maxReconnectDelay);
          console.log(`[SafePathAI WS] Disconnected. Reconnecting in ${Math.round(delay)}ms...`);
          setTimeout(initSocket, delay);
        }
      };
    } catch (err) {
      console.warn("[SafePathAI WS] Initialization exception:", err);
      if (!isClosedManually) {
        setTimeout(initSocket, 3000);
      }
    }
  }

  initSocket();

  return () => {
    isClosedManually = true;
    if (ws) {
      ws.close();
      ws = null;
    }
  };
}

/** Deployment status comes from the loaded model manifest, never a marketing label. */
export async function fetchModelStatus(): Promise<ModelStatusResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/models/status`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Không tải được trạng thái mô hình (${response.status}).`);
  return response.json();
}

/** Fetches localized real-time weather at specific GPS coordinates */
export async function getLocationWeather(lat: number, lng: number): Promise<LocationWeatherResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/weather/location?lat=${lat}&lng=${lng}`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Không tải được thời tiết vị trí (${response.status}).`);
  return response.json();
}

/** Fetches real-time municipal and verified traffic news in a radius */
export async function getNearbyTrafficNews(
  lat: number,
  lng: number,
  radiusKm = 3.0
): Promise<NearbyTrafficNewsResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/traffic-news/nearby?lat=${lat}&lng=${lng}&radius_km=${radiusKm}`,
    { cache: "no-store" }
  );
  if (!response.ok) throw new Error(`Không tải được tin giao thông gần đây (${response.status}).`);
  return response.json();
}

export interface FetchTrafficNewsParams {
  limit?: number;
  offset?: number;
  category?: string;
  timeframe?: string;
  search?: string;
  lat?: number;
  lng?: number;
  radius_km?: number;
}

/** Fetches paginated list of traffic news with filters */
export async function fetchTrafficNews(
  params: FetchTrafficNewsParams = {}
): Promise<TrafficNewsListResponse> {
  const query = new URLSearchParams();
  if (params.limit !== undefined) query.set("limit", String(params.limit));
  if (params.offset !== undefined) query.set("offset", String(params.offset));
  if (params.category) query.set("category", params.category);
  if (params.timeframe) query.set("timeframe", params.timeframe);
  if (params.search) query.set("search", params.search);
  if (params.lat !== undefined) query.set("lat", String(params.lat));
  if (params.lng !== undefined) query.set("lng", String(params.lng));
  if (params.radius_km !== undefined) query.set("radius_km", String(params.radius_km));

  const qs = query.toString();
  const url = `${API_BASE_URL}/api/v1/traffic-news${qs ? `?${qs}` : ""}`;
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`Không tải được danh sách tin giao thông (${response.status}).`);
  return response.json();
}

/** Fetches high-signal traffic news highlights for hero and spotlight */
export async function fetchTrafficNewsHighlights(
  limit = 5
): Promise<TrafficNewsHighlightsResponse> {
  const response = await fetch(
    `${API_BASE_URL}/api/v1/traffic-news/highlights?limit=${limit}`,
    { cache: "no-store" }
  );
  if (!response.ok) throw new Error(`Không tải được tin nổi bật (${response.status}).`);
  return response.json();
}

/** Fetches traffic news summary, category counts, and source statuses */
export async function fetchTrafficNewsSummary(): Promise<TrafficNewsSummaryResponse> {
  const response = await fetch(`${API_BASE_URL}/api/v1/traffic-news/summary`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Không tải được thống kê bản tin (${response.status}).`);
  return response.json();
}

export type CameraViewAnalysis = {
  status: string;
  reason?: string;
  snapshot_id?: string;
  content_sha256?: string;
  retrieved_at?: string;
  provider?: string;
  image_url?: string;
  overlay_url?: string;
  vehicle_count?: number;
  vehicle_counts?: Record<string, number> | null;
  flood_ratio?: number | null;
  model_status?: string | null;
  notice?: string;
};

/** Explicit selected-camera preparation; never requested by the Monitor gallery. */
export async function prepareCameraAnalysis(camId: string, signal?: AbortSignal, snapshotId?: string): Promise<CameraViewAnalysis> {
  if (!/^[0-9a-f]{24}$/i.test(camId)) throw new Error("Mã camera không hợp lệ.");
  let expected = snapshotId;
  for (let attempt = 0; attempt < 2; attempt++) {
    const response = await fetch(`${API_BASE_URL}/api/v1/cameras/${encodeURIComponent(camId)}/analysis`, {
      method: "POST", signal, cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(expected ? { snapshot_id: expected } : {}),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => null);
      throw new Error(error?.detail?.message || `Không phân tích được ảnh camera (${response.status}).`);
    }
    const result: CameraViewAnalysis = await response.json();
    if (attempt === 0 && result.status === "FRAME_CHANGED" && result.content_sha256) {
      expected = result.content_sha256;
      continue;
    }
    return result;
  }
  throw new Error("Ảnh camera thay đổi trong lúc phân tích; vui lòng lấy ảnh mới.");
}

/** Source-timestamped daily tide bulletin; not a real-time station gauge. */
export async function fetchHydrologyBulletin(): Promise<import("../types/contracts").HydrologyBulletin> {
  const response = await fetch(`${API_BASE_URL}/api/v1/hydrology/bulletin`, { cache: "no-store" });
  if (!response.ok) throw new Error("Không tải được bản tin thủy văn chính thức.");
  return response.json();
}

/** Resolves server-returned immutable image paths through the configured API origin. */
export function cameraAnalysisImageUrl(path: string): string {
  return new URL(path, API_BASE_URL).toString();
}
