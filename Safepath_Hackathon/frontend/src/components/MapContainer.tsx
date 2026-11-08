"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ScatterplotLayer } from "@deck.gl/layers";
import * as maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { CameraEvidence, Coordinates, MapSelectionMode, RiskLevel, RouteSegmentRisk, SafeRouteResponse } from "../types/contracts";
import { registerActiveViewedCameras } from "../services/api";
import { Camera, MapPin, Box, Activity, Info } from "lucide-react";
import { hasVerifiedFloodObservation } from "../lib/observations";
import GlassToggle, { CameraFilterMode } from "./Glass/GlassToggle";

interface MapContainerProps {
  isSidebarCollapsed?: boolean;
  spatialDark?: boolean;
  pitch?: number;
  showFloodObservations?: boolean;
  cameras: CameraEvidence[];
  recommendedRoute: SafeRouteResponse | null;
  alternativeRoutes: SafeRouteResponse[];
  highlightedSegment?: RouteSegmentRisk | null;
  origin: Coordinates | null;
  destination: Coordinates | null;
  currentLocation?: { lat: number; lng: number; accuracy?: number } | null;
  locationFocusToken?: number;
  mapSelectionMode?: MapSelectionMode;
  onMapClickCoordinates: (coords: Coordinates) => void;
  onSelectCamera: (camera: CameraEvidence) => void;
  onSelectRoute?: (route: SafeRouteResponse) => void;
  onRequestCurrentLocation?: () => void;
  isRequestingLocation?: boolean;
  showCameras?: boolean;
  onToggleCameras?: (show: boolean) => void;
  pitch3D?: boolean;
  onTogglePitch3D?: () => void;
}

const empty = (): GeoJSON.FeatureCollection => ({ type: "FeatureCollection", features: [] });
const cameraNearRoute = (lng: number, lat: number, coords?: number[][]) => {
  if (!coords || coords.length < 2) return false;
  const scale = Math.cos((lat * Math.PI) / 180);
  for (let i = 1; i < coords.length; i++) {
    const [aLng, aLat] = coords[i - 1];
    const [bLng, bLat] = coords[i];
    const dx = (bLng - aLng) * scale;
    const dy = bLat - aLat;
    const length = dx * dx + dy * dy;
    const t = length ? Math.max(0, Math.min(1, ((lng - aLng) * scale * dx + (lat - aLat) * dy) / length)) : 0;
    if (Math.hypot((lng - aLng) * scale - t * dx, lat - aLat - t * dy) < 0.0008) return true;
  }
  return false;
};
const lineFeature = (route: SafeRouteResponse): GeoJSON.Feature => ({
  type: "Feature",
  properties: { routeId: route.route_id },
  geometry: route.geojson_path as GeoJSON.LineString,
});
const setSource = (map: maplibregl.Map, id: string, data: GeoJSON.FeatureCollection) =>
  (map.getSource(id) as maplibregl.GeoJSONSource | undefined)?.setData(data);

