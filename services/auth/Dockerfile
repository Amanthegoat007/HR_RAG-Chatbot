# ============================================================================
# FILE: services/auth/Dockerfile
# PURPOSE: Lightweight auth service image for JWT-based authentication.
#          Handles login, JWT issuance, and audit logging only.
# ARCHITECTURE REF: §9 — Security Implementation, §4.4 — auth/query/ingest Dockerfiles
# DEPENDENCIES: python:3.12-slim
# ============================================================================

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (security hardening — no reason to run auth as root)
RUN useradd --system --create-home --shell /bin/bash authuser

WORKDIR /app

COPY services/auth/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy shared utilities
COPY shared/ /app/shared/

# Copy service code
COPY services/auth/app/ /app/app/

RUN chown -R authuser:authuser /app

USER authuser

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=5s --retries=5 --start-period=15s \
    CMD curl -sf http://localhost:8001/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", \
    "--workers", "1", "--log-level", "warning"]
