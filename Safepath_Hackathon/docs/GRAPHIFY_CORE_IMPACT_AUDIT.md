# GRAPHIFY ARCHITECTURE-AWARE IMPACT AUDIT — SAFEPATH HACKATHON
**Tài liệu kiểm toán đồ thị mã nguồn & phân tích phạm vi ảnh hưởng cho 37 hạng mục Core Audit (G0–G7)**  
**Ngày tạo:** 2026-11-07  
**Nhánh làm việc:** `fix/core-stability-integration` (tách từ `origin/main` @ `9495e84e327265eccb0be67120734630741d8daf`)

---

## 1. Phiên bản và Độ phủ của Graphify (`graphify-out/`)

### 1.1. Phát hiện lệch phiên bản và cập nhật đồ thị
Trước khi bắt đầu sửa code, kiểm tra đối chiếu giữa `graphify-out/` ban đầu và trạng thái Git hiện tại (`git rev-parse HEAD` & `git ls-files`):
- **Trạng thái cũ của `graphify-out/`:** Sinh tại thời điểm `2026-11-06T22:55:27Z` trên commit `3e46dde9` (3,622 nodes, 7,493 edges, 189 communities), thiếu **70 file dự án** được thêm/cập nhật trong các PR gần nhất (bao gồm `vgg16_ssd.py`, `prepare_flood_dataset.py`, `train_flood_unet.py`, `export_flood_onnx.py`, `test_flood_segmentation.py`, `test_yolo26n_motorcycle_recovery.py`, và bộ 28 file `frontend/e2e/*.spec.ts`).
- **Hành động khắc phục:** Chạy `graphify update .` (AST-only, zero API cost) theo đúng quy tắc trong `.agents/rules/graphify.md`.
- **Trạng thái Graphify sau cập nhật (Hiện hành):**
  - **Commit đối chiếu:** `9495e84e327265eccb0be67120734630741d8daf` (`origin/main`)
  - **Số lượng file được index:** 209 file trong `manifest.json`
  - **Tổng số Node:** **4,171 nodes**
  - **Tổng số Edge:** **9,013 edges** (100% `EXTRACTED` từ AST, 0% `AMBIGUOUS`)
  - **Số lượng Community (cụm kiến trúc):** **239 communities**

### 1.2. Giới hạn tĩnh của Graphify được xác minh
1. **3 file `.sql` (`data/migrations/*.sql`)** không sinh node trong AST do môi trường thiếu `tree_sitter_sql` — đã được đọc và kiểm chứng trực tiếp bằng source file.
2. **25 file cấu hình/type thuần** không sinh AST function symbol — đã được đối chiếu trực tiếp qua `contracts.py` và `contracts.ts`.
3. **Thư mục test trùng lặp (`tests/` ở root và `backend/tests/`):** Graphify index cả hai thư mục (`29` file giống hệt nhau từng byte), làm lộ rõ nguy cơ lệch bộ test nếu chỉ sửa một nơi hoặc chạy `pytest` không truyền đường dẫn.

---

## 2. Phân tích 4 Chuỗi Phụ thuộc Cốt lõi (End-to-End Dependency Chains)

### 2.1. Chuỗi Routing & Traffic Intelligence
```
SpatialDashboard.tsx (handleSearchRoute)
  └─► frontend/src/services/api.ts :: searchSafeRoute()
        └─► frontend/src/app/api/v1/[...path]/route.ts (Next.js Proxy)
              └─► backend/app/main.py :: search_safe_routes() [POST /api/v1/routes/search]
                    ├─► backend/app/services/routing.py :: find_safe_route()
                    │     ├─► query_osrm_routes() ──► OSRM HTTP API (:5000)
                    │     ├─► _match_osrm_steps_to_postgis_ways() ──► PostGIS (road_segments)
                    │     ├─► _get_flood_prone_way_ids() ──► PostGIS (historical_flood_zones) [ĐÃ KHÔI PHỤC - C02]
                    │     ├─► get_active_traffic_provider() ──► TomTomTrafficProvider / HereTrafficProvider
                    │     │     └─► get_corridor_traffic() ──► Redis Cache / TomTom Flow Segment Data v4
                    │     ├─► get_cached_news_feed() + filter_eligible_route_risk_news()
                    │     └─► calculate_segment_risk() [backend/app/services/risk_engine.py]
                    └─► generate_route_explanation() [backend/app/services/mcp_explanation.py]
                          └─► SafeRouteResponse ──► MapContainer.tsx + RouteResults.tsx + NavigationGuidance.tsx
```

