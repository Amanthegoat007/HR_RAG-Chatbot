FROM python:3.11-slim
WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# System dependencies (cached layer)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch (saves ~5GB vs CUDA — backend doesn't need GPU)
RUN pip install --default-timeout=30000 --no-cache-dir --only-binary :all: \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Install Python dependencies (only invalidated when requirements.txt changes)
COPY requirements.txt .
RUN pip install --default-timeout=30000 --no-cache-dir --prefer-binary -r requirements.txt

# Copy application source (changes most often → last layer for cache)
COPY . .

# Copy Supervisor configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 8000

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
