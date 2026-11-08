"use client";

import React, { useEffect } from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface GlassModalProps {
  isOpen: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
  children: React.ReactNode;
  maxWidth?: "sm" | "md" | "lg" | "xl" | "2xl";
  className?: string;
}

export const GlassModal: React.FC<GlassModalProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  icon,
  children,
  maxWidth = "xl",
  className = "",
}) => {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (isOpen) {
      document.addEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "hidden";
    }
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = "";
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const maxWidthStyles = {
    sm: "max-w-sm",
    md: "max-w-md",
    lg: "max-w-lg",
    xl: "max-w-xl",
    "2xl": "max-w-2xl",
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5 bg-slate-900/25 backdrop-blur-sm animate-fadeIn"
      onClick={onClose}
    >
      <div
        className={cn(
          "relative w-full overflow-hidden text-ink-900 glass-panel-elevated rounded-3xl border border-white/95 shadow-2xl animate-slideUp flex flex-col",
          maxWidthStyles[maxWidth],
          className
        )}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        {(title || icon) && (
          <div className="flex items-center justify-between p-5 border-b border-slate-200/60 bg-white/80 backdrop-blur-md">
            <div className="flex items-center gap-3">
              {icon && (
                <div className="p-2.5 bg-indigo-50 border border-indigo-100 rounded-2xl text-indigo-600">
                  {icon}
                </div>
              )}
              <div>
                {title && <h3 className="text-base font-bold text-ink-950 tracking-wide">{title}</h3>}
                {subtitle && <p className="text-xs text-ink-500 mt-0.5">{subtitle}</p>}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Đóng"
              className="w-11 h-11 flex items-center justify-center rounded-full text-ink-500 hover:text-ink-950 hover:bg-slate-100 transition cursor-pointer shrink-0"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        )}

        {/* Body */}
        <div className="p-5 max-h-[80vh] overflow-y-auto">{children}</div>
      </div>
    </div>
  );
};

export default GlassModal;