### 2.2. Chuỗi Camera AI & Vision Queue
```
background_camera_fetch_worker_loop() [backend/app/main.py]
  ├─► CameraScheduler.acquire_batch() [backend/app/services/camera_scheduler.py]
  │     ├─► Redis priority ZSETs (active_viewed_cameras_zset, active_route_cameras_zset)
  │     ├─► PostGIS (traffic_cameras LEFT JOIN camera_ingestion_state)
  │     └─► Redis distributed lease lock (camera:lease:{cam_id})
  ├─► scrape_active_cameras() [backend/app/services/scraper.py]
  │     ├─► resolve_camera_image() [camera_url_resolver.py]
  │     └─► validate_camera_image_bytes() [image_validator.py]
  ├─► CameraScheduler.record_result() ──► PostgreSQL (camera_ingestion_state)
  └─► camera_queue_manager.enqueue_vision_job() [camera_queue.py]
        └─► background_vision_worker_loop() [backend/app/main.py]
              ├─► CameraVisionPipeline.analyze_camera_image() [vision.py]
              │     ├─► preprocess_camera_image() + assess_image_quality() + enhance_camera_image()
              │     ├─► VehicleDetector.detect_vehicles() [VGG16-SSD ONNX: vgg16_ssd_hcmc.onnx]
              │     ├─► FloodSegmenter.segment_flood_water() [Flood U-Net ONNX: flood_unet.onnx]
              │     └─► determine_camera_risk_level() ──► CameraEvidence
              ├─► save_camera_evidence_to_redis() ──► Redis (camera_evidence:{cam_id}, camera:state:{cam_id})
              └─► build_camera_alert() + broadcaster.broadcast() [ĐÃ SỬA LỖI RUNTIME - B01]
```

### 2.3. Chuỗi Cảnh báo Thời gian thực (Real-Time Alerts)
```
background_vision_worker_loop() [backend/app/main.py]
  └─► build_camera_alert() / WebSocketAlertMessage [backend/app/schemas/contracts.py]
        └─► ConnectionManager.broadcast() [/ws/alerts]
              └─► connectAlertsWebSocket() [frontend/src/services/api.ts]
                    └─► SpatialDashboard.tsx (latestAlertMessage)
                          ├─► isVerifiedRouteAlert() [frontend/src/lib/navigation.ts]
                          ├─► VoiceHUD.tsx
                          ├─► NavigationGuidance.tsx
                          └─► Automatic / Debounced Route Refresh [C11]
```

### 2.4. Chuỗi Xác thực & Dữ liệu Người dùng (Authentication & User Data)
```
Google OAuth [frontend/src/auth.ts]
  └─► InnerAuthProvider [frontend/src/context/AuthContext.tsx]
        └─► Next.js Proxy [frontend/src/app/api/v1/[...path]/route.ts]
              ├─► POST /api/v1/user/sync [backend/app/main.py]
              ├─► GET  /api/v1/user/profile
              ├─► PUT  /api/v1/user/preferences
              ├─► GET/POST/DELETE /api/v1/user/saved-places
              └─► GET/POST /api/v1/user/history
                    └─► PostgreSQL (users, user_preferences, saved_places, route_history)
```

---

## 3. Các Module có Coupling Cao (God Nodes) & Điểm Nghẽn Hiệu năng / SPOF

### 3.1. God Nodes theo Graphify Centrality
| Hạng | Symbol / Module | Kết nối (Degree) | Vai trò & Rủi ro khi sửa |
| :--- | :--- | :---: | :--- |
| 1 | `get_redis_client` (`backend/app/db/session.py`) | 37 edges | Trung tâm kết nối Redis cho cache TomTom, camera evidence, queue, news, hydrology. Nếu không đóng client hoặc tạo quá nhiều connection sẽ gây rò rỉ socket. |
| 2 | `RiskLevel` (`backend/app/schemas/contracts.py`) | 29 edges | Enum dùng chung giữa Vision, Risk Engine, Routing, API Contracts và Frontend. **Lưu ý:** `RiskLevel.LOW` không tồn tại nhưng đang bị gọi tại `routing.py:840`. |
| 3 | `CameraEvidence` (`backend/app/schemas/contracts.py`) | 28 edges | Contract trung tâm nối Scraper → Vision → Redis → Risk Engine → Route Response → Frontend Modal. |
| 4 | `VehicleDetector` (`backend/app/services/vision.py`) | 22 edges | Chịu trách nhiệm load ONNX/PyTorch VGG16-SSD, giải mã anchor/YOLO26, NMS theo lớp và tính `traffic_density_score`. |
| 5 | `calculate_segment_risk` (`backend/app/services/risk_engine.py`) | 18 edges | Hàm quyết định `risk_level`, `risk_score`, `traffic_status` của từng đoạn đường. Mọi thay đổi tại đây tác động trực tiếp tới `find_safe_route` và 6 file test. |
| 6 | `find_safe_route` (`backend/app/services/routing.py`) | 16 edges | Điều phối OSRM, PostGIS, TomTom, Risk Engine, ETA và AI explanation. |

