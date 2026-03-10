# ============================================================================
# FILE: services/query/Dockerfile
# PURPOSE: Lightweight query service — RAG orchestrator with SSE streaming.
#          No ML models loaded here; delegates to embedding-svc and reranker-svc.
# ARCHITECTURE REF: §4 — RAG Query Pipeline, §4.4 — auth/query/ingest Dockerfiles
# DEPENDENCIES: python:3.12-slim
# ============================================================================

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --create-home --shell /bin/bash queryuser

WORKDIR /app

COPY services/query/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --default-timeout=30000 --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/
COPY services/query/app/ /app/app/

RUN chown -R queryuser:queryuser /app

USER queryuser

EXPOSE 8002

HEALTHCHECK --interval=15s --timeout=10s --retries=5 --start-period=30s \
    CMD curl -sf http://localhost:8002/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", \
    "--workers", "1", "--log-level", "warning"]
