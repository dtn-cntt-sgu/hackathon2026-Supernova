# Page Design Override: Camera Monitor (`/monitor`)
## SafePath AI — Urban Surveillance Intelligence Matrix

> **Role & Intent:**
> Trung tâm giám sát hình ảnh thực tế từ 796 camera giao thông TP.HCM.
> Trình bày trực quan, tải ảnh nhanh, phân loại rõ ràng trạng thái AI Inference và tính xác thực của ảnh.

---

### 1. Bố cục & Hệ thống lưới (Monitoring Grid)

- **Header Tác nghiệp:**
  - Tiêu đề gọn gàng, bộ đếm tổng số camera có ảnh / đã phân tích xe & lưu thông / đang ngoại tuyến.
  - Tích hợp nút refresh thủ công (có cooldown 5s) và bộ đếm chu kỳ tự động.
- **Thanh công cụ lọc (Filter Bar):**
  - Ô tìm kiếm tên đường / mã camera với icon kính lúp.
  - Dropdown chọn Quận/Huyện có scroll mượt.
  - Toggle switch "Chỉ hiện camera có ảnh trực tiếp".
- **Camera Card Matrix:**
  - Desktop: Grid 3 đến 4 cột (`grid-template-columns: repeat(auto-fill, minmax(280px, 1fr))`).
  - Tablet: Grid 2 cột.
  - Mobile: Grid 1 cột (tối ưu tốc độ tải ảnh và thao tác cuộn ngón cái).

---

### 2. Thiết kế Camera Card Specs

- **Tỷ lệ ảnh khung hình:** 16:9 cố định, `overflow: hidden`, bo góc 16px.
- **Skeleton Loading:** Khi ảnh đang tải, hiển thị `animate-pulse` màu slate-800 với icon camera mờ; không để layout bị giật nhảy (CLS = 0).
- **Trạng thái Placeholder:** Khi ảnh trả về `IMAGE NOT AVAILABLE`, gắn badge màu hổ phách `"Chưa có ảnh mới"` và hiển thị thời gian truy xuất gần nhất, không để ô ảnh bị vỡ.
- **AI Overlay Badge:**
  - Gắn badge góc trên bên phải: `"YOLO26n: X xe"` hoặc `"Thông thoáng"`.
  - Nếu phát hiện rủi ro ngập: viền đỏ neon tinh tế xung quanh card.
- **Thao tác Click:** Mở `CameraEvidenceModal` lập tức kích hoạt mức ưu tiên **Tier 1 (refresh 60 giây)** trên backend.

