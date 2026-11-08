# SafePath — Camera reverse-proxy + AI chỉ dành cho Route

**Nguồn khảo sát:** `giakhoi0123/Safepath_Hackathon` (`main`) và `ePlus-DEV/camera` (`main`), ngày 2026-11-08.

**Tình trạng:** Bộ mã nguồn khởi đầu đã kiểm thử riêng; **chưa ghép/kiểm thử vào toàn bộ SafePath** vì môi trường hiện tại chỉ được phép *đọc* repository qua GitHub connector (`push=false`). Đây **không phải** bản nâng cấp đã deploy.

## 0. Không copy PHP vào backend Python

`ePlus-DEV/camera/proxy.php` dùng Guzzle GET URL cố định `https://giaothong.hochiminhcity.gov.vn:8007/Render/CameraHandler.ashx?id=...`, kiểm tra mã 24 hex, `Content-Type` bắt đầu `image/`, rồi chuyển tiếp bytes; browser thay `?t=` để refresh. Đây là **reverse proxy**, không phải rotating IP proxy.

SafePath đã có `backend/app/services/scraper.py`, `camera_url_resolver.py`, `image_validator.py`, DB `traffic_cameras` và `storage/cams`; nên giữ lại, đừng sao chép danh mục `data-camera.json` của repo PHP (nguy cơ danh mục không đồng bộ). Repository ePlus hiện không thể hiện `LICENSE` ở root; chỉ chép code nguyên văn nếu đã xác minh quyền sử dụng.

## 1. Tích hợp proxy trong SafePath

Chép `backend/app/services/camera_live_proxy.py` vào đường dẫn tương ứng của SafePath. Giữ nguyên phương thức `get_frame` (thời gian cache mặc định 10 giây, tối đa 64 camera trong RAM, tối đa 3 MB/ảnh, 4 kết nối đồng thời). Module dùng `httpx` đã có trong stack và gọi `validate_camera_image_bytes` để loại ảnh hỏng/placeholder. Không lấy URL từ query người dùng, không tự theo redirect, không can thiệp đăng nhập hay chống 403/429.

Trong `backend/app/main.py`, thêm imports:

```python
from backend.app.services.camera_live_proxy import camera_live_proxy, CameraProxyError
```

Sau các endpoint camera khác, thêm endpoint này:

```python
@app.get("/api/v1/cameras/{cam_id}/proxy", tags=["Surveillance"])
async def get_live_camera_proxy(
    cam_id: str,
    session: AsyncSession = Depends(get_db),
):
    if not (settings.CAMERA_ALLOW_VIEW_ONLY or settings.CAMERA_INGESTION_PERMITTED):
        raise HTTPException(status_code=403, detail="Camera viewing is not permitted")
    # Strict 24-hex gate (no arbitrary custom-slug or arbitrary URL).
    if len(cam_id) != 24 or any(c not in "0123456789abcdefABCDEF" for c in cam_id):
        raise HTTPException(status_code=400, detail="Invalid camera ID")
    row = await session.execute(
        text("SELECT 1 FROM traffic_cameras WHERE cam_id = :cam_id LIMIT 1"),
        {"cam_id": cam_id},
    )
    if row.first() is None:
        raise HTTPException(status_code=404, detail="Unregistered camera")
    try:
        image = await camera_live_proxy.get_frame(cam_id)
    except CameraProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.reason) from exc
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={
            "Cache-Control": "no-store, max-age=0",
            "ETag": '"' + image.sha256_hex + '"',
            "X-Content-Type-Options": "nosniff",
            "X-Image-Kind": "original",
            "X-Camera-Status": "RETRIEVED_CAPTURE_TIME_UNKNOWN",
            "X-Retrieved-At": image.retrieved_at.isoformat(),
        },
    )
```

**Lưu ý:** `CAMERA_ALLOW_VIEW_ONLY` là cờ kỹ thuật, không tự tạo ra quyền dùng nguồn bên ngoài. Phải xác minh điều khoản/quyền truy cập của nhà cung cấp.

## 2. Chuyển frontend quan trắc sang proxy

1. Trong `frontend/src/services/api.ts`, hàm `getCameraImageUrl` đổi đuôi URL **chỉ cho ảnh gốc** từ `/image` sang `/proxy`. Giữ `getCameraAnalyzedImageUrl` cho route (nếu cần), không để giao diện Monitor gọi.
2. Chép `frontend/src/components/ProxyCameraImage.tsx` vào repo. Trong trang Monitor, thay ảnh `<img>` của từng thẻ bằng `<ProxyCameraImage camId={cam.cam_id} name={cam.name} />` để **camera chưa từng cache** vẫn có cơ hội tải ảnh trực tiếp. Không lấy `cam.has_image` làm điều kiện duy nhất để render ảnh.
3. Làm một modal Monitor chỉ có ảnh proxy, tên, quận, giờ nhận, thông báo lỗi và nút tải lại. **Tháo** tab Original/Enhanced/Analyzed và badge AI, xe, phân đoạn nước, tỷ lệ ngập **khỏi giao diện Monitor**. Không dùng modal AI hiện tại ở trang này.
4. Giới hạn danh sách ảnh cùng lúc (ví dụ 12 camera/trang), lazy load và refresh chỉ cho camera đang hiển thị. Pause khi tab ẩn. Không tự gọi toàn bộ ~796 proxy endpoint trong một lần render; phân trang và giới hạn toàn cục phía backend.
5. Đừng hiển thị chữ "camera trực tuyến thời gian thực" chỉ vì vừa tải được HTTP 200. Khi chưa có timestamp nguồn xác thực, hiển thị "Mới nhận ảnh — giờ chụp chưa xác minh".

