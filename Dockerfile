# syntax=docker/dockerfile:1

# ---- Stage 1: build the React/Vite frontend ----
FROM node:20-slim AS frontend
WORKDIR /app/frontend
# install deps first (cached unless package files change)
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
# then build
COPY frontend/ ./
RUN npm run build          # -> /app/frontend/dist

# ---- Stage 2: Python backend runtime (serves API + built SPA) ----
FROM python:3.11-slim AS runtime
WORKDIR /app

# Install the package with the API extras. src + pyproject + README only,
# so the layer is cached unless those change.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[api]"

# Bring in the built frontend where FastAPI expects it (/app/frontend/dist).
COPY --from=frontend /app/frontend/dist ./frontend/dist

# The DB lives in a Docker volume mounted at /data (NOT in the repo / OneDrive).
ENV PAYOUT_DB=/data/payout.db \
    PAYOUT_CORS_ORIGINS=* \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "payout.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