export const MapContainer: React.FC<MapContainerProps> = ({
  isSidebarCollapsed = false,
  spatialDark = false,
  pitch = 0,
  showFloodObservations = false,
  cameras,
  recommendedRoute,
  alternativeRoutes,
  highlightedSegment,
  origin,
  destination,
  currentLocation,
  locationFocusToken = 0,
  mapSelectionMode = "NONE",
  onMapClickCoordinates,
  onSelectCamera,
  onSelectRoute,
  showCameras: controlledShowCameras,
  onToggleCameras,
  pitch3D,
  onTogglePitch3D,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const callbacksRef = useRef({ onMapClickCoordinates, onSelectCamera, onSelectRoute });
  const [internalShowCameras, setInternalShowCameras] = useState(true);
  const [cameraFilter, setCameraFilter] = useState<CameraFilterMode>("ALL");
  const [showTrafficLegend, setShowTrafficLegend] = useState<boolean>(false);
  const isControlled = typeof controlledShowCameras === "boolean";
  const showCameras = isControlled ? controlledShowCameras : internalShowCameras;
  const hasQualifiedTrafficData = Boolean(
    recommendedRoute?.segments?.some(
      (s) => s.traffic_status && s.traffic_status !== "UNKNOWN"
    )
  );

  useEffect(() => {
    const timer = setTimeout(() => {
      if (!mapRef.current) return;
      mapRef.current.resize();
      if (recommendedRoute?.geojson_path?.coordinates?.length) {
        const coords = recommendedRoute.geojson_path.coordinates as number[][];
        if (coords.length >= 2) {
          const bounds = coords.reduce((b, p) => b.extend([p[0], p[1]]), new maplibregl.LngLatBounds());
          mapRef.current.fitBounds(bounds, {
            padding: { top: 75, bottom: 75, left: 55, right: 55 },
            duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 250,
            maxZoom: 15,
          });
        }
      }
    }, 220);
    return () => clearTimeout(timer);
  }, [isSidebarCollapsed, recommendedRoute]);

  const dataRef = useRef({
    cameras,
    recommendedRoute,
    alternativeRoutes,
    highlightedSegment,
    mapSelectionMode,
    showCameras,
    cameraFilter,
  });
  const markerRef = useRef<maplibregl.Marker[]>([]);
  const tooltipPopupRef = useRef<maplibregl.Popup | null>(null);
  const lastLocationFocusRef = useRef(0);
  const lastFitRouteRef = useRef<string | null>(null);
  const cameraPreferenceSetRef = useRef(false);
  const [styleVersion, setStyleVersion] = useState(0);
  const [mapError, setMapError] = useState(false);
  const [debugStats, setDebugStats] = useState<{
    apiTotal: number;
    validCoords: number;
    filterMode: CameraFilterMode;
    sourceFeatures: number;
    renderedPoints: number;
    renderedClusters: number;
    zoom: number;
    layerVisible: boolean;
  } | null>(null);

  callbacksRef.current = { onMapClickCoordinates, onSelectCamera, onSelectRoute };
  dataRef.current = {
    cameras,
    recommendedRoute,
    alternativeRoutes,
    highlightedSegment,
    mapSelectionMode,
    showCameras,
    cameraFilter,
  };

  useEffect(() => {
    const saved = sessionStorage.getItem("safepath.showCameras");
    if (saved !== null) {
      cameraPreferenceSetRef.current = true;
      const parsed = saved === "true";
      setInternalShowCameras(parsed);
      onToggleCameras?.(parsed);
    }
  }, [onToggleCameras]);

  useEffect(() => {
    if (recommendedRoute?.route_id && !cameraPreferenceSetRef.current) {
      setInternalShowCameras(false);
      onToggleCameras?.(false);
    }
  }, [recommendedRoute?.route_id, onToggleCameras]);

  const updateCameras = useCallback((overrideFilter?: CameraFilterMode, overrideShowCameras?: boolean) => {
    const map = mapRef.current;
    const { cameras: all, recommendedRoute: route } = dataRef.current;
    const visible = overrideShowCameras !== undefined ? overrideShowCameras : dataRef.current.showCameras;
    const filter = overrideFilter !== undefined ? overrideFilter : dataRef.current.cameraFilter;

    if (!map?.getSource("camera-source")) return;
    if (!visible) {
      setSource(map, "camera-source", empty());
      if (containerRef.current) containerRef.current.dataset.cameraFeatureCount = "0";
      if (process.env.NODE_ENV !== "production") {
        setDebugStats({
          apiTotal: all.length,
          validCoords: all.filter((c) => Number.isFinite(c.lng) && Number.isFinite(c.lat)).length,
          filterMode: filter,
          sourceFeatures: 0,
          renderedPoints: 0,
          renderedClusters: 0,
          zoom: parseFloat(map.getZoom().toFixed(2)),
          layerVisible: false,
        });
      }
      return;
    }

    const routeCoords = route?.geojson_path?.coordinates as number[][] | undefined;
    const validCams = all.filter((cam) => Number.isFinite(cam.lng) && Number.isFinite(cam.lat));

    const filtered = validCams.filter((cam) => {
      if (filter === "ON_ROUTE") {
        if (!routeCoords || routeCoords.length < 2) return false;
        return cameraNearRoute(cam.lng, cam.lat, routeCoords);
      }
      if (filter === "HAS_IMAGE") return Boolean(cam.has_image);
      return true;
    });

    const features: GeoJSON.Feature[] = filtered.map((cam) => {
      const onRoute = routeCoords ? cameraNearRoute(cam.lng, cam.lat, routeCoords) : false;
      let iconName = "camera-icon-gray";
      if (onRoute) {
        iconName = "camera-icon-route";
      } else if (cam.has_image && cam.source_status === "LIVE") {
        iconName = "camera-icon-cyan";
      } else if (cam.has_image || cam.source_status === "STALE") {
        iconName = "camera-icon-amber";
      } else if (cam.image_access_status === "EXTERNAL_ACCESS_RESTRICTED" || (cam as any).source_status === "OFFLINE") {
        iconName = "camera-icon-red";
      } else {
        iconName = "camera-icon-gray";
      }

      return {
        type: "Feature",
        geometry: { type: "Point", coordinates: [cam.lng, cam.lat] },
        properties: {
          id: cam.cam_id,
          label: cam.code || cam.name || "Camera",
          name: cam.name,
          district: cam.district || "TP.HCM",
          iconName,
          onRoute: onRoute ? 1 : 0,
          hasImage: cam.has_image ? 1 : 0,
          sourceStatus: cam.source_status,
        },
      };
    });

    setSource(map, "camera-source", { type: "FeatureCollection", features });
    if (containerRef.current) containerRef.current.dataset.cameraFeatureCount = String(features.length);

    if (process.env.NODE_ENV !== "production") {
      let renderedPoints = 0;
      let renderedClusters = 0;
      try {
        renderedPoints = map.queryRenderedFeatures(undefined, { layers: ["camera-points"] }).length;
        renderedClusters = map.queryRenderedFeatures(undefined, { layers: ["camera-clusters"] }).length;
      } catch {
        // Query may fail before style load
      }
      setDebugStats({
        apiTotal: all.length,
        validCoords: validCams.length,
        filterMode: filter,
        sourceFeatures: features.length,
        renderedPoints,
        renderedClusters,
        zoom: parseFloat(map.getZoom().toFixed(2)),
        layerVisible: true,
      });
    }
  }, []);

  const handleToggleCameras = useCallback(() => {
    cameraPreferenceSetRef.current = true;
    const nextVal = !showCameras;
    setInternalShowCameras(nextVal);
    sessionStorage.setItem("safepath.showCameras", String(nextVal));
    onToggleCameras?.(nextVal);
    updateCameras(undefined, nextVal);
  }, [showCameras, onToggleCameras, updateCameras]);

  const initialMapView = useRef({ spatialDark, pitch });
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    maplibregl.setWorkerUrl(new URL("maplibre-gl/dist/maplibre-gl-worker.mjs", import.meta.url).toString());
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: initialMapView.current.spatialDark ? "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json" : "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
      pitch: initialMapView.current.pitch,
      center: [106.7009, 10.7769],
      zoom: 13,
      attributionControl: false,
    });
    mapRef.current = map;
    if (typeof window !== "undefined") (window as any).__safepath_map = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: false }), "bottom-right");

    const registerCameraIcons = (mapInstance: maplibregl.Map) => {
      const themes: Array<[string, string, string, string, string]> = [
        ["camera-icon-cyan", "#06B6D4", "#06B6D4", "rgba(255,255,255,0.98)", "rgba(207,250,254,0.95)"],
        ["camera-icon-gray", "#94A3B8", "#64748B", "rgba(255,255,255,0.98)", "rgba(241,245,249,0.95)"],
        ["camera-icon-amber", "#F59E0B", "#F59E0B", "rgba(255,255,255,0.98)", "rgba(254,243,199,0.95)"],
        ["camera-icon-red", "#EF4444", "#EF4444", "rgba(255,255,255,0.98)", "rgba(254,226,226,0.95)"],
        ["camera-icon-route", "#F59E0B", "#D97706", "rgba(255,251,235,0.98)", "rgba(253,230,138,0.95)"],
      ];

      for (const [id, borderColor, ledColor, bg1, bg2] of themes) {
        if (!mapInstance.hasImage(id)) {
          const canvas = document.createElement("canvas");
          canvas.width = 64;
          canvas.height = 64;
          const ctx = canvas.getContext("2d");
          if (ctx) {
            ctx.shadowColor = "rgba(0, 0, 0, 0.18)";
            ctx.shadowBlur = 8;
            ctx.shadowOffsetY = 3;

            ctx.beginPath();
            ctx.arc(32, 32, 24, 0, Math.PI * 2);
            const grad = ctx.createLinearGradient(12, 12, 52, 52);
            grad.addColorStop(0, bg1);
            grad.addColorStop(1, bg2);
            ctx.fillStyle = grad;
            ctx.fill();

            ctx.shadowColor = "transparent";
            ctx.lineWidth = 2.5;
            ctx.strokeStyle = borderColor;
            ctx.stroke();

            ctx.beginPath();
            ctx.arc(32, 32, 22, 0, Math.PI * 2);
            ctx.lineWidth = 1;
            ctx.strokeStyle = "rgba(255, 255, 255, 0.8)";
            ctx.stroke();

            ctx.fillStyle = "#1E293B";
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(20, 24, 24, 16, [4]);
            else ctx.rect(20, 24, 24, 16);
            ctx.fill();

            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(25, 21, 8, 4, [2]);
            else ctx.rect(25, 21, 8, 4);
            ctx.fill();

            ctx.beginPath();
            ctx.arc(32, 32, 5.5, 0, Math.PI * 2);
            ctx.fillStyle = borderColor;
            ctx.fill();

            ctx.beginPath();
            ctx.arc(32, 32, 3.2, 0, Math.PI * 2);
            ctx.fillStyle = "#0F172A";
            ctx.fill();

            ctx.beginPath();
            ctx.arc(31, 30.8, 1.2, 0, Math.PI * 2);
            ctx.fillStyle = "#FFFFFF";
            ctx.fill();

            ctx.beginPath();
            ctx.arc(39.5, 27.5, 1.8, 0, Math.PI * 2);
            ctx.fillStyle = ledColor;
            ctx.fill();

            mapInstance.addImage(id, ctx.getImageData(0, 0, 64, 64), { pixelRatio: 2 });
          }
        }
      }

      if (!mapInstance.hasImage("camera-cluster-icon")) {
        const cCanvas = document.createElement("canvas");
        cCanvas.width = 76;
        cCanvas.height = 76;
        const cCtx = cCanvas.getContext("2d");
        if (cCtx) {
          cCtx.shadowColor = "rgba(15, 23, 42, 0.28)";
          cCtx.shadowBlur = 10;
          cCtx.shadowOffsetY = 4;

          cCtx.beginPath();
          cCtx.arc(38, 38, 30, 0, Math.PI * 2);
          const grad = cCtx.createLinearGradient(12, 12, 64, 64);
          grad.addColorStop(0, "#4F46E5");
          grad.addColorStop(0.5, "#2563EB");
          grad.addColorStop(1, "#06B6D4");
          cCtx.fillStyle = grad;
          cCtx.fill();

          cCtx.shadowColor = "transparent";
          cCtx.lineWidth = 2.5;
          cCtx.strokeStyle = "#FFFFFF";
          cCtx.stroke();

          cCtx.beginPath();
          cCtx.arc(38, 38, 27.5, 0, Math.PI * 2);
          cCtx.lineWidth = 1;
          cCtx.strokeStyle = "rgba(255, 255, 255, 0.4)";
          cCtx.stroke();

          cCtx.beginPath();
          cCtx.arc(54, 20, 9, 0, Math.PI * 2);
          cCtx.fillStyle = "#1E1B4B";
          cCtx.fill();
          cCtx.lineWidth = 1.5;
          cCtx.strokeStyle = "#FFFFFF";
          cCtx.stroke();

          cCtx.fillStyle = "#FFFFFF";
          cCtx.beginPath();
          if (cCtx.roundRect) cCtx.roundRect(49, 17, 10, 6, [1.5]);
          else cCtx.rect(49, 17, 10, 6);
          cCtx.fill();
          cCtx.beginPath();
          cCtx.arc(54, 20, 1.5, 0, Math.PI * 2);
          cCtx.fillStyle = "#06B6D4";
          cCtx.fill();

          mapInstance.addImage("camera-cluster-icon", cCtx.getImageData(0, 0, 76, 76), { pixelRatio: 2 });
        }
      }
    };

    const onStyleLoad = () => {
      setMapError(false);
      registerCameraIcons(map);

      // Camera Layers - Refined luminous pearl / aurora style
      map.addSource("camera-source", {
        type: "geojson",
        data: empty(),
        cluster: true,
        clusterRadius: 42,
        clusterMaxZoom: 13,
      });
      map.addLayer({
        id: "camera-clusters",
        type: "symbol",
        source: "camera-source",
        filter: ["has", "point_count"],
        layout: {
          "icon-image": "camera-cluster-icon",
          "icon-size": 0.5,
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
          "text-field": ["get", "point_count_abbreviated"],
          "text-font": ["Noto Sans Bold"],
          "text-size": 11,
          "text-allow-overlap": true,
          "text-ignore-placement": true,
        },
        paint: {
          "text-color": "#FFFFFF",
        },
      });
      map.addLayer({
        id: "camera-points",
        type: "symbol",
        source: "camera-source",
        filter: ["!", ["has", "point_count"]],
        layout: {
          "icon-image": ["coalesce", ["get", "iconName"], "camera-icon-gray"],
          "icon-size": 0.5,
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
      });
      map.addLayer({
        id: "camera-label",
        type: "symbol",
        source: "camera-source",
        filter: ["!", ["has", "point_count"]],
        minzoom: 14,
        layout: {
          "text-field": ["get", "label"],
          "text-font": ["Noto Sans Regular"],
          "text-size": 10,
          "text-offset": [0, 1.8],
          "text-optional": true,
        },
        paint: { "text-color": "#15233D", "text-halo-color": "#FFFFFF", "text-halo-width": 2 },
      });

      // Route Layers - Daylight Spatial / Light Cinematic
      map.addSource("route-alternatives-source", { type: "geojson", data: empty() });
      map.addLayer({
        id: "route-alternatives-line",
        type: "line",
        source: "route-alternatives-source",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#9BB1C2", "line-width": 5, "line-opacity": 0.85, "line-dasharray": [2, 1] },
      });

      map.addSource("route-recommended-source", { type: "geojson", data: empty() });
      map.addLayer({
        id: "route-recommended-casing",
        type: "line",
        source: "route-recommended-source",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#18B6AD", "line-width": 11, "line-opacity": 0.45 },
      });
      map.addLayer({
        id: "route-recommended-core",
        type: "line",
        source: "route-recommended-source",
        filter: ["!has", "risk_level"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#168BD2", "line-width": 6, "line-opacity": 1 },
      });

      map.addSource("route-traffic-source", { type: "geojson", data: empty() });
      map.addLayer({
        id: "route-traffic-casing",
        type: "line",
        source: "route-traffic-source",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#FFFFFF", "line-width": 10, "line-opacity": 0.8 },
      });
      map.addLayer({
        id: "route-traffic-flow",
        type: "line",
        source: "route-traffic-source",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-width": 6,
          "line-opacity": 0.95,
          "line-color": [
            "match",
            ["get", "traffic_status"],
            "FREE_FLOW", "#16A34A",
            "SLOW", "#F59E0B",
            "CONGESTED", "#EF4444",
            "CLOSED", "#7F1D1D",
            "UNKNOWN", "#94A3B8",
            "#94A3B8",
          ],
        },
      });
      map.addLayer({
        id: "route-warning-segments",
        type: "line",
        source: "route-recommended-source",
        filter: ["==", ["get", "risk_level"], "MODERATE"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#E8A13B", "line-width": 7, "line-opacity": 1 },
      });
      map.addLayer({
        id: "route-critical-segments",
        type: "line",
        source: "route-recommended-source",
        filter: ["==", ["get", "risk_level"], "CRITICAL"],
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#E16B68", "line-width": 8, "line-opacity": 1 },
      });

      map.addSource("route-step-source", { type: "geojson", data: empty() });
      map.addLayer({
        id: "route-step-highlight",
        type: "line",
        source: "route-step-source",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#18B6AD", "line-width": 8, "line-opacity": 1 },
      });

      if (containerRef.current) {
        const ids = map.getStyle().layers.map((layer) => layer.id);
        containerRef.current.dataset.routeAboveCamera = String(
          ids.indexOf("route-recommended-core") > ids.indexOf("camera-points")
        );
      }
      setStyleVersion((v) => v + 1);
      updateCameras();
    };

    const onMapClick = (e: maplibregl.MapMouseEvent) => {
      if (dataRef.current.mapSelectionMode !== "NONE") {
        callbacksRef.current.onMapClickCoordinates({ lat: e.lngLat.lat, lng: e.lngLat.lng });
        return;
      }
      if (dataRef.current.showCameras) {
        const bbox: [maplibregl.PointLike, maplibregl.PointLike] = [
          [e.point.x - 18, e.point.y - 18],
          [e.point.x + 18, e.point.y + 18],
        ];
        if (map.getLayer("camera-points")) {
          const pointFeatures = map.queryRenderedFeatures(bbox, { layers: ["camera-points"] });
          if (pointFeatures.length > 0) {
            const id = pointFeatures[0].properties?.id;
            const camera = dataRef.current.cameras.find((c) => c.cam_id === id);
            if (camera) {
              callbacksRef.current.onSelectCamera(camera);
              return;
            }
          }
        }
        if (map.getLayer("camera-clusters")) {
          const clusterFeatures = map.queryRenderedFeatures(bbox, { layers: ["camera-clusters"] });
          if (clusterFeatures.length > 0) {
            const clusterId = clusterFeatures[0].properties?.cluster_id;
            const source = map.getSource("camera-source") as maplibregl.GeoJSONSource | undefined;
            if (source && clusterId !== undefined) {
              source.getClusterExpansionZoom(clusterId).then((zoom) => {
                if (zoom === null || zoom === undefined) return;
                const coords = (clusterFeatures[0].geometry as GeoJSON.Point).coordinates;
                map.easeTo({ center: [coords[0], coords[1]], zoom: zoom + 1 });
              }).catch(() => {});
              return;
            }
          }
        }
      }
    };

    const onMapMouseMove = (e: maplibregl.MapMouseEvent) => {
      if (!dataRef.current.showCameras || !map.getLayer("camera-points")) {
        resetCursor();
        if (tooltipPopupRef.current) tooltipPopupRef.current.remove();
        return;
      }
      const bbox: [maplibregl.PointLike, maplibregl.PointLike] = [
        [e.point.x - 16, e.point.y - 16],
        [e.point.x + 16, e.point.y + 16],
      ];
      const pointFeatures = map.queryRenderedFeatures(bbox, { layers: ["camera-points"] });
      const clusterFeatures = map.queryRenderedFeatures(bbox, { layers: ["camera-clusters"] });

      if (pointFeatures.length > 0) {
        setCursorPointer();
        const feat = pointFeatures[0];
        const coords = (feat.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
        const props = feat.properties || {};

        if (!tooltipPopupRef.current) {
          tooltipPopupRef.current = new maplibregl.Popup({
            closeButton: false,
            closeOnClick: false,
            offset: [0, -20],
            className: "camera-map-tooltip",
          });
        }

        const hasImg = props.hasImage === 1;
        const onRoute = props.onRoute === 1;
        const statusText = onRoute
          ? "⭐ Camera trên tuyến tìm kiếm"
          : hasImg
          ? "🟢 Có ảnh trực tiếp"
          : "⚪ Chưa có ảnh";
        const html = `
          <div style="font-family: system-ui, -apple-system, sans-serif; padding: 4px 6px; font-size: 11px; line-height: 1.35; color: #1E1B4B; min-width: 140px;">
            <div style="font-weight: 700; color: #1E1B4B;">${props.label || "Camera"}</div>
            <div style="color: #64748B; font-size: 10px; margin-top: 1px;">${props.name || props.district || "TP.HCM"}</div>
            <div style="color: ${onRoute ? "#D97706" : hasImg ? "#059669" : "#64748B"}; font-size: 10px; font-weight: 600; margin-top: 3px;">${statusText}</div>
          </div>
        `;
        tooltipPopupRef.current.setLngLat(coords).setHTML(html).addTo(map);
        return;
      }

      if (clusterFeatures.length > 0) {
        setCursorPointer();
        if (tooltipPopupRef.current) tooltipPopupRef.current.remove();
        return;
      }

      resetCursor();
      if (tooltipPopupRef.current) tooltipPopupRef.current.remove();
    };

    const onCameraClick = (e: maplibregl.MapLayerMouseEvent) => {
      if (!dataRef.current.showCameras) return;
      const id = e.features?.[0]?.properties?.id;
      const camera = dataRef.current.cameras.find((c) => c.cam_id === id);
      if (camera) callbacksRef.current.onSelectCamera(camera);
    };

    const onRouteClick = (e: maplibregl.MapLayerMouseEvent) => {
      if (dataRef.current.mapSelectionMode !== "NONE") return;
      const id = e.features?.[0]?.properties?.routeId;
      const route = dataRef.current.alternativeRoutes.find((r) => r.route_id === id);
      if (route) callbacksRef.current.onSelectRoute?.(route);
    };

    const onIdle = () => {
      if (map.areTilesLoaded() && containerRef.current) containerRef.current.dataset.tilesReady = "true";
      if (process.env.NODE_ENV !== "production") {
        try {
          if (map.getLayer("camera-points") && map.getLayer("camera-clusters")) {
            const renderedPoints = map.queryRenderedFeatures(undefined, { layers: ["camera-points"] }).length;
            const renderedClusters = map.queryRenderedFeatures(undefined, { layers: ["camera-clusters"] }).length;
            setDebugStats((prev) => prev ? { ...prev, renderedPoints, renderedClusters } : null);
          }
        } catch {}
      }
    };

    const onMoveEnd = () => {
      if (containerRef.current) containerRef.current.dataset.mapZoom = map.getZoom().toFixed(3);
      try {
        if (map.getLayer("camera-points")) {
          const rendered = map.queryRenderedFeatures(undefined, { layers: ["camera-points"] });
          const ids = (rendered || []).slice(0, 10).map((f) => f.properties?.id).filter(Boolean);
          if (ids.length > 0) {
            registerActiveViewedCameras(ids, 90).catch(() => {});
          }
        }
      } catch {}
      if (process.env.NODE_ENV !== "production") {
        try {
          if (map.getLayer("camera-points") && map.getLayer("camera-clusters")) {
            const renderedPoints = map.queryRenderedFeatures(undefined, { layers: ["camera-points"] }).length;
            const renderedClusters = map.queryRenderedFeatures(undefined, { layers: ["camera-clusters"] }).length;
            setDebugStats((prev) => prev ? {
              ...prev,
              renderedPoints,
              renderedClusters,
              zoom: parseFloat(map.getZoom().toFixed(2)),
            } : null);
          }
        } catch {}
      }
    };

    const setCursorPointer = () => { if (mapRef.current) mapRef.current.getCanvas().style.cursor = "pointer"; };
    const resetCursor = () => { if (mapRef.current) mapRef.current.getCanvas().style.cursor = ""; };

    const onCameraMouseEnter = (e: maplibregl.MapLayerMouseEvent) => {
      setCursorPointer();
      const feature = e.features?.[0];
      if (!feature || !mapRef.current) return;
      const coords = (feature.geometry as GeoJSON.Point).coordinates.slice() as [number, number];
      const props = feature.properties || {};

      if (!tooltipPopupRef.current) {
        tooltipPopupRef.current = new maplibregl.Popup({
          closeButton: false,
          closeOnClick: false,
          offset: [0, -18],
          className: "camera-map-tooltip",
        });
      }

      const hasImg = props.hasImage === 1;
      const onRoute = props.onRoute === 1;
      const statusText = onRoute
        ? "⭐ Camera trên tuyến tìm kiếm"
        : hasImg
        ? "🟢 Có ảnh trực tiếp"
        : "⚪ Chưa có ảnh";
      const html = `
        <div style="font-family: system-ui, -apple-system, sans-serif; padding: 4px 6px; font-size: 11px; line-height: 1.35; color: #1E1B4B; min-width: 140px;">
          <div style="font-weight: 700; color: #1E1B4B;">${props.label || "Camera"}</div>
          <div style="color: #64748B; font-size: 10px; margin-top: 1px;">${props.name || props.district || "TP.HCM"}</div>
          <div style="color: ${onRoute ? "#D97706" : hasImg ? "#059669" : "#64748B"}; font-size: 10px; font-weight: 600; margin-top: 3px;">${statusText}</div>
        </div>
      `;
      tooltipPopupRef.current.setLngLat(coords).setHTML(html).addTo(mapRef.current);
    };

    const onCameraMouseLeave = () => {
      resetCursor();
      if (tooltipPopupRef.current) {
        tooltipPopupRef.current.remove();
      }
    };

    const onClusterClick = (e: maplibregl.MapLayerMouseEvent) => {
      const features = map.queryRenderedFeatures(e.point, { layers: ["camera-clusters"] });
      const clusterId = features[0]?.properties?.cluster_id;
      const source = map.getSource("camera-source") as maplibregl.GeoJSONSource | undefined;
      if (source && clusterId !== undefined) {
        source.getClusterExpansionZoom(clusterId).then((zoom) => {
          if (zoom === null || zoom === undefined) return;
          const coords = (features[0].geometry as GeoJSON.Point).coordinates;
          map.easeTo({ center: [coords[0], coords[1]], zoom: zoom + 1 });
        }).catch(() => {});
      }
    };

    const onTrafficSegmentClick = (e: maplibregl.MapMouseEvent) => {
      const features = map.queryRenderedFeatures(e.point, { layers: ["route-traffic-flow"] });
      if (!features.length || !features[0].properties) return;
      const props = features[0].properties;

      const status = props.traffic_status || "UNKNOWN";
      const statusMap: Record<string, { label: string; color: string; bg: string }> = {
        FREE_FLOW: { label: "Thông thoáng", color: "#16A34A", bg: "#DCFCE7" },
        SLOW: { label: "Di chuyển chậm", color: "#D97706", bg: "#FEF3C7" },
        CONGESTED: { label: "Ùn tắc", color: "#DC2626", bg: "#FEE2E2" },
        CLOSED: { label: "Phong tỏa / Cấm đường", color: "#991B1B", bg: "#FECACA" },
        UNKNOWN: { label: "Chưa rõ dữ liệu", color: "#64748B", bg: "#F1F5F9" },
      };
      const info = statusMap[status] || statusMap.UNKNOWN;
      const delaySec = props.traffic_delay_seconds ? Math.round(Number(props.traffic_delay_seconds)) : 0;
      const currentSpeed = props.observed_speed_kmh ? `${Number(props.observed_speed_kmh).toFixed(0)} km/h` : null;
      const freeFlowSpeed = props.free_flow_speed_kmh ? `${Number(props.free_flow_speed_kmh).toFixed(0)} km/h` : null;
      const source = props.traffic_source ? (String(props.traffic_source).includes("tomtom") ? "TomTom Live Flow" : String(props.traffic_source).includes("camera") ? "Camera AI" : String(props.traffic_source)) : "Dữ liệu cơ sở";
      const conf = props.traffic_confidence ? `${Math.round(Number(props.traffic_confidence) * 100)}%` : null;
      const isFloodProne = props.historical_flood_prone === true || props.historical_flood_prone === "true";
      const isCritical = props.risk_level === "CRITICAL";

      const html = `
        <div style="font-family: system-ui, -apple-system, sans-serif; padding: 8px 10px; max-width: 240px; color: #0f172a; line-height: 1.4;">
          <div style="font-size: 12px; font-weight: 800; color: #0f172a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 4px;">
            ${props.street_name || "Đoạn đường"}
          </div>
          <div style="display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 6px;">
            <div style="display: inline-flex; align-items: center; gap: 4px; padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 700; color: ${info.color}; background: ${info.bg};">
              <span>●</span> <span>${info.label}</span>
            </div>
            ${isCritical ? `<div style="display: inline-flex; align-items: center; gap: 3px; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; color: #b91c1c; background: #fee2e2;">⚠️ Ngập sâu</div>` : isFloodProne ? `<div style="display: inline-flex; align-items: center; gap: 3px; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: 700; color: #c2410c; background: #ffedd5;">🌊 Điểm ngập lịch sử</div>` : ""}
          </div>
          <div style="font-size: 11px; color: #475569; display: flex; flex-direction: column; gap: 2px;">
            <div>Chiều dài đoạn: <strong>${Math.round(Number(props.length_meters || 0))}m</strong></div>
            ${currentSpeed ? `<div>Vận tốc hiện tại: <strong style="color: #0f172a;">${currentSpeed}</strong>${freeFlowSpeed ? ` <span style="color: #94a3b8; font-weight: normal;">(chuẩn: ${freeFlowSpeed})</span>` : ""}</div>` : ""}
            ${delaySec > 0 ? `<div style="color: #ea580c; font-weight: 600;">Ước tính trễ: <strong>+${Math.round(delaySec / 60)} phút</strong> (${delaySec}s)</div>` : ""}
            <div style="font-size: 10px; color: #94a3b8; margin-top: 4px; border-top: 1px solid #f1f5f9; padding-top: 3px; display: flex; justify-content: space-between;">
              <span>Nguồn: <strong>${source}</strong></span>
              ${conf ? `<span>Độ tin cậy: <strong>${conf}</strong></span>` : ""}
            </div>
          </div>
        </div>
      `;

      new maplibregl.Popup({ closeButton: true, closeOnClick: true, maxWidth: "260px", className: "traffic-segment-popup" })
        .setLngLat(e.lngLat)
        .setHTML(html)
        .addTo(map);
    };

    map.on("style.load", onStyleLoad);
    map.on("click", onMapClick);
    map.on("mousemove", onMapMouseMove);
    map.on("click", "camera-points", onCameraClick);
    map.on("click", "camera-clusters", onClusterClick);
    map.on("mouseenter", "camera-points", onCameraMouseEnter);
    map.on("mouseleave", "camera-points", onCameraMouseLeave);
    map.on("mouseenter", "camera-clusters", setCursorPointer);
    map.on("mouseleave", "camera-clusters", resetCursor);
    map.on("click", "route-alternatives-line", onRouteClick);
    map.on("click", "route-traffic-flow", onTrafficSegmentClick);
    map.on("mouseenter", "route-traffic-flow", setCursorPointer);
    map.on("mouseleave", "route-traffic-flow", resetCursor);
    map.on("moveend", onMoveEnd);
    map.on("idle", onIdle);

    const timer = window.setTimeout(() => {
      if (!map.getSource("route-recommended-source")) setMapError(true);
    }, 15000);
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(containerRef.current);

    return () => {
      window.clearTimeout(timer);
      observer.disconnect();
      if (tooltipPopupRef.current) tooltipPopupRef.current.remove();
      markerRef.current.forEach((m) => m.remove());
      markerRef.current = [];
      map.off("style.load", onStyleLoad);
      map.off("click", onMapClick);
      map.off("mousemove", onMapMouseMove);
      map.off("click", "camera-points", onCameraClick);
      map.off("click", "camera-clusters", onClusterClick);
      map.off("mouseenter", "camera-points", onCameraMouseEnter);
      map.off("mouseleave", "camera-points", onCameraMouseLeave);
      map.off("mouseenter", "camera-clusters", setCursorPointer);
      map.off("mouseleave", "camera-clusters", resetCursor);
      map.off("click", "route-alternatives-line", onRouteClick);
      map.off("click", "route-traffic-flow", onTrafficSegmentClick);
      map.off("mouseenter", "route-traffic-flow", setCursorPointer);
      map.off("mouseleave", "route-traffic-flow", resetCursor);
      map.off("moveend", onMoveEnd);
      map.off("idle", onIdle);
      map.remove();
      mapRef.current = null;
      if (typeof window !== "undefined") delete (window as any).__safepath_map;
    };
  }, [updateCameras]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getSource("route-recommended-source")) return;
    const segmentRiskFeatures = (recommendedRoute?.segments || [])
      .filter((s) => s.geojson_path && (s.risk_level === RiskLevel.MODERATE || s.risk_level === RiskLevel.CRITICAL))
      .map((s) => ({
        type: "Feature" as const,
        properties: { routeId: recommendedRoute!.route_id, risk_level: s.risk_level },
        geometry: s.geojson_path as GeoJSON.LineString,
      }));

    setSource(map, "route-recommended-source", {
      type: "FeatureCollection",
      features: recommendedRoute ? [lineFeature(recommendedRoute), ...segmentRiskFeatures] : [],
    });
    setSource(map, "route-alternatives-source", {
      type: "FeatureCollection",
      features: alternativeRoutes.map(lineFeature),
    });
    setSource(map, "route-step-source", {
      type: "FeatureCollection",
      features: highlightedSegment?.geojson_path
        ? [{ type: "Feature", properties: {}, geometry: highlightedSegment.geojson_path as GeoJSON.LineString }]
        : [],
    });

    const trafficFeatures = (recommendedRoute?.segments || [])
      .filter((s) => s.geojson_path && s.geojson_path.coordinates && s.geojson_path.coordinates.length >= 2)
      .map((s, idx) => ({
        type: "Feature" as const,
        properties: {
          segment_idx: idx,
          street_name: s.street_name || "Đoạn đường",
          length_meters: s.length_meters,
          traffic_status: s.traffic_status || "UNKNOWN",
          observed_speed_kmh: s.observed_speed_kmh,
          free_flow_speed_kmh: s.free_flow_speed_kmh,
          traffic_density_score: s.traffic_density_score,
          traffic_confidence: s.traffic_confidence,
          traffic_freshness_seconds: s.traffic_freshness_seconds,
          traffic_source: s.traffic_source,
          traffic_delay_seconds: s.traffic_delay_seconds,
          observed_at: s.observed_at,
          risk_level: s.risk_level,
          historical_flood_prone: s.historical_flood_prone,
          weather_risk: s.weather_risk,
        },
        geometry: s.geojson_path as GeoJSON.LineString,
      }));

    if (map.getSource("route-traffic-source")) {
      setSource(map, "route-traffic-source", {
        type: "FeatureCollection",
        features: recommendedRoute ? trafficFeatures : [],
      });
    }

    if (containerRef.current) {
      if (recommendedRoute) {
        containerRef.current.dataset.routeVertices = String(recommendedRoute.geojson_path.coordinates.length);
        containerRef.current.dataset.selectedRouteId = recommendedRoute.route_id;
        const coordinates = recommendedRoute.geojson_path.coordinates as number[][];
        containerRef.current.dataset.routeGeometryKey = JSON.stringify([
          coordinates.length,
          coordinates[Math.floor(coordinates.length / 3)],
          coordinates[Math.floor((coordinates.length * 2) / 3)],
        ]);
      } else {
        delete containerRef.current.dataset.routeVertices;
        delete containerRef.current.dataset.selectedRouteId;
        delete containerRef.current.dataset.routeGeometryKey;
      }
      if (highlightedSegment?.geojson_path) {
        containerRef.current.dataset.highlightVertices = String(highlightedSegment.geojson_path.coordinates.length);
      } else {
        delete containerRef.current.dataset.highlightVertices;
      }
    }

    updateCameras();

    if (recommendedRoute?.route_id && lastFitRouteRef.current !== recommendedRoute.route_id) {
      const coords = recommendedRoute.geojson_path.coordinates as number[][];
      if (coords.length) {
        const bounds = coords.reduce((b, p) => b.extend([p[0], p[1]]), new maplibregl.LngLatBounds());
        map.resize();
        map.fitBounds(bounds, {
          padding: { top: 75, bottom: 75, left: 55, right: 55 },
          duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 600,
          maxZoom: 15,
        });
        lastFitRouteRef.current = recommendedRoute.route_id;
      }
    }
    if (!recommendedRoute) lastFitRouteRef.current = null;
  }, [recommendedRoute, alternativeRoutes, highlightedSegment, styleVersion, updateCameras]);

  useEffect(() => {
    updateCameras();
  }, [cameras, showCameras, cameraFilter, updateCameras, styleVersion]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    markerRef.current.forEach((m) => m.remove());
    markerRef.current = [];
    const add = (point: Coordinates | null | undefined, label: string, colorClass: string, type: string) => {
      if (!point) return;
      const el = document.createElement("div");
      el.className = `w-8 h-8 rounded-full border-2 border-white shadow-glass flex items-center justify-center text-white font-bold text-xs ${colorClass}`;
      el.textContent = label;
      el.setAttribute("role", "img");
      el.setAttribute("aria-label", type);
      el.dataset.markerType = type;
      markerRef.current.push(new maplibregl.Marker({ element: el }).setLngLat([point.lng, point.lat]).addTo(map));
    };
    add(origin, "A", "bg-emerald-500", "origin");
    add(destination, "B", "bg-rose-500", "destination");
    add(currentLocation, "●", "bg-blue-600 ring-4 ring-blue-400/30", "current-location");
  }, [origin, destination, currentLocation]);

  useEffect(() => {
    if (currentLocation && mapRef.current && locationFocusToken > lastLocationFocusRef.current) {
      lastLocationFocusRef.current = locationFocusToken;
      mapRef.current.flyTo({
        center: [currentLocation.lng, currentLocation.lat],
        zoom: 16,
        duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 600,
      });
    }
  }, [currentLocation, locationFocusToken]);

  useEffect(() => {
    mapRef.current?.easeTo({ pitch, duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 850 });
  }, [pitch]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !spatialDark) return;
    const data = cameras.filter(c => hasVerifiedFloodObservation(c) && Number.isFinite(c.lng) && Number.isFinite(c.lat));
    const layers = showFloodObservations ? [new ScatterplotLayer<CameraEvidence>({
      id: "verified-water-observations", data, getPosition: c => [c.lng, c.lat],
      getRadius: 35, radiusMinPixels: 8, radiusMaxPixels: 18,
      getFillColor: c => c.risk_level === "CRITICAL" ? [255, 110, 130, 130] : [135, 170, 195, 130],
      stroked: true, getLineColor: [200, 220, 235, 210], lineWidthMinPixels: 1,
      pickable: false,
    })] : [];
    const overlay = new MapboxOverlay({ interleaved: false, layers });
    map.addControl(overlay);
    return () => { if (mapRef.current === map) map.removeControl(overlay); };
  }, [cameras, showFloodObservations, spatialDark, styleVersion]);

  return (
    <div className="relative w-full h-full min-h-0 overflow-hidden bg-pearl-100">
      <div ref={containerRef} className="w-full h-full" aria-label="Bản đồ tuyến đường" data-testid="route-map" />

      {mapError && (
        <div role="alert" className="absolute bottom-12 left-3 z-20 rounded-2xl glass-panel-elevated p-3 text-sm text-ink-900 border border-rose-200">
          Không tải được bản đồ.{" "}
          <button className="underline text-indigo-600 font-semibold" onClick={() => window.location.reload()}>
            Thử lại
          </button>
        </div>
      )}

      {mapSelectionMode !== "NONE" && (
        <div className="absolute top-4 left-4 right-20 z-20 rounded-2xl glass-panel px-4 py-2.5 text-xs font-bold text-ink-900 pointer-events-none flex items-center gap-2 border border-amber-300 shadow-glass animate-float">
          <MapPin className="h-4 w-4 text-amber-500" />
          <span>{mapSelectionMode === "ORIGIN" ? "Chạm bản đồ để chọn điểm đi" : "Chạm bản đồ để chọn điểm đến"}</span>
        </div>
      )}

      {showFloodObservations && <div className="water-layer-legend liquid-island" role="status">
        {cameras.some(c => hasVerifiedFloodObservation(c)) ? "Điểm quan trắc nước đã xác minh · không biểu thị độ sâu" : "Chưa có quan trắc nước đủ xác minh để hiển thị"}
      </div>}

      {/* Floating Liquid Glass Controls: Floating Camera & 3D Toggles */}
      <div data-tour="camera-toggle" className="map-camera-controls absolute z-20 flex flex-col items-end gap-2">
        <div className="flex items-center gap-2">
          {onTogglePitch3D && (
            <button
              type="button"
              onClick={onTogglePitch3D}
              aria-pressed={pitch3D}
              aria-label={pitch3D ? "Chuyển sang chế độ bản đồ 2D" : "Chuyển sang chế độ bản đồ 3D"}
              title={pitch3D ? "Chuyển sang 2D" : "Chuyển sang 3D"}
              className="min-h-[44px] min-w-[44px] px-3 py-1.5 rounded-full text-xs font-bold glass-surface border border-white/90 shadow-glass-sm text-ink-800 hover:text-ink-950 flex items-center justify-center gap-1.5 cursor-pointer transition-all duration-200"
            >
              <Box className="w-4 h-4 text-indigo-600" />
              <span>{pitch3D ? "3D" : "2D"}</span>
            </button>
          )}
          <GlassToggle
            checked={showCameras}
            onChange={handleToggleCameras}
            label="Hiển thị camera"
            filter={cameraFilter}
            onFilterChange={(f) => {
              setCameraFilter(f);
              updateCameras(f);
            }}
            cameraCount={{
              active: cameras.filter((c) => {
                if (!Number.isFinite(c.lng) || !Number.isFinite(c.lat)) return false;
                if (cameraFilter === "HAS_IMAGE") return Boolean(c.has_image);
                if (cameraFilter === "ON_ROUTE") {
                  const routeCoords = recommendedRoute?.geojson_path?.coordinates as number[][] | undefined;
                  return routeCoords ? cameraNearRoute(c.lng, c.lat, routeCoords) : false;
                }
                return true;
              }).length,
              total: cameras.length,
            }}
          />
        </div>

        {showCameras && cameraFilter === "ON_ROUTE" && !recommendedRoute && (
          <div className="rounded-xl glass-panel px-3 py-1.5 text-[11px] font-medium text-amber-900 border border-amber-200/90 shadow-glass flex items-center gap-1.5 animate-fadeIn backdrop-blur-md">
            <span>Chưa có lộ trình: Vui lòng tìm đường để lọc camera trên tuyến</span>
          </div>
        )}
      </div>

      {/* Floating Traffic Legend & Status (Automatic when route exists) */}
      {recommendedRoute && (
        <div
          className="map-traffic-legend absolute bottom-6 right-3 z-20 rounded-2xl glass-panel-elevated p-2.5 text-xs text-ink-900 border border-white/95 shadow-glass backdrop-blur-md animate-fadeIn"
          data-testid="traffic-legend"
        >
          <div className="flex items-center justify-between gap-3 mb-1.5 font-bold text-[11px] text-ink-800 border-b border-slate-100 pb-1">
            <span className="flex items-center gap-1.5">
              <Activity className="w-3.5 h-3.5 text-emerald-600" />
              Tình trạng giao thông
            </span>
            <button
              type="button"
              onClick={() => setShowTrafficLegend((v) => !v)}
              aria-expanded={showTrafficLegend}
              className="text-[10px] text-indigo-600 hover:text-indigo-800 font-semibold cursor-pointer"
            >
              {showTrafficLegend ? "Thu gọn" : "Chi tiết"}
            </button>
          </div>
          {showTrafficLegend ? (
            <div className="flex flex-col gap-1.5 text-[11px]">
              <div className="flex items-center gap-2">
                <span className="w-3 h-1.5 rounded-full bg-[#16A34A] shrink-0" />
                <span className="font-medium text-ink-800">Thông thoáng (FREE_FLOW)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-1.5 rounded-full bg-[#F59E0B] shrink-0" />
                <span className="font-medium text-ink-800">Di chuyển chậm (SLOW)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-1.5 rounded-full bg-[#EF4444] shrink-0" />
                <span className="font-medium text-ink-800">Ùn tắc (CONGESTED)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-1.5 rounded-full bg-[#7F1D1D] shrink-0" />
                <span className="font-medium text-ink-800">Phong tỏa / Cấm đường (CLOSED)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-1.5 rounded-full bg-[#94A3B8] shrink-0" />
                <span className="font-medium text-ink-500">Chưa đủ dữ liệu (UNKNOWN)</span>
              </div>
              <div className="pt-1 mt-0.5 border-t border-slate-100/80 text-[10px] text-slate-500 flex items-center justify-between gap-2">
                <span className="truncate">Nguồn: {recommendedRoute.traffic_eta_source || "Cảm biến/Tin tức"}</span>
                {recommendedRoute.traffic_coverage_ratio !== undefined && recommendedRoute.traffic_coverage_ratio !== null && (
                  <span className="font-bold text-indigo-600 shrink-0">
                    Phủ {Math.round((recommendedRoute.traffic_coverage_ratio || 0) * 100)}%
                  </span>
                )}
              </div>
              {!hasQualifiedTrafficData && (
                <div className="pt-1 text-[10px] text-amber-700 font-medium">
                  Chưa có dữ liệu giao thông đủ tin cậy trong khu vực này
                </div>
              )}
            </div>
          ) : (
            <div className="text-[10px] text-slate-500 font-medium">
              {!hasQualifiedTrafficData ? "Chưa có dữ liệu tin cậy" : "Tự động phân tích theo đoạn"}
            </div>
          )}
        </div>
      )}

      {/* Dev-only Debug Panel for MapLibre Telemetry (Explicitly opt-in) */}
      {process.env.NODE_ENV !== "production" && debugStats && (typeof window !== "undefined" && (window as any).__SAFEPATH_TELEMETRY__) && (
        <div
          data-testid="camera-debug-panel"
          className="absolute bottom-6 left-3 z-20 rounded-2xl glass-panel p-2.5 text-[10px] text-ink-800 border border-indigo-200/80 shadow-glass backdrop-blur-md max-w-xs space-y-1 select-none pointer-events-none"
        >
          <div className="font-bold text-indigo-700 flex items-center justify-between border-b border-indigo-100 pb-1">
            <span>MapLibre Camera Telemetry</span>
            <span className="font-mono text-[9px] bg-indigo-100 px-1 rounded">{debugStats.filterMode}</span>
          </div>
          <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 font-mono text-[9px]">
            <div>API Total: <strong>{debugStats.apiTotal}</strong></div>
            <div>Valid GPS: <strong>{debugStats.validCoords}</strong></div>
            <div>GeoJSON Feat: <strong>{debugStats.sourceFeatures}</strong></div>
            <div>Map Zoom: <strong>{debugStats.zoom}</strong></div>
            <div>Render Pts: <strong>{debugStats.renderedPoints}</strong></div>
            <div>Clusters: <strong>{debugStats.renderedClusters}</strong></div>
            <div>Visible: <strong className={debugStats.layerVisible ? "text-emerald-600" : "text-rose-600"}>{debugStats.layerVisible ? "YES" : "NO"}</strong></div>
          </div>
        </div>
      )}
    </div>
  );
};
