"use client";

import React, { useState, useEffect, useRef, useCallback, useId } from "react";
import { PlaceResult, Coordinates } from "../types/contracts";
import { searchPlaces } from "../services/api";
import { MapPin, Search, X, Loader2, Crosshair } from "lucide-react";

const LOCAL_LANDMARKS: PlaceResult[] = [
  {
    id: "preset_ben_thanh",
    name: "Chợ Bến Thành",
    display_name: "Chợ Bến Thành, Phường Bến Thành, Quận 1, TP. Hồ Chí Minh",
    lat: 10.7725,
    lng: 106.6980,
    type: "landmark",
    district: "Quận 1",
    city: "Thành phố Hồ Chí Minh",
    provenance: "osm.hcm_preset",
  },
  {
    id: "preset_landmark_81",
    name: "Landmark 81",
    display_name: "Tòa nhà Landmark 81, Vinhomes Central Park, Bình Thạnh, TP. Hồ Chí Minh",
    lat: 10.7950,
    lng: 106.7218,
    type: "landmark",
    district: "Bình Thạnh",
    city: "Thành phố Hồ Chí Minh",
    provenance: "osm.hcm_preset",
  },
  {
    id: "preset_hang_xanh",
    name: "Ngã tư Hàng Xanh",
    display_name: "Ngã tư Hàng Xanh, Phường 21, Bình Thạnh, TP. Hồ Chí Minh",
    lat: 10.8012,
    lng: 106.7115,
    type: "intersection",
    district: "Bình Thạnh",
    city: "Thành phố Hồ Chí Minh",
    provenance: "osm.hcm_preset",
  },
  {
    id: "preset_nguyen_huu_canh",
    name: "Đường Nguyễn Hữu Cảnh",
    display_name: "Đường Nguyễn Hữu Cảnh, Quận 1 / Bình Thạnh, TP. Hồ Chí Minh",
    lat: 10.7981,
    lng: 106.7186,
    type: "street",
    district: "Bình Thạnh",
    city: "Thành phố Hồ Chí Minh",
    provenance: "osm.hcm_preset",
  },
  {
    id: "preset_tan_son_nhat",
    name: "Sân bay Tân Sơn Nhất",
    display_name: "Cảng hàng không quốc tế Tân Sơn Nhất, Tân Bình, TP. Hồ Chí Minh",
    lat: 10.8185,
    lng: 106.6588,
    type: "airport",
    district: "Tân Bình",
    city: "Thành phố Hồ Chí Minh",
    provenance: "osm.hcm_preset",
  },
  {
    id: "preset_duc_ba",
    name: "Nhà thờ Đức Bà",
    display_name: "Nhà thờ Đức Bà Sài Gòn, Công xã Paris, Quận 1, TP. Hồ Chí Minh",
    lat: 10.7798,
    lng: 106.6990,
    type: "landmark",
    district: "Quận 1",
    city: "Thành phố Hồ Chí Minh",
    provenance: "osm.hcm_preset",
  },
];

interface PlaceSearchComboboxProps {
  label: string;
  placeholder: string;
  color: "emerald" | "rose";
  value: string;
  onChangeText: (text: string) => void;
  selectedCoordinates: Coordinates | null;
  onSelectPlace: (place: PlaceResult | null) => void;
  onLocateMe?: () => void;
  isLocating?: boolean;
  isPickingOnMap?: boolean;
  onTogglePickOnMap?: () => void;
  ariaLabel: string;
  testId?: string;
}

