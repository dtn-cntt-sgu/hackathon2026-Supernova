# SafePathAI — Cinematic frontend implementation

Cập nhật nghiệm thu: 25/10/2026. Triển khai trong working tree hiện tại; không push hoặc deploy.

## 1. Audit và nguyên nhân

Đã rà soát landing, globals, Liquid Glass CSS, layout/provider, CityScene, ObservationImage, LiquidGlassCard, map/SpatialDashboard/MapContainer, CameraEvidenceModal, monitor/news/dashboard/account, useLiveObservations, API, contracts, package và các test liên quan.

| Khu vực | Hiện trạng trước sửa / nguyên nhân | Thay đổi | Trạng thái triển khai |
|---|---|---|---|
| Hero | `.hero-bottom` absolute ngoài copy; cảnh absolute trong viewport cố định và bị cắt | Thống kê nằm trong hero-copy, grid bình thường, cách trust caption 28px; nội dung được cuộn | DONE |
| Điều hướng chương | Thanh cố định phía dưới che thống kê/telemetry trên màn hình thấp | Chuyển lên dưới navbar, dành khoảng trống trong layout; giữ tap target 44px | DONE |
| CSS | Minified CSS trộn cảnh cũ và nhiều override, !important tranh chấp | Chia tokens, glass, cinematic, animations, responsive, app-surfaces; bỏ override !important của app surfaces | DONE |
| Canvas | CSS MapLibre thắng positioning, canvas khởi tạo cao 300px; sai thứ tự lớp | Selector container rõ ràng, width/height đầy đủ, ResizeObserver và thứ tự lớp riêng | DONE |
| Camera bản đồ | Mousemove thay pitch/bearing đồng thời với easeTo; canvas particles chạy liên tục | Một chủ điều khiển camera, stop trước transition, dừng khi tab hidden; bỏ vòng particles | DONE |
| Dữ liệu | 796 mặc định, null mưa → 0, null triều → 1.25; cảnh/route/report mô phỏng | Bỏ giá trị bịa và khẳng định an toàn; giữ unknown/stale và thời điểm từng nguồn | DONE |
| Dashboard | Tuyến đi làm 22 phút/6.8 km dựng sẵn; report cộng đồng có lượt xác nhận giả | Bỏ thẻ dựng sẵn; dùng saved places/history thật, empty state khi chưa có dịch vụ báo cáo | DONE |
| Account | Nhập địa chỉ bất kỳ nhưng luôn lưu tọa độ trung tâm | Dùng PlaceSearchCombobox hiện có, chỉ lưu tọa độ địa điểm đã chọn | DONE |
| Header ứng dụng | h-14/h-16 không đủ cho tiêu đề và nav mobile | AppPageHeader dùng chung cho camera/dashboard/account, tăng chiều cao theo nội dung | DONE |
| Accessibility | Thẻ camera chỉ click; modal chưa chặn Tab ra ngoài | Enter/Space, role/label, focus trap, Escape và restore focus | DONE |
| Model | YOLO26n weights/decoder/config đã có trong cây mã hiện tại | Kiểm chứng hash, inference ảnh thật và tests; bỏ benchmark không có bằng chứng | VERIFIED |

## 2. Kiến trúc sau sửa

- `app/page.tsx`: ghép bốn chương; dữ liệu quan trắc qua hook hiện có.
- `hooks/useCinematicScene.ts`: chapter IDs/camera presets, native scroll, rAF gộp sự kiện. React chỉ đổi state khi đổi chương; progress cập nhật CSS custom property. Không scroll hijacking.
- `components/spatial/CityScene.tsx`: dynamic import, một MapLibre context, camera registry thật có clustering, selected camera highlight, resize/visibility/reduced-motion cleanup.
- `components/cinematic/NewsEditorialCards.tsx`: lấy ba tin từ API thật, featured + hai secondary cards, nguồn và thời điểm đăng; loading/error/empty riêng.
- `components/cinematic/RoutingLaunchPanel.tsx`: chọn điểm đi/đến thật qua component tìm địa điểm hiện có, chuyển sang `/map` bằng query có tọa độ. Map kiểm tra tọa độ đầu vào; chưa tự vẽ hoặc tính tuyến.
- `components/cinematic/AnimatedCounter.tsx`: hiệu ứng nhấn nhẹ khi số thật thay đổi; không sinh số trung gian/đếm giả.
- `components/ui/AppPageHeader.tsx`: header sáng dùng chung, layout linh hoạt, nav có trạng thái trang hiện tại.
- `styles/liquid-glass.css`: entry point cho sáu stylesheet chuyên trách. Các component Glass cũ tiếp tục dùng shared surface classes để giữ chức năng.

