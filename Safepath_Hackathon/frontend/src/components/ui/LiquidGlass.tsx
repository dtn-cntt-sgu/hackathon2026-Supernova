"use client";

import React, {
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type HTMLAttributes,
  type ElementType,
} from "react";
import { cn } from "@/lib/utils";

export type LiquidGlassVariant = "pill" | "button" | "panel" | "modal";
export type GlassLevel = "static" | "interactive" | "mobile";
export type RenderMode = "static" | "dynamic";

export type LiquidGlassProps = React.AllHTMLAttributes<HTMLElement> & {
  as?: ElementType;
  variant?: LiquidGlassVariant;
  glassLevel?: GlassLevel;
  renderMode?: RenderMode;
  contentClassName?: string;
  /** Corner radius in px. */
  radius?: number;
  /** Rim band that bends light, in px. */
  bevelDepth?: number;
  /** Displacement strength in px. */
  scale?: number;
  /** Chromatic aberration spread in px. */
  aberration?: number;
  /** Extra blur after refraction, in px. */
  frost?: number;
  /** White body tint 0–1. */
  tint?: number;
  /** Enable gentle pointer specular highlight */
  interactive?: boolean;
};

interface VariantDefaults {
  radius: number;
  bevelDepth: number;
  scale: number;
  aberration: number;
  frost: number;
  tint: number;
}

const VARIANT_PRESETS: Record<LiquidGlassVariant, VariantDefaults> = {
  pill: {
    radius: 999,
    bevelDepth: 7,
    scale: 22,
    aberration: 1.5,
    frost: 0.2,
    tint: 0.08,
  },
  button: {
    radius: 999,
    bevelDepth: 6,
    scale: 18,
    aberration: 1.2,
    frost: 0.2,
    tint: 0.10,
  },
  panel: {
    radius: 24,
    bevelDepth: 8,
    scale: 16,
    aberration: 1.0,
    frost: 0.35,
    tint: 0.12,
  },
  modal: {
    radius: 28,
    bevelDepth: 10,
    scale: 18,
    aberration: 1.2,
    frost: 0.5,
    tint: 0.15,
  },
};

/**
 * SafePath AI — Liquid Glass V2 Component (Aceternity UI Engine).
 * Employs Snell's-law displacement mapping to bend background pixels through
 * an SVG filter attached via CSS `backdrop-filter`.
 *
 * - Chromium: True refractive lens with chromatic aberration fringing and rim highlights.
 * - Safari/Firefox/Unsupported: Smooth frosted glass fallback (no black boxes or glitches).
 * - Reduced Transparency: Clean solid/subtle tinted background.
 */
