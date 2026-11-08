"use client";
import { useEffect, useRef, useState, useCallback } from "react";

export const sceneIds = ["city", "vision", "news", "routing"] as const;
export const sceneCameras = [
  { center: [106.7009, 10.7769] as [number, number], zoom: 13.4, pitch: 48, bearing: -12 },
  { center: [106.698, 10.772] as [number, number], zoom: 15.2, pitch: 56, bearing: 18 },
  { center: [106.711, 10.789] as [number, number], zoom: 14, pitch: 42, bearing: -28 },
  { center: [106.696, 10.773] as [number, number], zoom: 14.8, pitch: 52, bearing: 8 },
];

/**
 * High-performance cinematic scrollytelling tracker:
 * Uses IntersectionObserver to detect active scenes without triggering synchronous layout reflows (forced layouts).
 * Progress calculation reads window.scrollY passively.
 */
export function useCinematicScene() {
  const track = useRef<HTMLDivElement>(null);
  const [scene, setScene] = useState(0);
  const sceneRef = useRef(0);
  const isProgrammaticJumpRef = useRef(false);
  const jumpTimeoutRef = useRef<number>(0);

  useEffect(() => {
    const root = track.current;
    if (!root) return;

    const sections = root.querySelectorAll<HTMLElement>(".story-scene");
    if (!sections.length) return;

    // 1. Zero-reflow focal band observer with hysteresis to eliminate border jitter
    const ratios = new Map<HTMLElement, number>();
    const observer = new IntersectionObserver(
      (entries) => {
        if (isProgrammaticJumpRef.current) return;

        entries.forEach((entry) => {
          ratios.set(entry.target as HTMLElement, entry.intersectionRatio);
        });

        const currentSec = sections[sceneRef.current];
        const currentRatio = (currentSec && ratios.get(currentSec)) || 0;

        let maxRatio = 0;
        let candidateIdx = -1;
        sections.forEach((sec, idx) => {
          const ratio = ratios.get(sec) || 0;
          if (ratio > maxRatio) {
            maxRatio = ratio;
            candidateIdx = idx;
          }
        });

        // Hysteresis threshold: requires candidate to exceed current by 0.18 or current has left (< 0.08)
        const HYSTERESIS = 0.18;
        if (candidateIdx !== -1 && candidateIdx !== sceneRef.current) {
          const shouldSwitch =
            maxRatio > currentRatio + HYSTERESIS ||
            (currentRatio < 0.08 && maxRatio > 0.15);

          if (shouldSwitch) {
            sceneRef.current = candidateIdx;
            setScene(candidateIdx);
          }
        }
      },
      {
        root: null,
        rootMargin: "-20% 0px -25% 0px",
        threshold: [0, 0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 1.0],
      }
    );

    sections.forEach((sec) => observer.observe(sec));

    // 2. Passive scroll progress without forced getBoundingClientRect
    let progressFrame = 0;
    const updateProgress = () => {
      cancelAnimationFrame(progressFrame);
      progressFrame = requestAnimationFrame(() => {
        const total = document.documentElement.scrollHeight - window.innerHeight;
        const progress = total > 0 ? Math.max(0, Math.min(1, window.scrollY / total)) : 0;
        root.style.setProperty("--story-progress", progress.toFixed(4));
      });
    };

    updateProgress();
    window.addEventListener("scroll", updateProgress, { passive: true });
    window.addEventListener("resize", updateProgress, { passive: true });

    return () => {
      observer.disconnect();
      cancelAnimationFrame(progressFrame);
      if (jumpTimeoutRef.current) clearTimeout(jumpTimeoutRef.current);
      window.removeEventListener("scroll", updateProgress);
      window.removeEventListener("resize", updateProgress);
    };
  }, []);

  const jump = useCallback((index: number) => {
    const target = document.getElementById(sceneIds[index]);
    if (target) {
      isProgrammaticJumpRef.current = true;
      sceneRef.current = index;
      setScene(index);

      target.scrollIntoView({
        behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth",
        block: "start",
      });

      if (jumpTimeoutRef.current) clearTimeout(jumpTimeoutRef.current);
      jumpTimeoutRef.current = window.setTimeout(() => {
        isProgrammaticJumpRef.current = false;
      }, 750);
    }
  }, []);

  return { track, scene, jump };
}
