"use client";

import React from "react";

export interface GlassButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger" | "ghost" | "pill";
  size?: "sm" | "md" | "lg" | "icon";
  isLoading?: boolean;
}

export const GlassButton: React.FC<GlassButtonProps> = ({
  variant = "secondary",
  size = "md",
  isLoading = false,
  className = "",
  disabled,
  children,
  ...props
}) => {
  const sizeStyles = {
    sm: "px-3 py-1.5 text-xs rounded-full gap-1.5",
    md: "px-4 py-2.5 text-xs font-bold rounded-2xl gap-2",
    lg: "px-5 py-3 text-sm font-bold rounded-2xl gap-2.5",
    icon: "p-2.5 rounded-full",
  };

  const variantStyles = {
    primary:
      "aurora-btn-primary text-white shadow-md shadow-indigo-500/25 border-0 hover:shadow-indigo-500/40",
    secondary:
      "bg-white/80 hover:bg-white text-ink-800 hover:text-ink-950 border border-white/90 shadow-glass-sm hover:shadow-glass hover:border-white",
    danger:
      "bg-rose-50/90 hover:bg-rose-100 text-rose-700 border border-rose-200/90 shadow-glass-sm hover:shadow-glass",
    ghost:
      "bg-transparent hover:bg-white/60 text-ink-700 hover:text-ink-950 border-0 shadow-none",
    pill:
      "glass-pill text-ink-700 hover:text-ink-950 border border-white/90 shadow-glass-sm rounded-full",
  };

  return (
    <button
      disabled={disabled || isLoading}
      className={`inline-flex items-center justify-center transition-all duration-200 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed select-none active:scale-[0.98] ${sizeStyles[size]} ${variantStyles[variant]} ${className}`}
      {...props}
    >
      {isLoading ? (
        <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
      ) : null}
      {children}
    </button>
  );
};

export default GlassButton;