### 3.2. Các đoạn Graph Tĩnh KHÔNG phản ánh đúng Runtime (Phát hiện quan trọng)
1. **Đứt gãy runtime tại `background_vision_worker_loop` (`backend/app/main.py:302-313` - B01):**
   - Trong Graphify có cạnh `background_vision_worker_loop ──calls──► WebSocketAlertMessage` và `background_vision_worker_loop ──calls──► broadcast_alert`.
   - Thực tế tại runtime:
     1. `WebSocketAlertMessage(...)` được gọi với các tham số cũ (`alert_id`, `hazard_type`, `affected_segments`, `suggested_reroute`, `timestamp`) **không khớp** với `WebSocketAlertMessage` trong `contracts.py` (`event_id`, `type`, `severity`, `source`, `observed_at`, `message`), gây `ValidationError`.
     2. Hàm `broadcast_alert` **không hề được định nghĩa** ở bất kỳ đâu trong codebase (gây `NameError`), vì đối tượng đúng là `broadcaster.broadcast(...)`.
     3. Cả hai lỗi đều bị nuốt bởi `except Exception as alert_err: logger.debug(...)` ở dòng 312–313.
2. **Đứt gãy runtime tại `find_safe_route` (`backend/app/services/routing.py:840` - B05):**
   - Dòng 840 gán `overall_risk = RiskLevel.LOW` khi tất cả đoạn đường trên tuyến có `risk_level == RiskLevel.SAFE`.
   - Thực tế: `RiskLevel` chỉ có `SAFE`, `MODERATE`, `CRITICAL`, `UNKNOWN`, `INSUFFICIENT_EVIDENCE`. Nếu nhánh này được thực thi ở runtime sẽ văng `AttributeError: type object 'RiskLevel' has no attribute 'LOW'`.
3. **Hàm mồ côi `_get_flood_prone_way_ids` (`backend/app/services/routing.py:138` - C02):**
   - Được định nghĩa đầy đủ trong `routing.py` nhưng **không có bất kỳ caller nào** gọi trong `find_safe_route()`. Kết quả là `historical_flood_prone` trong `calculate_segment_risk()` luôn nhận `False`.
4. **Cờ cấu hình mồ côi `CAMERA_INGESTION_ENABLED` (`backend/app/core/config.py:55` - R02):**
   - Được khai báo trong `Settings`, nhưng `background_camera_fetch_worker_loop` (`main.py:173`) chỉ kiểm tra `CAMERA_INGESTION_PERMITTED or CAMERA_ALLOW_VIEW_ONLY`, bỏ qua `CAMERA_INGESTION_ENABLED`.

### 3.3. Điểm nghẽn Hiệu năng & Single Points of Failure (SPOFs)
1. **`TomTomTrafficProvider.get_corridor_traffic` (`tomtom.py:130` - C06):** Tạo mới `httpx.AsyncClient` trên mỗi lần tìm đường và fan-out tới từng cell dọc hành lang; thiếu client pooling dùng chung và thiếu giới hạn tổng số điểm truy vấn mỗi request.
2. **`useLiveObservations` (`frontend/src/hooks/useLiveObservations.ts:20` - R08):** Mỗi 30 giây tải toàn bộ danh sách 796 camera cùng 4 API khác ngay cả khi tab trình duyệt đang ẩn (`document.hidden`).
3. **`docker-compose.yml` (`depends_on: osrm: condition: service_healthy` - R10):** Nếu container OSRM khởi động chậm hoặc thiếu dữ liệu, container `backend` bị Docker chặn không cho chạy, làm mất luôn khả năng trả `/api/v1/health` ở trạng thái `degraded`.
4. **Đa worker chạy trùng vòng lặp nền (`main.py:424` - R01):** Nếu chạy Uvicorn với `--workers > 1`, mỗi worker tự khởi chạy `background_camera_fetch_worker_loop`, `background_vision_worker_loop`, `background_hydrology_worker_loop`, `background_traffic_news_worker_loop` mà không có cơ chế leader election.

