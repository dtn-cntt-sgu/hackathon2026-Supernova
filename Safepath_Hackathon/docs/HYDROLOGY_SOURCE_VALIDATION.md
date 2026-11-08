# SAFEPATHAI — HYDROLOGY SOURCE & TIDAL VALIDATION REPORT

**Author:** Principal AI Engineer, Senior Hydrological Data Architect  
**Project:** SafePathAI (Phase P0: Real-Time Hydrology & Tidal Ingestion)  
**Date:** October 2026  
**Status:** Validated · PostgreSQL Persisted · Redis Synchronized · Zero-Mock Enforced

---

## 1. Executive Summary

SafePathAI requires precise, ground-truth hydrological telemetry to prevent sending commuters through inundated roadways during high tide in Ho Chi Minh City. Prior versions queried a volatile Redis key without persistent storage or automated ingestion.

In Phase P0, a dedicated **Real-Time Hydrology Ingestion Pipeline** was developed and verified, featuring:
1. Two official HCMC hydrographic observation stations: **Trạm Phú An** (Sông Sài Gòn) and **Trạm Nhà Bè** (Sông Đồng Điền).
2. Strict vertical datum grounding to **Hải đồ Hòn Dấu (VN-2000)** with water levels in meters.
3. Official tidal warning thresholds under **Quyết định 18/2021/QĐ-TTg** (Báo động I: 1.40m, II: 1.50m, III: 1.60m).
4. PostgreSQL persistent storage in `hydrology_observations` and multi-tier Redis caching.
5. Automated quality provenance states (`OBSERVED_LIVE`, `OBSERVED_STALE`, `FORECAST`, `UNAVAILABLE`).
6. REST API suite (`/api/v1/hydrology/*`) and seamless backward compatibility with `weather_tide.py`.

---

## 2. Station Registry & Vertical Datum

| Metric / Attribute | Trạm Phú An (Bình Thạnh) | Trạm Nhà Bè (Nhà Bè) | Reference Standard |
| :--- | :--- | :--- | :--- |
| **Station ID** | `tram_phu_an` | `tram_nha_be` | Internal registry key |
| **River System** | Sông Sài Gòn | Sông Đồng Điền (Hợp lưu Đồng Nai) | Lưu vực sông Đồng Nai - Sài Gòn |
| **Latitude** | `10.793° N` | `10.655° N` | WGS-84 (EPSG:4326) |
| **Longitude** | `106.711° E` | `106.745° E` | WGS-84 (EPSG:4326) |
| **Vertical Datum** | Hòn Dấu (VN-2000) | Hòn Dấu (VN-2000) | Hệ mốc Quốc gia Hải đồ |
| **Báo động I (Chú ý)** | `1.40 m` | `1.40 m` | QĐ 18/2021/QĐ-TTg |
| **Báo động II (Cảnh báo)**| `1.50 m` | `1.50 m` | QĐ 18/2021/QĐ-TTg |
| **Báo động III (Nguy hiểm)**| `1.60 m` | `1.60 m` | QĐ 18/2021/QĐ-TTg |
| **Primary Source** | Đài Khí tượng Thủy văn Nam Bộ | Đài Khí tượng Thủy văn Nam Bộ | kttv-nb.gov.vn |

---

## 3. Data Flow & Provenance Architecture

```
   [Official Hydrological Bulletins / Telemetry Feed]
                         │
                         ▼
             [HydrologySourceAdapter]
       (Regex NLP parser & quality tagger)
                         │
                         ▼
            [HydrologyIngestionService]
            /                         \
           ▼                           ▼
[PostgreSQL: hydrology_observations]  [Redis Cache Layer]
 (Persistent Historical Records)       - hydrology:stations:latest
                                       - hydrology:station:{id}:latest
                                       - env:tide:verified_bulletin
                                       │
                                       ▼
                             [FastAPI REST APIs]
                               - /api/v1/hydrology/stations
                               - /api/v1/hydrology/latest
                               - /api/v1/hydrology/history
                               - /api/v1/weather-tide (Routing Engine)
```

### Provenance Quality Lifecycle:
- **`OBSERVED_LIVE`**: Telemetry observation verified within the last 6 hours (`age <= 21600s`).
- **`OBSERVED_STALE`**: Last verified observation between 6 and 48 hours old; alerts routing engine to exercise caution without fabricating synthetic tides.
- **`FORECAST`**: Future peak predictions published in official bulletin outlooks.
- **`UNAVAILABLE`**: Offline without valid observation records within 48 hours. Never defaults to 0.0m or fake sine waves.

---

## 4. API Endpoints Reference

### 1. Station Listing
- **Endpoint:** `GET /api/v1/hydrology/stations`
- **Output:** List of verified monitoring stations with GPS coordinates, river names, and alarm thresholds.

### 2. Latest Observations & Warning Status
- **Endpoint:** `GET /api/v1/hydrology/latest`
- **Output:**
```json
{
  "timestamp": "2026-10-24T06:22:45.123456Z",
  "quality_status": "OBSERVED_LIVE",
  "max_alarm_level": 2,
  "is_flood_warning": true,
  "stations": [
    {
      "station_id": "tram_phu_an",
      "station_name": "Trạm Phú An",
      "river_name": "Sông Sài Gòn",
      "water_level_m": 1.52,
      "alarm_level": 2,
      "alarm_description": "Báo động II (Cảnh báo - Ngập các vùng trũng thấp ven sông)",
      "vertical_datum": "Hòn Dấu (VN-2000)",
      "observed_at": "2026-10-24T06:00:00Z",
      "quality_status": "OBSERVED_LIVE",
      "is_flood_warning": true
    }
  ]
}
```

### 3. Historical Station Observations
- **Endpoint:** `GET /api/v1/hydrology/history?station_id=tram_phu_an&limit=24`
- **Output:** Time-series array of historical water level measurements.

### 4. Bulletin Ingestion Trigger
- **Endpoint:** `POST /api/v1/hydrology/ingest`
- **Payload:** `{"bulletin_text": "Mực nước đỉnh triều tại trạm Phú An đạt 1.58m..."}`
- **Output:** Ingested observations saved to PostgreSQL and Redis.

---

## 5. Automated Test Verification

Execution results from `backend/tests/test_hydrology_ingestion.py`:
- `test_hydrology_station_registry` — **PASSED** (coordinates, rivers, datum verified).
- `test_alarm_level_thresholds` — **PASSED** (0, 1, 2, 3 alarm transitions verified).
- `test_quality_status_assessment` — **PASSED** (LIVE, STALE, FORECAST, UNAVAILABLE).
- `test_bulletin_text_parser` — **PASSED** (Vietnamese bulletin regex NLP parser).
- `test_hydrology_persistence_and_cache` — **PASSED** (PostgreSQL insert + Redis cache + `weather_tide` signal check).
- `test_hydrology_api_endpoints` — **PASSED** (all HTTP routes 200 OK).

