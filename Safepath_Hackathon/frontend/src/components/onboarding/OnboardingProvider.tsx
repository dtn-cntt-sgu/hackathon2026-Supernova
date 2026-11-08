"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { usePathname } from "next/navigation";
import { TourState, INITIAL_TOUR_STATE } from "../../lib/onboarding/tourSteps";

interface OnboardingContextType {
  tourState: TourState;
  activeTour: "map" | "news" | null;
  welcomeOpen: boolean;
  startTour: (tour: "map" | "news") => void;
  stopTour: () => void;
  skipTour: () => void;
  completeTour: (tour: "map" | "news") => void;
  openWelcomeModal: () => void;
  closeWelcomeModal: (dontShowAgain?: boolean) => void;
  resetTour: () => void;
}

const STORAGE_KEY = "safepath_tour_state_v1";

const OnboardingContext = createContext<OnboardingContextType | null>(null);

export function OnboardingProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [tourState, setTourState] = useState<TourState>(INITIAL_TOUR_STATE);
  const [activeTour, setActiveTour] = useState<"map" | "news" | null>(null);
  const [welcomeOpen, setWelcomeOpen] = useState(false);
  const [hasHydrated, setHasHydrated] = useState(false);

  // Hydrate from localStorage safely on client
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed: TourState = JSON.parse(stored);
        if (parsed.version === "v1") {
          setTourState(parsed);
        }
      }
    } catch {
      // Ignore
    } finally {
      setHasHydrated(true);
    }
  }, []);

  // Save tour state changes
  const saveState = useCallback((state: TourState) => {
    setTourState(state);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // Ignore
    }
  }, []);

  // First-time visit detection on /map or /news
  useEffect(() => {
    if (!hasHydrated) return;

    // Check if user is on map, di-duong or news and has not skipped or completed tour
    const isTargetPage = pathname === "/map" || pathname === "/di-duong" || pathname === "/news";
    if (isTargetPage && tourState.status === "idle") {
      // Avoid auto-triggering when another modal is already active
      const otherModal = document.querySelector('[role="dialog"]:not([aria-labelledby="onboarding-welcome-title"])');
      if (otherModal) return;

      // Short delay after page hydration to let DOM render
      const timer = setTimeout(() => {
        const stillOtherModal = document.querySelector('[role="dialog"]:not([aria-labelledby="onboarding-welcome-title"])');
        if (!stillOtherModal) {
          setWelcomeOpen(true);
        }
      }, 400);
      return () => clearTimeout(timer);
    }
  }, [hasHydrated, pathname, tourState.status]);

  const startTour = useCallback((tour: "map" | "news") => {
    setWelcomeOpen(false);
    setActiveTour(tour);
    saveState({
      version: "v1",
      status: "in_progress",
      lastStepId: tour,
      updatedAt: new Date().toISOString(),
    });
  }, [saveState]);

  const stopTour = useCallback(() => {
    setActiveTour(null);
  }, []);

  const skipTour = useCallback(() => {
    setActiveTour(null);
    setWelcomeOpen(false);
    saveState({
      version: "v1",
      status: "skipped",
      updatedAt: new Date().toISOString(),
    });
  }, [saveState]);

  const completeTour = useCallback((tour: "map" | "news") => {
    setActiveTour(null);
    setWelcomeOpen(false);
    saveState({
      version: "v1",
      status: "completed",
      lastStepId: tour,
      updatedAt: new Date().toISOString(),
    });
  }, [saveState]);

  const openWelcomeModal = useCallback(() => {
    setWelcomeOpen(true);
  }, []);

  const closeWelcomeModal = useCallback((dontShowAgain = false) => {
    setWelcomeOpen(false);
    if (dontShowAgain) {
      skipTour();
    }
  }, [skipTour]);

  const resetTour = useCallback(() => {
    saveState(INITIAL_TOUR_STATE);
  }, [saveState]);

  return (
    <OnboardingContext.Provider
      value={{
        tourState,
        activeTour,
        welcomeOpen,
        startTour,
        stopTour,
        skipTour,
        completeTour,
        openWelcomeModal,
        closeWelcomeModal,
        resetTour,
      }}
    >
      {children}
    </OnboardingContext.Provider>
  );
}

export function useOnboarding() {
  const ctx = useContext(OnboardingContext);
  if (!ctx) {
    throw new Error("useOnboarding must be used within OnboardingProvider");
  }
  return ctx;
}
