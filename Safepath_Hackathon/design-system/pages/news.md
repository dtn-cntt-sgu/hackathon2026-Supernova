# Page Design Override: Traffic News (`/news`)
## SafePath AI — Real-Time Municipal Incident Newsroom

> **Role & Intent:**
> Cổng tin tức giao thông, ngập úng và thi công cập nhật hàng ngày tại TP.HCM.
> Thiết kế dạng Newsroom hiện đại, kết hợp bản đồ vị trí xác minh và phân loại sự cố chuẩn xác.

---

### 1. Cấu trúc giao diện Newsroom

- **Featured Incident Spotlight:**
  - Tin sự cố quan trọng nhất (ngập sâu, tắc đường diện rộng, sạt lở) được đặt ở vị trí Hero Card với ảnh kích thước lớn, nhãn cảnh báo đỏ và tọa độ bản đồ gắn kèm.
- **Category Filter Tabs:**
  - Các danh mục sự cố: *Tất cả*, *Ngập nước*, *Ùn tắc*, *Tai nạn*, *Thi công / Cấm đường*, *Thời tiết*, *Đã khắc phục*.
  - Mỗi tab mang một màu nhận diện tín hiệu riêng biệt và bộ đếm số lượng tin tức.
- **Editorial News Grid:**
  - Card bài viết: Ảnh trích xuất từ báo chí (nếu có), tiêu đề in đậm dễ đọc, tóm tắt sự việc 2 dòng, nguồn tin chính thức (VnExpress, Tuổi Trẻ, Cổng TTGT) kèm liên kết gốc.
  - Vị trí địa lý: Nếu bài báo đã được trích xuất tọa độ thành công, gắn nhãn xanh `"Vị trí xác minh"` và cho phép click để xem ngay trên bản đồ `/map`.

---

### 2. Trạng thái rỗng & Chống tin giả

- Khi chưa có tin tức trong khoảng thời gian đã chọn: Hiển thị Empty State trang nhã với icon báo chí, thông báo rõ ràng hệ thống đang theo dõi và không có sự cố nào ghi nhận.
- Tuyệt đối không tạo dữ liệu bài báo giả lập để lấp đầy giao diện.

