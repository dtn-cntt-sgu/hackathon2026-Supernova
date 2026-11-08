# BẰNG CHỨNG NGHIỆM THU THỰC NGHIỆM (ACCEPTANCE EVIDENCE MANIFEST)

Tài liệu này tổng hợp toàn bộ bằng chứng khách quan, nhật ký thực thi câu lệnh và kết quả đo kiểm trên hệ thống thực tế theo đúng cam kết **Zero-Mock in Runtime**.

---

## 1. Trạng thái Vận hành Hạ tầng Container (Docker Compose)

Lệnh kiểm tra: `docker compose ps`

```
NAME                    IMAGE                               COMMAND                  SERVICE   CREATED       STATUS                 PORTS
safepath_osrm           ghcr.io/project-osrm/osrm-backend   "osrm-routed --algor…"   osrm      3 hours ago   Up 3 hours (healthy)   0.0.0.0:5001->5000/tcp
safepath_postgis        postgis/postgis:16-3.4              "docker-entrypoint.s…"   postgis   3 hours ago   Up 3 hours (healthy)   0.0.0.0:5432->5432/tcp
safepath_redis          redis:7-alpine                      "docker-entrypoint.s…"   redis     3 hours ago   Up 3 hours (healthy)   0.0.0.0:6379->6379/tcp
```

Kiểm tra số lượng bản ghi PostGIS:
```
- Bảng road_segments: 343.610 bản ghi OSM Way (SRID 4326)
- Bảng road_edges: 1.858.355 bản ghi cạnh cặp đỉnh (SRID 4326)
- Bảng traffic_cameras: 796 camera đăng ký danh mục
- Bảng historical_flood_points: 13 điểm ngập chính thức từ Sở Xây Dựng
```

---

## 2. Kết quả Đo kiểm Hiệu năng Thực tế (k6 Concurrency Load Test)

Lệnh kiểm tra: `k6 run load_tests/k6_route_search.js`

- **Thời gian chạy**: 30 giây liên tục.
- **Tải đồng thời**: **30 Virtual Users (VUs)**.
- **Kịch bản**: 4 cặp tọa độ huyết mạch phân bố đều trên địa bàn TP.HCM:
  1. Chợ Bến Thành (Quận 1) ↔ Ngã tư Hàng Xanh (Bình Thạnh)
  2. Landmark 81 (Bình Thạnh) ↔ Sân bay Tân Sơn Nhất (Tân Bình)
  3. Nhà thờ Đức Bà (Quận 1) ↔ Đường Nguyễn Hữu Cảnh (Bình Thạnh)
  4. Phú Mỹ Hưng (Quận 7) ↔ Chợ Bến Thành (Quận 1)

### Chỉ số Đo lường Thực nghiệm Thực tế:

| Chỉ số Đo kiểm (Metric) | Kết quả Đo thực | Đánh giá Khách quan |
|---|---|---|
| **Tổng số lượt tìm tuyến (Total Requests)** | **421 requests** | Tương đương 13.43 requests/giây |
| **Số lượt thành công (Successful Searches)** | **411 requests** | Đạt **97.63%** thành công hợp đồng |
| **Tỷ lệ kiểm tra hợp lệ (Checks Succeeded)** | **98.79%** | 1.644 / 1.664 checks (status 200, route_id, distance, explanation) |
| **Tỷ lệ lỗi dưới tải cực đại (Error Rate)** | **2.37%** (10 requests) | Do timeout 5s khi 30 VUs đồng thời truy vấn PostGIS trên 1 worker Uvicorn |
| **Độ trễ tối thiểu (Min Latency)** | **856.84 ms** | Truy vấn có sẵn cache hành lang |
| **Độ trễ Trung vị (p50 / Median Latency)** | **1.86s - 2.01s** | Thời gian phản hồi tiêu chuẩn |
| **Độ trễ Phân vị 90 (p90 Latency)** | **2.99s - 3.06s** | Dưới tải đồng thời 30 luồng |
| **Độ trễ Phân vị 95 (p95 Latency)** | **3.26s - 3.49s** | Đo trên hạ tầng thực tế |
| **Lưu lượng mạng (Network Data Transfer)** | **12 MB** nhận / **107 kB** gửi | Tốc độ truyền tải 390 kB/s |

> [!NOTE]
> Khác với các tuyên bố "ảo" trước đây khẳng định `p(95) < 300ms` khi dùng dữ liệu giả, kết quả đo thực tế trên đồ thị 343.610 đường và OSRM đa ứng viên cho thấy p50 thực tế là **~1.9s** và p95 là **~3.3s** dưới tải 30 người dùng đồng thời.

---

## 3. Kết quả Kiểm thử Tự động Giao diện Thực (Playwright E2E)

Lệnh kiểm tra: `cd frontend && npx playwright test`

