# ============================================================================
# FILE: services/embed/Dockerfile
# PURPOSE: Build the embedding service image with BGE-M3 model pre-downloaded.
#          Baking the model into the image means fast container startup
#          (no download on each container start — critical for on-premises deployment).
# ARCHITECTURE REF: §3.3 — BGE-M3 Optimization for CPU, §4.2 — embed-svc Dockerfile
# DEPENDENCIES: python:3.12-slim, torch (CPU), FlagEmbedding
# ============================================================================

FROM python:3.12-slim

# Avoid interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
# CPU PARALLELISM ENVIRONMENT VARIABLES
# Set at image level so they apply to both uvicorn server and model inference
# OMP_NUM_THREADS: OpenMP threads for BLAS/numpy operations
# MKL_NUM_THREADS: Intel MKL threads (if PyTorch built with MKL)
# Tune to available CPU cores, leaving headroom for other services
# With 8-core server and multiple services, 4 threads is a good balance
# ---------------------------------------------------------------------------
ENV OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    TOKENIZERS_PARALLELISM=false \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
# libgomp1: OpenMP runtime (required by PyTorch CPU operations)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user (security: don't run ML inference as root)
RUN useradd --system --create-home --shell /bin/bash embeduser

WORKDIR /app

# ---------------------------------------------------------------------------
# INSTALL PYTHON DEPENDENCIES
# Install in a separate step (cached by Docker if requirements.txt unchanged)
# ---------------------------------------------------------------------------
COPY services/embed/requirements.txt .

# CPU-only PyTorch — saves ~1.5 GB compared to CUDA version
# Using index URL to get CPU-only wheel (not default from PyPI)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# ---------------------------------------------------------------------------
# NOTE: Model pre-download removed from build step due to dependency conflicts.
# The BGE-M3 model (~1.1 GB) will auto-download on first container start.
# First startup will take 2-3 minutes longer. Subsequent starts are instant
# if the container's filesystem is preserved (or use a named volume for cache).
# ---------------------------------------------------------------------------

# Copy shared utilities (jwt_utils not needed here, but logging is)
COPY shared/ /app/shared/

# Copy service application code
COPY services/embed/app/ /app/app/

# Change ownership to non-root user
RUN chown -R embeduser:embeduser /app

USER embeduser

EXPOSE 8004

# Health check — calls the /health endpoint
HEALTHCHECK --interval=15s --timeout=10s --retries=5 --start-period=120s \
    CMD curl -sf http://localhost:8004/health || exit 1

# Start FastAPI server with uvicorn
# --workers 1: single worker (asyncio handles concurrency; multiple workers would
#              load multiple model copies, exhausting RAM on a 32GB server)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004", \
    "--workers", "1", "--log-level", "warning"]
