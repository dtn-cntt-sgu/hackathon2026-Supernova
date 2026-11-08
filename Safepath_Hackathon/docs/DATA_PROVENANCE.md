# BẢN ĐỒ NGUỒN GỐC DỮ LIỆU (DATA PROVENANCE & LINEAGE MANIFEST)

SafePathAI tuân thủ nghiêm ngặt nguyên tắc **Zero-Mock in Runtime** (`Codex.md` & `Antigravity.md`). Tài liệu này ghi nhận đầy đủ xuất xứ pháp lý, giấy phép, phương thức thu thập, độ phủ và giới hạn của tất cả các luồng dữ liệu được nạp vào hệ thống.

---

## 1. Đồ thị Đường bộ & Định tuyến (OSM Road Graph & OSRM)

| Thuộc tính | Giá trị chi tiết |
|---|---|
| **Nhà cung cấp (Provider)** | OpenStreetMap contributors / Geofabrik GmbH |
| **URL Tải dữ liệu** | `https://download.geofabrik.de/asia/vietnam-latest.osm.pbf` |
| **Thời điểm trích xuất (Timestamp)** | `2026-10-21T20:21:46Z` |
| **Checksum (MD5)** | `b07130ce86163a4e0ccb6298c66ba2b4` |
| **Kích thước file nguồn** | ~206 MB (`vietnam-latest.osm.pbf`) |
| **Giấy phép (License)** | Open Database License (ODbL) 1.0 / © OpenStreetMap contributors |
| **Quy mô đồ thị OSRM** | 46.480.906 node, 4.746.385 way, 2.085 restriction (loại 428 restriction lỗi) |
| **Dung lượng đồ thị MLD** | ~5.4 GiB (bao gồm `.osrm`, `.partition`, `.cells`, `.mldgr`) |
| **Hệ tọa độ** | WGS84 (EPSG:4326) |
| **Độ phủ** | Toàn bộ lãnh thổ Việt Nam, tối ưu hóa định tuyến ô tô (`car.lua`) tại TP.HCM |
| **Giới hạn** | OSRM tính toán thời gian di chuyển dựa trên tốc độ giới hạn pháp lý (`maxspeed`), chưa tích hợp vận tốc xe chạy thực tế theo thời gian thực (live floating car data). |

---

## 2. Mạng lưới Cạnh Đường PostGIS (Road Edges & Spatial Graph)

| Thuộc tính | Giá trị chi tiết |
|---|---|
| **Bảng cơ sở dữ liệu** | `road_segments` (Way) và `road_edges` (Cạnh phân đoạn cặp đỉnh) |
| **Số lượng Way OSM** | **343.610** Way (`osm_way_id` duy nhất) |
| **Số lượng Cạnh (Edges)** | **1.858.355** Cạnh (`osm_way_id, edge_index`) |
| **Chỉ mục không gian** | Spatial GiST trên `geom` (SRID 4326) và Functional GiST trên `geography(geom)` |
| **Khớp hành lang (Buffer)** | Bán kính `80 mét` theo hình học địa lý thực (`ST_DWithin(geom::geography, ..., 80)`) |
| **Ghi nhận nguồn** | Kế thừa trực tiếp `osm_way_id` từ Geofabrik PBF. Không tự phát sinh ID tuyến ảo. |
| **Giới hạn** | Các cạnh OSM ứng viên phát hiện qua ST_DWithin được phân loại minh bạch là `SPATIALLY_NEAR` / `CANDIDATE_ONLY`. Không tự ý gán `osm_way_id` vào step của OSRM khi chưa có thuật toán Map Matching chính xác 100%. |

---

## 3. Điểm đen Ngập lụt Lịch sử Đô thị (Historical Flood Points)

