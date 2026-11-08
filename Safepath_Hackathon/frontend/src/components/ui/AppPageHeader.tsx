"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Navigation,
  Camera,
  Newspaper,
  LayoutDashboard,
  User,
  Menu,
  X,
} from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { OnboardingHelpButton } from "../onboarding/OnboardingHelpButton";

const NAV_LINKS = [
  { href: "/di-duong", label: "Bản đồ", icon: Navigation, altHref: "/map" },
  { href: "/monitor", label: "Camera", icon: Camera },
  { href: "/news", label: "Bản tin", icon: Newspaper },
  { href: "/dashboard", label: "Của tôi", icon: LayoutDashboard },
  { href: "/account", label: "Tài khoản", icon: User },
];

interface AppPageHeaderProps {
  title: string;
  description: string;
  badge?: string;
  rightAction?: React.ReactNode;
}

export function AppPageHeader({ title, description, badge, rightAction }: AppPageHeaderProps) {
  const pathname = usePathname();
  const { user } = useAuth();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const isLinkActive = (item: (typeof NAV_LINKS)[0]) => {
    if (pathname === item.href) return true;
    if (item.altHref && pathname === item.altHref) return true;
    if (item.href !== "/" && pathname.startsWith(item.href)) return true;
    return false;
  };

  return (
    <header className="sticky top-0 z-40 w-full glass-surface border-b border-white/90 shadow-glass-sm transition-all duration-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 md:px-8 h-16 md:h-20 flex items-center justify-between gap-3">
        {/* Left Section: SafePath AI Brand + Divider + Page Title */}
        <div className="flex items-center gap-3 min-w-0">
          {/* Logo Mark + Brand */}
          <Link href="/" className="flex items-center gap-2.5 group shrink-0" aria-label="SafePathAI Trang chủ">
            <div className="p-2 bg-gradient-to-tr from-[#168BD2] via-[#168BD2] to-[#18B6AD] rounded-2xl shadow-md shadow-[#168BD2]/20 text-white group-hover:scale-105 transition-transform">
              <Navigation className="w-5 h-5" />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-base font-black tracking-tight text-[#142A3B]">
                SafePath<span className="aurora-gradient-text font-black">AI</span>
              </span>
              <span className="hidden sm:inline-block text-[10px] font-bold tracking-wider px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200/70 shadow-sm">
                3.1
              </span>
            </div>
          </Link>

          {/* Vertical Divider */}
          <div className="hidden sm:block h-5 w-px bg-slate-200/90 mx-1 shrink-0" />

          {/* Page Title & Subtitle */}
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="text-sm sm:text-base font-extrabold text-[#142A3B] truncate tracking-tight">
                {title}
              </h1>
              {badge && (
                <span className="hidden sm:inline-block text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                  {badge}
                </span>
              )}
            </div>
            <p className="hidden xl:block text-[11px] text-[#607889] font-medium leading-none mt-0.5 truncate">
              {description}
            </p>
          </div>
        </div>

        {/* Center / Right Section: Desktop Navigation */}
        <nav className="hidden md:flex items-center gap-1.5" aria-label="Điều hướng chính">
          {NAV_LINKS.map((item) => {
            const active = isLinkActive(item);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`px-3.5 py-1.5 rounded-full text-xs font-semibold transition-all duration-200 cursor-pointer ${
                  active
                    ? "font-bold text-[#168BD2] bg-[#E9F5FF] border border-[#168BD2]/30 shadow-glass-sm"
                    : "text-[#607889] hover:text-[#168BD2] hover:bg-white/80 border border-transparent"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Right Section: User Profile & Actions (Desktop) + Mobile Menu Toggle */}
        <div className="flex items-center gap-2 shrink-0">
          {rightAction}

          {/* Help tour button (desktop) */}
          <div className="hidden sm:block">
            <OnboardingHelpButton variant="pill" />
          </div>

          {/* User profile link (desktop) */}
          <Link
            href="/account"
            className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/80 hover:bg-white border border-white/90 shadow-glass-sm transition text-xs font-bold text-[#142A3B] cursor-pointer"
            title="Tài khoản và Cấu hình xe"
          >
            {user ? (
              <>
                {user.avatar ? (
                  // Preserve remote source bytes without the image optimization proxy.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={user.avatar}
                    alt={user.name}
                    className="w-5 h-5 rounded-full border border-indigo-200 object-cover"
                  />
                ) : (
                  <User className="w-4 h-4 text-[#168BD2]" />
                )}
                <span className="hidden lg:inline max-w-[85px] truncate">{user.name}</span>
              </>
            ) : (
              <>
                <User className="w-4 h-4 text-[#168BD2]" />
                <span className="hidden lg:inline">Tài khoản</span>
              </>
            )}
          </Link>

          {/* Mobile Hamburger Button */}
          <button
            type="button"
            data-testid="mobile-menu-btn"
            onClick={() => setMobileMenuOpen((v) => !v)}
            aria-label={mobileMenuOpen ? "Đóng menu điều hướng" : "Mở menu điều hướng"}
            aria-expanded={mobileMenuOpen}
            className="md:hidden p-2 rounded-xl bg-white/90 hover:bg-white border border-slate-200/80 text-[#142A3B] hover:text-[#168BD2] shadow-glass-sm transition-all cursor-pointer flex items-center justify-center min-w-10 min-h-10"
          >
            {mobileMenuOpen ? <X className="w-5 h-5 text-[#168BD2]" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Dropdown Menu Drawer */}
      {mobileMenuOpen && (
        <div data-testid="mobile-menu-drawer" className="md:hidden border-t border-indigo-100/70 glass-surface px-4 py-3 shadow-glass-elevated animate-fadeIn space-y-2">
          {/* Subtitle in mobile view */}
          <p className="text-xs text-[#607889] px-2 pt-1 font-medium">{description}</p>

          <div className="grid grid-cols-1 gap-1 pt-1">
            {NAV_LINKS.map((item) => {
              const active = isLinkActive(item);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={() => setMobileMenuOpen(false)}
                  aria-current={active ? "page" : undefined}
                  className={`flex items-center gap-3 px-3.5 py-3 rounded-2xl text-xs font-bold transition-all min-h-12 ${
                    active
                      ? "bg-[#E9F5FF] text-[#168BD2] border border-[#168BD2]/30 shadow-sm"
                      : "text-[#142A3B] hover:bg-slate-50 border border-transparent"
                  }`}
                >
                  <div
                    className={`p-2 rounded-xl ${
                      active ? "bg-[#168BD2] text-white" : "bg-slate-100 text-[#607889]"
                    }`}
                  >
                    <Icon className="w-4 h-4" />
                  </div>
                  <span className="flex-1">{item.label}</span>
                  {active && (
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-[#168BD2] text-white">
                      Đang xem
                    </span>
                  )}
                </Link>
              );
            })}
          </div>

          <div className="pt-2 border-t border-slate-100 flex items-center justify-between px-2">
            <Link
              href="/account"
              onClick={() => setMobileMenuOpen(false)}
              className="flex items-center gap-2 text-xs font-bold text-[#142A3B]"
            >
              <User className="w-4 h-4 text-[#168BD2]" />
              <span>{user ? user.name : "Đăng nhập tài khoản"}</span>
            </Link>
            <OnboardingHelpButton variant="minimal" />
          </div>
        </div>
      )}
    </header>
  );
}