export const PlaceSearchCombobox: React.FC<PlaceSearchComboboxProps> = ({
  label,
  placeholder,
  color,
  value,
  onChangeText,
  selectedCoordinates,
  onSelectPlace,
  onLocateMe,
  isLocating,
  isPickingOnMap,
  onTogglePickOnMap,
  ariaLabel,
  testId,
}) => {
  const suggestionsId = useId();
  const [isOpen, setIsOpen] = useState(false);
  const [suggestions, setSuggestions] = useState<PlaceResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Close dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Debounced search places
  const performSearch = useCallback(
    async (queryText: string) => {
      const clean = queryText.trim();

      // Check if user input is raw "lat, lng" coordinates
      const coordMatch = clean.match(/^\s*([+-]?\d+(?:\.\d+)?)\s*,\s*([+-]?\d+(?:\.\d+)?)\s*$/);
      if (coordMatch) {
        const lat = parseFloat(coordMatch[1]);
        const lng = parseFloat(coordMatch[2]);
        if (!isNaN(lat) && !isNaN(lng) && lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180) {
          const directPlace: PlaceResult = {
            id: `coord_${lat.toFixed(5)}_${lng.toFixed(5)}`,
            name: `Tọa độ: ${lat.toFixed(5)}, ${lng.toFixed(5)}`,
            display_name: `Tọa độ [${lat.toFixed(5)}, ${lng.toFixed(5)}]`,
            lat,
            lng,
            type: "coordinate",
            provenance: "user_coordinates",
          };
          setSuggestions([directPlace]);
          setIsLoading(false);
          setIsOpen(true);
          return;
        }
      }

      if (clean.length < 3) {
        setSuggestions([]);
        setIsLoading(false);
        return;
      }

      // Check local landmarks for instant matching (0ms local latency)
      const localMatches = LOCAL_LANDMARKS.filter(
        (l) =>
          l.name.toLowerCase().includes(clean.toLowerCase()) ||
          l.display_name.toLowerCase().includes(clean.toLowerCase())
      );
      if (localMatches.length > 0) {
        setSuggestions(localMatches);
        setIsOpen(true);
      }

      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      const controller = new AbortController();
      abortControllerRef.current = controller;

      setIsLoading(localMatches.length === 0);
      setSearchError(null);

      try {
        const response = await searchPlaces(clean, 6, controller.signal);
        const remoteResults = response.results || [];
        // Combine local and remote results without duplicates
        const combined = [...localMatches];
        for (const r of remoteResults) {
          if (!combined.some((c) => Math.abs(c.lat - r.lat) < 1e-4 && Math.abs(c.lng - r.lng) < 1e-4)) {
            combined.push(r);
          }
        }
        setSuggestions(combined.slice(0, 8));
        setIsOpen(true);
      } catch (err: any) {
        if (err.name !== "AbortError") {
          if (localMatches.length === 0) {
            setSearchError("Không thể tải gợi ý địa điểm.");
            setSuggestions([]);
          }
        }
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const text = e.target.value;
    onChangeText(text);

    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const clean = text.trim();
    if (clean.length < 3) {
      setSuggestions([]);
      setIsOpen(false);
      setIsLoading(false);
      if (!clean) {
        onSelectPlace(null);
      }
      return;
    }

    // Synchronously match local landmarks to eliminate stale options immediately
    const localMatches = LOCAL_LANDMARKS.filter(
      (l) =>
        l.name.toLowerCase().includes(clean.toLowerCase()) ||
        l.display_name.toLowerCase().includes(clean.toLowerCase())
    );
    setSuggestions(localMatches);
    if (localMatches.length > 0) {
      setIsOpen(true);
    }

    debounceTimerRef.current = setTimeout(() => {
      performSearch(text);
    }, 280);
  };

  const handleSelect = (place: PlaceResult) => {
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current);
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    onChangeText(place.name || place.display_name);
    onSelectPlace(place);
    setIsOpen(false);
    setSuggestions([]);
    setIsLoading(false);
  };

  const handleClear = () => {
    onChangeText("");
    onSelectPlace(null);
    setSuggestions([]);
    setIsOpen(false);
  };

  return (
    <div ref={containerRef} className="space-y-1.5 relative" data-testid={testId}>
      {/* Label and actions */}
      <div className="flex items-center justify-between">
        <label className="text-xs font-semibold flex items-center gap-1.5 text-ink-800">
          <span
            className={`w-2.5 h-2.5 rounded-full ring-2 ${
              color === "emerald"
                ? "bg-emerald-500 ring-emerald-200"
                : "bg-rose-500 ring-rose-200"
            }`}
          />
          {label}
        </label>
        <div className="flex items-center gap-1.5">
          {onLocateMe && (
            <button
              type="button"
              onClick={onLocateMe}
              disabled={isLocating}
              className="flex items-center gap-1.5 text-[11px] font-bold text-indigo-700 hover:text-indigo-950 px-3 py-1 rounded-full bg-gradient-to-r from-ice-100/90 to-white/90 hover:from-white hover:to-ice-200/90 border border-indigo-200/90 shadow-glass-sm hover:shadow-glass hover:-translate-y-0.5 transition-all duration-200 disabled:opacity-50 select-none cursor-pointer"
              title="Lấy vị trí GPS hiện tại của thiết bị"
            >
              {isLocating ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin text-indigo-600 shrink-0" />
              ) : (
                <Crosshair className="w-3.5 h-3.5 text-indigo-600 shrink-0" />
              )}
              <span>Vị trí của tôi</span>
            </button>
          )}
          {onTogglePickOnMap && (
            <button
              type="button"
              onClick={onTogglePickOnMap}
              className={`flex items-center gap-1.5 text-[11px] font-bold px-3 py-1 rounded-full border transition-all duration-200 select-none cursor-pointer ${
                isPickingOnMap
                  ? "bg-amber-100/90 text-amber-900 border-amber-300 shadow-sm"
                  : "bg-white/85 text-ink-700 hover:text-ink-950 border-white/90 hover:bg-white shadow-glass-sm hover:-translate-y-0.5 hover:shadow-glass"
              }`}
              title="Bật chế độ chọn điểm này trực tiếp bằng cách click trên bản đồ"
            >
              <MapPin className="w-3.5 h-3.5 text-amber-500 shrink-0" />
              <span>{isPickingOnMap ? "Đang chọn trên map" : "Chọn trên map"}</span>
            </button>
          )}
        </div>
      </div>

      {/* Input container */}
      <div className="relative">
        <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-ink-400">
          <Search className="w-4 h-4" />
        </div>
        <input
          type="text"
          role="combobox"
          aria-controls={suggestionsId}
          aria-expanded={isOpen}
          aria-label={ariaLabel}
          aria-autocomplete="list"
          value={value}
          onChange={handleInputChange}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (suggestions.length > 0) {
                handleSelect(suggestions[0]);
              }
            } else if (e.key === "Escape") {
              setIsOpen(false);
            }
          }}
          onFocus={() => {
            if (suggestions.length > 0) setIsOpen(true);
            else if (value.trim().length >= 3) performSearch(value);
          }}
          placeholder={placeholder}
          className="w-full bg-white/90 hover:bg-white focus:bg-white text-ink-950 text-xs font-semibold placeholder:text-ink-400 rounded-2xl pl-10 pr-9 py-2.5 border border-indigo-100/90 shadow-glass-sm focus:shadow-glass focus:border-indigo-400 focus:ring-4 focus:ring-indigo-400/20 outline-none transition-all duration-200"
        />
        {isLoading && (
          <div className="absolute inset-y-0 right-3 flex items-center">
            <Loader2 className="w-4 h-4 animate-spin text-indigo-600" />
          </div>
        )}
        {!isLoading && value && (
          <button
            type="button"
            onClick={handleClear}
            className="absolute inset-y-0 right-3 flex items-center text-ink-400 hover:text-ink-800 transition"
            title="Xóa tìm kiếm"
            aria-label="Xóa nội dung"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Coordinate badge if coordinate is locked */}
      {selectedCoordinates && (
        <div className="text-[10px] text-ink-500 font-mono flex items-center gap-1.5 px-1.5">
          <span>Tọa độ WGS84:</span>
          <span className="text-indigo-600 font-semibold">
            {selectedCoordinates.lat.toFixed(5)}, {selectedCoordinates.lng.toFixed(5)}
          </span>
        </div>
      )}

      {/* Dropdown Suggestions */}
      {isOpen && (
        <div
          role="listbox"
          id={suggestionsId}
          className="absolute left-0 right-0 top-full mt-2 rounded-2xl border border-white/95 bg-white/95 backdrop-blur-2xl shadow-glass-elevated z-50 max-h-64 overflow-y-auto divide-y divide-slate-100/80 p-1.5 animate-fadeIn"
        >
          {suggestions.length > 0 ? (
            suggestions.map((item) => (
              <div
                key={item.id}
                role="option"
                aria-selected={false}
                tabIndex={0}
                onClick={() => handleSelect(item)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    handleSelect(item);
                  }
                }}
                className="p-3 rounded-xl hover:bg-gradient-to-r hover:from-indigo-50/90 hover:to-ice-100/70 cursor-pointer transition text-left flex items-start gap-3 focus:bg-indigo-50/90 focus:outline-none"
              >
                <div className="p-2 rounded-xl bg-indigo-50/90 border border-indigo-100 text-indigo-600 shrink-0 mt-0.5 shadow-sm">
                  <MapPin className="w-3.5 h-3.5" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-bold text-ink-950 truncate">{item.name}</div>
                  <div className="text-[11px] text-ink-600 line-clamp-1 mt-0.5">{item.display_name}</div>
                  <div className="flex items-center gap-2 mt-1.5">
                    {item.district && (
                      <span className="text-[9px] px-2 py-0.5 rounded-full bg-slate-100/90 border border-slate-200/80 text-ink-700 font-semibold">
                        {item.district}
                      </span>
                    )}
                    <span className="text-[9px] text-ink-400 font-mono font-medium">
                      {item.lat.toFixed(4)}, {item.lng.toFixed(4)}
                    </span>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className="p-3.5 text-center text-xs text-ink-500 font-medium">
              {cleanTextState(value)}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

function cleanTextState(val: string): string {
  if (val.trim().length < 3) {
    return "Nhập ít nhất 3 ký tự để tìm kiếm...";
  }
  return "Không tìm thấy địa điểm phù hợp tại TP.HCM.";
}
