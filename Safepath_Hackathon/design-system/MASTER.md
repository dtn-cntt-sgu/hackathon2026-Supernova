# SafePath AI — Design System Master File (Global Source of Truth)
# Language: Cinematic Urban Intelligence

> **Hierarchical Retrieval Contract:**
> When implementing or reviewing a specific route/page:
> 1. Check `design-system/safe-path-ai/pages/[page-name].md`.
> 2. If the page file exists, its rules **override** this Master file for that route.
> 3. If no page file exists, strictly adhere to the global tokens and component specifications below.

---

## 1. Brand Identity & Visual Manifesto

- **Product Name:** SafePath AI (Định tuyến thông minh & Cảnh báo ngập thời gian thực TP.HCM)
- **Visual Direction:** **Cinematic Urban Intelligence**
  - Fusion of high-precision spatial computing, dark tactical navigation HUD, and controlled liquid glass.
  - Sắc sảo, hiện đại, uy tín kỹ thuật, không rườm rà.
  - Phục vụ người tham gia giao thông trong điều kiện thời tiết phức tạp (mưa lớn, triều cường, đêm tối).
- **Core Mood:**
  - *Precision:* Từng pixel, tọa độ, con số đo đạc đều chính xác, minh bạch nguồn gốc (Zero-Mock).
  - *Atmospheric Depth:* Không gian đô thị 3D có chiều sâu, ánh sáng phản chiếu cực quang (Aurora Cyan & Indigo).
  - *Tactical Clarity:* Giao diện chỉ đường ban đêm và trời mưa phải nhìn rõ trong 0.5 giây.

---

## 2. Design Tokens Architecture (3-Layer Hierarchy)

### Layer 1: Primitive Tokens (Raw Values)

```css
:root {
  /* Primitives — Dark Navy & Urban Abyssal */
  --slate-950: #0B1120;
  --slate-900: #0F172A;
  --slate-850: #131E36;
  --slate-800: #1E293B;
  --slate-700: #334155;
  --slate-600: #475569;
  --slate-500: #64748B;
  --slate-400: #94A3B8;
  --slate-300: #CBD5E1;
  --slate-200: #E2E8F0;
  --slate-100: #F1F5F9;
  --slate-50:  #F8FAFC;

  /* Primitives — Electric Cyan & Neon Aurora */
  --cyan-500:  #00F0FF;
  --cyan-400:  #38BDF8;
  --cyan-600:  #0284C7;
  --cyan-950:  #082F49;

  --indigo-500: #6366F1;
  --indigo-600: #4F46E5;
  --indigo-400: #818CF8;
  --indigo-950: #1E1B4B;

  /* Primitives — Tactical Risk Telemetry */
  --emerald-500: #10B981;
  --emerald-400: #34D399;
  --emerald-950: #064E3B;

  --amber-500:   #F59E0B;
  --amber-400:   #FBBF24;
  --amber-950:   #78350F;

  --rose-500:    #F43F5E;
  --rose-400:    #FB7185;
  --rose-950:    #881337;
}
```

### Layer 2: Semantic Tokens (Purpose Aliases)

```css
:root {
  /* Surfaces & Canvas */
  --bg-app:             var(--slate-950);   /* Nền tổng thể #0B1120 */
  --bg-surface:         var(--slate-900);   /* Thẻ/Panel nền #0F172A */
  --bg-surface-elevated: var(--slate-850);  /* Panel nổi/Modal #131E36 */
  --bg-surface-glass:   rgba(15, 23, 42, 0.78); /* Liquid Glass Controlled */

  /* Borders & Highlights */
  --border-subtle:      rgba(255, 255, 255, 0.08);
  --border-medium:      rgba(255, 255, 255, 0.16);
  --border-active:      rgba(56, 189, 248, 0.45);
  --border-glass-shine: inset 0 1px 0 rgba(255, 255, 255, 0.15);

  /* Typography Colors (WCAG AAA Compliant) */
  --text-primary:       #F8FAFC;  /* 15.8:1 contrast on #0B1120 */
  --text-secondary:     #CBD5E1;  /* 9.4:1 contrast */
  --text-muted:         #94A3B8;  /* 5.2:1 contrast (vượt chuẩn 4.5:1) */
  --text-disabled:      #64748B;
  --text-accent:        var(--cyan-400);

  /* Tactical Signal Semantics */
  --status-safe:        var(--emerald-400);
  --status-moderate:    var(--amber-400);
  --status-critical:    var(--rose-400);
  --status-info:        var(--cyan-400);

  /* Elevation Shadows */
  --shadow-hud-sm:  0 2px 8px -1px rgba(0, 0, 0, 0.4), 0 0 1px 1px var(--border-subtle);
  --shadow-hud-md:  0 10px 25px -4px rgba(0, 0, 0, 0.5), 0 0 0 1px var(--border-medium);
  --shadow-hud-lg:  0 24px 48px -8px rgba(0, 0, 0, 0.7), 0 0 0 1px var(--border-medium);
  --shadow-neon-cyan: 0 0 20px -2px rgba(0, 240, 255, 0.35);
  --shadow-neon-blue: 0 0 25px -3px rgba(79, 70, 229, 0.4);
}
```

### Layer 3: Component Tokens (Component-Specific)

- `--btn-primary-bg`: `linear-gradient(135deg, #0284C7 0%, #2563EB 50%, #4F46E5 100%)`
- `--btn-primary-glow`: `0 0 20px rgba(56, 189, 248, 0.3)`
- `--hud-pill-bg`: `rgba(15, 23, 42, 0.85)`
- `--hud-pill-border`: `rgba(56, 189, 248, 0.25)`
- `--card-specular-glow`: `radial-gradient(400px circle at var(--spot-x) var(--spot-y), rgba(0, 240, 255, 0.12), transparent 70%)`