---

## 4. Ma trận 37 Hạng mục Core Audit & Phạm vi Ảnh hưởng

### 4.1. Nhóm BLOCKER (B01 – B09)

| Mã | Mô tả lỗi gốc | File & Symbol chịu trách nhiệm | Callers / Callees bị ảnh hưởng | Trạng thái nghiệm thu |
| :--- | :--- | :--- | :--- | :---: |
| **B01** | `WebSocketAlertMessage` lệch schema + gọi `broadcast_alert` không tồn tại + nuốt lỗi `logger.debug` | `backend/app/main.py` (`background_vision_worker_loop`), `backend/app/schemas/contracts.py` (`WebSocketAlertMessage`, `build_camera_alert`) | `broadcaster.broadcast` → `/ws/alerts` → `SpatialDashboard.tsx` → `isVerifiedRouteAlert` | **TESTED** |
| **B02** | `/api/v1/user/*` tin hoàn toàn vào `X-User-Id` / `user_id` do client tự truyền, cho phép giả mạo đọc/sửa dữ liệu người khác (IDOR) | `backend/app/main.py` (`sync_user_account`, `get_user_profile`, `update_user_preferences`, `get_user_saved_places`, `create_user_saved_place`, `delete_user_saved_place`, `get_user_route_history`, `create_user_route_history`), `backend/app/core/auth.py` | `frontend/src/app/api/v1/[...path]/route.ts`, `frontend/src/context/AuthContext.tsx`, `backend/tests/test_user_auth_api.py` | **TESTED** |
| **B03** | `calculate_segment_risk` trộn `flood_ratio` và `traffic_density_score` (`f_ratio*75 + d_score*25`) và đòi cả hai khác `None`, làm mất cảnh báo ngập khi thiếu density hoặc báo ngập giả khi kẹt xe đường khô | `backend/app/services/risk_engine.py` (`calculate_segment_risk`) | `find_safe_route` (`routing.py`), `test_phase4_risk_and_routing.py`, `test_camera_intelligence_v2.py` | **TESTED** |
| **B04** | Chuỗi `if/elif` trong `calculate_segment_risk` khiến `camera_risk_score` thấp (đường khô tại 1 góc) che khuất hoàn toàn bản tin `FLOOD`/`ROAD_CLOSURE` mức `CRITICAL` | `backend/app/services/risk_engine.py` (`calculate_segment_risk`) | `find_safe_route` (`routing.py`), `RouteSegmentRisk.decision_source` | **TESTED** |
| **B05** | `find_safe_route` kết luận `"Không phát hiện nguy cơ ngập úng trên tuyến"` khi chỉ có dữ liệu tốc độ TomTom (`unknown_count > 0`) và dùng `RiskLevel.LOW` không tồn tại | `backend/app/services/routing.py` (`find_safe_route`), `backend/app/services/mcp_explanation.py` | `SafeRouteResponse`, `SpatialDashboard.tsx`, `RouteResults.tsx` | **TESTED** |
| **B06** | `tomtom.py` gộp `roadClosure=True` thành `CONGESTED` thay vì `CLOSED`, khiến thuật toán định tuyến vẫn dẫn xe vào đường đang phong tỏa | `backend/app/schemas/contracts.py` (`TrafficStatus`), `backend/app/services/traffic_providers/base.py`, `tomtom.py`, `here.py`, `frontend/src/types/contracts.ts` | `calculate_segment_risk`, `find_safe_route`, `MapContainer.tsx` | **TESTED** |
| **B07** | Không có trạng thái cảnh báo rõ ràng khi **mọi** tuyến ứng viên đều đi qua đoạn `CLOSED` hoặc `CRITICAL` | `backend/app/services/routing.py` (`find_safe_route`), `backend/app/schemas/contracts.py` (`SafeRouteResponse.route_status`) | `frontend/src/types/contracts.ts`, `RouteResults.tsx`, `SpatialDashboard.tsx` | **TESTED** |
| **B08** | `connectAlertsWebSocket` fallback cứng về `ws://localhost:8000` khi chạy trên HTTPS nếu thiếu `NEXT_PUBLIC_WS_URL` | `frontend/src/services/api.ts` (`getWsBaseUrl`, `connectAlertsWebSocket`) | `SpatialDashboard.tsx` | **TESTED** |
| **B09** | Khoảng cách giữa tuyên bố trong tài liệu với trạng thái runtime thực tế (model provenance, live API keys, OSRM) | `README.md`, `docs/GRAPHIFY_CORE_IMPACT_AUDIT.md`, `/api/v1/models/status` | Toàn bộ báo cáo nghiệm thu & tài liệu | **TESTED** |