| Thuộc tính | Giá trị chi tiết |
|---|---|
| **Cơ quan phát hành** | Sở Xây Dựng TP.HCM & Trung tâm Quản lý Hạ tầng Kỹ thuật TP.HCM |
| **File dữ liệu** | [`data/floods/hcmc_historical_flood_points.json`](file:///Users/phamgiakhoi/SafePath-Hackathon/data/floods/hcmc_historical_flood_points.json) |
| **Số lượng điểm đen** | **13 vị trí trọng yếu** đã thẩm định: |
| | - Nguyễn Hữu Cảnh (Bình Thạnh) |
| | - Quốc Hương, Thảo Điền, Nguyễn Văn Hưởng (TP. Thủ Đức - Q.2) |
| | - Huỳnh Tấn Phát, Trần Xuân Soạn, Lê Văn Lương (Quận 7) |
| | - Kha Vạn Cân, Dương Văn Cam, Lương Định Của (TP. Thủ Đức) |
| | - Bạch Đằng (Bình Thạnh), Hồ Học Lãm (Bình Tân), An Dương Vương (Quận 8) |
| **Khớp không gian** | Đã spatial join gán cờ `is_flood_prone_history = TRUE` cho đúng 13 đoạn đường OSM tương ứng. |
| **Quy tắc Zero-Mock** | 343.597 đoạn đường còn lại mang giá trị `NULL` (chưa có hồ sơ), tuyệt đối không suy diễn thành `FALSE` (an toàn). |

---

## 4. Dữ liệu Khí tượng Thời gian thực (Live Weather)

| Thuộc tính | Giá trị chi tiết |
|---|---|
| **Nhà cung cấp (Provider)** | Open-Meteo Weather Forecast API |
| **Endpoint** | `https://api.open-meteo.com/v1/forecast` |
| **Thông số trích xuất** | `precipitation`, `rain`, `weather_code` |
| **Múi giờ** | `Asia/Ho_Chi_Minh` (UTC+7) |
| **Cơ chế Cache** | Redis key phân vùng theo lưới tọa độ (`env:weather:{lat}:{lng}`) với TTL 900 giây (15 phút) |
| **Quy tắc Zero-Mock** | Khi API gặp lỗi kết nối, timeout hoặc HTTP 429, hệ thống trả về `(None, "WEATHER_UNAVAILABLE", None, None)`, tuyệt đối không fallback về `0.0 mm/h`. |

---

## 5. Dữ liệu Thủy triều & Trạm Thủy văn (Hydrology & Tide Datum)

| Thuộc tính | Giá trị chi tiết |
|---|---|
| **Cơ quan đo đạc** | Đài Khí tượng Thủy văn Khu vực Nam Bộ / Viện Quy hoạch Thủy lợi Miền Nam |
| **Trạm quan trắc** | Trạm Phú An (Sông Sài Gòn, 10.793°N, 106.712°E) & Trạm Nhà Bè (Sông Đồng Điền, 10.655°N, 106.745°E) |
| **Hệ mốc cao độ Quốc gia** | **Mốc Hòn Dấu (Hệ quy chiếu VN-2000)** |
| **Các cấp báo động** | Báo động I (1.40m), Báo động II (1.50m - bắt đầu ngập vùng trũng), Báo động III (1.60m) |
| **Quy tắc Zero-Mock** | Loại bỏ hoàn toàn hàm sóng sin mô phỏng. Mặc định hệ thống trả về `tide_status = "TIDE_UNAVAILABLE"`, `tide_level_meters = None`. Chỉ cập nhật khi tiếp nhận bản tin quan trắc chính thức qua `ingest_verified_tide_bulletin()`. |

---

## 6. Trọng số Mô hình Computer Vision (AI Model Weights)

### 6.1 Mô hình Nhận diện Phương tiện (Vehicle Detection)
| Thuộc tính | Giá trị chi tiết |
|---|---|
| **Kiến trúc mô hình** | Ultralytics YOLO26n ONNX (Official release weights) |
| **Đường dẫn lưu trữ** | [`data/models/yolo26n.onnx`](file:///Users/phamgiakhoi/SafePath-Hackathon/data/models/yolo26n.onnx) |
| **Kích thước file** | 9.930.306 bytes (~9.9 MB) |
| **Checksum (SHA-256)** | `18eac704c629a851c0689ebd9164a12c4ef6ad6b5959b299c32f917815fc49b7` |
| **Giấy phép (License)** | AGPL-3.0 / Enterprise |
| **Tập dữ liệu huấn luyện** | MS COCO 2017 (80 classes, 118.287 training images) |
| **Các lớp phương tiện** | Car (2), Motorcycle (3), Bus (5), Truck (7) |
| **Độ chính xác** | mAP 50-95: 0.395, độ trễ suy luận P95: ~3.8ms |
| **Cơ chế suy luận** | `onnxruntime.InferenceSession` với Class-Aware NMS và 2x2 adaptive tiling phục hồi xe máy xa/mờ |

### 6.2 Mô hình Phân đoạn Ngập nước (Flood Road Segmentation)
| Thuộc tính | Giá trị chi tiết |
|---|---|
| **Kiến trúc mô hình** | U-Net Semantic Segmentation ONNX (HCMC Road Surface Optimized) |
| **Đường dẫn lưu trữ** | [`data/models/flood_unet.onnx`](file:///Users/phamgiakhoi/SafePath-Hackathon/data/models/flood_unet.onnx) |
| **Kích thước file** | 165.175 bytes (~165 KB) |
| **Checksum (SHA-256)** | `ea537875c78762a22261af663997e0d98b724f03c063698286fa02d161198496` |
| **Tập dữ liệu huấn luyện** | HCMC Urban Road Flood & Tidal Overflow Dataset (mặt đường đô thị, nước đục, phản chiếu ánh đèn đêm) |
| **Chỉ số Benchmark** | IoU: 0.7059, F1-score: 0.8276, Precision: 0.9902, Recall: 0.7109 |
| **Độ trễ suy luận** | P95: ~18.5ms trên CPU |
| **Quy tắc Zero-Mock** | Chỉ trích xuất tỷ lệ pixel nước nghi vấn trên vùng quan tâm (ROI mặt đường). Tuyệt đối không suy diễn độ sâu cm từ 1 ảnh 2D camera đơn lẻ. |

---

## 7. Danh mục Camera Giao thông (Camera Surveillance Registry)

| Thuộc tính | Giá trị chi tiết |
|---|---|
| **File snapshot nguồn** | [`list_camera_coordinate.txt`](file:///Users/phamgiakhoi/SafePath-Hackathon/list_camera_coordinate.txt) |
| **Số lượng Camera** | **796 camera giao thông** trên địa bàn TP.HCM |
| **Trường thông tin** | `CamId`, `Code`, `CamStatus`, `Disctrict`, `Angle`, `Published`, `Lat`, `Lng` |
| **Quy tắc Zero-Mock** | Dữ liệu hình ảnh từ camera chỉ được tải khi cờ cấu hình `CAMERA_INGESTION_PERMITTED=True` được cấp phép rõ ràng. Mọi camera chưa được xác minh góc nhìn hướng thẳng vào mặt đường đều được xếp loại `SPATIALLY_NEAR_UNVERIFIED_VIEW` và gán trạng thái `UNKNOWN`. |

---

## 8. Lớp Bản đồ Số (Vector Map Tiles)

| Thuộc tính | Giá trị chi tiết |
|---|---|
| **Nhà cung cấp Tiles** | OpenFreeMap (`https://openfreemap.org`) |
| **Nguồn dữ liệu nền** | OpenMapTiles / OpenStreetMap contributors |
| **Kiểu hiển thị** | Vector Tiles PBF (Style: `positron` / `liberty`) |
| **Giấy phép (License)** | CC-BY 4.0 / ODbL |
| **Attribution** | Hiển thị đầy đủ liên kết bản quyền MapLibre, OpenFreeMap, OpenMapTiles và OpenStreetMap trên bản đồ. |

