# Page Design Override: Landing Page (`/`)
## SafePath AI — The Cinematic Observatory

> **Role & Intent:**
> Giới thiệu tầm vóc của một hạ tầng số đô thị thông minh (Digital Twin).
> Cho phép visual storytelling điện ảnh 3D phong phú, nhưng **không được phép làm vỡ layout văn bản, không được lag giật, và tuân thủ tuyệt đối quy tắc Zero-Mock**.

---

### 1. Phân cảnh Scrollytelling (4 Scenes)

- **Scene 01: The City Awakens (Nhìn rõ thành phố · Lối đi an toàn)**
  - *Visual:* Toàn cảnh TP.HCM 3D (pitch 48°, bearing -12°), ánh sáng cực quang cyan/indigo dịu mắt.
  - *Layout:*
    - Navigation Pill cố định trên cùng (`max-width: 1140px`, backdrop blur 20px).
    - Hero Copy bên trái: Eyebrow monospace, Headline 2 dòng, Description, CTA tìm đường, Trust Badge (Sở GTVT & KTTV).
    - **Hero Bottom Statistics:** Nằm trong luồng Flexbox/Grid tự nhiên, cách CTA tối thiểu 32px (khoảng cách an toàn, KHÔNG dùng `position: absolute; bottom: 10px; left: 0`).
    - Hero Telemetry Card bên phải: Hiển thị số ảnh trong 15 phút, chu kỳ cập nhật thật từ backend.
- **Scene 02: The City Has Eyes (Mắt thần 796 Camera)**
  - *Visual:* Camera bay hạ thấp xuống khu vực trung tâm, làm nổi bật mạng lưới camera thật.
  - *Cards:* Bộ 3 thẻ Liquid Glass có chiều sâu: Ảnh camera gốc, Ảnh AI nhận diện phương tiện (YOLO26n), Đánh giá lưu thông & nguy cơ ngập.
- **Scene 03: The City's Pulse (Bản tin giao thông thời gian thực)**
  - *Visual:* Góc nhìn ven sông Sài Gòn & các trục huyết mạch.
  - *Editorial Feed:* 2 thẻ bản tin xác thực từ các tòa soạn lớn (VnExpress, Tuổi Trẻ) và bản tin KTTV.
- **Scene 04: Choose Your Path (Định tuyến tránh ngập thông minh)**
  - *Visual:* Góc nhìn dẫn đường hướng tâm.
  - *Interaction:* So sánh tuyến thông thường vs. Tuyến đề xuất SafePath AI (ưu tiên độ cao & tránh điểm ngập), nút CTA mở `/map`.

---

### 2. Các quy tắc đặc thù của Landing Page

1. **Sửa dứt điểm Hero Bottom Overlap:**
   - Dùng CSS Grid `grid-template-columns: repeat(3, minmax(0, 1fr))` trên Desktop, chuyển sang `repeat(2, 1fr)` trên Tablet và `1fr` trên Mobile.
   - Luôn nằm bên dưới CTA và Trust Caption trong DOM tree.
   - Không bị che lấp bất kể độ dài tiêu đề (2 dòng, 3 dòng hay 4 dòng).
2. **Hiệu suất Scroll & GSAP:**
   - Không chạy `setState` liên tục ở mỗi pixel cuộn trang.
   - Dùng `startTransition` hoặc GSAP ScrollTrigger gắn với `useGSAP` để cleanup bộ nhớ.
   - Parallax chỉ áp dụng cho layer hạt bụi và mesh nền, không bao giờ di chuyển text gây mỏi mắt.
3. **Fallback khi thiếu WebGL:**
   - Khi WebGL không hỗ trợ hoặc tải bản đồ thất bại, hiển thị nền gradient Aurora nhẹ nhàng, toàn bộ nội dung văn bản và nút bấm vẫn hoạt động 100%.

