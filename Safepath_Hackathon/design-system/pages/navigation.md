# Page Design Override: Navigation & Map (`/map`)
## SafePath AI — Tactical High-Clarity HUD

> **Role & Intent:**
> Đây là màn hình tác nghiệp cốt lõi dành cho tài xế và người đi đường tại TP.HCM.
> **Quy tắc vàng: Tối đa hóa diện tích bản đồ, không có bất kỳ animation 3D thừa thãi nào làm cản trở việc xem đường hay chậm trễ thao tác.**

---

### 1. Bố cục không gian (Spatial HUD Layout)

- **Bản đồ nền (Full-bleed Map):** Chiếm toàn bộ 100vw x 100vh.
- **Top Header Pill (`z-index: 30`):**
  - Chiều cao `54px`, bo tròn 9999px, nền `rgba(15, 23, 42, 0.82)`.
  - Giữ khoảng cách `18px` từ mép trên, `20px` hai bên.
  - Chứa Logo thương hiệu, trạng thái GPS mạng lưới và kết nối WebSocket trực tiếp.
- **Floating Tactical Navigator (`z-index: 30`):**
  - Desktop: Chiều rộng cố định `380px`, đặt ở góc trái (`left: 20px`, `top: 86px`, `bottom: 86px`).
  - Mobile: Chuyển thành **Bottom Sheet** có thể kéo mở / thu gọn (`height: 38dvh` đến `58dvh`), giải phóng 100% tầm nhìn bản đồ phía trên.
- **Voice Guidance HUD (`z-index: 32`):**
  - Đặt ở vị trí trung tâm phía trên hoặc góc phải trên tablet.
  - Thiết kế dạng viên thuốc compact khi chờ, mở rộng êm ái khi có chỉ dẫn ngã rẽ.
  - Nút giọng nói tiếng Việt với sóng âm thanh (Voice bars) phản hồi trực quan.
- **Bottom Dock Controls (`z-index: 35`):**
  - Nằm ở đáy màn hình (`bottom: 24px`, căn giữa).
  - Gồm các phím chuyển đổi 2D/3D, bật lớp nguy cơ ngập (Flood Layer), mở danh mục camera và về vị trí hiện tại.

---

### 2. Tiêu chuẩn hiển thị Tuyến đường & Rủi ro

| Mức rủi ro | Màu hiển thị trên bản đồ | Độ đậm nét | Ý nghĩa an toàn |
| :--- | :--- | :--- | :--- |
| **SAFE** | `#10B981` (Emerald) | `5px` (halo 8px) | Tuyến đường cao ráo, thông thoáng, không ghi nhận ngập |
| **MODERATE** | `#F59E0B` (Amber) | `5px` (halo 8px) | Đoạn đường trũng thấp, mưa lớn có thể đọng nước |
| **CRITICAL** | `#F43F5E` (Rose) | `6px` (halo 10px pulse) | Cảnh báo ngập sâu (>20cm) hoặc kẹt xe nghiêm trọng từ camera |
| **UNKNOWN** | `#64748B` (Muted Slate) | `4px` nét đứt | Chưa có bằng chứng thực địa, cần thận trọng quan sát |

---

### 3. Nguyên tắc tương tác nghiêm ngặt

1. **Không tự ý xoay/nghiêng bản đồ khi đang tìm đường:**
   - Khi người dùng gõ tìm điểm đến hoặc xem danh sách lộ trình, giữ góc nhìn ổn định.
   - Chỉ fitBounds tự nhiên bao trọn toàn bộ tuyến đường sau khi OSRM trả về kết quả.
2. **Camera Marker không được che khuất chỉ dẫn rẽ:**
   - Dùng clustering ở zoom nhỏ (< 13).
   - Ở zoom lớn (>= 14), camera marker hiển thị icon gọn gàng 24x24px, click mở modal bằng chứng thực tế.
3. **Hiệu suất 60 FPS:**
   - Không chạy particle effect hay mesh 3D phức tạp trên trang `/map`.
   - Giữ GPU tập trung hoàn toàn cho vector tiles của MapLibre.

