"use client";

import React, { HTMLAttributes } from "react";
import { LiquidGlass, LiquidGlassProps } from "./LiquidGlass";

export interface LiquidGlassCardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: LiquidGlassProps["variant"];
  glassLevel?: LiquidGlassProps["glassLevel"];
  renderMode?: LiquidGlassProps["renderMode"];
  radius?: number;
  bevelDepth?: number;
  scale?: number;
  aberration?: number;
  frost?: number;
  tint?: number;
  interactive?: boolean;
}

export function LiquidGlassCard({
  className = "",
  variant = "panel",
  glassLevel = "static",
  renderMode = "static",
  interactive = false,
  children,
  ...props
}: LiquidGlassCardProps) {
  return (
    <LiquidGlass
      variant={variant}
      glassLevel={glassLevel}
      renderMode={renderMode}
      interactive={interactive}
      className={className}
      {...props}
    >
      {children}
    </LiquidGlass>
  );
}