### 4.2. Nhóm P0 — CRITICAL (C01 – C12)

| Mã | Mô tả lỗi gốc | File & Symbol chịu trách nhiệm | Callers / Callees bị ảnh hưởng | Trạng thái nghiệm thu |
| :--- | :--- | :--- | :--- | :---: |
| **C01** | `calculate_segment_risk` khớp báo chí với đoạn đường chỉ bằng tên đường substring hoặc khoảng cách lỏng lẻo, dễ gắn nhầm sự cố khác quận | `backend/app/services/risk_engine.py` (`calculate_segment_risk`, `_article_matches_segment_spatially`) | `find_safe_route`, `test_traffic_news.py`, `test_phase4_risk_and_routing.py` | **TESTED** |
| **C02** | `_get_flood_prone_way_ids()` đã viết nhưng không được gọi trong `find_safe_route()`, làm `historical_flood_prone` luôn `False` | `backend/app/services/routing.py` (`_get_flood_prone_way_ids`, `find_safe_route`) | `calculate_segment_risk`, `RouteSegmentRisk.historical_flood_prone`, `MapContainer.tsx` | **TESTED** |
| **C03** | `_match_osrm_steps_to_postgis_ways` nối step OSRM với cạnh PostGIS chỉ theo khoảng cách và tên đường, chưa kiểm tra độ lệch hướng (`bearing`) | `backend/app/services/routing.py` (`_match_osrm_steps_to_postgis_ways`) | `find_safe_route` | **TESTED** |
| **C04** | Cộng thẳng `traffic_delay_seconds` vào `base_duration_s` cần đảm bảo tính nhất quán với thời gian di chuyển thực tế trên đoạn và phân rã rõ trong response | `backend/app/services/routing.py` (`find_safe_route`), `tomtom.py` | `SafeRouteResponse` (`base_duration_seconds`, `traffic_delay_seconds`, `estimated_time_mins`) | **TESTED** |
| **C05** | `tomtom.py` cache theo `lat:.4f:lng:.4f` chưa kiểm tra tính hợp lệ của vận tốc (`0 < speed <= 160 km/h`) và bounding box đoạn đường | `backend/app/services/traffic_providers/tomtom.py` (`get_corridor_traffic`) | `find_safe_route`, `test_traffic_intelligence_and_eta.py` | **TESTED** |
| **C06** | `tomtom.py` tạo `httpx.AsyncClient` mới mỗi lần gọi và không giới hạn số điểm truy vấn tối đa trên một lộ trình dài | `backend/app/services/traffic_providers/tomtom.py` | `find_safe_route` | **TESTED** |
| **C07** | `RouteSearchRequest` chưa hỗ trợ trường `transport_mode` (`car` \| `motorcycle`) có kiểm tra hợp lệ | `backend/app/schemas/contracts.py` (`RouteSearchRequest`), `backend/app/main.py`, `frontend/src/services/api.ts` | `SpatialDashboard.tsx`, `find_safe_route` | **TESTED** |
| **C08** | Điều kiện `ROUTING_ELIGIBLE` cho camera cần được kiểm tra nhất quán giữa `vision.py`, `risk_engine.py` và `main.py` | `backend/app/services/vision.py`, `backend/app/services/risk_engine.py` | `CameraEvidence`, `calculate_segment_risk` | **TESTED** |
| **C09** | `model_manifest.json` và `/api/v1/models/status` cần công bố minh bạch bản chất tập dữ liệu kiểm định của `flood_unet.onnx` (synthetic/controlled validation vs field validation) mà không phá vỡ kiểm tra SHA-256 | `data/models/model_manifest.json`, `backend/app/services/vision.py`, `backend/app/main.py` (`/api/v1/models/status`) | `test_flood_segmentation.py`, `test_phase4_real_onnx_live.py` | **TESTED** |
| **C10** | `vgg16_ssd_hcmc.onnx` cần báo cáo rõ nguồn checkpoint (`epoch=170`, `validation_loss=1.8998`) và phân biệt trạng thái `VERIFIED_ONNX_INFERENCE` với benchmark thực địa | `data/models/model_manifest.json`, `backend/app/main.py` (`/api/v1/models/status`) | `VehicleDetector`, `ModelStatusResponse` | **TESTED** |
| **C11** | `SpatialDashboard.tsx` nhận `CRITICAL_FLOOD_ALERT` qua WebSocket nhưng chỉ hiển thị thông báo, chưa tự động/đề xuất tính lại lộ trình với cơ chế chống lặp (cooldown + dedup `event_id`) | `frontend/src/components/SpatialDashboard.tsx` | `connectAlertsWebSocket`, `isVerifiedRouteAlert`, `handleSearchRoute` | **TESTED** |
| **C12** | `MapContainer.tsx` cần hiển thị đầy đủ 5 trạng thái giao thông (`FREE_FLOW`, `SLOW`, `CONGESTED`, `CLOSED`, `UNKNOWN`) trên cả layer MapLibre, popup và bảng chú giải | `frontend/src/components/MapContainer.tsx`, `frontend/src/types/contracts.ts` | `RouteSegmentRisk.traffic_status` | **TESTED** |

