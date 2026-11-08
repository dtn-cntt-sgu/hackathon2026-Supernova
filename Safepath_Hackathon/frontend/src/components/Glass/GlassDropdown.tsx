"use client";

import React, { useState, useRef, useEffect } from "react";
import { ChevronDown } from "lucide-react";

export interface DropdownItem {
  id: string;
  label: string;
  icon?: React.ReactNode;
  badge?: string;
  disabled?: boolean;
}

export interface GlassDropdownProps {
  triggerLabel: string;
  items: DropdownItem[];
  selectedId?: string;
  onSelect: (item: DropdownItem) => void;
  triggerIcon?: React.ReactNode;
  className?: string;
}

export const GlassDropdown: React.FC<GlassDropdownProps> = ({
  triggerLabel,
  items,
  selectedId,
  onSelect,
  triggerIcon,
  className = "",
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div ref={containerRef} className={`relative inline-block ${className}`}>
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className="glass-pill flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-semibold bg-white/85 hover:bg-white border border-white/90 shadow-glass-sm text-ink-800 transition"
      >
        {triggerIcon}
        <span>{triggerLabel}</span>
        <ChevronDown className="w-3.5 h-3.5 text-ink-500" />
      </button>

      {isOpen && (
        <div className="absolute right-0 top-full mt-2 w-52 rounded-2xl glass-panel-elevated p-1.5 border border-white/95 shadow-glass-elevated z-40 animate-fadeIn text-xs">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              disabled={item.disabled}
              onClick={() => {
                onSelect(item);
                setIsOpen(false);
              }}
              className={`w-full flex items-center justify-between px-3 py-2 rounded-xl text-left transition ${
                selectedId === item.id
                  ? "bg-indigo-50 text-indigo-700 font-bold"
                  : "text-ink-700 hover:bg-white/80"
              } ${item.disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}`}
            >
              <div className="flex items-center gap-2">
                {item.icon}
                <span>{item.label}</span>
              </div>
              {item.badge && (
                <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-ink-500">
                  {item.badge}
                </span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default GlassDropdown;

