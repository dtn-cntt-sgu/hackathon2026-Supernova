"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { AppPageHeader } from "../../components/ui/AppPageHeader";
import {
  Navigation,
  Newspaper,
  Clock,
  MapPin,
  AlertTriangle,
  CheckCircle,
  Search,
  Filter,
  ArrowUpRight,
  CloudRain,
  Waves,
  Compass,
  ShieldCheck,
  Bookmark,
  BookmarkCheck,
  RefreshCw,
  ExternalLink,
  Car,
  AlertOctagon,
  Calendar,
  Radio,
  Share2,
  ChevronRight,
  User,
  SlidersHorizontal,
  Info,
  Droplets,
  Building,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { OnboardingHelpButton } from "../../components/onboarding/OnboardingHelpButton";
import { useLiveObservations } from "../../hooks/useLiveObservations";
import { currentRain, currentTide, observationTime } from "../../lib/observations";
import {
  fetchTrafficNews,
  fetchTrafficNewsHighlights,
  fetchTrafficNewsSummary,
} from "../../services/api";
import type {
  TrafficNewsItem,
  TrafficNewsSummaryResponse,
  TrafficNewsHighlightsResponse,
} from "../../types/contracts";

const CATEGORY_TABS = [
  { id: "ALL", label: "Tất cả", icon: Newspaper },
  { id: "FLOOD", label: "Ngập nước", icon: Droplets, color: "text-sky-600 bg-sky-50 border-sky-200" },
  { id: "CONGESTION", label: "Ùn tắc", icon: Car, color: "text-amber-600 bg-amber-50 border-amber-200" },
  { id: "ACCIDENT", label: "Tai nạn", icon: AlertOctagon, color: "text-rose-600 bg-rose-50 border-rose-200" },
  { id: "ROAD_CLOSURE", label: "Thi công / Cấm đường", icon: AlertTriangle, color: "text-indigo-600 bg-indigo-50 border-indigo-200" },
  { id: "WEATHER", label: "Thời tiết", icon: CloudRain, color: "text-blue-600 bg-blue-50 border-blue-200" },
  { id: "RECOVERY", label: "Đã khắc phục", icon: CheckCircle, color: "text-emerald-600 bg-emerald-50 border-emerald-200" },
];

const TIMEFRAME_OPTIONS = [
  { id: "24h", label: "24 giờ qua" },
  { id: "7d", label: "7 ngày qua" },
  { id: "30d", label: "30 ngày qua" },
  { id: "all", label: "Toàn bộ" },
];

const HCMC_DISTRICTS = [
  "Tất cả quận / huyện",
  "Quận 1",
  "Quận 3",
  "Quận 4",
  "Quận 5",
  "Quận 6",
  "Quận 7",
  "Quận 8",
  "Quận 10",
  "Quận 11",
  "Quận 12",
  "Bình Thạnh",
  "Thủ Đức",
  "Gò Vấp",
  "Tân Bình",
  "Tân Phú",
  "Bình Tân",
  "Nhà Bè",
  "Hóc Môn",
  "Bình Chánh",
  "Củ Chi",
  "Cần Giờ",
];

function formatTimeAgo(dateStr?: string | null): string {
  if (!dateStr) return "Mới cập nhật";
  try {
    const date = new Date(dateStr);
    const now = Date.now();
    const diffSec = Math.floor((now - date.getTime()) / 1000);
    if (diffSec < 60) return "Vừa xong";
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin} phút trước`;
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return `${diffHours} giờ trước`;
    const diffDays = Math.floor(diffHours / 24);
    if (diffDays < 7) return `${diffDays} ngày trước`;
    return date.toLocaleDateString("vi-VN", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
    });
  } catch {
    return "Mới cập nhật";
  }
}

function getCategoryBadge(category: string) {
  const cat = (category || "").toUpperCase();
  if (cat.includes("NGẬP") || cat.includes("FLOOD")) {
    return {
      label: "Ngập nước",
      className: "bg-sky-50 text-sky-700 border-sky-200/80",
      dot: "bg-sky-500",
    };
  }
  if (cat.includes("ÙN") || cat.includes("KẸT") || cat.includes("CONGESTION")) {
    return {
      label: "Ùn tắc",
      className: "bg-amber-50 text-amber-700 border-amber-200/80",
      dot: "bg-amber-500",
    };
  }
  if (cat.includes("TAI NẠN") || cat.includes("ACCIDENT")) {
    return {
      label: "Tai nạn",
      className: "bg-rose-50 text-rose-700 border-rose-200/80",
      dot: "bg-rose-500",
    };
  }
  if (cat.includes("CẤM") || cat.includes("THI CÔNG") || cat.includes("HẠ TẦNG") || cat.includes("CONSTRUCTION")) {
    return {
      label: "Thi công / Cấm đường",
      className: "bg-indigo-50 text-indigo-700 border-indigo-200/80",
      dot: "bg-indigo-500",
    };
  }
  if (cat.includes("THỜI TIẾT") || cat.includes("WEATHER")) {
    return {
      label: "Thời tiết",
      className: "bg-blue-50 text-blue-700 border-blue-200/80",
      dot: "bg-blue-500",
    };
  }
  if (cat.includes("KHẮC PHỤC") || cat.includes("RECOVERY")) {
    return {
      label: "Đã khắc phục",
      className: "bg-emerald-50 text-emerald-700 border-emerald-200/80",
      dot: "bg-emerald-500",
    };
  }
  return {
    label: "Tin giao thông",
    className: "bg-slate-50 text-ink-700 border-slate-200/80",
    dot: "bg-slate-400",
  };
}

export default function TrafficNewsPage() {
  const { user } = useAuth();
  const live = useLiveObservations();
  const rain = currentRain(live.weather, live.now);
  const tide = currentTide(live.weather, live.now);

  const [summary, setSummary] = useState<TrafficNewsSummaryResponse | null>(null);
  const [highlights, setHighlights] = useState<TrafficNewsItem[]>([]);
  const [articles, setArticles] = useState<TrafficNewsItem[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);

  const [selectedCategory, setSelectedCategory] = useState<string>("ALL");
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>("all");
  const [selectedDistrict, setSelectedDistrict] = useState<string>("Tất cả quận / huyện");
  const [searchQuery, setSearchQuery] = useState<string>("");

  const [isNearMe, setIsNearMe] = useState<boolean>(false);
  const [userCoords, setUserCoords] = useState<{ lat: number; lng: number } | null>(null);
  const [isLocating, setIsLocating] = useState<boolean>(false);
  const [locationError, setLocationError] = useState<string | null>(null);

  const [savedArticleIds, setSavedArticleIds] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);

  // Load saved articles from localStorage
  useEffect(() => {
    try {
      const stored = localStorage.getItem("safepath_saved_news");
      if (stored) {
        setSavedArticleIds(new Set(JSON.parse(stored)));
      }
    } catch {
      // Ignore
    }
  }, []);

  const toggleBookmark = (id: string) => {
    setSavedArticleIds((prev) => {
      const updated = new Set(prev);
      if (updated.has(id)) {
        updated.delete(id);
      } else {
        updated.add(id);
      }
      try {
        localStorage.setItem("safepath_saved_news", JSON.stringify(Array.from(updated)));
      } catch {
        // Ignore
      }
      return updated;
    });
  };

  const loadData = useCallback(async () => {
    setIsLoading(true);
    try {
      const [sumData, highData] = await Promise.all([
        fetchTrafficNewsSummary().catch(() => null),
        fetchTrafficNewsHighlights(5).catch(() => ({ count: 0, items: [], fetched_at: "" })),
      ]);
      if (sumData) setSummary(sumData);
      if (highData?.items) setHighlights(highData.items);
    } catch (err) {
      console.warn("Failed to load initial news summary/highlights:", err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const loadArticles = useCallback(async () => {
    try {
      const searchTerms = [
        searchQuery.trim(),
        selectedDistrict !== "Tất cả quận / huyện" ? selectedDistrict : "",
      ]
        .filter(Boolean)
        .join(" ");

      const params: Parameters<typeof fetchTrafficNews>[0] = {
        limit: 50,
        offset: 0,
        category: selectedCategory !== "ALL" ? selectedCategory : undefined,
        timeframe: selectedTimeframe !== "all" ? selectedTimeframe : undefined,
        search: searchTerms || undefined,
      };

      if (isNearMe && userCoords) {
        params.lat = userCoords.lat;
        params.lng = userCoords.lng;
        params.radius_km = 6.0;
      }

      const res = await fetchTrafficNews(params);
      setArticles(res.items);
      setTotalCount(res.total);
    } catch (err) {
      console.warn("Failed to query traffic news list:", err);
    }
  }, [selectedCategory, selectedTimeframe, selectedDistrict, searchQuery, isNearMe, userCoords]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    loadArticles();
  }, [loadArticles]);

  const handleRefresh = async () => {
    setIsRefreshing(true);
    await Promise.all([loadData(), loadArticles()]);
    setIsRefreshing(false);
  };

  const handleRequestLocation = () => {
    if (isNearMe) {
      setIsNearMe(false);
      setUserCoords(null);
      return;
    }

    if (!navigator.geolocation) {
      setLocationError("Trình duyệt không hỗ trợ xác định vị trí GPS.");
      return;
    }

    setIsLocating(true);
    setLocationError(null);

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setIsLocating(false);
        setUserCoords({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
        });
        setIsNearMe(true);
      },
      (err) => {
        setIsLocating(false);
        if (err.code === 1) {
          setLocationError("Bạn đã từ chối quyền định vị. Vui lòng bật lại trong cài đặt.");
        } else {
          setLocationError("Không thể xác định vị trí hiện tại.");
        }
      },
      { timeout: 10000, enableHighAccuracy: true }
    );
  };

  const heroNews = highlights[0] || articles[0] || null;

  return (
    <div className="min-h-screen bg-pearl-100 text-ink-900 selection:bg-indigo-600 selection:text-white relative overflow-x-hidden">
      {/* Background Aurora ambient glows */}
      <div className="fixed top-[-10%] left-[-10%] w-[55vw] h-[55vw] rounded-full bg-gradient-to-br from-indigo-200/35 via-ice-200/25 to-transparent blur-3xl pointer-events-none -z-10" />
      <div className="fixed bottom-[-15%] right-[-10%] w-[50vw] h-[50vw] rounded-full bg-gradient-to-tl from-lavender-200/35 via-sky-200/25 to-transparent blur-3xl pointer-events-none -z-10" />

      {/* Top Floating Glass Navigation Bar */}
      <AppPageHeader
        title="Bản tin Giao thông"
        description="Bản tin giao thông đô thị TP.HCM"
        badge="Tin tức"
        rightAction={
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="p-2 rounded-full glass-pill border border-white/90 hover:bg-white transition text-ink-600 hover:text-indigo-600 shadow-glass-sm"
            title="Làm mới dữ liệu tin tức"
          >
            <RefreshCw className={`w-4 h-4 ${isRefreshing ? "animate-spin text-indigo-600" : ""}`} />
          </button>
        }
      />

      {/* Main Container */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* SECTION A: HERO NEWS & STATUS */}
        <section className="space-y-4" data-tour="news-hero">
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
            <div>
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-indigo-50/80 border border-indigo-200/70 text-indigo-700 text-xs font-bold shadow-glass-sm mb-2">
                <Radio className="w-3.5 h-3.5 animate-pulse text-indigo-600" />
                <span>Nguồn tin chính thống · Cập nhật liên tục</span>
              </div>
              <h1 className="text-2xl sm:text-4xl font-black text-ink-950 tracking-tight">
                Bản tin giao thông TP.HCM
              </h1>
              <p className="text-sm sm:text-base text-ink-600 mt-1 max-w-2xl font-normal leading-relaxed">
                Những thông tin giao thông đáng chú ý để bạn chủ động trước mỗi hành trình.
              </p>
            </div>

            {/* Quick Metrics Badge */}
            <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
              <div className="px-3 py-1.5 rounded-2xl glass-panel border border-white/90 shadow-glass-sm text-ink-700 flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-indigo-600" />
                <span>Cập nhật gần nhất: {formatTimeAgo(summary?.latest_update)}</span>
              </div>

            </div>
          </div>

          {/* Hero Featured Card (Tin nổi bật thực tế) */}
          {heroNews && (
            <div className="glass-panel-elevated rounded-3xl border border-white/90 shadow-glass-elevated overflow-hidden p-6 md:p-8 relative">
              <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-center">
                {/* Hero Image if available */}
                <div className="lg:col-span-5 h-56 sm:h-72 rounded-2xl overflow-hidden bg-slate-100 border border-slate-200/80 relative shadow-inner">
                  {heroNews.image_url ? (
                    // Preserve remote source bytes without the image optimization proxy.
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={heroNews.image_url}
                      alt={heroNews.title}
                      className="w-full h-full object-cover transition-transform duration-500 hover:scale-105"
                      onError={(e) => {
                        (e.target as HTMLElement).style.display = "none";
                      }}
                    />
                  ) : (
                    <div className="w-full h-full flex flex-col items-center justify-center text-slate-400 p-6 text-center space-y-2">
                      <Newspaper className="w-12 h-12 text-slate-300" />
                      <span className="text-xs font-medium">Ảnh bản quyền thuộc cơ quan báo chí</span>
                    </div>
                  )}
                  <div className="absolute top-3 left-3 flex items-center gap-1.5">
                    <span className="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider bg-white/95 text-indigo-900 shadow-md backdrop-blur-md border border-white/80">
                      Tin tiêu điểm
                    </span>
                  </div>
                </div>

                {/* Hero Content */}
                <div className="lg:col-span-7 space-y-3.5">
                  <div className="flex flex-wrap items-center gap-2">
                    {(() => {
                      const badge = getCategoryBadge(heroNews.category);
                      return (
                        <span className={`px-2.5 py-1 rounded-full text-xs font-bold border flex items-center gap-1.5 ${badge.className}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${badge.dot}`} />
                          {badge.label}
                        </span>
                      );
                    })()}

                    {heroNews.lat && heroNews.lng && (
                      <span className="px-2.5 py-1 rounded-full text-xs font-semibold bg-white/85 text-ink-700 border border-slate-200/80 shadow-sm flex items-center gap-1">
                        <MapPin className="w-3 h-3 text-indigo-600" />
                        <span>Đã định vị thực địa</span>
                      </span>
                    )}

                    <span className="text-xs text-ink-500 flex items-center gap-1 ml-auto">
                      <Clock className="w-3.5 h-3.5" />
                      {formatTimeAgo(heroNews.published_at)}
                    </span>
                  </div>

                  <h2 className="text-xl sm:text-2xl font-black text-ink-950 leading-snug">
                    <a
                      href={heroNews.canonical_url || heroNews.link || "#"}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="hover:text-indigo-600 transition"
                    >
                      {heroNews.title}
                    </a>
                  </h2>

                  <p className="text-sm text-ink-700 leading-relaxed break-words whitespace-normal">
                    {heroNews.summary}
                  </p>

                  <div className="pt-2 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200/70">
                    <span className="text-xs font-bold text-ink-600">
                      Nguồn: <strong className="text-indigo-700">{heroNews.source_name || "Báo chí chính thống"}</strong>
                    </span>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => toggleBookmark(heroNews.id)}
                        data-tour={articles.length === 0 ? "news-bookmark-action" : undefined}
                        className={`p-2 rounded-full border transition ${
                          savedArticleIds.has(heroNews.id)
                            ? "bg-indigo-50 border-indigo-300 text-indigo-600"
                            : "bg-white/80 border-slate-200 text-ink-600 hover:bg-white"
                        }`}
                        title={savedArticleIds.has(heroNews.id) ? "Đã lưu bản tin" : "Lưu bản tin"}
                      >
                        {savedArticleIds.has(heroNews.id) ? (
                          <BookmarkCheck className="w-4 h-4" />
                        ) : (
                          <Bookmark className="w-4 h-4" />
                        )}
                      </button>

                      <a
                        href={heroNews.canonical_url || heroNews.link || "#"}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="aurora-btn-primary px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-1.5 shadow-md"
                      >
                        <span>Đọc toàn văn bài báo</span>
                        <ExternalLink className="w-3.5 h-3.5" />
                      </a>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>

        {/* SECTION B: NOTABLE INCIDENTS HIGHLIGHTS CAROUSEL */}
        {(isLoading || highlights.length > 1) && (
          <section className="space-y-3" data-tour="news-highlights">
            <div className="flex items-center justify-between">
              <h3 className="text-base sm:text-lg font-bold text-ink-950 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-500" />
                <span>Tình hình giao thông đáng chú ý</span>
              </h3>
              <span className="text-xs text-ink-500 font-medium">Sắp xếp theo mức độ ảnh hưởng</span>
            </div>

            {isLoading ? (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {[1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="glass-panel rounded-2xl p-4 border border-white/90 shadow-glass-sm animate-pulse h-28 bg-slate-100/60"
                  />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {highlights.slice(1, 4).map((item) => {
                  const badge = getCategoryBadge(item.category);
                  return (
                    <div
                      key={item.id}
                      className="glass-interactive rounded-2xl p-4 sm:p-5 border border-white/90 shadow-glass-sm hover:shadow-glass hover:-translate-y-0.5 transition flex flex-col justify-between space-y-3"
                    >
                      <div className="space-y-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border flex items-center gap-1 ${badge.className}`}>
                            <span className={`w-1 h-1 rounded-full ${badge.dot}`} />
                            {badge.label}
                          </span>
                          <span className="text-[11px] text-ink-400 font-mono">
                            {formatTimeAgo(item.published_at)}
                          </span>
                        </div>

                        <h4 className="font-bold text-sm text-ink-950 leading-snug break-words hover:text-indigo-600 transition">
                          <a href={item.canonical_url || item.link || "#"} target="_blank" rel="noopener noreferrer">
                            {item.title}
                          </a>
                        </h4>

                        <p className="text-xs text-ink-600 leading-relaxed break-words whitespace-normal">
                          {item.summary}
                        </p>
                      </div>

                      <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs">
                        <span className="text-[11px] text-ink-500 font-medium break-words">
                          {item.source_name || "Báo chí"}
                        </span>
                        <a
                          href={item.canonical_url || item.link || "#"}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-indigo-600 font-bold hover:underline flex items-center gap-1"
                        >
                          <span>Chi tiết</span>
                          <ArrowUpRight className="w-3 h-3" />
                        </a>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        )}

        {/* SECTION D: FILTERS & AREA EXPLORER BAR */}
        <section className="glass-panel rounded-3xl p-5 border border-white/90 shadow-glass space-y-4" data-tour="news-filters">
          <div className="flex flex-col lg:flex-row gap-3 items-stretch lg:items-center justify-between">
            {/* Search Input */}
            <div className="relative flex-1">
              <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-400" />
              <input
                type="text"
                placeholder="Tìm theo tên đường, cầu vượt, giao lộ, quận huyện..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 rounded-2xl glass-input text-xs font-semibold text-ink-900 border border-slate-200/90 focus:border-indigo-400 focus:outline-none"
              />
            </div>

            {/* District Selector */}
            <div className="flex items-center gap-2">
              <select
                value={selectedDistrict}
                onChange={(e) => setSelectedDistrict(e.target.value)}
                className="px-3.5 py-2.5 rounded-2xl glass-input text-xs font-semibold text-ink-800 border border-slate-200/90 focus:border-indigo-400 focus:outline-none cursor-pointer"
              >
                {HCMC_DISTRICTS.map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>

              {/* Timeframe Selector */}
              <select
                value={selectedTimeframe}
                onChange={(e) => setSelectedTimeframe(e.target.value)}
                className="px-3.5 py-2.5 rounded-2xl glass-input text-xs font-semibold text-ink-800 border border-slate-200/90 focus:border-indigo-400 focus:outline-none cursor-pointer"
              >
                {TIMEFRAME_OPTIONS.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.label}
                  </option>
                ))}
              </select>

              {/* Near Me GPS Button */}
              <button
                type="button"
                onClick={handleRequestLocation}
                disabled={isLocating}
                className={`px-3.5 py-2.5 rounded-2xl text-xs font-bold flex items-center gap-1.5 transition cursor-pointer border ${
                  isNearMe
                    ? "bg-indigo-600 text-white border-indigo-600 shadow-md"
                    : "glass-pill text-ink-700 border-white/90 hover:bg-white"
                }`}
                title="Lọc tin gần vị trí hiện tại"
              >
                <Compass className={`w-3.5 h-3.5 ${isLocating ? "animate-spin" : ""}`} />
                <span className="hidden sm:inline">{isNearMe ? "Đang bật: Gần tôi" : "Gần tôi"}</span>
              </button>
            </div>
          </div>

          {/* Location Error alert if any */}
          {locationError && (
            <div className="p-3 bg-amber-50 border border-amber-200 rounded-2xl text-xs text-amber-800 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
              <span>{locationError}</span>
              <button
                onClick={() => setLocationError(null)}
                className="ml-auto font-bold hover:underline text-amber-900"
              >
                Đóng
              </button>
            </div>
          )}

          {/* Category Tabs */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-none">
            {CATEGORY_TABS.map((cat) => {
              const Icon = cat.icon;
              const isSelected = selectedCategory === cat.id;
              return (
                <button
                  key={cat.id}
                  onClick={() => setSelectedCategory(cat.id)}
                  className={`px-3 py-1.5 rounded-full text-xs font-semibold shrink-0 transition flex items-center gap-1.5 border cursor-pointer ${
                    isSelected
                      ? "bg-indigo-600 text-white border-indigo-600 shadow-sm"
                      : "bg-white/80 text-ink-700 border-slate-200/80 hover:bg-white hover:text-ink-950"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <span>{cat.label}</span>
                </button>
              );
            })}
          </div>
        </section>

        {/* SECTION C & E: TWO-COLUMN MAIN WORKSPACE */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          {/* LEFT: LATEST NEWS STREAM (Khối C) */}
          <div className="lg:col-span-8 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-200/70 pb-3">
              <h3 className="font-bold text-base text-ink-950 flex items-center gap-2">
                <Newspaper className="w-4 h-4 text-indigo-600" />
                <span>Bản tin mới nhất</span>
                <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-100">
                  {articles.length} bài
                </span>
              </h3>

              <div className="text-xs text-ink-500 font-medium">
                {isNearMe ? "Ưu tiên bán kính 6 km từ GPS" : "Toàn thành phố"}
              </div>
            </div>

            {/* Articles Stream */}
            {isLoading ? (
              <div className="space-y-4">
                {[1, 2, 3].map((i) => (
                  <div
                    key={i}
                    className="glass-panel rounded-3xl p-5 border border-white/90 shadow-glass-sm animate-pulse flex flex-col sm:flex-row gap-5"
                  >
                    <div className="sm:w-44 h-36 rounded-2xl bg-slate-200/80 shrink-0" />
                    <div className="flex-1 space-y-3">
                      <div className="h-4 bg-slate-200/80 rounded w-1/4" />
                      <div className="h-6 bg-slate-200/80 rounded w-3/4" />
                      <div className="h-12 bg-slate-200/80 rounded w-full" />
                      <div className="flex justify-between items-center pt-2">
                        <div className="h-4 bg-slate-200/80 rounded w-1/3" />
                        <button
                          type="button"
                          data-tour={i === 1 ? "news-bookmark-action" : undefined}
                          className="p-2 rounded-full border border-slate-200 bg-white text-slate-300"
                          title="Lưu bản tin"
                          aria-label="Lưu bản tin"
                        >
                          <Bookmark className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : articles.length > 0 ? (
              <div className="space-y-4">
                {articles.map((item, idx) => {
                  const badge = getCategoryBadge(item.category);
                  const isSaved = savedArticleIds.has(item.id);
                  return (
                    <article
                      key={item.id}
                      className="glass-interactive rounded-3xl p-5 sm:p-6 border border-white/90 shadow-glass-sm hover:shadow-glass hover:-translate-y-0.5 transition flex flex-col sm:flex-row gap-5"
                    >
                      {/* Thumbnail if available */}
                      {item.image_url && (
                        <div className="sm:w-44 h-36 rounded-2xl overflow-hidden bg-slate-100 shrink-0 border border-slate-200/80 relative">
                          {/* Preserve remote source bytes without the image optimization proxy. */}
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img
                            src={item.image_url}
                            alt={item.title}
                            className="w-full h-full object-cover"
                            onError={(e) => {
                              (e.target as HTMLElement).style.display = "none";
                            }}
                          />
                        </div>
                      )}

                      {/* Content */}
                      <div className="flex-1 flex flex-col justify-between space-y-2.5">
                        <div className="space-y-2">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold border flex items-center gap-1 ${badge.className}`}>
                              <span className={`w-1 h-1 rounded-full ${badge.dot}`} />
                              {badge.label}
                            </span>

                            {item.location_confidence !== "UNRESOLVED" && item.lat && item.lng && (
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-white/80 text-ink-700 border border-slate-200/70 flex items-center gap-1">
                                <MapPin className="w-3 h-3 text-indigo-600" />
                                <span>{item.location_confidence === "EXACT" ? "Địa điểm xác thực" : "Khu vực lân cận"}</span>
                              </span>
                            )}

                            {item.distance_km !== null && item.distance_km !== undefined && (
                              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">
                                Cách bạn {item.distance_km.toFixed(1)} km
                              </span>
                            )}

                            <span className="text-[11px] text-ink-400 font-mono ml-auto">
                              {formatTimeAgo(item.published_at)}
                            </span>
                          </div>

                          <h4 className="font-bold text-base text-ink-950 leading-snug break-words hover:text-indigo-600 transition">
                            <a href={item.canonical_url || item.link || "#"} target="_blank" rel="noopener noreferrer">
                              {item.title}
                            </a>
                          </h4>

                          <p className="text-xs sm:text-[13px] text-ink-600 leading-relaxed break-words whitespace-normal">
                            {item.summary}
                          </p>
                        </div>

                        {/* Footer Card */}
                        <div className="pt-2 border-t border-slate-100 flex items-center justify-between text-xs">
                          <span className="text-[11px] font-semibold text-ink-500">
                            {item.source_name || "Nguồn tin công khai"}
                          </span>

                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => toggleBookmark(item.id)}
                              data-tour={idx === 0 ? "news-bookmark-action" : undefined}
                              className={`p-1.5 rounded-full border transition ${
                                isSaved
                                  ? "bg-indigo-50 border-indigo-300 text-indigo-600"
                                  : "bg-white/80 border-slate-200 text-ink-600 hover:bg-white"
                              }`}
                              title={isSaved ? "Bỏ lưu" : "Lưu tin"}
                              aria-label={isSaved ? "Bỏ lưu tin tức" : "Lưu tin tức quan trọng"}
                            >
                              {isSaved ? <BookmarkCheck className="w-3.5 h-3.5" /> : <Bookmark className="w-3.5 h-3.5" />}
                            </button>

                            <a
                              href={item.canonical_url || item.link || "#"}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="font-bold text-indigo-600 hover:text-indigo-800 flex items-center gap-1 hover:underline"
                            >
                              <span>Xem nguồn</span>
                              <ExternalLink className="w-3 h-3" />
                            </a>
                          </div>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              /* Honest Empty State */
              <div className="glass-panel rounded-3xl p-10 text-center space-y-4 border border-white/90 shadow-glass">
                <div className="w-14 h-14 rounded-full bg-indigo-50 border border-indigo-200 text-indigo-600 flex items-center justify-center mx-auto">
                  <Search className="w-6 h-6" />
                </div>
                <div className="space-y-1">
                  <h4 className="text-base font-bold text-ink-950">
                    Chưa tìm thấy bản tin nào phù hợp
                  </h4>
                  <p className="text-xs text-ink-600 max-w-md mx-auto leading-relaxed">
                    Hệ thống không tìm thấy bài viết thỏa mãn điều kiện lọc. Vui lòng chọn danh mục khác, nới rộng mốc thời gian hoặc đặt lại từ khóa tìm kiếm.
                  </p>
                </div>
                <button
                  onClick={() => {
                    setSelectedCategory("ALL");
                    setSelectedTimeframe("all");
                    setSelectedDistrict("Tất cả quận / huyện");
                    setSearchQuery("");
                    setIsNearMe(false);
                  }}
                  className="px-4 py-2 rounded-xl bg-white border border-slate-200/90 text-xs font-bold text-indigo-600 hover:bg-indigo-50 transition shadow-sm"
                >
                  Đặt lại toàn bộ bộ lọc
                </button>
              </div>
            )}
          </div>

          {/* RIGHT SIDEBAR: METEOROLOGY, TIDES & DATA HEALTH (Khối E) */}
          <aside className="lg:col-span-4 space-y-6">
            {/* Environmental Weather & Tide Card */}
            <div className="glass-panel rounded-3xl p-5 border border-white/90 shadow-glass space-y-4">
              <div className="flex items-center justify-between border-b border-slate-200/70 pb-3">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-xl bg-sky-50 text-sky-600 border border-sky-100">
                    <CloudRain className="w-4 h-4" />
                  </div>
                  <h4 className="font-bold text-xs uppercase tracking-wider text-ink-900">
                    Thời tiết & Thủy văn thực tế
                  </h4>
                </div>
                <span className="text-[10px] text-ink-400 font-mono">Open-Meteo & KTTV</span>
              </div>

              {/* Rain Section */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-ink-600 font-medium">Lượng mưa từ nguồn thời tiết:</span>
                  <strong className="text-ink-950 font-bold">
                    {rain !== null ? `${rain.toFixed(1)} mm/h` : "Chưa có dữ liệu"}
                  </strong>
                </div>
                <div className="p-3 rounded-2xl bg-gradient-to-br from-white/90 to-sky-50/50 border border-sky-100/80 shadow-sm flex items-center justify-between">
                  <span className="text-xs text-sky-800 font-semibold">
                    {rain === null ? "Chưa có dữ liệu đủ mới" : "Lượng mưa theo nguồn thời tiết; không xác nhận đường an toàn"}
                  </span>
                  <span className={`w-2.5 h-2.5 rounded-full ${rain !== null && rain > 0 ? "bg-blue-500 animate-ping" : "bg-emerald-500"}`} />
                </div>
              </div>

              {/* Tide Section */}
              <div className="space-y-1.5 pt-2 border-t border-slate-100">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-ink-600 font-medium">
                    Mực nước triều {live.weather?.tide_station ? `(${live.weather.tide_station})` : "(chưa rõ trạm)"}:
                  </span>
                  <strong className="text-ink-950 font-bold">
                    {tide !== null ? `${tide.toFixed(2)} m` : "—"}
                  </strong>
                </div>
                <div className="p-3 rounded-2xl bg-gradient-to-br from-white/90 to-cyan-50/50 border border-cyan-100/80 shadow-sm space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-cyan-900">
                      {tide === null ? "Chưa có bản tin triều đủ mới" : live.weather?.is_high_tide_alert === true ? "Nguồn dữ liệu báo triều cao" : "Đối chiếu bản tin trạm; không phải độ sâu ngập"}
                    </span>
                    <span className="text-[10px] font-mono text-ink-400">{live.weather?.tide_datum || "Chưa rõ hệ mốc"}</span>
                  </div>
                  <p className="text-[10px] text-ink-500 leading-relaxed">
                    Lưu ý: Mực nước tại trạm đo sông không phải là độ sâu ngập trên mặt đường.
                  </p>
                </div>
              </div>

              <div className="pt-2">
                <Link
                  href="/di-duong"
                  className="aurora-btn-primary w-full py-2.5 rounded-2xl text-xs font-bold flex items-center justify-center gap-2 shadow-sm"
                >
                  <Compass className="w-3.5 h-3.5" />
                  <span>Xem tuyến đường an toàn trên bản đồ</span>
                </Link>
              </div>
            </div>

            {/* Source Connectivity & Health Card */}
            <div className="glass-panel rounded-3xl p-5 border border-white/90 shadow-glass space-y-3">
              <div className="flex items-center justify-between border-b border-slate-200/70 pb-2.5">
                <span className="text-xs font-bold text-ink-800 uppercase tracking-wider flex items-center gap-1.5">
                  <ShieldCheck className="w-3.5 h-3.5 text-indigo-600" />
                  Nguồn dữ liệu bản tin
                </span>
                <span className="text-[10px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
                  Chu kỳ 15 phút
                </span>
              </div>

              <div className="space-y-2 text-xs">
                {summary?.sources &&
                  Object.entries(summary.sources).map(([k, s]) => (
                    <div key={k} className="flex items-center justify-between p-2 rounded-xl bg-white/70 border border-slate-100">
                      <span className="font-semibold text-ink-800">{s.name}</span>
                      <span className="text-[10px] font-bold text-emerald-600 flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                        {s.status}
                      </span>
                    </div>
                  ))}
              </div>

              <p className="text-[10px] text-ink-500 leading-relaxed pt-1">
                SafePathAI tổng hợp tin giao thông tự động phân loại ngữ cảnh phủ định và không sao chép nguyên văn báo chí.
              </p>
            </div>
          </aside>
        </div>
      </main>

      {/* Footer */}
      <footer className="mt-16 py-8 border-t border-slate-200/80 bg-white/60 text-center text-xs text-ink-500">
        <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2 font-bold text-ink-900">
            <Navigation className="w-4 h-4 text-indigo-600" />
            <span>SafePathAI · Bản tin giao thông đô thị TP.HCM</span>
          </div>
          <span>Dữ liệu thực địa từ Sở GTVT, Đài KTTV Nam Bộ và Báo chí chính thống</span>
        </div>
      </footer>
    </div>
  );
}
