# ============================================================================
# FILE: services/ingest/Dockerfile
# PURPOSE: Ingest service image — handles document upload API AND background
#          Celery worker. Both use the same image with different CMD.
#          Includes Tesseract OCR for scanned PDFs and full document processing stack.
# ARCHITECTURE REF: §3 — Document Ingestion Pipeline, §4.5 — ingest-svc Dockerfile
# DEPENDENCIES: python:3.12-slim, Tesseract OCR, poppler-utils, libmagic
# ============================================================================

FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ---------------------------------------------------------------------------
# SYSTEM DEPENDENCIES
# - tesseract-ocr: OCR engine for scanned PDF pages
# - tesseract-ocr-ara: Arabic language data for OCR (UAE HR docs may have Arabic)
# - poppler-utils: PDF tools (pdfinfo, pdftotext) used by Unstructured.io
# - libmagic1: MIME type detection (python-magic uses this)
# - libgomp1: OpenMP runtime for Unstructured.io ML components
# - curl: health checks
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ara \
    poppler-utils \
    libmagic1 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd --system --create-home --shell /bin/bash ingestuser

WORKDIR /app

# Install Python dependencies
COPY services/ingest/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy shared utilities and service code
COPY shared/ /app/shared/
COPY services/ingest/app/ /app/app/

RUN chown -R ingestuser:ingestuser /app

USER ingestuser

EXPOSE 8003

HEALTHCHECK --interval=15s --timeout=10s --retries=5 --start-period=30s \
    CMD curl -sf http://localhost:8003/health || exit 1

# Default CMD: FastAPI API server (for ingest-svc)
# docker-compose.yml overrides this for ingest-worker with Celery command
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003", \
    "--workers", "1", "--log-level", "warning"]
