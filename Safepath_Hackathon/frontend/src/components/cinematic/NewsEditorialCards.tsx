"use client";

import { useEffect, useState } from "react";
import { MapPin, Newspaper, ExternalLink } from "lucide-react";
import { LiquidGlassCard } from "../ui/LiquidGlassCard";
import { CardContainer, CardBody, CardItem } from "../ui/ThreeDCard";
import { fetchTrafficNewsHighlights } from "../../services/api";
import { observationTime } from "../../lib/observations";
import type { TrafficNewsItem } from "../../types/contracts";

export function NewsEditorialCards() {
  const [newsHighlights, setNewsHighlights] = useState<TrafficNewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    fetchTrafficNewsHighlights(3)
      .then((result) => {
        if (active) setNewsHighlights(result.items || []);
      })
      .catch(() => {
        if (active) setFailed(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 sm:gap-7 my-6">
      {newsHighlights.length > 0 ? (
        newsHighlights.slice(0, 3).map((item) => (
          <CardContainer key={item.id} maxTilt={2} className="h-full">
            <CardBody className="h-full">
              <LiquidGlassCard
                glassLevel="interactive"
                className="news-float-card flex flex-col justify-between h-full p-6 sm:p-7 rounded-3xl shadow-glass transition-all duration-300"
              >
                <div className="space-y-4">
                  {/* Category & Geo Coordinates Tag */}
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <CardItem
                      translateZ={2}
                      className="px-3 py-1 rounded-full text-[11px] font-bold bg-indigo-50/90 text-indigo-700 border border-indigo-200/80 shadow-xs"
                    >
                      {item.category || "Tin giao thông"}
                    </CardItem>
                    {item.location_confidence !== "UNRESOLVED" && item.lat && (
                      <CardItem
                        translateZ={2}
                        className="px-2.5 py-0.5 rounded-full text-[10.5px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 flex items-center gap-1 shadow-xs"
                      >
                        <MapPin size={11} />
                        <span>Có tọa độ</span>
                      </CardItem>
                    )}
                  </div>

                  {/* Standard Crisp High-Resolution Editorial Image (Right-Side Up, Zero WebGL) */}
                  {item.image_url && (
                    <CardItem translateZ={3} className="w-full">
                      <div className="w-full h-48 sm:h-52 rounded-2xl overflow-hidden bg-slate-100 border border-slate-200/80 shadow-inner group">
                        {/* Preserve remote source bytes without the image optimization proxy. */}
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={item.image_url}
                          alt={item.title}
                          loading="lazy"
                          decoding="async"
                          className="w-full h-full object-cover object-center group-hover:scale-[1.02] transition-transform duration-300"
                          onError={(e) => {
                            // Fallback hiding on error
                            (e.target as HTMLElement).style.display = "none";
                          }}
                        />
                      </div>
                    </CardItem>
                  )}

                  {/* Full Headline — NO Truncation, NO Ellipsis */}
                  <CardItem translateZ={2}>
                    <h3 className="font-bold text-base sm:text-lg text-ink-950 leading-snug tracking-tight break-words">
                      {item.title}
                    </h3>
                  </CardItem>

                  {/* Editorial Summary — Full text, zero line-clamp cutting */}
                  <p className="text-xs sm:text-[13.5px] text-ink-700 leading-relaxed break-words whitespace-normal">
                    {item.summary}
                  </p>

                  {/* Publishing Timestamp */}
                  <p className="text-[11px] text-ink-500 font-medium">
                    Đăng lúc: {observationTime(item.published_at)}
                  </p>
                </div>

                {/* Footer with Source & Direct Verified Link */}
                <div className="pt-4 border-t border-slate-200/60 flex items-center justify-between gap-3 text-xs mt-4">
                  <span className="text-[11.5px] text-ink-600 font-semibold leading-normal break-words">
                    {item.source_name || "Nguồn tin báo chí"}
                  </span>
                  <a
                    href={item.canonical_url || item.link || "#"}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0 font-bold text-indigo-600 hover:text-indigo-800 transition flex items-center gap-1.5 text-xs py-1 px-2.5 rounded-lg hover:bg-indigo-50/70"
                  >
                    <span>Xem nguồn</span>
                    <ExternalLink size={13} />
                  </a>
                </div>
              </LiquidGlassCard>
            </CardBody>
          </CardContainer>
        ))
      ) : (
        <div className="col-span-full">
          <LiquidGlassCard className="news-empty text-center p-8 space-y-3 rounded-3xl shadow-glass">
            <Newspaper size={36} className="mx-auto text-indigo-400" />
            <h3 className="font-bold text-base text-ink-950">
              {loading ? "Đang tải bản tin giao thông..." : failed ? "Không tải được bản tin" : "Chưa có bản tin khả dụng"}
            </h3>
            <p className="text-xs text-ink-600 max-w-md mx-auto">
              Bạn có thể mở trang bản tin để kiểm tra nguồn báo Tuổi Trẻ, VnExpress và thử tải lại.
            </p>
          </LiquidGlassCard>
        </div>
      )}
    </div>
  );
}
