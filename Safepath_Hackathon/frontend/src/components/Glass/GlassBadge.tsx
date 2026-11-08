"use client";

import React from "react";

export interface GlassBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "emerald" | "amber" | "rose" | "indigo" | "cyan" | "slate";
  size?: "sm" | "md";
  glow?: boolean;
}

export const GlassBadge: React.FC<GlassBadgeProps> = ({
  variant = "indigo",
  size = "md",
  glow = false,
  className = "",
  children,
  ...props
}) => {
  const variantStyles = {
    emerald: "bg-emerald-50/90 text-emerald-700 border-emerald-200/90",
    amber: "bg-amber-50/90 text-amber-700 border-amber-200/90",
    rose: "bg-rose-50/90 text-rose-700 border-rose-200/90",
    indigo: "bg-indigo-50/90 text-indigo-700 border-indigo-200/80",
    cyan: "bg-cyan-50/90 text-cyan-700 border-cyan-200/90",
    slate: "bg-slate-100/90 text-ink-600 border-slate-200/80",
  };

  const glowStyles = {
    emerald: "ring-2 ring-emerald-400/20 shadow-sm",
    amber: "ring-2 ring-amber-400/20 shadow-sm",
    rose: "ring-2 ring-rose-400/20 shadow-sm",
    indigo: "ring-2 ring-indigo-400/20 shadow-sm",
    cyan: "ring-2 ring-cyan-400/20 shadow-sm",
    slate: "shadow-sm",
  };

  const sizeStyles = {
    sm: "px-2 py-0.5 text-[10px]",
    md: "px-2.5 py-1 text-xs",
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-bold rounded-full border backdrop-blur-md select-none ${sizeStyles[size]} ${variantStyles[variant]} ${glow ? glowStyles[variant] : ""} ${className}`}
      {...props}
    >
      {children}
    </span>
  );
};

export default GlassBadge;

