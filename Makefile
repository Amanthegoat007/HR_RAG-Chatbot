# ============================================================================
# FILE: Makefile
# PURPOSE: Convenience targets for Linux/WSL/Git Bash users.
#          Windows users: see make.ps1 for PowerShell equivalents.
# ARCHITECTURE REF: §8.3 — Deployment & Operations
# USAGE: make <target>
#        Run 'make help' for a full list of targets
# ============================================================================

# Default target when 'make' is run without arguments
.DEFAULT_GOAL := help

# Detect OS for platform-specific commands
UNAME_S := $(shell uname -s 2>/dev/null || echo Windows)

# Compose files
COMPOSE_BASE = docker-compose.yml
COMPOSE_DEV  = docker-compose.dev.yml
COMPOSE_PROD = docker-compose.prod.yml

# Color codes for output
RED    = \033[0;31m
GREEN  = \033[0;32m
YELLOW = \033[0;33m
NC     = \033[0m  # No Color

.PHONY: help up up-dev up-prod down restart logs ps health build pull \
        clean hash-password ssl test lint

## ─── HELP ────────────────────────────────────────────────────────────────────

help: ## Show this help message
	@echo ""
	@echo "HR RAG Chatbot — Docker Management"
	@echo "===================================="
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make $(YELLOW)<target>$(NC)\n\nTargets:\n"} \
	      /^[a-zA-Z_-]+:.*?##/ { printf "  $(GREEN)%-18s$(NC) %s\n", $$1, $$2 }' $(MAKEFILE_LIST)
	@echo ""

## ─── STACK MANAGEMENT ────────────────────────────────────────────────────────

up: ## Start all services (production mode)
	docker compose -f $(COMPOSE_BASE) up -d
	@echo "$(GREEN)Services started. Run 'make health' to verify.$(NC)"

up-dev: ## Start all services (development mode — extra ports exposed, hot-reload)
	docker compose -f $(COMPOSE_BASE) -f $(COMPOSE_DEV) up -d

up-prod: ## Start all services (production hardening — strict restarts, read-only)
	docker compose -f $(COMPOSE_BASE) -f $(COMPOSE_PROD) up -d

down: ## Stop and remove all containers (keeps volumes)
	docker compose -f $(COMPOSE_BASE) down

down-volumes: ## Stop all containers AND delete persistent volumes (⚠ DATA LOSS)
	@echo "$(RED)WARNING: This will delete all persistent data (DB, MinIO, Qdrant, Redis)!$(NC)"
	@read -p "Type 'yes' to confirm: " confirm; \
	  [ "$$confirm" = "yes" ] && docker compose -f $(COMPOSE_BASE) down -v || echo "Aborted."

restart: ## Restart all services
	docker compose -f $(COMPOSE_BASE) restart

restart-svc: ## Restart a specific service: make restart-svc SVC=query-svc
	docker compose -f $(COMPOSE_BASE) restart $(SVC)

## ─── OBSERVABILITY ───────────────────────────────────────────────────────────

logs: ## Tail logs from all services (Ctrl+C to stop)
	docker compose -f $(COMPOSE_BASE) logs -f --tail=100

logs-svc: ## Tail logs from a specific service: make logs-svc SVC=query-svc
	docker compose -f $(COMPOSE_BASE) logs -f --tail=200 $(SVC)

ps: ## Show status of all containers
	docker compose -f $(COMPOSE_BASE) ps

health: ## Run health checks on all services
	@bash utils/health_check.sh

## ─── BUILD & UPDATE ──────────────────────────────────────────────────────────

build: ## Rebuild all service images (no cache)
	docker compose -f $(COMPOSE_BASE) build --no-cache

build-svc: ## Rebuild a specific service: make build-svc SVC=ingest-svc
	docker compose -f $(COMPOSE_BASE) build --no-cache $(SVC)

pull: ## Pull latest base images (infrastructure services)
	docker compose -f $(COMPOSE_BASE) pull postgres redis minio qdrant prometheus grafana

## ─── UTILITIES ───────────────────────────────────────────────────────────────

hash-password: ## Generate bcrypt hash: make hash-password PWD=yourpassword
	python utils/hash_password.py $(PWD)

ssl: ## Generate self-signed SSL certificate for development
	bash nginx/ssl/generate-self-signed.sh

## ─── TESTING ─────────────────────────────────────────────────────────────────

test: ## Run all unit tests (requires Python + pytest installed)
	python -m pytest services/ -v --tb=short

test-load: ## Run load test (30 concurrent users): requires BASE_URL env var
	python utils/load_test.py --base-url $(or $(BASE_URL), https://localhost) --users 30

## ─── CLEANUP ─────────────────────────────────────────────────────────────────

clean: ## Remove stopped containers, unused networks, dangling images
	docker system prune -f

clean-images: ## Remove all project images (forces full rebuild)
	docker compose -f $(COMPOSE_BASE) down --rmi local
