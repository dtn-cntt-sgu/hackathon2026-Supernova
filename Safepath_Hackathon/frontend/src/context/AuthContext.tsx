"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { SessionProvider, useSession, signIn, signOut } from "next-auth/react";

export interface SavedPlace {
  id: string;
  label: string;
  name: string;
  address?: string;
  lat: number;
  lng: number;
}

export interface RouteHistoryItem {
  id: string;
  originName: string;
  destName: string;
  distanceKm: number;
  durationMins: number;
  timestamp: string;
}

export interface UserProfile {
  id: string;
  name: string;
  email: string;
  avatar: string | null;
  sessionToken?: string | null;
  vehicle: "motorcycle" | "car";
  rainAlertsEnabled: boolean;
  tideAlertsEnabled: boolean;
  savedPlaces: SavedPlace[];
  history: RouteHistoryItem[];
}

interface AuthContextType {
  user: UserProfile | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  isConfigured: boolean;
  oauthStatus: "CONFIGURED" | "BLOCKED_CONFIGURATION" | "CHECKING";
  loginWithGoogle: () => Promise<void>;
  logout: () => Promise<void>;
  updateVehicle: (vehicle: "motorcycle" | "car") => Promise<void>;
  savePlace: (place: { name: string; address?: string; lat: number; lng: number; label?: string }) => Promise<void>;
  removeSavedPlace: (id: string) => Promise<void>;
  addRouteHistory: (item: {
    originName: string;
    destName: string;
    distanceKm: number;
    durationMins: number;
    originLat?: number;
    originLng?: number;
    destLat?: number;
    destLng?: number;
  }) => Promise<void>;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function InnerAuthProvider({ children }: { children: React.ReactNode }) {
  const { data: session, status } = useSession();
  const [user, setUser] = useState<UserProfile | null>(null);
  const [isConfigured, setIsConfigured] = useState<boolean>(false);
  const [oauthStatus, setOauthStatus] = useState<"CONFIGURED" | "BLOCKED_CONFIGURATION" | "CHECKING">("CHECKING");
  const [isLoadingProfile, setIsLoadingProfile] = useState<boolean>(false);

  // Check Google OAuth server configuration status on mount
  useEffect(() => {
    let isMounted = true;
    async function checkAuthStatus() {
      try {
        const res = await fetch("/api/auth/config", { cache: "no-store" });
        if (res.ok) {
          const data = await res.json();
          if (isMounted) {
            setIsConfigured(Boolean(data.google_oauth_configured));
            setOauthStatus(data.status === "CONFIGURED" ? "CONFIGURED" : "BLOCKED_CONFIGURATION");
          }
        } else {
          if (isMounted) {
            setIsConfigured(false);
            setOauthStatus("BLOCKED_CONFIGURATION");
          }
        }
      } catch (err) {
        if (isMounted) {
          setIsConfigured(false);
          setOauthStatus("BLOCKED_CONFIGURATION");
        }
      }
    }
    checkAuthStatus();
    return () => {
      isMounted = false;
    };
  }, []);

  // Fetch or sync user profile with PostgreSQL backend when authenticated
  const refreshProfile = useCallback(async () => {
    if (status !== "authenticated" || !session?.user?.email) {
      setUser(null);
      return;
    }

    setIsLoadingProfile(true);
    try {
      // 1. First sync to ensure account exists in database
      const syncRes = await fetch("/api/v1/user/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: "google",
          provider_account_id: (session.user as any).providerAccountId || (session.user as any).id || session.user.email,
          email: session.user.email,
          display_name: session.user.name || "Người dùng Google",
          avatar_url: session.user.image || null,
        }),
      });

      if (syncRes.ok) {
        const data = await syncRes.json();
        if (!data.is_active) { setUser(null); return; }
        setUser({
          id: data.id,
          name: data.display_name,
          email: data.email,
          avatar: data.avatar_url,
          sessionToken: data.session_token || null,
          vehicle: (data.preferences?.transport_mode === "car" ? "car" : "motorcycle"),
          rainAlertsEnabled: Boolean(data.preferences?.alert_notifications),
          tideAlertsEnabled: Boolean(data.preferences?.alert_notifications),
          savedPlaces: (data.saved_places || []).map((sp: any) => ({
            id: sp.id,
            label: sp.category || "Địa điểm",
            name: sp.name,
            address: sp.address,
            lat: sp.lat,
            lng: sp.lng,
          })),
          history: (data.route_history || []).map((rh: any) => ({
            id: rh.id,
            originName: rh.origin_name,
            destName: rh.dest_name,
            distanceKm: rh.distance_km,
            durationMins: rh.duration_mins,
            timestamp: rh.created_at || "",
          })),
        });
      } else {
        setUser(null);
      }
    } catch (err) {
      setUser(null);
      console.warn("Could not sync user profile with backend.");
    } finally {
      setIsLoadingProfile(false);
    }
  }, [session, status]);

  useEffect(() => {
    if (status === "authenticated") {
      refreshProfile();
    } else if (status === "unauthenticated") {
      setUser(null);
    }
  }, [status, refreshProfile]);

  const loginWithGoogle = async () => {
    if (!isConfigured) {
      console.warn("Google OAuth is not configured in backend/frontend environment (BLOCKED_CONFIGURATION).");
      return;
    }
    await signIn("google");
  };

  const logout = async () => {
    setUser(null);
    await signOut();
  };

  const getAuthHeaders = (includeJson = false): Record<string, string> => {
    const h: Record<string, string> = {};
    if (includeJson) h["Content-Type"] = "application/json";
    if (user?.id) h["X-User-Id"] = user.id;
    if (user?.sessionToken) {
      h["Authorization"] = `Bearer ${user.sessionToken}`;
      h["X-User-Token"] = user.sessionToken;
    }
    return h;
  };

  const updateVehicle = async (vehicle: "motorcycle" | "car") => {
    if (!user) return;
    try {
      await fetch("/api/v1/user/preferences", {
        method: "PUT",
        headers: getAuthHeaders(true),
        body: JSON.stringify({
          transport_mode: vehicle,
          avoid_flood_level: "MEDIUM",
          avoid_high_density: false,
          alert_notifications: user.rainAlertsEnabled,
          voice_guidance_enabled: true,
        }),
      });
      setUser((prev) => (prev ? { ...prev, vehicle } : null));
    } catch (err) {
      console.error("Failed to update vehicle preference:", err);
    }
  };

  const savePlace = async (place: { name: string; address?: string; lat: number; lng: number; label?: string }) => {
    if (!user) throw new Error("Vui lòng đăng nhập để lưu địa điểm.");
    try {
      const res = await fetch("/api/v1/user/saved-places", {
        method: "POST",
        headers: getAuthHeaders(true),
        body: JSON.stringify({
          name: place.name,
          address: place.address || place.name,
          lat: place.lat,
          lng: place.lng,
          category: place.label || "favorite",
        }),
      });
      if (!res.ok) throw new Error(`Không thể cập nhật địa điểm (${res.status}).`);
      if (res.ok) {
        const saved = await res.json();
        setUser((prev) =>
          prev
            ? {
                ...prev,
                savedPlaces: [
                  ...prev.savedPlaces,
                  {
                    id: saved.id,
                    label: saved.category,
                    name: saved.name,
                    address: saved.address,
                    lat: saved.lat,
                    lng: saved.lng,
                  },
                ],
              }
            : null
        );
      }
    } catch (err) {
      throw err;
    }
  };

  const removeSavedPlace = async (id: string) => {
    if (!user) throw new Error("Vui lòng đăng nhập để lưu địa điểm.");
    try {
      const res = await fetch(`/api/v1/user/saved-places/${id}`, {
        method: "DELETE",
        headers: getAuthHeaders(false),
      });
      if (!res.ok) throw new Error(`Không thể cập nhật địa điểm (${res.status}).`);
      if (res.ok) {
        setUser((prev) =>
          prev
            ? {
                ...prev,
                savedPlaces: prev.savedPlaces.filter((p) => p.id !== id),
              }
            : null
        );
      }
    } catch (err) {
      throw err;
    }
  };

  const addRouteHistory = async (item: {
    originName: string;
    destName: string;
    distanceKm: number;
    durationMins: number;
    originLat?: number;
    originLng?: number;
    destLat?: number;
    destLng?: number;
  }) => {
    if (!user) return;
    try {
      const res = await fetch("/api/v1/user/history", {
        method: "POST",
        headers: getAuthHeaders(true),
        body: JSON.stringify({
          origin_name: item.originName,
          dest_name: item.destName,
          origin_lat: item.originLat,
          origin_lng: item.originLng,
          dest_lat: item.destLat,
          dest_lng: item.destLng,
          distance_km: item.distanceKm,
          duration_mins: item.durationMins,
          travel_mode: user.vehicle,
        }),
      });
      if (res.ok) {
        const created = await res.json();
        setUser((prev) =>
          prev
            ? {
                ...prev,
                history: [
                  {
                    id: created.id,
                    originName: created.origin_name,
                    destName: created.dest_name,
                    distanceKm: created.distance_km,
                    durationMins: created.duration_mins,
                    timestamp: created.created_at || "",
                  },
                  ...prev.history.slice(0, 19),
                ],
              }
            : null
        );
      }
    } catch (err) {
      console.error("Failed to record route history:", err);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: status === "authenticated" && Boolean(user),
        isLoading: status === "loading" || isLoadingProfile,
        isConfigured,
        oauthStatus,
        loginWithGoogle,
        logout,
        updateVehicle,
        savePlace,
        removeSavedPlace,
        addRouteHistory,
        refreshProfile,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  return (
    <SessionProvider>
      <InnerAuthProvider>{children}</InnerAuthProvider>
    </SessionProvider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
};
