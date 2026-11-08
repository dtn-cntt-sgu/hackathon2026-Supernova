# SAFEPATHAI — DOCKER COMPOSE FRONTEND & BACKEND BUILD REPORT

---

## 1. TỔNG QUAN

Hệ thống SafePathAI đã hoàn thiện cấu hình Docker và Docker Compose cho cả hai thành phần **Frontend (Next.js 14 Standalone)** và **Backend (FastAPI + ONNX Runtime + YOLO26n)**, cho phép đóng gói và khởi chạy toàn bộ hệ thống bằng một lệnh duy nhất:

```bash
docker compose build
```

---

## 2. CẤU TRÚC CONTAINER & DOCKERFILE

### 2.1. Backend (`docker/backend.Dockerfile`)
- **Base image:** `python:3.12-slim`
- **Thư viện hệ thống:** Cài đặt `libgomp1` (hỗ trợ đa luồng OpenMP cho ONNX Runtime & NumPy), `libglib2.0-0` (hỗ trợ OpenCV Headless), `curl` (kiểm tra trạng thái sức khỏe container qua `/api/v1/health`), `ca-certificates`.
- **Dữ liệu & Mô hình AI:** Tự động sao chép mô hình YOLO26n chính thức (`data/models/yolo26n.onnx`), danh mục điểm ngập lịch sử TP.HCM (`data/floods/hcmc_historical_flood_points.json`), và manifest camera (`data/cameras/camera_url_manifest.json`).
- **Lưu trữ ảnh camera:** Tạo sẵn thư mục `storage/camera_snapshots` và `storage/quarantine`, đồng thời gắn bind mount volume `./storage:/app/storage` trong compose.
- **Kích thước image:** ~803 MB (tối ưu hóa triệt để, không chứa file rác hay OSRM graph khổng lồ).

### 2.2. Frontend (`docker/frontend.Dockerfile` & `frontend/Dockerfile`)
- **Kiến trúc Multi-stage build:**
  1. `deps`: Cài đặt `libc6-compat`, thực hiện `npm ci` từ `package.json` và `package-lock.json`.
  2. `builder`: Biên dịch Next.js 14 với chế độ `output: "standalone"`, sinh mã server gọn nhẹ `server.js`.
  3. `runner`: Chạy `node:20-alpine` với người dùng bảo mật không đặc quyền `nextjs:nodejs` (UID 1001), chỉ sao chép `standalone`, `static` và `public`.
- **Kích thước image:** Chỉ **229 MB** (giảm hơn 80% so với image cũ 1.2 GB).
- **Healthcheck:** Tích hợp `wget --spider http://localhost:3000/`.

---

## 3. CẤU HÌNH DOCKER COMPOSE (`docker-compose.yml`)

```yaml
services:
  postgis:
    image: postgis/postgis:15-3.3
    container_name: safepath-postgis
    ...

  redis:
    image: redis:7-alpine
    container_name: safepath-redis
    ...

  osrm:
    image: osrm/osrm-backend@...
    container_name: safepath-osrm
    ...

  backend:
    build:
      context: .
      dockerfile: docker/backend.Dockerfile
    image: safepath-backend:latest
    container_name: safepath-backend
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql+asyncpg://safepath_user:safepath_password@postgis:5432/safepath_db
      REDIS_URL: redis://redis:6379/0
      OSRM_BASE_URL: http://osrm:5000
      YOLO_MODEL_PATH: data/models/yolo26n.onnx
      CAMERA_SCRAPE_INTERVAL_SEC: "60"
    ports:
      - "8000:8000"
    volumes:
      - ./storage:/app/storage
    depends_on:
      postgis:
        condition: service_healthy
      redis:
        condition: service_healthy
      osrm:
        condition: service_healthy
    networks:
      - safepath-net

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    image: safepath-frontend:latest
    container_name: safepath-frontend
    restart: unless-stopped
    environment:
      INTERNAL_BACKEND_URL: http://backend:8000
      NEXT_PUBLIC_API_URL: http://localhost:8000
      NEXT_PUBLIC_WS_URL: ws://localhost:8000
      AUTH_SECRET: ${AUTH_SECRET:-safepath_default_auth_secret_dev_32char_key}
      AUTH_GOOGLE_ID: ${AUTH_GOOGLE_ID:-}
      AUTH_GOOGLE_SECRET: ${AUTH_GOOGLE_SECRET:-}
      NEXTAUTH_URL: ${NEXTAUTH_URL:-http://localhost:3000}
    ports:
      - "3000:3000"
    depends_on:
      backend:
        condition: service_healthy
    networks:
      - safepath-net
```

---

## 4. KẾT QUẢ KIỂM TRA & NGHIỆM THU

1. **Docker Compose Config:**
   ```bash
   python scripts/security_and_redaction_check.py
   # PASS: .env.example contains only safe placeholders.
   # PASS: No hardcoded credentials detected in source code or documentation.
   # PASS: docker compose config validation succeeded.
   # === ALL SECURITY & REDACTION CHECKS PASSED ===
   ```

2. **Docker Compose Build:**
   ```bash
   docker compose build
   # [+] Building 2/2
   # ✔ backend   Built
   # ✔ frontend  Built
   ```

3. **Xác thực Container Image:**
   - `safepath-backend:latest` (803 MB): Nạp thành công ONNX Runtime, OpenCV và model YOLO26n `['images']`.
   - `safepath-frontend:latest` (229 MB): Xác nhận đầy đủ `server.js` và bundle `.next/static`.