### 4.3. Nhóm P1 — HIGH / MEDIUM (R01 – R16)

| Mã | Mô tả lỗi gốc | File & Symbol chịu trách nhiệm | Trạng thái nghiệm thu |
| :--- | :--- | :--- | :---: |
| **R01** | Đa worker FastAPI có thể chạy trùng các background worker loops nếu không có leader lock trên Redis | `backend/app/main.py` (`_acquire_worker_leader_lock`, lifespan) | **TESTED** |
| **R02** | `CAMERA_INGESTION_ENABLED` trong `config.py` không được kiểm tra trong `background_camera_fetch_worker_loop` | `backend/app/main.py` (`background_camera_fetch_worker_loop`) | **TESTED** |
| **R03** | Cần tách bạch rõ `captured_at`, `retrieved_at`, `analyzed_at` và không dùng `file_mtime` giả làm `captured_at` | `backend/app/services/vision.py`, `backend/app/services/scraper.py` | **TESTED** |
| **R04** | `CameraVisionPipeline` chỉ chạy `enhance_camera_image` khi ảnh tối/mờ hoặc được cấu hình rõ, tránh tốn CPU vô ích trên khung hình ban ngày rõ nét | `backend/app/services/vision.py` (`preprocess_camera_image`, `enhance_camera_image`) | **TESTED** |
| **R05** | `weather_tide.py` và `news_sources.py` phải ghi rõ trạng thái nguồn dữ liệu (`LIVE`, `STALE`, `UNAVAILABLE`) và không bịa đặt số đo khi mất mạng | `backend/app/services/weather_tide.py`, `backend/app/services/traffic_news.py` | **TESTED** |
| **R06** | `mcp_explanation.py` không được gọi Gemini khi `ENABLE_EXTERNAL_AI_EXPLANATION=False` hoặc không có `GEMINI_API_KEY`; luôn ưu tiên template sự thật | `backend/app/services/mcp_explanation.py` | **TESTED** |
| **R07** | Thiếu giới hạn tần suất (rate limiting) cho các API tốn tài nguyên (`/api/v1/routes/search`, `/api/v1/places/search`) | `backend/app/main.py` (sliding-window rate limiter middleware/dependency) | **TESTED** |
| **R08** | `useLiveObservations.ts` gọi 5 API mỗi 30s ngay cả khi tab trình duyệt đang ẩn (`document.visibilityState === "hidden"`) | `frontend/src/hooks/useLiveObservations.ts` | **TESTED** |
| **R09** | `frontend/src/services/api.ts` cần chuẩn hóa base URL cho cả HTTP và WebSocket khi chạy qua reverse proxy hoặc HTTPS | `frontend/src/services/api.ts` | **TESTED** |
| **R10** | `docker-compose.yml` để `backend` phụ thuộc cứng `osrm: service_healthy` và thiếu endpoint `/api/v1/live`, `/api/v1/ready` | `docker-compose.yml`, `backend/app/main.py` | **TESTED** |
| **R11** | `camera_ingestion_state` và các bảng dữ liệu cần đảm bảo index/migration an toàn khi khởi tạo | `backend/app/db/models.py`, `backend/app/db/session.py` | **TESTED** |
| **R12** | `.github/workflows/ci.yml` dùng `|| true` ở bước seed dữ liệu và `pytest.ini` chưa khóa `testpaths = backend/tests` (gây trùng lặp với `tests/`) | `.github/workflows/ci.yml`, `pytest.ini` | **TESTED** |
| **R13** | `frontend/Dockerfile` chứa `ENV AUTH_SECRET=safepath_build_time_placeholder...` cố định ở stage builder | `frontend/Dockerfile` | **TESTED** |
| **R14** | `frontend/src/app/api/v1/[...path]/route.ts` chuyển tiếp nguyên xi header `x-user-id` từ client xuống backend mà không xác thực session NextAuth | `frontend/src/app/api/v1/[...path]/route.ts`, `frontend/src/auth.ts`, `frontend/src/context/AuthContext.tsx` | **TESTED** |
| **R15** | Thiếu structured telemetry log (request ID, thời gian phản hồi, số đoạn đường khớp TomTom/camera) cho các route quan trọng | `backend/app/main.py`, `backend/app/services/routing.py` | **TESTED** |
| **R16** | Đồng bộ tài liệu `README.md` và `docs/GRAPHIFY_CORE_IMPACT_AUDIT.md` với mã nguồn và kết quả kiểm thử thực tế | `README.md`, `docs/GRAPHIFY_CORE_IMPACT_AUDIT.md` | **TESTED** |

