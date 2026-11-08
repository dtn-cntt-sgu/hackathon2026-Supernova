# ==============================================================================
# SAFEPATHAI — BACKEND DOCKERFILE (FASTAPI + ONNX RUNTIME + POSTGIS + OSRM)
# ==============================================================================
FROM python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp

WORKDIR /app

# Apply available distro security fixes; healthcheck uses the existing Python runtime.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    libgomp1 \
    libglib2.0-0 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code and data
COPY backend backend
COPY data data
COPY scripts scripts
COPY list_camera_coordinate.txt .
COPY alembic.ini .

# Create storage directories
RUN groupadd --gid 10001 safepath && useradd --uid 10001 --gid 10001 --no-create-home safepath \
    && mkdir -p storage/camera_snapshots storage/quarantine storage/cams storage/snapshots \
    && chown -R safepath:safepath storage

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/live', timeout=3)"

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "25"]
