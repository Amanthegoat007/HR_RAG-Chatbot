# ============================================================================
# FILE: utils/Health-Check.ps1
# PURPOSE: Windows PowerShell health check for all HR RAG Chatbot services.
# ARCHITECTURE REF: §8.3 — Operations & Deployment
# USAGE: .\utils\Health-Check.ps1
#        Or: .\utils\Health-Check.ps1 -BaseUrl https://myserver
#
# Platform: Windows PowerShell 5.1+ / PowerShell 7+
# For Linux/WSL/Git Bash, use: bash utils/health_check.sh
# ============================================================================

param(
    [string]$BaseUrl = "https://localhost",
    [string]$DevBaseUrl = "http://localhost"
)

# Skip SSL certificate validation for self-signed dev certs
# (PowerShell 7+ method)
if ($PSVersionTable.PSVersion.Major -ge 7) {
    $null = [System.Net.Http.HttpClientHandler]::new()
}

# PowerShell 5.1 method — add type for ignoring cert errors
Add-Type @"
    using System.Net;
    using System.Security.Cryptography.X509Certificates;
    public class TrustAll : ICertificatePolicy {
        public bool CheckValidationResult(ServicePoint sp, X509Certificate cert, WebRequest req, int prob) {
            return true;
        }
    }
"@ -ErrorAction SilentlyContinue
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAll -ErrorAction SilentlyContinue

# ─── Colors ───────────────────────────────────────────────────────────────────
$Green  = [System.ConsoleColor]::Green
$Red    = [System.ConsoleColor]::Red
$Yellow = [System.ConsoleColor]::Yellow

Write-Host ""
Write-Host "HR RAG Chatbot — Service Health Check" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "Base URL: $BaseUrl"
Write-Host ""

$AllHealthy = $true

function Test-ServiceHealth {
    param(
        [string]$Name,
        [string]$Url,
        [int]$TimeoutSeconds = 10
    )

    $padded = $Name.PadRight(22)

    try {
        # Use Invoke-WebRequest with -SkipCertificateCheck (PS7+) or -UseBasicParsing (PS5)
        $params = @{
            Uri             = $Url
            Method          = "GET"
            TimeoutSec      = $TimeoutSeconds
            UseBasicParsing = $true
            ErrorAction     = "Stop"
        }

        # Add SkipCertificateCheck for PowerShell 7+
        if ($PSVersionTable.PSVersion.Major -ge 7) {
            $params["SkipCertificateCheck"] = $true
        }

        $response = Invoke-WebRequest @params
        $body     = $response.Content | ConvertFrom-Json -ErrorAction SilentlyContinue
        $status   = $body.status

        if ($status -eq "healthy") {
            Write-Host "  $padded" -NoNewline
            Write-Host "HEALTHY" -ForegroundColor $Green
        } elseif ($status -eq "degraded") {
            Write-Host "  $padded" -NoNewline
            Write-Host "DEGRADED" -ForegroundColor $Yellow
            $script:AllHealthy = $false
        } else {
            Write-Host "  $padded" -NoNewline
            Write-Host "UNHEALTHY (status: $status)" -ForegroundColor $Red
            $script:AllHealthy = $false
        }

    } catch [System.Net.WebException] {
        Write-Host "  $padded" -NoNewline
        Write-Host "UNREACHABLE ($($_.Exception.Message))" -ForegroundColor $Red
        $script:AllHealthy = $false

    } catch {
        Write-Host "  $padded" -NoNewline
        Write-Host "ERROR ($($_.Exception.Message))" -ForegroundColor $Red
        $script:AllHealthy = $false
    }
}

# ─── Application Services ─────────────────────────────────────────────────────
Write-Host "Application Services:"
Test-ServiceHealth -Name "auth-svc"   -Url "$BaseUrl/auth/health"
Test-ServiceHealth -Name "query-svc"  -Url "$BaseUrl/api/health"
Test-ServiceHealth -Name "ingest-svc" -Url "$BaseUrl/ingest/health"

Write-Host ""
Write-Host "AI Model Services (internal — only reachable in dev mode):"
Test-ServiceHealth -Name "embedding-svc" -Url "${DevBaseUrl}:8004/health"
Test-ServiceHealth -Name "reranker-svc"  -Url "${DevBaseUrl}:8005/health"
Test-ServiceHealth -Name "llm-server"    -Url "${DevBaseUrl}:8080/health"

Write-Host ""

# ─── Summary ──────────────────────────────────────────────────────────────────
if ($AllHealthy) {
    Write-Host "All services are healthy!" -ForegroundColor $Green
    exit 0
} else {
    Write-Host "One or more services are unhealthy." -ForegroundColor $Red
    Write-Host "To see container logs: docker compose logs <service-name>" -ForegroundColor $Yellow
    exit 1
}