Không thêm GSAP, Three.js/R3F hoặc nâng React/Next. Chuyển camera theo chương, CSS reveal và native scrolling đáp ứng cách chuyển cảnh này mà không cần thêm animation engine thứ hai.

## 3. Địa lý, 3D và các chương

Bản đồ nền: OpenFreeMap Positron / OpenMapTiles / OpenStreetMap, có attribution. Tham khảo [hướng dẫn chính thức OpenFreeMap](https://openfreemap.org/quick_start/).

Fill-extrusion chỉ dùng building source được style khai báo và feature có `height` dương. Không dùng mặc định 22m, không biến `building:levels` thành chiều cao đo được. Nếu nguồn không có height thì giữ footprint; không khẳng định mọi tòa nhà TP.HCM có dữ liệu 3D đã xác minh.

1. **Thành phố:** góc nghiêng TP.HCM, hero/caption/thống kê cùng flow; telemetry thật. Intro stagger và pointer highlight nhẹ.
2. **Camera:** bay đến tọa độ camera đang chọn, ảnh gốc/ảnh phân tích thật, giờ chụp/nhận/phân tích, model từ backend; không tạo detection boxes.
3. **Bản tin:** đổi góc nhìn, ba editorial cards từ news API; mưa/triều là context phụ có nguồn/thời điểm khi sẵn có.
4. **Hành trình:** panel chọn địa điểm thật, mở form map đã điền; chỉ OSRM trả kết quả mới có tuyến.

Reduced motion bỏ animation và chuyển camera tức thời. Map có giảm pitch trên mobile; không còn mouse parallax ghi góc camera. Card hover nâng 4px; button nâng 3px, icon dịch 4px, press 0.98. Không tự bật tiếng nói.

## 4. Dữ liệu và chức năng

- Không dùng số 0 thay dữ liệu chưa nhận. Zero mưa hợp lệ vẫn hiển thị 0.0.
- Mưa cần nguồn, timestamp, trạng thái LIVE và còn thời hạn; triều cần timestamp và nguồn riêng.
- Ảnh tải gần đây không chứng minh ảnh vừa chụp. Camera LIVE cần timestamp chụp hợp lệ/còn mới.
- Tỷ lệ pixel nước không phải độ sâu ngập; không gán “mặt đường khô” từ giá trị thiếu.
- Giữ routing, PostGIS, session/auth, ingestion và API contracts. Không đổi backend để phục vụ animation.
- Shared header giữ đường dẫn map/camera/news/dashboard/account. News bookmarks và onboarding hiện có được giữ nguyên.
- OAuth thật chưa đăng nhập tự động; không tuyên bố đã kiểm tra phiên tài khoản Google của người dùng.

## 5. Kiểm thử và ảnh nghiệm thu

**PASS — 28 trường hợp đã được kiểm chứng trên bản production hiện tại.** Lần chạy đầy đủ đạt 26/28; hai test news thất bại vì tìm heading trong header. Sau khi sửa locator đến heading nội dung (không sửa/bỏ assertion chức năng), chạy lại hai test đạt 2/2. Không còn test thất bại chưa xử lý trong bộ nghiệm thu này.

| Kiểm tra | Kết quả |
|---|---|
| TypeScript `npm run type-check` | PASS |
| Production build `.next-cinematic` | PASS |
| Cinematic + spatial Playwright | 28/28 cases verified, như mô tả trên |
| Unit observations/navigation | 5 passed |
| Backend truth/model + YOLO26n recovery | 11 passed |
| Định tuyến thật | Geometry trên map khớp response OSRM |
| Screenshot / responsive | Đủ 8 viewport hero; thêm 5 trang ứng dụng ở desktop/mobile |
| OAuth với người dùng thật | NOT TESTED |
| 60 FPS ổn định / memory soak dài hạn | PARTIAL, chưa đạt xác nhận |

 Acceptance gọi backend, OSRM, tiles và camera thật; không route interception hoặc response fixture. Test offline ngắt kết nối trình duyệt rồi refresh để kiểm tra lỗi thật.

Viewport: 1920×1080, 1440×900, 1366×768, 1280×720, 1024×768, 768×1024, 390×844, 375×667. Kiểm tra khoảng cách caption/statistics, non-absolute flow, dock không giao statistics, telemetry không giao hero-copy, overflow, chiều cao canvas và unhandled exceptions.

Bộ test gồm CSS load, API values, forward/reverse chapter navigation, một canvas sau chuyển cảnh, route geometry khớp response OSRM, chuyển địa điểm từ landing sang map, modal keyboard/restore focus, reduced motion, API offline và WebSocket không phát demo.

Ảnh đã lưu tại `docs/artifacts/cinematic/` và đã mở kiểm tra trực quan. Qua ảnh, đã sửa thêm lỗi canvas chỉ cao 300px, dock che telemetry và header mobile cắt chữ; không chỉ dựa vào DOM assertions.

- [Hero desktop 1440×900](artifacts/cinematic/cinematic-hero-1440x900.png)
- [Hero màn hình thấp 1280×720](artifacts/cinematic/cinematic-hero-1280x720.png)
- [Hero mobile 390×844](artifacts/cinematic/cinematic-hero-390x844.png)
- [Hero mobile 375×667](artifacts/cinematic/cinematic-hero-375x667.png)
- [Toàn bộ landing desktop](artifacts/cinematic/cinematic-1440x900.png)
- [Toàn bộ landing mobile](artifacts/cinematic/cinematic-375x667.png)
- [Account mobile](artifacts/cinematic/account-390.png), [dashboard mobile](artifacts/cinematic/dashboard-390.png)
- [Map mobile](artifacts/cinematic/map-390.png), [monitor mobile](artifacts/cinematic/monitor-390.png), [news mobile](artifacts/cinematic/news-390.png)

 Với mobile/màn hình thấp, một phần telemetry/thống kê ở dưới fold và có thể cuộn đến; không thu nhỏ cả trang hoặc cắt nội dung để nhét vào một màn hình.

## 6. Hiệu năng và giới hạn phép đo

Script: `frontend/scripts/measure-cinematic.mjs`; kết quả: [CINEMATIC_PERFORMANCE.json](CINEMATIC_PERFORMANCE.json).

Local production Chromium headless, một lần/viewport, không CPU/network throttle; API và tiles thật. Đây không phải Lighthouse hoặc điện thoại vật lý.

| Viewport | LCP | CLS | rAF median | rAF p95 |
|---|---:|---:|---:|---:|
| 1440×900 | 520 ms | 0.0000144 | 16.7 ms | 150 ms |
| 390×844 | 428 ms | 0 | 16.7 ms | 33.3 ms |

LCP/CLS đạt mục tiêu trong lần đo local này. Nhịp rAF không chứng minh GPU FPS; p95 desktop có frame dài, vì vậy **chưa đạt xác nhận 60 FPS ổn định**. Chưa benchmark trên điện thoại phổ thông hoặc chạy memory soak dài hạn. Sau nhiều lần chuyển chương, canvas count vẫn là 1.

Build: landing first-load JS khoảng 111 kB; map khoảng 141 kB trước khi lazy-load WebGL (trước tách module, map là khoảng 563 kB). Dynamic import giảm bundle ban đầu, không có nghĩa tổng tài nguyên WebGL đã biến mất.

## 7. YOLO26n

Chi tiết tại [BENCHMARK_YOLO26N.md](BENCHMARK_YOLO26N.md) và [YOLO26N_LOCAL_VERIFICATION.json](YOLO26N_LOCAL_VERIFICATION.json). Runtime báo `yolo26n.onnx`, `EXPERIMENTAL_HCMC`; 8 ảnh thật đã chạy inference. Installed export là one-to-many `[1,84,8400]`, có suppression. Không gắn nhãn NMS-free cho export này và không công bố accuracy TP.HCM chưa đo.

## 8. Những phần chưa xác nhận

- **PARTIAL:** target FPS ổn định, long-duration memory/GPU usage và thiết bị mobile thật.
- **CONDITIONAL:** buildings 3D phụ thuộc thuộc tính height thật trong nguồn tiles; không tự bổ sung chiều cao thiếu.
- **BLOCKED theo dữ liệu:** mưa/triều/camera thiếu hoặc cũ hiển thị unavailable/stale; không điền dữ liệu để làm đẹp.
- **NOT TESTED:** Google OAuth với tài khoản người dùng và phát âm thanh tiếng Việt trên thiết bị vật lý.
- Không có dịch vụ community-report thực trong API hiện tại; UI thông báo rõ thay vì giả gửi thành công.
