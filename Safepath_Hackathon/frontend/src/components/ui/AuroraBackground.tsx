"use client";

import React, { ReactNode } from "react";
import { cn } from "../../lib/utils";

export interface AuroraBackgroundProps extends React.HTMLProps<HTMLDivElement> {
  children?: ReactNode;
  showRadialGradient?: boolean;
}

/**
 * Aurora Background (Light Cinematic Edition)
 * Ported & optimized from Aceternity UI for SafePath AI.
 *
 * Characteristics:
 * - Single persistent background instance across ACT 01–04
 * - Pure Light Cinematic Liquid Glass palette (Pearl #F8FBFF, Ice #E9F5FF, Sky #BFE8F7, Cyan #8EDAE8, Teal #C5F1E8)
 * - 75s gentle linear keyframe animation driven purely by CSS background-position
 * - Zero mouse-tracking RAF overhead, zero background-attachment:fixed repaint jank
 * - Mobile-first GPU optimization (scaled blur, reduced motion support)
 */
export const AuroraBackground = ({
  className,
  children,
  showRadialGradient = true,
  ...props
}: AuroraBackgroundProps) => {
  return (
    <div
      className={cn(
        "relative overflow-hidden bg-[#F8FBFF] text-ink-950 transition-colors pointer-events-none",
        className
      )}
      aria-hidden="true"
      {...props}
    >
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div
          className={cn(
            `
            [--aurora:repeating-linear-gradient(100deg,#8EDAE8_10%,#BFE8F7_15%,#C5F1E8_20%,#E9F5FF_25%,#8EDAE8_30%)]
            [--pearl-gradient:repeating-linear-gradient(100deg,#F8FBFF_0%,#F8FBFF_7%,transparent_10%,transparent_12%,#F8FBFF_16%)]
            [background-image:var(--pearl-gradient),var(--aurora)]
            [background-size:300%,_200%]
            [background-position:50%_50%,50%_50%]
            filter blur-[8px] md:blur-[14px]
            after:content-[""] after:absolute after:inset-0
            after:[background-image:var(--pearl-gradient),var(--aurora)]
            after:[background-size:200%,_100%]
            after:animate-aurora
            motion-reduce:after:animate-none
            after:mix-blend-soft-light
            after:opacity-90
            pointer-events-none
            absolute -inset-[10px] opacity-80 will-change-[background-position]`,
            showRadialGradient &&
              `[mask-image:radial-gradient(ellipse_at_100%_0%,black_20%,transparent_80%)]`
          )}
        />
      </div>

      {/* Subtle Spatial Coordinate Grid Overlay */}
      <div
        className="absolute inset-0 bg-[linear-gradient(to_right,rgba(22,139,210,0.03)_1px,transparent_1px),linear-gradient(to_bottom,rgba(22,139,210,0.03)_1px,transparent_1px)] bg-[size:48px_48px] [mask-image:radial-gradient(ellipse_75%_65%_at_50%_25%,black_35%,transparent_95%)] pointer-events-none"
        aria-hidden="true"
      />

      {children && (
        <div className="relative z-10 pointer-events-auto">
          {children}
        </div>
      )}
    </div>
  );
};