## 3. Chỉ chạy AI cho route, khi cần

Vị trí **đã kiểm chứng trong SafePath**:

- `backend/app/main.py` `background_camera_fetch_worker_loop`: sau `camera_scheduler.record_result`, code hiện tự `camera_queue_manager.enqueue_vision_job` cho mọi frame mới hợp lệ. **Thay điều kiện** bằng `CAMERA_ROUTE_AI_ENABLED AND CAMERA_INGESTION_PERMITTED AND CAMERA_ROUTING_EVIDENCE_PERMITTED AND route-active-unexpired AND frame-fresh AND not-already-analyzed`. Tham chiếu `zscore("active_route_cameras_zset", cam_id)` và so với `time.time()`, không chỉ `sismember` trên tập có TTL toàn cục.
- `background_vision_worker_loop`: trước `process_all_cameras_vision`, **kiểm tra lại** quyền và route-active TTL. Các job cũ của Monitor/ingestion không được inference; ACK/skip hợp lệ, ghi rõ log. Dedupe theo `(cam_id, frame_sha256, model_version)`.
- `backend/app/services/routing.py` `_batched_spatial_context` đã tìm camera trong hành lang và đăng ký `active_route_cameras`; `find_safe_route` đọc `camera_evidence:*` và chấm `calculate_segment_risk`. Với ảnh cần phân tích, enqueue **có giới hạn** (ví dụ tối đa 3 camera thuộc route được đề xuất, ưu tiên có line_of_sight_verified + observed_osm_way_id, snapshot đủ mới). Trả trạng thái `PENDING` hoặc `UNKNOWN` nếu chưa có inference, không đánh dấu SAFE giả.
- Chỉ đưa kết quả AI vào scoring khi camera đã xác minh view direction/road edge + snapshot đúng phiên bản + timestamp và độ mới phù hợp + quyền sử dụng nguồn cho phân tích/routing; nếu không vẫn `UNKNOWN` và dùng các tín hiệu độc lập (weather, news, live traffic provider).
- Tách đường đi cho Monitor và route: **Monitor không được kích hoạt AI** chỉ vì `/api/v1/cameras/active-view`, `fetchCameras`, `getCameraImageUrl`, hoặc mở modal.

Đặt cờ riêng `CAMERA_ROUTE_AI_ENABLED` mặc định `False` để rollout thử, chỉ bật sau khi đã kiểm thử quyền, chuẩn hóa rủi ro, và test đủ. Đừng tùy tiện bật `CAMERA_ROUTING_EVIDENCE_PERMITTED=True` vì mặc định repo đang tắt có chủ đích.

## 4. Kiểm thử bắt buộc

- `python -m pytest -q backend/tests/test_camera_live_proxy.py` (5 ca mock, đã PASS ở môi trường tạo starter).
- `python -m pytest -q backend/tests` + `python -m pytest -q tests` từ repo sau khi tích hợp; xác định test cũ nào dựa trên AI chạy nền và cập nhật kỳ vọng với mode mới.
- `cd frontend && npm ci && npm run build` và Playwright Monitor/Route.
- Đo số HTTP GET upstream, số job Vision và số lần inference trước/sau: **Monitor-only = 0 lần AI**; Route khi flag tắt = 0 lần AI; Route khi hợp lệ và flag bật = tối đa quota đã đặt; ảnh lỗi/403/429 không trở thành ảnh hợp lệ.
- Kiểm tra 1, 12, 24 và 100 người dùng đồng thời; quan sát rate limit/backoff, Redis lock giữa nhiều worker, không spam upstream khi ảnh thất bại.
- Kiểm tra tình huống source ảnh đổi nhưng overlay cũ: không dùng overlay/risk sai snapshot. Kiểm tra khi Redis/DB/camera provider down.

## 5. Hạn chế của starter hiện tại

- Đã viết **module proxy độc lập**, **frontend image component** và **unit tests**; **chưa** chèn route vào `main.py` hoặc refactor modal/route. Tất cả thay đổi đó là hướng dẫn áp dụng có điều kiện trong repo thực.
- Module có cache cục bộ; nhiều Gunicorn/Uvicorn workers cần Redis throttle chung + per-provider circuit breaker để không nhân request upstream.
- Chưa thử kết nối trực tiếp nguồn camera; không có cam nào được xác nhận "online" khi build starter.
- `ProxyCameraImage` dùng `getCameraImageUrl()` nên cần đổi URL trong `frontend/src/services/api.ts` như mục 2.

## 6. Route AI policy helper (starter)

Có thêm `backend/app/services/route_ai_policy.py` với `RouteAIAdmission` và `route_ai_admission_reason()`. Đây là **policy độc lập**, đã unit test, nhưng **chưa được nối** với `main.py`/`routing.py`. Khi tích hợp, route sẽ truyền thời hạn hoạt động lấy từ `Redis ZSCORE(active_route_cameras_zset, cam_id)`, frame SHA-256, thời điểm truy xuất, trạng thái đã phân tích và chứng cứ khớp hướng nhìn/OSM Way. Gọi kiểm tra **hai lần**: trước enqueue và ngay trước worker inference. Kết quả `ALLOW` không tự động đồng nghĩa risk `SAFE`/`CRITICAL`; risk engine vẫn phải kiểm tra ngữ nghĩa evidence và timestamp nguồn.
