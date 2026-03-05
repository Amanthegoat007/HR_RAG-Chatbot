FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (for Supervisor and potential Python packages)
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first (docling pulls torch, but we don't need CUDA — saves ~700MB)
RUN pip install --default-timeout=300 --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Install Python dependencies
COPY requirements.txt .
RUN pip install --default-timeout=300 --no-cache-dir -r requirements.txt

# Copy shared library (assuming it's mounted in docker-compose, but good practice to copy if standalone)
# In docker-compose, we'll mount /app/shared

# Copy application source
COPY . .

# Copy Supervisor configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Expose FastAPI port
EXPOSE 8000

# Start Supervisor
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
