#!/bin/bash
# ============================================================================
# FILE: nginx/ssl/generate-self-signed.sh
# PURPOSE: Generate a self-signed TLS certificate for development.
#          For production, replace with certificates from Let's Encrypt or your CA.
# ARCHITECTURE REF: §9 — Security Implementation
# USAGE: bash nginx/ssl/generate-self-signed.sh
#        (Run from the hr-rag-chatbot/ project root)
#        OR on Windows: see Generate-SelfSigned.ps1
# ============================================================================

set -euo pipefail

# Directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR"

echo "Generating self-signed TLS certificate for development..."
echo "Output directory: $OUTPUT_DIR"

# Generate a 2048-bit RSA private key and self-signed certificate
# -x509: output a self-signed certificate (not a CSR)
# -nodes: don't encrypt the private key (no passphrase — needed for nginx auto-start)
# -days 365: certificate valid for 1 year
# -newkey rsa:2048: generate a new 2048-bit RSA key pair
# -subj: certificate subject fields (CN=localhost for local development)
openssl req \
    -x509 \
    -nodes \
    -days 365 \
    -newkey rsa:2048 \
    -keyout "$OUTPUT_DIR/server.key" \
    -out    "$OUTPUT_DIR/server.crt" \
    -subj "/C=AE/ST=Dubai/L=Dubai/O=Esyasoft/OU=HR-RAG/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

# Set restrictive permissions on private key (readable only by owner)
chmod 600 "$OUTPUT_DIR/server.key"
chmod 644 "$OUTPUT_DIR/server.crt"

echo ""
echo "✓ Certificate generated:"
echo "  Certificate: $OUTPUT_DIR/server.crt"
echo "  Private key: $OUTPUT_DIR/server.key"
echo ""
echo "Certificate details:"
openssl x509 -in "$OUTPUT_DIR/server.crt" -noout -subject -dates
echo ""
echo "NOTE: This is a self-signed certificate for DEVELOPMENT ONLY."
echo "      Browsers will show a security warning — this is expected."
echo "      For production, replace with certificates from a trusted CA."
