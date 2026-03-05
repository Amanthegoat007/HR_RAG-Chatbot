<#
.SYNOPSIS
    Generate a self-signed TLS certificate for development on Windows.

.DESCRIPTION
    Uses Docker to run OpenSSL (avoiding the need to install OpenSSL natively on Windows).
    Generates server.key and server.crt in nginx/ssl/ directory.
    For production, replace these files with certificates from Let's Encrypt or your CA.

.USAGE
    .\nginx\ssl\Generate-SelfSigned.ps1
    (Run from the hr-rag-chatbot\ project root)

.NOTES
    Requires Docker Desktop to be running (uses alpine image with openssl).
#>

$ErrorActionPreference = "Stop"

# Resolve output directory (nginx/ssl relative to script location)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$OutputDir = $ScriptDir

Write-Host "Generating self-signed TLS certificate for development..." -ForegroundColor Yellow
Write-Host "Output directory: $OutputDir"

# Check Docker is running
try {
    docker version | Out-Null
}
catch {
    Write-Host "ERROR: Docker Desktop is not running. Please start Docker Desktop and try again." -ForegroundColor Red
    exit 1
}

# Use Docker to run OpenSSL
docker run --rm `
    -v "${OutputDir}:/ssl" `
    alpine/openssl `
    req `
    -x509 `
    -nodes `
    -days 365 `
    -newkey rsa:2048 `
    -keyout /ssl/server.key `
    -out    /ssl/server.crt `
    -subj "/C=AE/ST=Dubai/L=Dubai/O=Esyasoft/OU=HR-RAG/CN=localhost" `
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Certificate generation failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Certificate generated successfully:" -ForegroundColor Green
Write-Host "  Certificate: $OutputDir\server.crt"
Write-Host "  Private key: $OutputDir\server.key"
Write-Host ""
Write-Host "NOTE: This is a self-signed certificate for DEVELOPMENT ONLY." -ForegroundColor Yellow
Write-Host "      Browsers will show a security warning. This is expected."
Write-Host "      For production, replace with certificates from a trusted CA."