```
Running 4 tests using 1 worker

  -  1 …/osrm-down.spec.ts:4:5 › provider outage never draws a fabricated route (SKIPPED)
  ✓  2 …/road-segment-live.spec.ts:3:5 › a sourced OSRM step can be highlighted without claiming an OSM Way ID (5.2s)
  ✓  3 …/safepath.spec.ts:4:5 › OSRM route appears on the live map (7.3s)
  ✓  4 …/safepath.spec.ts:46:5 › five independent HCMC pairs render real routes on tiles (19.0s)

  1 skipped
  3 passed (33.5s)
```

### Danh mục Ảnh chụp Thực tế (Screenshots Artifacts):

| Tên File Ảnh | Đường dẫn Lưu trữ | Mô tả Nội dung Bằng chứng |
|---|---|---|
| `osrm-live-map-primary.png` | [`docs/screenshots/osrm-live-map-primary.png`](file:///Users/phamgiakhoi/SafePath-Hackathon/docs/screenshots/osrm-live-map-primary.png) | Tuyến đường chính hiển thị trên nền vector tile OpenFreeMap kèm bảng rủi ro UNKNOWN |
| `osrm-live-map-detail.png` | [`docs/screenshots/osrm-live-map-detail.png`](file:///Users/phamgiakhoi/SafePath-Hackathon/docs/screenshots/osrm-live-map-detail.png) | Phóng to (Zoom-in) chi tiết các giao lộ ngã tư Hàng Xanh và cầu Thị Nghè |
| `osrm-live-map-alternative.png` | [`docs/screenshots/osrm-live-map-alternative.png`](file:///Users/phamgiakhoi/SafePath-Hackathon/docs/screenshots/osrm-live-map-alternative.png) | Chuyển đổi tuyến ứng viên thay thế mượt mà |
| `phase2-step-highlight.png` | [`docs/screenshots/phase2-step-highlight.png`](file:///Users/phamgiakhoi/SafePath-Hackathon/docs/screenshots/phase2-step-highlight.png) | Highlight phân đoạn OSRM mà không nhận vơ Way ID |
| `osrm-hcm-pair-1.png` | [`docs/screenshots/osrm-hcm-pair-1.png`](file:///Users/phamgiakhoi/SafePath-Hackathon/docs/screenshots/osrm-hcm-pair-1.png) | Cặp 1: Chợ Bến Thành -> Ngã tư Hàng Xanh |
| `osrm-hcm-pair-2.png` | [`docs/screenshots/osrm-hcm-pair-2.png`](file:///Users/phamgiakhoi/SafePath-Hackathon/docs/screenshots/osrm-hcm-pair-2.png) | Cặp 2: Sân bay Tân Sơn Nhất -> Chợ Bến Thành |
| `osrm-hcm-pair-3.png` | [`docs/screenshots/osrm-hcm-pair-3.png`](file:///Users/phamgiakhoi/SafePath-Hackathon/docs/screenshots/osrm-hcm-pair-3.png) | Cặp 3: Landmark 81 -> Ngã tư Hàng Xanh |
| `osrm-hcm-pair-4.png` | [`docs/screenshots/osrm-hcm-pair-4.png`](file:///Users/phamgiakhoi/SafePath-Hackathon/docs/screenshots/osrm-hcm-pair-4.png) | Cặp 4: Nhà thờ Đức Bà -> Landmark 81 |
| `osrm-hcm-pair-5.png` | [`docs/screenshots/osrm-hcm-pair-5.png`](file:///Users/phamgiakhoi/SafePath-Hackathon/docs/screenshots/osrm-hcm-pair-5.png) | Cặp 5: Đường Nguyễn Hữu Cảnh -> Sân bay Tân Sơn Nhất |

---

## 4. Kết quả Toàn bộ Test Suite Backend (Pytest)

Lệnh kiểm tra: `OSRM_LIVE_TESTS=1 OSM_ROAD_LIVE_TESTS=1 .venv/bin/pytest backend/tests/ -v`

```
======================= 108 passed, 5 skipped in 16.60s ========================
```

Bao gồm:
- `test_camera_metadata_and_snapshot_live.py`: 6 passed
- `test_osm_road_graph_live.py`: 5 passed
- `test_osrm_live.py`: 8 passed, 5 skipped (các test E2E bổ sung)
- `test_phase1_contracts_and_db.py`: 12 passed
- `test_phase2_ingestion.py`: 12 passed
- `test_phase3_vision.py`: 8 passed
- `test_phase4_real_onnx_live.py`: 13 passed
- `test_phase4_risk_and_routing.py`: 6 passed
- `test_phase5_api.py`: 12 passed
- `test_phase5_weather_tide_risk_live.py`: 16 passed
- `test_phase7_failure_resilience_live.py`: 10 passed

---

## 5. Kết quả Kiểm tra Rà soát Bảo mật (Redaction Audit)

Lệnh kiểm tra: `python3 scripts/security_and_redaction_check.py`

```
=== SafePathAI Security & Redaction Audit ===
PASS: .env.example contains only safe placeholders.
PASS: No hardcoded credentials detected in source code or documentation.
PASS: docker compose config validation succeeded.
=== ALL SECURITY & REDACTION CHECKS PASSED ===
```

