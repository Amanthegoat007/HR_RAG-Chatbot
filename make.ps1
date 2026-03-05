<#
.SYNOPSIS
    Windows PowerShell equivalent of the Makefile for HR RAG Chatbot management.

.DESCRIPTION
    Provides convenience commands for managing the Docker Compose stack on Windows.
    All commands call standard Docker CLI which works identically on Windows with Docker Desktop.

.ARCHITECTURE REF
    §8.3 — Deployment & Operations

.USAGE
    .\make.ps1 <command> [options]
    .\make.ps1 help          # Show all commands
    .\make.ps1 up            # Start all services
    .\make.ps1 health        # Run health checks
    .\make.ps1 hash-password -Password "yourpassword"

.NOTES
    Requires: Docker Desktop ≥ 4.27 with WSL2 backend
    Requires: Python 3.12 on PATH (for utility scripts)
#>

param(
    [Parameter(Position = 0)]
    [string]$Command = "help",

    [Parameter(Position = 1)]
    [string]$Service = "",

    [string]$Password = "",
    [string]$BaseUrl = "https://localhost"
)

# Base compose file paths
$ComposeBase = "docker-compose.yml"
$ComposeDev  = "docker-compose.dev.yml"
$ComposeProd = "docker-compose.prod.yml"

# Helper: print colored output
function Write-Green  { param($msg) Write-Host $msg -ForegroundColor Green }
function Write-Yellow { param($msg) Write-Host $msg -ForegroundColor Yellow }
function Write-Red    { param($msg) Write-Host $msg -ForegroundColor Red }

switch ($Command) {

    "help" {
        Write-Host ""
        Write-Green "HR RAG Chatbot — Docker Management (PowerShell)"
        Write-Green "================================================"
        Write-Host ""
        Write-Yellow "Stack Management:"
        Write-Host "  .\make.ps1 up              Start all services (production mode)"
        Write-Host "  .\make.ps1 up-dev           Start with development overrides (extra ports, hot-reload)"
        Write-Host "  .\make.ps1 up-prod          Start with production hardening"
        Write-Host "  .\make.ps1 down             Stop and remove containers (keeps volumes)"
        Write-Host "  .\make.ps1 down-volumes     Stop containers AND delete volumes (WARNING: data loss)"
        Write-Host "  .\make.ps1 restart          Restart all services"
        Write-Host "  .\make.ps1 restart -Service <name>  Restart a specific service"
        Write-Host ""
        Write-Yellow "Observability:"
        Write-Host "  .\make.ps1 logs             Tail logs from all services"
        Write-Host "  .\make.ps1 logs -Service <name>     Tail logs from a specific service"
        Write-Host "  .\make.ps1 ps               Show container status"
        Write-Host "  .\make.ps1 health           Run health checks on all services"
        Write-Host ""
        Write-Yellow "Build & Update:"
        Write-Host "  .\make.ps1 build            Rebuild all images (no cache)"
        Write-Host "  .\make.ps1 build -Service <name>    Rebuild a specific service"
        Write-Host "  .\make.ps1 pull             Pull latest base images"
        Write-Host ""
        Write-Yellow "Utilities:"
        Write-Host "  .\make.ps1 hash-password -Password <pwd>   Generate bcrypt hash"
        Write-Host "  .\make.ps1 ssl              Generate self-signed SSL certificate"
        Write-Host ""
        Write-Yellow "Testing:"
        Write-Host "  .\make.ps1 test             Run all unit tests"
        Write-Host "  .\make.ps1 test-load -BaseUrl <url>   Run load test (30 concurrent users)"
        Write-Host ""
    }

    "up" {
        Write-Yellow "Starting all services (production mode)..."
        docker compose -f $ComposeBase up -d
        if ($LASTEXITCODE -eq 0) {
            Write-Green "Services started. Run '.\make.ps1 health' to verify."
        }
    }

    "up-dev" {
        Write-Yellow "Starting all services (development mode — extra ports, hot-reload)..."
        docker compose -f $ComposeBase -f $ComposeDev up -d
    }

    "up-prod" {
        Write-Yellow "Starting all services (production hardening)..."
        docker compose -f $ComposeBase -f $ComposeProd up -d
    }

    "down" {
        Write-Yellow "Stopping and removing containers (volumes preserved)..."
        docker compose -f $ComposeBase down
    }

    "down-volumes" {
        Write-Red "WARNING: This will permanently delete all data (DB, MinIO, Qdrant, Redis)!"
        $confirm = Read-Host "Type 'yes' to confirm"
        if ($confirm -eq "yes") {
            docker compose -f $ComposeBase down -v
            Write-Green "All containers and volumes removed."
        } else {
            Write-Yellow "Aborted."
        }
    }

    "restart" {
        if ($Service) {
            Write-Yellow "Restarting $Service..."
            docker compose -f $ComposeBase restart $Service
        } else {
            Write-Yellow "Restarting all services..."
            docker compose -f $ComposeBase restart
        }
    }

    "logs" {
        if ($Service) {
            docker compose -f $ComposeBase logs -f --tail=200 $Service
        } else {
            docker compose -f $ComposeBase logs -f --tail=100
        }
    }

    "ps" {
        docker compose -f $ComposeBase ps
    }

    "health" {
        Write-Yellow "Running health checks on all services..."
        & .\utils\Health-Check.ps1
    }

    "build" {
        if ($Service) {
            Write-Yellow "Rebuilding $Service (no cache)..."
            docker compose -f $ComposeBase build --no-cache $Service
        } else {
            Write-Yellow "Rebuilding all services (no cache)..."
            docker compose -f $ComposeBase build --no-cache
        }
    }

    "pull" {
        Write-Yellow "Pulling latest base images..."
        docker compose -f $ComposeBase pull postgres redis minio qdrant prometheus grafana
    }

    "hash-password" {
        if (-not $Password) {
            $Password = Read-Host "Enter password to hash"
        }
        python utils\hash_password.py $Password
    }

    "ssl" {
        Write-Yellow "Generating self-signed SSL certificate..."
        & .\nginx\ssl\Generate-SelfSigned.ps1
    }

    "test" {
        Write-Yellow "Running unit tests..."
        python -m pytest services/ -v --tb=short
    }

    "test-load" {
        Write-Yellow "Running load test against $BaseUrl (30 concurrent users)..."
        python utils\load_test.py --base-url $BaseUrl --users 30
    }

    "clean" {
        Write-Yellow "Removing stopped containers, unused networks, dangling images..."
        docker system prune -f
    }

    default {
        Write-Red "Unknown command: $Command"
        Write-Yellow "Run '.\make.ps1 help' for available commands."
        exit 1
    }
}