export function LiquidGlass({
  as: Component = "div",
  variant = "pill",
  glassLevel: propGlassLevel,
  renderMode = "static",
  children,
  className,
  contentClassName,
  radius: propRadius,
  bevelDepth: propBevelDepth,
  scale: propScale,
  aberration: propAberration,
  frost: propFrost,
  tint: propTint,
  interactive = false,
  style,
  onPointerMove,
  ...rest
}: LiquidGlassProps) {
  // Determine effective material tier: static (default), interactive (accent desktop CTAs), mobile (opaque high-contrast)
  const effectiveLevel: GlassLevel =
    propGlassLevel ?? (interactive ? "interactive" : "static");

  const defaults = VARIANT_PRESETS[variant] || VARIANT_PRESETS.pill;
  const radius = propRadius ?? defaults.radius;
  const bevelDepth = propBevelDepth ?? defaults.bevelDepth;
  const scale = propScale ?? defaults.scale;
  const aberration = propAberration ?? defaults.aberration;
  const frost = propFrost ?? defaults.frost;
  const tint = propTint ?? defaults.tint;

  const reactId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const rootRef = useRef<HTMLDivElement>(null);
  const blobRef = useRef<string | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [filter, setFilter] = useState<{ id: string; svg: string } | null>(null);
  const [mode, setMode] = useState<"pending" | "simple" | "opaque">(() =>
    renderMode === "static" || effectiveLevel === "static"
      ? "simple"
      : effectiveLevel === "mobile"
        ? "opaque"
        : "pending"
  );

  const rafRef = useRef<number>(0);
  const rectRef = useRef<{ left: number; top: number; width: number; height: number } | null>(null);

  useEffect(() => {
    const isMobileOrTouch =
      typeof window !== "undefined" &&
      (window.innerWidth < 1024 || ("ontouchstart" in window));

    if (prefersReducedTransparency() || effectiveLevel === "mobile") {
      setMode("opaque");
    } else if (
      renderMode === "static" ||
      effectiveLevel === "static" ||
      isMobileOrTouch ||
      isSafariLike() ||
      !supportsUrlBackdropFilter()
    ) {
      setMode("simple");
    }
  }, [effectiveLevel, renderMode]);

  useEffect(() => {
    const el = rootRef.current;
    // Static and mobile modes NEVER execute ResizeObserver or canvas displacement mapping
    if (!el || mode !== "pending") return;

    const ro = new ResizeObserver(([entry]) => {
      if (!entry) return;
      const box = entry.borderBoxSize?.[0];
      const width = box?.inlineSize ?? entry.contentRect.width;
      const height = box?.blockSize ?? entry.contentRect.height;
      const roundedW = Math.max(1, Math.round(width));
      const roundedH = Math.max(1, Math.round(height));

      setSize((prev) => {
        // Prevent oscillation loops with an 8px threshold
        if (Math.abs(prev.w - roundedW) < 8 && Math.abs(prev.h - roundedH) < 8) {
          return prev;
        }
        return { w: roundedW, h: roundedH };
      });
    });

    ro.observe(el);
    return () => ro.disconnect();
  }, [mode]);

  useEffect(() => {
    if (mode !== "pending" || size.w <= 1 || size.h <= 1) return;
    let cancelled = false;

    (async () => {
      try {
        const dpr = Math.min(typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1, 1.5);
        const mapUrl = await generateDisplacementBlobUrl({
          width: size.w,
          height: size.h,
          radius: Math.min(radius, size.w / 2, size.h / 2),
          bevelDepth: Math.min(bevelDepth, Math.min(size.w, size.h) / 2),
          dpr,
        });

        // Pre-decode before attaching
        await new Promise<void>((resolve) => {
          const img = new Image();
          img.onload = img.onerror = () => resolve();
          img.src = mapUrl;
        });

        if (cancelled) {
          URL.revokeObjectURL(mapUrl);
          return;
        }

        if (blobRef.current) URL.revokeObjectURL(blobRef.current);
        blobRef.current = mapUrl;

        // Stable ID per element dimension without Date.now() to prevent render loop invalidation
        const id = `lg-${reactId}-${size.w}x${size.h}`;
        setFilter({
          id,
          svg: buildFilterSvg({
            id,
            mapUrl,
            width: size.w,
            height: size.h,
            scale,
            aberration,
            frost,
          }),
        });
      } catch (err) {
        setMode("simple");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [mode, size.w, size.h, radius, bevelDepth, scale, aberration, frost, reactId]);

  useEffect(() => {
    return () => {
      cancelAnimationFrame(rafRef.current);
      if (blobRef.current) URL.revokeObjectURL(blobRef.current);
    };
  }, []);

  const handlePointerEnter = () => {
    if (mode === "pending" && interactive && rootRef.current) {
      const b = rootRef.current.getBoundingClientRect();
      rectRef.current = { left: b.left, top: b.top, width: b.width, height: b.height };
    }
  };

  const handlePointerLeave = () => {
    rectRef.current = null;
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (mode === "pending" && interactive && rootRef.current && e.pointerType === "mouse") {
      const clientX = e.clientX;
      const clientY = e.clientY;
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(() => {
        const el = rootRef.current;
        if (!el) return;
        const rect = rectRef.current || el.getBoundingClientRect();
        el.style.setProperty("--spot-x", `${clientX - rect.left}px`);
        el.style.setProperty("--spot-y", `${clientY - rect.top}px`);
      });
    }
    if (onPointerMove) onPointerMove(e);
  };

  const backdrop =
    mode === "opaque"
      ? "none"
      : mode === "simple"
        ? "blur(18px) saturate(160%)"
        : filter
          ? `url(#${filter.id}) blur(0.2px) saturate(135%)`
          : "blur(18px) saturate(160%)";

  // Light Mode styling with subtle pearl refraction & soft edges
  const variantBaseClasses = {
    pill: "liquid-pill-v2 border border-white/80 shadow-[0_4px_20px_rgba(22,139,210,0.06)]",
    button: "liquid-btn-v2 border border-white/85 shadow-[0_2px_12px_rgba(22,139,210,0.08)] active:scale-[0.98] transition-transform",
    panel: "liquid-panel-v2 border border-white/85 shadow-[0_8px_28px_rgba(22,139,210,0.05)]",
    modal: "liquid-modal-v2 border border-white/90 shadow-[0_16px_40px_rgba(20,42,59,0.10)]",
  };

  return (
    <Component
      ref={rootRef}
      data-refract={mode === "pending" && filter ? "true" : "false"}
      data-variant={variant}
      className={cn(
        "relative overflow-hidden isolation-auto",
        variantBaseClasses[variant],
        effectiveLevel === "interactive"
          ? "glass-interactive"
          : effectiveLevel === "mobile"
            ? "glass-mobile"
            : "glass-surface",
        interactive && mode === "pending" && "specular-card",
        className,
      )}
      style={{
        borderRadius: radius,
        backgroundColor:
          mode === "pending"
            ? `rgba(255, 255, 255, ${tint})`
            : undefined,
        backdropFilter: backdrop,
        WebkitBackdropFilter: backdrop,
        ...style,
      }}
      onPointerEnter={handlePointerEnter}
      onPointerLeave={handlePointerLeave}
      onPointerMove={handlePointerMove}
      {...rest}
    >
      {filter ? (
        <span
          key={filter.id}
          aria-hidden="true"
          className="pointer-events-none absolute size-0 overflow-hidden"
          dangerouslySetInnerHTML={{ __html: filter.svg }}
        />
      ) : null}

      {/* Internal rim light reflection layer */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 rounded-[inherit] border border-white/60 shadow-[inset_0_1px_1px_rgba(255,255,255,0.7)]"
      />

      {contentClassName ? (
        <div className={cn("relative z-10", contentClassName)}>{children}</div>
      ) : (
        children
      )}
    </Component>
  );
}

/* ---------------------------------------------------------------------------
 * Browser Capability Checks
 * ------------------------------------------------------------------------- */

function supportsUrlBackdropFilter(): boolean {
  if (typeof CSS === "undefined" || !CSS.supports) return false;
  return (
    CSS.supports("backdrop-filter", "url(#x)") ||
    CSS.supports("-webkit-backdrop-filter", "url(#x)")
  );
}

function prefersReducedTransparency(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-transparency: reduce)").matches;
}

function isSafariLike(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent;
  return /Safari/.test(ua) && !/Chrome|Chromium|Edg|OPR/.test(ua);
}

/* ---------------------------------------------------------------------------
 * Snell's-law Displacement Map Generator
 * R = horizontal displacement
 * G = vertical displacement
 * B = specular rim highlight
 * A = shape mask
 * ------------------------------------------------------------------------- */

interface DisplacementOptions {
  width: number;
  height: number;
  radius: number;
  bevelDepth: number;
  gain?: number;
  light?: { x: number; y: number };
  dpr?: number;
}

/** Signed distance to a rounded rectangle centered at origin */
function sdRoundedBox(
  px: number,
  py: number,
  halfW: number,
  halfH: number,
  r: number,
): number {
  const qx = Math.abs(px) - halfW + r;
  const qy = Math.abs(py) - halfH + r;
  const outside = Math.hypot(Math.max(qx, 0), Math.max(qy, 0));
  const inside = Math.min(Math.max(qx, qy), 0);
  return inside + outside - r;
}

/** Squircle-dome slope mapping to Snell's-law bend */
function bendFromDepth(x: number): number {
  const u = 1 - Math.min(1, Math.max(0, x));
  const denom = (1 - u ** 4) ** 0.75;
  if (denom < 1e-6) return 0;
  const thetaI = Math.atan(Math.min(u ** 3 / denom, 8));
  const sinT = Math.sin(thetaI) / 1.5;
  if (sinT >= 1) return Math.sin(thetaI);
  return Math.sin(thetaI - Math.asin(sinT));
}

/** Integrated phi lookup table */
function buildPhiTable(bevelPx: number): Float32Array {
  const n = Math.max(1, Math.ceil(bevelPx));
  const phi = new Float32Array(n + 1);
  for (let d = 1; d <= n; d++) {
    phi[d] = phi[d - 1] + bendFromDepth(d / n);
  }
  return phi;
}

function samplePhi(phi: Float32Array, depth: number): number {
  const max = phi.length - 1;
  if (depth <= 0) return phi[0];
  if (depth >= max) return phi[max];
  const i = Math.floor(depth);
  const f = depth - i;
  return phi[i] * (1 - f) + phi[i + 1] * f;
}

function computeDisplacementData(opts: DisplacementOptions) {
  const dpr = opts.dpr ?? 1;
  const gain = opts.gain ?? 1.35;
  const light = opts.light ?? { x: -0.55, y: -0.85 };
  const lightLen = Math.hypot(light.x, light.y) || 1;
  const lx = light.x / lightLen;
  const ly = light.y / lightLen;

  const W = Math.max(1, Math.round(opts.width * dpr));
  const H = Math.max(1, Math.round(opts.height * dpr));
  const halfW = W / 2;
  const halfH = H / 2;
  const r = Math.min(opts.radius * dpr, halfW, halfH);
  const bevel = Math.max(1, opts.bevelDepth * dpr);
  const phi = buildPhiTable(bevel);

  const field = new Float32Array(W * H);
  for (let y = 0; y < H; y++) {
    const py = y - halfH + 0.5;
    for (let x = 0; x < W; x++) {
      const d = sdRoundedBox(x - halfW + 0.5, py, halfW, halfH, r);
      field[y * W + x] = d > 0 ? 0 : samplePhi(phi, Math.min(bevel, -d));
    }
  }

  const data = new Uint8ClampedArray(W * H * 4);
  for (let y = 0; y < H; y++) {
    const py = y - halfH + 0.5;
    for (let x = 0; x < W; x++) {
      const px = x - halfW + 0.5;
      const i = (y * W + x) << 2;
      const d = sdRoundedBox(px, py, halfW, halfH, r);

      if (d > 0) {
        data[i] = data[i + 1] = data[i + 2] = 128;
        data[i + 3] = 0;
        continue;
      }

      const x0 = Math.max(0, x - 1);
      const x1 = Math.min(W - 1, x + 1);
      const y0 = Math.max(0, y - 1);
      const y1 = Math.min(H - 1, y + 1);
      const dPhiX = (field[y * W + x1] - field[y * W + x0]) / (x1 - x0 || 1);
      const dPhiY = (field[y1 * W + x] - field[y0 * W + x]) / (y1 - y0 || 1);

      const dx = Math.max(-1, Math.min(1, dPhiX * gain));
      const dy = Math.max(-1, Math.min(1, dPhiY * gain));

      let specular = 0;
      if (d >= -bevel) {
        const gx =
          sdRoundedBox(px + 1, py, halfW, halfH, r) -
          sdRoundedBox(px - 1, py, halfW, halfH, r);
        const gy =
          sdRoundedBox(px, py + 1, halfW, halfH, r) -
          sdRoundedBox(px, py - 1, halfW, halfH, r);
        const len = Math.hypot(gx, gy) || 1;
        const dot = (gx / len) * lx + (gy / len) * ly;
        const rim = 1 - Math.min(1, -d / bevel);
        specular = (Math.max(0, dot) + Math.max(0, -dot) * 0.35) * rim;
      }

      data[i] = Math.round(128 + dx * 127);
      data[i + 1] = Math.round(128 + dy * 127);
      data[i + 2] = Math.round(specular * 255);
      data[i + 3] = 255;
    }
  }

  return { data, width: W, height: H };
}

async function generateDisplacementBlobUrl(opts: DisplacementOptions): Promise<string> {
  const { data, width, height } = computeDisplacementData(opts);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("2d context unavailable");
  ctx.putImageData(new ImageData(data, width, height), 0, 0);

  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/png"),
  );
  if (!blob) throw new Error("Failed to encode displacement map");
  return URL.createObjectURL(blob);
}

/* ---------------------------------------------------------------------------
 * SVG Filter with Chromatic Aberration
 * ------------------------------------------------------------------------- */

interface FilterOptions {
  id: string;
  mapUrl: string;
  width: number;
  height: number;
  scale: number;
  aberration: number;
  frost: number;
}

function buildFilterSvg({
  id,
  mapUrl,
  width,
  height,
  scale,
  aberration,
  frost,
}: FilterOptions): string {
  const pad = Math.ceil(scale + aberration + 4);
  const px = (pad / Math.max(1, width)) * 100;
  const py = (pad / Math.max(1, height)) * 100;
  const region = `x="-${px.toFixed(3)}%" y="-${py.toFixed(3)}%" width="${(100 + 2 * px).toFixed(3)}%" height="${(100 + 2 * py).toFixed(3)}%"`;

  const map = `<feImage href="${mapUrl}" xlink:href="${mapUrl}" x="0" y="0" width="${width}" height="${height}" result="map" preserveAspectRatio="none"/>`;
  const displace = (s: number, result: string) =>
    `<feDisplacementMap in="SourceGraphic" in2="map" scale="${s}" xChannelSelector="R" yChannelSelector="G" result="${result}"/>`;

  const body =
    aberration <= 0
      ? `${displace(scale, "rgb")}`
      : `${displace(scale + aberration, "dispR")}
  <feColorMatrix in="dispR" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="red"/>
  ${displace(scale, "dispG")}
  <feColorMatrix in="dispG" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0" result="green"/>
  ${displace(Math.max(0, scale - aberration), "dispB")}
  <feColorMatrix in="dispB" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0" result="blue"/>
  <feBlend in="red" in2="green" mode="screen" result="rg"/>
  <feBlend in="rg" in2="blue" mode="screen" result="rgb"/>`;

  return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="0" height="0" aria-hidden="true" style="position:absolute;width:0;height:0;overflow:hidden"><filter id="${id}" color-interpolation-filters="sRGB" ${region}>
  ${map}
  ${body}
  <feGaussianBlur in="rgb" stdDeviation="${frost}"/>
</filter></svg>`;
}