---

## 3. Typography Hierarchy & Font System

| Role | Font Family | Weights | Usage | Tracking |
| :--- | :--- | :--- | :--- | :--- |
| **Display / Headlines** | `Space Grotesk` (hoặc `Outfit`) | 600, 700 | Hero h1, Scene h2, Modal titles | `-0.03em` |
| **UI & Body** | `Inter` / `DM Sans` | 400, 500, 600 | Body copy, labels, dropdowns, descriptions | `0` |
| **Telemetry / HUD / Monospace** | `JetBrains Mono` / `Space Mono` | 500, 700 | Tọa độ GPS, sensor water/rain, timestamps, camera IDs | `+0.05em` |

### Scale System (8-Point Rhythm)

- `text-xs`: 12px (line-height 16px) — Metadata, chips, source attribution
- `text-sm`: 14px (line-height 20px) — Body secondary, table rows, button sm
- `text-base`: 16px (line-height 24px) — Body primary, inputs, button md
- `text-lg`: 18px (line-height 28px) — Subheaders, card titles
- `text-xl`: 20px (line-height 28px) — Section eyebrows, widget titles
- `text-2xl`: 24px (line-height 32px) — Modal headings
- `text-3xl`: 30px (line-height 36px) — Numerical statistics, sensor metrics
- `text-4xl`: 36px (line-height 40px) — Scene headings
- `text-5xl` to `text-6xl`: clamp(40px, 5vw, 64px) — Landing Hero main headline

---

## 4. Controlled Liquid Glass & HUD Shading Specs

Khắc phục triệt để lỗi "nhòe mờ chữ" và "xanh đen nặng nề":

1. **Độ trong suốt có kiểm soát:** Không dùng nền trắng đục 90% hay đen kịt 100%. Nền sử dụng `rgba(15, 23, 42, 0.82)` đối với dark theme và `rgba(255, 255, 255, 0.88)` đối với light theme khi bắt buộc.
2. **Backdrop Blur vừa đủ:** Giới hạn ở `16px - 20px` với `saturate(170%)`. Không tăng lên 40px-60px gây giật lag GPU trên mobile.
3. **Specular Highlight viền mỏng:** `box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.15)`. Ánh sáng nhẹ ở cạnh trên tạo hiệu ứng khúc xạ thủy tinh.
4. **Pointer Reactive Spotlight:** Khi rê chuột (`--spot-x`, `--spot-y`), ánh sáng phản chiếu chuyển động mượt mà không làm rung layout.

---

## 5. Interaction & Motion Rules (GSAP & CSS Transitions)

- **Micro-Interactions:**
  - Button hover: `transform: translateY(-1.5px)`, shadow tăng nhẹ, duration 200ms cubic-bezier(0.16, 1, 0.3, 1).
  - Button active/tap: `transform: scale(0.98)`, duration 100ms.
  - Card hover: nâng 2-4px, border sáng nhẹ từ `rgba(255,255,255,0.08)` lên `rgba(56,189,248,0.3)`.
- **Motion Intensity Tiers:**
  - *Tier 1 (Subtle):* Tooltip, badges, toggle switches — 150-200ms `ease-out`.
  - *Tier 2 (Standard):* Modal entrance, drawer slide, route results expansion — 300-400ms `cubic-bezier(0.16, 1, 0.3, 1)`.
  - *Tier 3 (Cinematic / Scrollytelling):* Camera transitions, GSAP scrubbed scene reveals — 600-1200ms có kiểm soát.
- **Accessibility & Reduced Motion:**
  - Mọi hiệu ứng 3D, parallax và camera tilt bắt buộc dừng khi `prefers-reduced-motion: reduce` được kích hoạt.
  - Cung cấp trạng thái tĩnh (static final state) rõ ràng, đọc được ngay lập tức.

---

## 6. Layout Systems & Responsive Breakpoints

- **Breakpoints:**
  - `mobile`: `< 640px` (Stack 1 cột, HUD bottom sheet cố định phía dưới)
  - `tablet`: `640px - 1024px` (Floating compact HUD bên cạnh, camera grid 2 cột)
  - `desktop`: `1024px - 1440px` (Side-by-side workspace, 3D viewport rộng)
  - `ultrawide`: `> 1440px` (Max content container 1280px-1440px, margin auto)
- **Spacing Scale Rhythm:**
  - 4px, 8px, 12px, 16px, 24px, 32px, 48px, 64px.
  - Không hardcode giá trị lẻ (`23px`, `27px`, `45px`) trừ khi là viền 1px/1.5px.

---

## 7. Anti-Patterns to Strictly Prohibit

1. ❌ **Không dùng `position: absolute` cho các khối nội dung chứa văn bản động:** Lỗi `.hero-bottom` bị chồng lấp lên caption do dùng absolute ở dưới cùng. Mọi thống kê phải nằm trong luồng Flexbox/Grid bình thường.
2. ❌ **Không dùng Emoji làm icon giao diện:** Sử dụng SVG vector đồng nhất từ `lucide-react` (độ dày nét 1.5px - 2px).
3. ❌ **Không giả lập dữ liệu quan trắc (Zero-Mock):** Khi không có tín hiệu camera/triều/mưa, trả về trạng thái `"Chưa có dữ liệu"` hoặc `"Bản tin trước đó"`, tuyệt đối không tự phát sinh con số 0.0 giả tạo.
4. ❌ **Không để chữ xám trên nền tối thiếu tương phản:** Text secondary tối thiểu đạt 4.5:1, text primary đạt 7:1+ trên mọi nền.
5. ❌ **Không dùng quá 1 WebGL Context trên cùng một trang:** Tái sử dụng canvas hoặc mount theo vòng đời component.