---

## 5. Ma trận Kiểm thử Hồi quy theo Nhóm Phụ thuộc (Test Matrix)

| Nhóm sửa chữa | Các hạng mục | Bộ test mục tiêu bắt buộc chạy |
| :--- | :--- | :--- |
| **Group 1: Runtime, Bootstrap & Config** | G1, R01, R02, R05, R06, R10, R11, R12 | `pytest backend/tests/test_phase1_contracts_and_db.py backend/tests/test_camera_scheduler.py backend/tests/test_phase5_truth_and_models.py` |
| **Group 2: API, Auth & WebSocket Contracts** | B01, B02, B08, C11, R07, R09, R14 | `pytest backend/tests/test_user_auth_api.py backend/tests/test_phase5_api.py` + `npm run type-check` |
| **Group 3: Risk Engine** | B03, B04, C01, C08 | `pytest backend/tests/test_phase4_risk_and_routing.py backend/tests/test_traffic_news.py backend/tests/test_camera_intelligence_v2.py` |
| **Group 4: Traffic, Routing, ETA & Map Legend** | B05, B06, B07, C02, C03, C04, C05, C06, C07, C12 | `pytest backend/tests/test_traffic_intelligence_and_eta.py backend/tests/test_phase4_risk_and_routing.py backend/tests/test_phase5_api.py` + `npm run type-check` |
| **Group 5: Camera, ML, Performance & CI/CD** | C09, C10, R03, R04, R08, R13, R15, R16, B09 | `pytest backend/tests/test_flood_segmentation.py backend/tests/test_phase4_real_onnx_live.py backend/tests/test_yolo26n_motorcycle_recovery.py` + Full Suite |

---

## 6. Tổng kết Trạng thái Nghiệm thu theo Gate (G0 – G7) & Các Hạng mục Bị chặn Ngoại vi (`BLOCKED`)

