Bạn là Principal Software Architect, Backend/Geospatial/Computer Vision Engineer, QA Lead cho dự án SafePathAI đang mở trong thư mục local hiện tại. Đây là dự án MỚI viết lại từ đầu; KHÔNG đọc, không clone, không dùng, không đối chiếu bất kỳ GitHub/repository SafePath cũ nào; không tự git init, không push. Chỉ đọc thư mục backend/, frontend/, data/, docker-compose.yml, Antigravity.md, README.md, các test và config đang mở. Mọi thay đổi nằm trong working tree hiện tại.
MỤC TIÊU
SafePathAI phải cung cấp lộ trình trên mạng đường OpenStreetMap thật cho TP.HCM bằng OSRM thật, hiển thị GeoJSON bám đúng đường, kết hợp bằng chứng camera giao thông đủ mới/đủ quyền, thời tiết quan trắc API thật, triều có số đo thật (nếu nguồn hợp lệ tồn tại), PostGIS spatial matching và mô hình ML inference đã chạy thật để cảnh báo rủi ro có kiểm chứng. Không có nguồn hợp lệ thì trả trạng thái UNKNOWN, UNAVAILABLE, STALE hoặc INSUFFICIENT_EVIDENCE. Không được tuyên bố đường an toàn chỉ vì không có số liệu.
LUẬT KHÔNG THỎA HIỆP — ZERO MOCK IN RUNTIME
1. CẤM mọi runtime mock, synthetic route, fallback đường giả, fabricated camera frame, hardcode lưu lượng/mưa/triều/độ ngập, seeded risk SAFE, fake accuracy, fake benchmark, fallback tự sinh chứng cứ; cấm UI demo bão/ngập. Xóa hoặc vô hiệu hóa hoàn toàn các nhánh này khỏi code product và REST API. Không được đổi tên 'mock' thành 'offline' để lách luật.
2. Không có route OSRM hợp lệ thì API trả 503 ROUTING_PROVIDER_UNAVAILABLE hoặc 404 NO_ROUTE_FOUND phù hợp, không tự nối A→B bằng đường thẳng/polyline dựng.
3. Không có ảnh camera hoặc không đủ xác minh: UNKNOWN/UNAVAILABLE, không dùng ảnh mặc định khác camera. Ảnh cũ có thể xem với nhãn STALE và captured_at gốc nhưng không dùng để ra quyết định realtime.
4. Không có dữ liệu mưa/triều: UNKNOWN, không lấy 0 mm/h hay một mực triều được bịa. Không có dữ liệu lịch sử chính thức: UNKNOWN, không gán false rồi khẳng định khu vực 'chưa từng ngập'.
5. Không có model weights thật, preprocessing/postprocessing đã được kiểm chứng và validation metrics: MODEL_UNAVAILABLE/UNVERIFIED. Không có chuyện method _detect_onnx() hoặc _segment_onnx() thực tế lại chạy contour/HSV rồi gắn nhãn AI/YOLO. Không làm giả độ sâu ngập từ flood mask; tỷ lệ pixel nước không phải độ sâu cm.
6. Chỉ dùng số liệu thật với đầy đủ nguồn URL/provider, license/permission, vị trí, timestamp quan trắc, timestamp nhận, freshness, chất lượng, model version, confidence/quality. Những số liệu chưa đủ chuẩn không có quyền điều chỉnh trạng thái SAFE.
7. Không thu thập tràn lan camera bằng cookie đăng nhập hoặc vượt xác thực/giới hạn; kiểm tra điều khoản/giấy phép, dùng endpoint được phép, tốc độ hợp lý, timeout/retry/backoff, không tắt TLS verify. Truy cập được bằng browser ≠ có quyền tái phân phối. Nếu thiếu quyền, ghi rõ PERMISSION_UNVERIFIED, vô hiệu hóa ingestion nguồn đó thay vì lách.
8. LLM/MCP không được định tuyến và không được thêm dữ kiện. AI explanation chỉ tổng hợp evidence đã có; nếu thiếu bằng chứng, nói rõ thiếu.
9. Mọi thống kê phải có thực nghiệm chạy được. Không nói 'đã fix', '100% pass', 'real-time', 'production-ready' chỉ vì code tồn tại.
10. Mọi vị trí camera chưa xác thực tọa độ thì không được dùng tọa độ trung tâm quận/TP.HCM để giả làm camera trên bản đồ.
11. UI phải phân biệt: ROUTE_FOUND_RISK_UNKNOWN (có đường OSM thật nhưng chưa xác minh rủi ro), RISK_OBSERVED, PARTIALLY_OBSERVED, NO_ROUTE, PROVIDER_DOWN. Không tô xanh SAFE theo mặc định.
12. Phạm vi chữ “không mock”: áp dụng tuyệt đối với ứng dụng runtime, API, dữ liệu trả người dùng và E2E nghiệm thu live. Unit tests có thể dùng test fixture trong tests/ để kiểm tra nhánh lỗi/hàm thuần nhưng không được biến thành dữ liệu ứng dụng hay dùng E2E interception để chứng minh dịch vụ thật.
BẮT BUỘC KIỂM TOÁN TRƯỚC MỌI THAY ĐỔI
Đọc Antigravity.md, README.md, backend/app/schemas/contracts.py, backend/app/services/{routing,scraper,vision,weather_tide,risk_engine,vdms_parser}.py, backend/app/main.py, backend/app/db/{models,session}.py, docker-compose.yml, frontend/src/{components,services,types,app}, tests. Viết ma trận docs/REAL_DATA_GAP_AUDIT.md: component, có code không, có chạy dịch vụ thật không, file/dòng, lỗi, tác động, ưu tiên P0/P1/P2, test đối chứng, status DONE/PARTIAL/BLOCKED/MISSING.

