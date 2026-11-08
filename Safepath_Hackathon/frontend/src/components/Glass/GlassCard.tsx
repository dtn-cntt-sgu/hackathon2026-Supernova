"use client";

import React from "react";

export interface GlassCardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "elevated" | "frosted" | "aurora";
  interactive?: boolean;
}

export const GlassCard: React.FC<GlassCardProps> = ({
  variant = "default",
  interactive = false,
  className = "",
  children,
  ...props
}) => {
  const variantStyles = {
    default: "glass-surface border-white/90 shadow-glass",
    elevated: "glass-panel-elevated border-white/95 shadow-glass-elevated",
    frosted: "glass-surface border border-white/80 shadow-glass-sm",
    aurora: "bg-gradient-to-br from-white/90 via-indigo-50/40 to-white/80 backdrop-blur-xl border border-indigo-200/60 shadow-glass-elevated",
  };

  const interactiveStyles = interactive
    ? "transition-all duration-200 hover:-translate-y-0.5 hover:shadow-glass-elevated hover:border-white cursor-pointer"
    : "";

  return (
    <div
      className={`rounded-3xl border p-4 text-ink-900 ${variantStyles[variant]} ${interactiveStyles} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
};

export default GlassCard;

