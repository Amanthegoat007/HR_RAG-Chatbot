# ============================================================================
# FILE: services/llm/Dockerfile
# PURPOSE: Build llama.cpp HTTP server from source with host-CPU optimizations.
#          GGML_NATIVE=ON detects and uses AVX2/AVX-512 SIMD instructions
#          for 20-40% faster inference compared to pre-built generic binaries.
# ARCHITECTURE REF: §3.2 — LLM Runtime Configuration, §4.1 — llm-server Dockerfile
# DEPENDENCIES: ubuntu:24.04 (builder), ubuntu:24.04 (runtime)
# ============================================================================

# ─── STAGE 1: BUILDER ────────────────────────────────────────────────────────
# Build llama.cpp from source with CPU-specific optimizations.
# This stage is discarded after building — only the binary is kept.
FROM ubuntu:24.04 AS builder

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install build dependencies
# - build-essential: gcc, g++, make
# - cmake: build system (required by llama.cpp)
# - git: clone the repository
# - libcurl4-openssl-dev: for HTTP client in llama-server
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    libcurl4-openssl-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone llama.cpp — pin to a specific tag for reproducible builds
# b3400 is a stable release that supports all features we need
ARG LLAMA_CPP_TAG=b3400
RUN git clone --depth 1 --branch ${LLAMA_CPP_TAG} \
    https://github.com/ggerganov/llama.cpp.git /llama.cpp \
    || git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /llama.cpp

WORKDIR /llama.cpp

# Build with CPU optimizations
# GGML_NATIVE=ON: auto-detect host CPU capabilities (AVX2, AVX-512, FMA, etc.)
#                 This is why we build from source — pre-built binaries are generic x86_64
#                 and don't use advanced SIMD instructions
# GGML_CPU_AARCH64=OFF: we're on x86_64, not ARM
# CMAKE_BUILD_TYPE=Release: enable compiler optimizations (-O3, LTO)
# LLAMA_SERVER=ON: build the HTTP server (our entry point)
RUN cmake -B build \
    -DGGML_NATIVE=ON \
    -DGGML_CPU_AARCH64=OFF \
    -DCMAKE_BUILD_TYPE=Release \
    -DLLAMA_SERVER=ON \
    -DLLAMA_CURL=ON \
    # Use all available CPU cores for compilation (faster build)
    && cmake --build build --config Release --target llama-server -j$(nproc)

# ─── STAGE 2: RUNTIME ─────────────────────────────────────────────────────────
# Minimal runtime image — only the compiled binary and its runtime dependencies.
# Dramatically smaller than the builder image (no compiler, no source code).
FROM ubuntu:24.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive

# Install only runtime dependencies (not build tools)
# - libgomp1: OpenMP runtime for multi-threaded inference
# - libcurl4: HTTP client runtime
# - curl: used for the HEALTHCHECK command
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libcurl4 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy compiled server binary and shared libraries from the builder stage
COPY --from=builder /llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
COPY --from=builder /llama.cpp/build/src/libllama.so /usr/local/lib/libllama.so
COPY --from=builder /llama.cpp/build/ggml/src/libggml*.so /usr/local/lib/

# Ensure shared libraries are found at runtime
RUN ldconfig

# Make binary executable
RUN chmod +x /usr/local/bin/llama-server

# Create non-root user for security
# The model files are mounted read-only, so no write permissions needed
RUN useradd --system --no-create-home --shell /sbin/nologin llama

# Create the models mount point directory with correct permissions
RUN mkdir -p /models && chown llama:llama /models

USER llama

# Expose llama.cpp HTTP server port
EXPOSE 8080

# Health check — llama.cpp exposes /health when the model is fully loaded
HEALTHCHECK --interval=30s --timeout=15s --retries=5 --start-period=120s \
    CMD curl -sf http://localhost:8080/health || exit 1

# Default command — overridden by docker-compose.yml with model path and flags
# See docker-compose.yml service 'llm-server' for the full command with all optimization flags
ENTRYPOINT ["llama-server"]
