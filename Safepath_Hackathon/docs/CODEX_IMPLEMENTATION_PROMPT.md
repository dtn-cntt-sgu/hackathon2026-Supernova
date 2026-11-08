# Prompt gửi cho Codex mở tại root `Safepath_Hackathon`

Đọc và kiểm tra **toàn bộ code hiện có** trước khi sửa, không tự suy diễn cấu trúc. Mục tiêu:

Chuyển quan trắc SafePath về **reverse proxy lấy snapshot thật** theo nguyên lý `ePlus-DEV/camera` (`proxy.php`: strict 24-hex CamId, upstream cố định, kiểm tra content type, chuyển tiếp ảnh), nhưng triển khai **bằng Python/FastAPI**. Chỉ chạy YOLO/segmentation và risk AI cho **route** khi thật sự cần và đáp ứng chính sách quyền/camera evidence. Giữ nguyên hệ thống OSRM, PostGIS, Redis, dữ liệu GIS 796 cameras, weather/news/risk engine và UI tinh chỉnh hiện có.

Có starter đi kèm: `backend/app/services/camera_live_proxy.py`, `backend/tests/test_camera_live_proxy.py`, `frontend/src/components/ProxyCameraImage.tsx`, và hướng dẫn `docs/INTEGRATION_GUIDE.md`. Đọc rồi tích hợp/refactor theo repo thực, không paste mù quáng.

## Quy trình

1. `git status` và xác định nhánh. Tạo branch `feature/camera-proxy-route-ai-only` từ nhánh cập nhật nếu có thể. Không commit/push/merge nếu chưa được yêu cầu. Không xóa code AI model, chỉ ngắt khỏi Monitor.
2. Audit `backend/app/main.py`, `backend/app/services/{scraper,camera_url_resolver,image_validator,camera_scheduler,camera_queue,vision,routing,risk_engine}.py`, `frontend/src/{app/monitor/page.tsx,components/CameraEvidenceModal.tsx,services/api.ts,types/contracts.ts}` và các test hiện có.
3. Backend: thêm `/api/v1/cameras/{cam_id}/proxy` chỉ chấp nhận ID hợp lệ trong DB, URL nguồn cố định, không public open proxy. Dùng `httpx` + TLS verify, timeout, bounded payload, MIME allowlist, existing image validator, bounded per-camera cache, rate limit, circuit breaker. Lỗi upstream/ảnh placeholder phải phản hồi thật; không mock/không tự điền `LIVE` khi giờ chụp chưa rõ.
4. Monitor: chỉ ảnh proxy và trạng thái nguồn; bỏ hoàn toàn AI badges, enhance/analyzed tab, overlay, xe/ước tính ngập và tất cả trigger AI trong trang này. Lazy load, tối đa 12-24 camera trang, refresh 10-30s chỉ ảnh đang hiển thị, tab ẩn dừng, không 796 request đồng thời; modal vẫn xem ảnh và thử lại.
5. Background: ingestion có thể tiếp tục như caching/health nếu tuân thủ rate limit, nhưng **tuyệt đối không enqueue AI** từ Monitor hoặc full network rotation. Xác minh `active_route_cameras_zset` TTL trước enqueue và trước inference; dedup hash/model. Thêm `CAMERA_ROUTE_AI_ENABLED=false` mặc định.
6. Route: chọn ít camera có liên quan đoạn đường đã xác minh, snapshot mới và chưa inference; fetch/schedule AI on-demand với quota và timeout, có trạng thái PENDING; kết quả chỉ tác động risk khi đủ rights/validation/line-of-sight/OSM edge. Không cho UNKNOWN thành SAFE, không chấm risk trên overlay cũ/sai snapshot. Cần quy trình để frontend cập nhật risk khi job xong, không ép mọi request route chờ model vô hạn.
7. Test mock proxy: valid image, HTML/placeholder, invalid ID, camera không DB, upstream 403/429/5xx, timeout, giant image, single-flight/cache, no redirects/SSRF. Test Monitor **0 calls to model**; route no permission=0 AI; route enabled + verified=limited AI; retry fails, no stale risk leakage. Update regression/Playwright, `npm run build`, pytest. Dùng fixtures, không cần request trực tiếp nguồn thật để test CI.
8. Báo cáo các file sửa, diff từng nhóm, lệnh test, kết quả PASS/FAIL thực, migration/config flags và vấn đề còn tồn tại. Nếu quyền nhà cung cấp camera không rõ, không vượt 403/429 và không bật route scoring từ camera.

**Không** rewrite toàn repo; **không** copy PHP/Guzzle hay `vendor/` sang Python; **không** xóa safeguards của SafePath; **không** thay số liệu cảnh báo bằng mock; **không** push thẳng `main`.
