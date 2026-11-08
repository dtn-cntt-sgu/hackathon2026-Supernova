"use client";

import React, { forwardRef } from "react";
import { X } from "lucide-react";

export interface GlassInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
  onClear?: () => void;
  error?: string;
}

export const GlassInput = forwardRef<HTMLInputElement, GlassInputProps>(
  ({ label, leftIcon, rightIcon, onClear, error, className = "", value, ...props }, ref) => {
    return (
      <div className="w-full space-y-1.5">
        {label && (
          <label className="block text-[11px] font-bold text-ink-700 uppercase tracking-wider">
            {label}
          </label>
        )}
        <div className="relative flex items-center">
          {leftIcon && (
            <div className="absolute left-3.5 flex items-center pointer-events-none text-ink-400">
              {leftIcon}
            </div>
          )}
          <input
            ref={ref}
            value={value}
            className={`w-full py-2.5 bg-white/85 hover:bg-white focus:bg-white text-ink-950 text-xs font-medium placeholder-ink-400 rounded-2xl border border-white/90 shadow-glass-sm focus:shadow-glass focus:border-indigo-400 focus:ring-4 focus:ring-indigo-400/15 outline-none transition-all ${
              leftIcon ? "pl-10" : "pl-3.5"
            } ${rightIcon || onClear ? "pr-10" : "pr-3.5"} ${
              error ? "border-rose-300 ring-2 ring-rose-400/20" : ""
            } ${className}`}
            {...props}
          />
          {onClear && value && (
            <button
              type="button"
              onClick={onClear}
              aria-label="Xóa nội dung"
              className="absolute right-3 p-1 rounded-full text-ink-400 hover:text-ink-700 hover:bg-slate-100 transition cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
          {!onClear && rightIcon && (
            <div className="absolute right-3.5 flex items-center pointer-events-none text-ink-400">
              {rightIcon}
            </div>
          )}
        </div>
        {error && <p className="text-[11px] text-rose-600 font-medium pl-1">{error}</p>}
      </div>
    );
  }
);

GlassInput.displayName = "GlassInput";

export default GlassInput;

