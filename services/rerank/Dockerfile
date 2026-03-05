# ============================================================================
# FILE: services/rerank/Dockerfile
# PURPOSE: Build the reranker service with BGE-Reranker-v2-m3 pre-downloaded.
#          Cross-encoder reranking: scores (query, document) pairs for relevance.
# ARCHITECTURE REF: §4.2 — Reranking, §4.3 — reranker-svc Dockerfile
# DEPENDENCIES: python:3.12-slim, torch (CPU), FlagEmbedding
# ============================================================================

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive

# CPU parallelism settings (same rationale as embed-svc)
ENV OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    TOKENIZERS_PARALLELISM=false \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --system --create-home --shell /bin/bash rerankuser

WORKDIR /app

COPY services/rerank/requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# NOTE: Model pre-download removed from build step due to dependency conflicts.
# The BGE-Reranker model will auto-download on first container start.
# First startup will take 1-2 minutes longer.

COPY shared/ /app/shared/
COPY services/rerank/app/ /app/app/

RUN chown -R rerankuser:rerankuser /app

USER rerankuser

EXPOSE 8005

HEALTHCHECK --interval=15s --timeout=10s --retries=5 --start-period=120s \
    CMD curl -sf http://localhost:8005/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005", \
    "--workers", "1", "--log-level", "warning"]
