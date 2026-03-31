#!/usr/bin/env bash
# ============================================================================
# FILE: utils/health_check.sh
# PURPOSE: Check the health of all HR RAG Chatbot services via /health endpoints.
# ARCHITECTURE REF: §8.3 — Operations & Deployment
# USAGE: bash utils/health_check.sh
#        Or via Makefile: make health
#
# Platform: Linux / WSL / Git Bash (Windows)
# For native Windows PowerShell, use: utils/Health-Check.ps1
# ============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'  # No Color

# Base URL — can be overridden via environment variable
BASE_URL="${BASE_URL:-https://localhost}"

echo ""
echo "HR RAG Chatbot — Service Health Check"
echo "======================================"
echo "Base URL: ${BASE_URL}"
echo ""

# Track overall status
ALL_HEALTHY=true

check_service() {
    local name="$1"
    local url="$2"
    local expected_key="${3:-status}"

    # Use --insecure because we use self-signed certs in dev
    local response
    response=$(curl -s --insecure --max-time 10 "${url}" 2>&1)
    local exit_code=$?

    if [ $exit_code -ne 0 ]; then
        printf "  %-20s ${RED}UNREACHABLE${NC} (curl exit: %d)\n" "${name}" "$exit_code"
        ALL_HEALTHY=false
        return
    fi

    # Parse "status" field from JSON response using basic grep/awk
    local status
    status=$(echo "$response" | grep -o '"status":"[^"]*"' | head -1 | awk -F'"' '{print $4}')

    if [ "$status" = "healthy" ]; then
        printf "  %-20s ${GREEN}HEALTHY${NC}\n" "${name}"
    elif [ "$status" = "degraded" ]; then
        printf "  %-20s ${YELLOW}DEGRADED${NC}\n" "${name}"
        ALL_HEALTHY=false
    else
        printf "  %-20s ${RED}UNHEALTHY${NC} (status: %s)\n" "${name}" "${status:-unknown}"
        ALL_HEALTHY=false
    fi
}

# ── Application Services ──────────────────────────────────────────────────────
echo "Application Services:"
check_service "auth-svc"       "${BASE_URL}/auth/health"
check_service "query-svc"      "${BASE_URL}/api/health"
check_service "ingest-svc"     "${BASE_URL}/ingest/health"

echo ""
echo "AI Model Services (internal — only accessible when using dev compose):"
# These are only directly reachable in dev mode (exposed ports in docker-compose.dev.yml)
DEV_BASE="${DEV_BASE:-http://localhost}"
check_service "embedding-svc"  "${DEV_BASE}:8004/health"
check_service "reranker-svc"   "${DEV_BASE}:8005/health"
check_service "llm-server"     "${DEV_BASE}:8080/health"

echo ""

# ── Summary ────────────────────────────────────────────────────────────────────
if [ "$ALL_HEALTHY" = true ]; then
    echo -e "${GREEN}All services are healthy!${NC}"
    exit 0
else
    echo -e "${RED}One or more services are unhealthy.${NC}"
    echo "Run 'make logs-svc SVC=<service-name>' to see container logs."
    exit 1
fi
