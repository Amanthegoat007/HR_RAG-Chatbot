FROM python:3.11-slim
WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# System deps — cached until apt list changes
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    supervisor \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install CUDA PyTorch for Embeddings and Reranker
# Pinned to cu121 for H200 compatibility; separate layer for caching
RUN pip install --default-timeout=30000 --no-cache-dir torch torchvision

# Python deps — only invalidated when requirements.txt changes
COPY requirements.txt .
RUN pip install --default-timeout=30000 --no-cache-dir --prefer-binary -r requirements.txt

# Copy application source (changes most often → last layer)
COPY . .

# Copy Supervisor configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 8002

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