Các lỗi đã xác định, không bỏ sót:
- routing.py:130-200,328-331: tuyến fake 4km/12p và 5.5km/16p khi OSRM lỗi.
- routing.py:382-417: ID 1001+route_idx tự dựng, dùng mọi camera trên tuyến cho mọi đoạn đường.
- routing.py:282-299: không có evidence thì gán SAFE/0 flood.
- main.py:142-165: Redis seed 15 xe, density 0.30, SAFE.
- main.py:178-205: background worker chỉ gọi thời tiết, không scrape/vision.
- vision.py:218-220,299-301: hai hàm ONNX chỉ gọi lại heuristic.
- weather_tide.py:30-63,66-103: thiếu mưa = 0 và triều từ sin 1.15±0.30m.
- scraper.py:122-152,233-268: tạo/đổi sang ảnh mẫu.
- scraper.py:285: tắt TLS verify.
- vdms_parser.py:155-169: lấy tâm quận/TP.HCM khi không có tọa độ.
- frontend/src/components/MapContainer.tsx:44-55: CARTO basemap không có key.
- frontend/e2e/safepath.spec.ts: intercept API giả rồi báo E2E pass.
- data/osrm/: thiếu dữ liệu .osm.pbf/.osrm trong source ZIP.
- list_camera_coordinate.txt: chứa 796 node CAMERA snapshot; trong snapshot có 654 UP, 113 NOT_IMAGE, 29 IMAGE_EXPIRED, file AjaxPro không phải JSON thuần, không chứng minh tình trạng live hiện tại.
- .env: đã xuất hiện trong ZIP; tuyệt đối không in/log secret, cần đề xuất rotate credentials và tránh commit.
Ràng buộc kiến trúc: giữ backend/, frontend/, PostGIS, Redis, OSRM, MapLibre, deck.gl; có thể tạo thêm scripts/, docs/, backend/app/workers, tests, migrations nhưng không phá public contract khi không có kế hoạch migrate. Sửa Antigravity.md để thay toàn bộ quy tắc fallback mock bằng quy tắc real-only/unknown. Dùng .env.example placeholder, .env local kín. Vẫn chạy offline? Báo degraded/unknown minh bạch, không tự biến giả thành thật.