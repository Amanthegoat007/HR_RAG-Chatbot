#!/bin/bash
# ============================================================================
# FILE: services/llm/download_model.sh
# PURPOSE: Download the Mistral-7B-Instruct-v0.3 Q5_K_M GGUF model file.
#          Run this ONCE before starting the stack to pre-populate models/.
# ARCHITECTURE REF: §3.2 — LLM Runtime (Mistral-7B-Instruct-v0.3, Q5_K_M)
# USAGE: bash services/llm/download_model.sh
#        OR on Windows: .\services\llm\Download-Model.ps1
# NOTES:
#   - Model size: ~5.14 GB — ensure enough disk space
#   - Download source: Hugging Face Hub (TheBloke or bartowski mirror)
#   - The file is saved to services/llm/models/ (mounted in docker-compose.yml)
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MODEL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/models"
MODEL_FILE="mistral-7b-instruct-v0.3.Q5_K_M.gguf"
MODEL_PATH="$MODEL_DIR/$MODEL_FILE"

# Primary download URL (Hugging Face - bartowski's reliable mirror)
# Q5_K_M: 5-bit K-means quantization, Medium variant — best quality/size trade-off
HF_URL="https://huggingface.co/bartowski/Mistral-7B-Instruct-v0.3-GGUF/resolve/main/$MODEL_FILE"

# Fallback URL (TheBloke mirror — widely mirrored)
FALLBACK_URL="https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.3-GGUF/resolve/main/$MODEL_FILE"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
mkdir -p "$MODEL_DIR"

echo "================================================================"
echo " Mistral-7B-Instruct-v0.3 Q5_K_M Model Downloader"
echo "================================================================"
echo ""
echo " Target path: $MODEL_PATH"
echo " Expected size: ~5.14 GB"
echo ""

# Check if model already exists
if [ -f "$MODEL_PATH" ]; then
    FILE_SIZE=$(du -h "$MODEL_PATH" | cut -f1)
    echo "✓ Model already exists ($FILE_SIZE): $MODEL_PATH"
    echo "  To re-download, delete the file and run this script again."
    exit 0
fi

# Check available disk space (need at least 6 GB)
AVAILABLE_KB=$(df -k "$MODEL_DIR" | tail -1 | awk '{print $4}')
REQUIRED_KB=$((6 * 1024 * 1024))  # 6 GB in KB
if [ "$AVAILABLE_KB" -lt "$REQUIRED_KB" ]; then
    echo "ERROR: Insufficient disk space."
    echo "  Available: $((AVAILABLE_KB / 1024 / 1024)) GB"
    echo "  Required:  6 GB (model ~5.14 GB + buffer)"
    exit 1
fi

# ---------------------------------------------------------------------------
# Download with wget or curl (whichever is available)
# ---------------------------------------------------------------------------
download_with_progress() {
    local url="$1"
    local output="$2"

    if command -v wget &>/dev/null; then
        wget --progress=bar:force --show-progress -O "$output" "$url"
    elif command -v curl &>/dev/null; then
        curl -L --progress-bar -o "$output" "$url"
    else
        echo "ERROR: Neither wget nor curl is installed."
        exit 1
    fi
}

echo "Downloading from primary source (Hugging Face)..."
echo "URL: $HF_URL"
echo ""

# Attempt primary download
if ! download_with_progress "$HF_URL" "$MODEL_PATH"; then
    echo ""
    echo "Primary download failed. Trying fallback URL..."
    echo "URL: $FALLBACK_URL"
    download_with_progress "$FALLBACK_URL" "$MODEL_PATH"
fi

# Verify download
if [ -f "$MODEL_PATH" ]; then
    FILE_SIZE=$(du -h "$MODEL_PATH" | cut -f1)
    echo ""
    echo "✓ Model downloaded successfully!"
    echo "  Path: $MODEL_PATH"
    echo "  Size: $FILE_SIZE"
    echo ""
    echo "You can now start the stack:"
    echo "  docker compose up -d"
else
    echo "ERROR: Download failed — file not found at $MODEL_PATH"
    exit 1
fi
