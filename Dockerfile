# syntax=docker/dockerfile:1

# ---- Stage 1: build the React/Vite frontend ----
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # -> /app/frontend/dist

# ---- Stage 2: Python backend runtime (serves API + built SPA) ----
FROM python:3.11-slim AS runtime
WORKDIR /app

# gosu lets the entrypoint fix the data-volume owner, then drop to a non-root user.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

# Install the package with API extras (cached unless these change).
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[api]"

# Built frontend where FastAPI serves it (/app/frontend/dist), + entrypoint.
COPY --from=frontend /app/frontend/dist ./frontend/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENV PAYOUT_DB=/data/payout.db \
    PAYOUT_CORS_ORIGINS=* \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "payout.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