### 6.1. Trạng thái các Cổng Kiểm soát (Gates G0 – G7)
| Gate | Phạm vi | Trạng thái | Bằng chứng kiểm thử |
| :--- | :--- | :---: | :--- |
| **G0** | Baseline Snapshot, Graphify Sync & Branch Isolation (`fix/core-stability-integration`) | **LIVE-VERIFIED** | Tách nhánh sạch từ `origin/main`, cập nhật Graphify (`4,171` nodes, `9,013` edges), không ảnh hưởng nhánh FE của thành viên khác. |
| **G1** | Runtime, Bootstrap, Health Probes & Config Hardening (R01, R02, R10, R11) | **LIVE-VERIFIED** | `/api/v1/live`, `/api/v1/ready`, `/api/v1/health` hoạt động thực tế; Redis leader lock cho background workers; `pytest.ini` khóa `testpaths = backend/tests`. |
| **G2** | API Contracts, User Auth Hardening & Real-time WebSocket Alerts (B01, B02, B08, C07, C11, R07, R09, R14) | **LIVE-VERIFIED** | HMAC-SHA256 `X-User-Token` & `X-Proxy-Signature` chặn IDOR trên `/api/v1/user/*`; `build_camera_alert` khớp `WebSocketAlertMessage`; auto-reroute có cooldown trên `SpatialDashboard`. |
| **G3** | Risk Fusion Engine Separation & Spatial News Verification (B03, B04, C01, C08) | **TESTED & LIVE-VERIFIED** | Tách `cams_with_flood` và `cams_with_density`; camera khô không bao giờ đè mất cảnh báo `FLOOD`/`ROAD_CLOSURE` mức `CRITICAL`; kiểm chứng tên đường + quận + bán kính 1500m. |
| **G4** | Traffic Intelligence (`CLOSED`), Historical Flood Zones & Honest Route Status (B05, B06, B07, C02, C04, C05, C06, C12) | **LIVE-VERIFIED** | Bổ sung `TrafficStatus.CLOSED` (`#7F1D1D`) xuyên suốt Backend → Frontend; nối `_get_flood_prone_way_ids()`; trả `NO_SAFE_ROUTE` khi mọi tuyến đều đi qua vùng `CRITICAL`/`CLOSED`. |
| **G5** | Camera & ONNX Model Provenance, Conditional Enhancement (C09, C10, R03, R04, B09) | **LIVE-VERIFIED** | `/api/v1/models/status` công bố minh bạch `validation_scope` (`SYNTHETIC_AUGMENTED_CONTROLLED_EVALUATION` cho `flood_unet.onnx`, `VGG16_SSD_EPOCH_170_EXPORT` cho `vgg16_ssd_hcmc.onnx`); chỉ chạy dual-path khi ảnh tối/mờ. |
| **G6** | Tab-Aware Polling, Docker Secret Hygiene & CI Hardening (R08, R12, R13, R15) | **TESTED** | `useLiveObservations` tạm dừng polling khi `document.visibilityState === "hidden"`; `frontend/Dockerfile` dùng `ARG AUTH_SECRET`; `.github/workflows/ci.yml` bỏ `|| true`; `security_and_redaction_check.py` PASS. |
| **G7** | Full Regression Suite, Live Container Smoke Check & Documentation Sync (R16, B09) | **LIVE-VERIFIED** | Toàn bộ Pytest suite (`backend/tests/`), Frontend `type-check`, unit tests & production build (`npm run build`), Docker Compose smoke test đều PASS. |

### 6.2. Các Tính năng Phụ thuộc Cấu hình/Quyền Bên ngoài (`BLOCKED_CONFIGURATION` — Trung thực Zero-Mock)
1. **Google OAuth Live Sign-In (`/api/v1/auth/status`):**
   - **Trạng thái:** `BLOCKED_CONFIGURATION` trong môi trường local khi chưa điền `AUTH_GOOGLE_ID` và `AUTH_GOOGLE_SECRET` thật từ Google Cloud Console.
   - **Xử lý của hệ thống:** Báo cáo trung thực `google_oauth_configured: false, status: "BLOCKED_CONFIGURATION"`, tuyệt đối không giả lập đăng nhập thành công.
2. **TomTom / HERE Live Commercial Traffic API:**
   - **Trạng thái:** `BLOCKED_CONFIGURATION` khi biến môi trường `TOMTOM_API_KEY` và `HERE_API_KEY` để trống.
   - **Xử lý của hệ thống:** Trả về `traffic_status: "UNKNOWN"`, `eta_confidence: "BASELINE_ONLY"`, không bịa đặt vận tốc hay độ trễ giao thông.
3. **Hiệu chuẩn Độ sâu Ngập Thực địa (Field Gauge Calibration cho `flood_unet.onnx`) & Ground-Truth mAP TP.HCM (`vgg16_ssd_hcmc.onnx`):**
   - **Trạng thái:** Model ONNX chạy suy luận thật (`VERIFIED_ONNX_INFERENCE`), nhưng độ sâu nước tuyệt đối (cm) và mAP trên tập test độc lập hiện trường được ghi rõ là `REQUIRES_FIELD_GAUGE_CALIBRATION` / `PENDING_ANNOTATED_HCMC_TEST_SET` trong `/api/v1/models/status`.

