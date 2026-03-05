FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies for building llama.cpp
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    git \
    wget \
    curl \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Use locally cloned llama.cpp
WORKDIR /llama.cpp
COPY llama.cpp/ .
RUN cmake -B build \
    && cmake --build build --config Release -j4 --target llama-server

# Install CPU-only PyTorch first (FlagEmbedding pulls torch, but we don't need CUDA — saves ~700MB)
WORKDIR /app
RUN pip install --default-timeout=300 --no-cache-dir \
    torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Install Python dependencies
COPY requirements.txt .
RUN pip install --default-timeout=300 --no-cache-dir -r requirements.txt

# BGE models are downloaded at first run and persist in the HF cache volume.
# They are NOT downloaded at build time (build-time network is unavailable in this environment).
# See: docker-compose.yml volumes: hf_cache -> /root/.cache/huggingface

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y supervisor curl libgomp1 && rm -rf /var/lib/apt/lists/*

# Copy built python packages
COPY --from=builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

# Copy llama.cpp server binary + shared libs (CMake builds to build/bin/)
COPY --from=builder /llama.cpp/build/bin/ /usr/local/lib/llama/
RUN ln -s /usr/local/lib/llama/llama-server /usr/local/bin/llama-server \
    && echo "/usr/local/lib/llama" > /etc/ld.so.conf.d/llama.conf && ldconfig

# Copy application source
COPY . .

# HuggingFace cache is persisted via the Docker volume (see docker-compose.yml)
# Remove offline mode — models download once on first run, then read from volume cache
# ENV HF_HUB_OFFLINE=1  (only set this after first successful model download)

# Copy Supervisor configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 8002 8080

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
