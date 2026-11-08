"use client";
import { useEffect, useRef } from "react";
/** Animate emphasis only when an actual value changes; never synthesize counts. */
export function AnimatedCounter({ value }: { value: number | null | undefined }) {
  const ref = useRef<HTMLSpanElement>(null);
  const previous = useRef(value);
  useEffect(() => {
    if (value === previous.current) return;
    previous.current = value;
    if (typeof value !== "number" || !Number.isFinite(value) || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const animation = ref.current?.animate([{ opacity: .45, transform: "translateY(4px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 280, easing: "ease-out" });
    return () => animation?.cancel();
  }, [value]);
  return <span ref={ref} style={{ display: "inline-block" }}>{typeof value === "number" && Number.isFinite(value) ? value : "—"}</span>;
}
