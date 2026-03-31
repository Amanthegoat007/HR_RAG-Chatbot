<#
.SYNOPSIS
    Download the Mistral-7B-Instruct-v0.3 Q5_K_M GGUF model on Windows.

.DESCRIPTION
    Downloads the ~5.14 GB model file to services\llm\models\ directory.
    Uses PowerShell's Invoke-WebRequest.
    Run this ONCE before starting the Docker Compose stack.

.USAGE
    .\services\llm\Download-Model.ps1
    (Run from the hr-rag-chatbot\ project root)

.NOTES
    Requires: ~6 GB free disk space, internet access to Hugging Face
#>

$ErrorActionPreference = "Stop"

# Configuration
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ModelDir   = Join-Path $ScriptDir "models"
$ModelFile  = "mistral-7b-instruct-v0.3.Q5_K_M.gguf"
$ModelPath  = Join-Path $ModelDir $ModelFile

# Hugging Face URLs (note: HuggingFace uses capital-M "Mistral" in the filename)
$HFModelFile = "Mistral-7B-Instruct-v0.3.Q5_K_M.gguf"
$PrimaryUrl  = "https://huggingface.co/MaziyarPanahi/Mistral-7B-Instruct-v0.3-GGUF/resolve/main/$HFModelFile"
$FallbackUrl = "https://huggingface.co/bartowski/Mistral-7B-Instruct-v0.3-GGUF/resolve/main/$HFModelFile"

# Pre-flight
Write-Host ""
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host " Mistral-7B-Instruct-v0.3 Q5_K_M Model Downloader (Windows)"   -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Target: $ModelPath"
Write-Host "Expected size: ~5.14 GB"
Write-Host ""

# Create models directory if needed
if (-not (Test-Path $ModelDir)) {
    New-Item -ItemType Directory -Path $ModelDir | Out-Null
    Write-Host "Created directory: $ModelDir"
}

# Check if model already exists
if (Test-Path $ModelPath) {
    $FileSize = (Get-Item $ModelPath).Length / 1GB
    Write-Host ("Model already exists ({0:N2} GB): $ModelPath" -f $FileSize) -ForegroundColor Green
    Write-Host "To re-download, delete the file and run this script again."
    exit 0
}

# Check available disk space (require at least 6 GB)
$Drive = Split-Path -Qualifier $ModelDir
$FreeSpaceGB = (Get-PSDrive ($Drive.TrimEnd(':'))).Free / 1GB
if ($FreeSpaceGB -lt 6) {
    Write-Host "ERROR: Insufficient disk space." -ForegroundColor Red
    Write-Host ("  Available: {0:N1} GB" -f $FreeSpaceGB)
    Write-Host "  Required:  6 GB (model ~5.14 GB + buffer)"
    exit 1
}

# Download function
function Download-File {
    param(
        [string]$Url,
        [string]$OutputPath
    )

    Write-Host "Downloading from: $Url" -ForegroundColor Yellow
    Write-Host "(This will take a while for a 5.14 GB file...)"
    Write-Host ""

    # Disable progress bar for speed (progress bar slows Invoke-WebRequest dramatically)
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $Url -OutFile $OutputPath -MaximumRedirection 10
}

# Download with fallback
try {
    Download-File -Url $PrimaryUrl -OutputPath $ModelPath
} catch {
    Write-Host "Primary download failed: $_" -ForegroundColor Yellow
    Write-Host "Trying fallback URL..."
    try {
        Download-File -Url $FallbackUrl -OutputPath $ModelPath
    } catch {
        Write-Host "ERROR: Both download attempts failed: $_" -ForegroundColor Red
        exit 1
    }
}

# Verify download
if (Test-Path $ModelPath) {
    $FileSize = (Get-Item $ModelPath).Length / 1GB
    Write-Host ""
    Write-Host "Model downloaded successfully!" -ForegroundColor Green
    Write-Host "  Path: $ModelPath"
    Write-Host ("  Size: {0:N2} GB" -f $FileSize)
    Write-Host ""
    Write-Host "You can now build and start the stack:" -ForegroundColor Cyan
    Write-Host "  docker compose build"
    Write-Host "  docker compose up -d"
} else {
    Write-Host "ERROR: Download failed. File not found at $ModelPath" -ForegroundColor Red
    exit 1
}
