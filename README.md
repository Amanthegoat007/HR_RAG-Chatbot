# HR Knowledge Chatbot — On-Premises RAG System

Production-grade, on-premises RAG (Retrieval-Augmented Generation) chatbot for UAE HR policies.
14 Docker containers, CPU-only, 32 GB RAM server, supports English and Arabic documents.

**Architecture Reference**: `HR_RAG_Architecture_v2_MOM_Aligned.docx` (20 Feb 2026)

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Prerequisites](#prerequisites)
3. [First-Time Setup](#first-time-setup) ← **Start here**
4. [Starting the System](#starting-the-system)
5. [Verifying the Deployment](#verifying-the-deployment)
6. [Using the Chatbot](#using-the-chatbot)
7. [Administration](#administration)
8. [Monitoring](#monitoring)
9. [Troubleshooting](#troubleshooting)
10. [Architecture Summary](#architecture-summary)

---

## System Overview

```
User Browser
    │ HTTPS
    ▼
[nginx]  ──────────────── SSL termination, rate limiting
    │
    ├── [auth-svc]        JWT authentication (bcrypt, 8h tokens)
    ├── [query-svc]       RAG pipeline: embed → search → rerank → LLM → SSE stream
    └── [ingest-svc]      Document upload and processing
         │
         └── [ingest-worker]  Celery background: convert → chunk → embed → store

AI Services (internal):
  [embedding-svc]   BGE-M3 1024-dim dense + sparse vectors
  [reranker-svc]    BGE-Reranker-v2-m3 cross-encoder
  [llm-server]      Mistral-7B-Instruct Q5_K_M via llama.cpp

Storage:
  [postgres]   Document metadata, job tracking, audit log
  [redis]      Semantic cache (DB0), Celery broker (DB1), results (DB2)
  [minio]      S3-compatible: original files + markdown intermediates
  [qdrant]     Vector database: dense + sparse embeddings (RRF hybrid search)

Monitoring:
  [prometheus]  Metrics collection from all services
  [grafana]     Dashboard: latency, cache hit rate, queue depth, RAM
```

---

## Prerequisites

### On the Windows Host Machine

| Requirement | Version | Download |
|-------------|---------|----------|
| Docker Desktop | ≥ 4.27 | https://www.docker.com/products/docker-desktop |
| Python | 3.12+ | https://www.python.org/downloads |
| Git for Windows | Latest | https://git-scm.com/download/win |

**Docker Desktop Setup**:
1. Install Docker Desktop
2. Open Settings → General → Enable "Use WSL 2 based engine"
3. Allocate RAM: Settings → Resources → Memory → set to **24 GB** minimum
4. Apply and restart Docker Desktop

**Verify Docker is working**:
```powershell
docker --version          # Should show 24.x or higher
docker compose version    # Should show v2.x
```

---

## First-Time Setup

> Run these steps once before the first deployment.
> All commands are **Windows PowerShell** unless noted.

### Step 1: Copy Environment Configuration

```powershell
Copy-Item .env.example .env
```

Open `.env` in Notepad (or VS Code) and fill in the required values:
```
notepad .env
```

**Required values to change** (search for `CHANGE_ME`):

| Variable | Description | How to get it |
|----------|-------------|---------------|
| `ADMIN_PASSWORD_HASH` | bcrypt hash of admin password | See Step 2 |
| `USER_PASSWORD_HASH` | bcrypt hash of user password | See Step 2 |
| `JWT_SECRET` | 32+ character random string | See Step 2 |
| `MINIO_ROOT_PASSWORD` | MinIO admin password | Choose any secure password |
| `POSTGRES_PASSWORD` | PostgreSQL password | Choose any secure password |

### Step 2: Generate Password Hashes

```powershell
# Install passlib (run once)
pip install passlib[bcrypt]

# Generate hash for admin password
python utils\hash_password.py YourAdminPassword123!
# Copy the output hash into ADMIN_PASSWORD_HASH in .env

# Generate hash for user password
python utils\hash_password.py YourUserPassword456!
# Copy the output hash into USER_PASSWORD_HASH in .env

# Generate JWT secret (64 random characters)
python -c "import secrets; print(secrets.token_hex(32))"
# Copy the output into JWT_SECRET in .env
```

### Step 3: Generate SSL Certificates

For development (self-signed certificates):
```powershell
.\nginx\ssl\Generate-SelfSigned.ps1
```

This creates `nginx/ssl/cert.pem` and `nginx/ssl/key.pem` using OpenSSL inside a Docker container — no local OpenSSL installation needed.

> **Production**: Replace the generated certificates with proper CA-signed certificates from your organization. Place them at `nginx/ssl/cert.pem` and `nginx/ssl/key.pem`.

### Step 4: Download the LLM Model

The Mistral-7B model file (~5 GB) must be downloaded before the LLM server can start:

```powershell
.\services\llm\Download-Model.ps1
```

This downloads `Mistral-7B-Instruct-v0.3.Q5_K_M.gguf` (~5 GB) into `services/llm/models/`.

**Approximate download time**: 30-60 minutes on a 10 Mbps connection.

> **Note**: The AI models for embedding (BGE-M3) and reranking (BGE-Reranker-v2-m3) are
> downloaded automatically when the Docker images are built (they are baked into the images).
> Only the LLM GGUF file needs to be downloaded separately.

### Step 5: Build Docker Images

```powershell
docker compose build
```

This builds all custom service images. Expect **20-40 minutes** on first build:
- `llm-server`: Compiles llama.cpp from source (~15 min)
- `embedding-svc`: Downloads BGE-M3 model (~5 min)
- `reranker-svc`: Downloads BGE-Reranker model (~3 min)
- Other services: ~2-5 min total

---

## Starting the System

### Production Mode (Recommended)
```powershell
# Start all 14 services
docker compose up -d

# Or with production hardening (read-only filesystems, strict restarts)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### Development Mode
```powershell
# Exposes debug ports for direct service access (no nginx required)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

In dev mode, services are accessible directly:
- auth-svc: http://localhost:8001/docs
- query-svc: http://localhost:8002/docs
- ingest-svc: http://localhost:8003/docs
- Qdrant dashboard: http://localhost:6333/dashboard
- MinIO console: http://localhost:9001

### Using make.ps1 (Windows)
```powershell
.\make.ps1 up          # Start production
.\make.ps1 up-dev      # Start development
.\make.ps1 down        # Stop all services
.\make.ps1 logs        # Tail all logs
.\make.ps1 help        # Show all commands
```

---

## Verifying the Deployment

### Quick Health Check (Windows)
```powershell
.\utils\Health-Check.ps1
```

Expected output:
```
HR RAG Chatbot — Service Health Check
======================================
Application Services:
  auth-svc             HEALTHY
  query-svc            HEALTHY
  ingest-svc           HEALTHY

AI Model Services:
  ...
```

### Manual Checks
```powershell
# Check all container statuses
docker compose ps

# View startup logs for a specific service
docker compose logs auth-svc
docker compose logs embedding-svc  # Check if BGE-M3 loaded
docker compose logs llm-server     # Check if model loaded

# Test the login endpoint
$body = '{"username":"hr_admin","password":"YourAdminPassword123!"}'
Invoke-WebRequest -Uri https://localhost/auth/login -Method POST `
    -Body $body -ContentType "application/json" `
    -SkipCertificateCheck | Select-Object -ExpandProperty Content
```

### Expected Startup Time

The system takes time to start because the AI models need to load:

| Service | Startup Time |
|---------|-------------|
| postgres, redis, minio, qdrant | < 30 seconds |
| auth-svc, ingest-svc | < 60 seconds |
| embedding-svc | 2-5 minutes (loads BGE-M3) |
| reranker-svc | 1-3 minutes (loads reranker) |
| llm-server | 3-8 minutes (loads Mistral-7B) |
| query-svc | After embedding-svc is healthy |
| nginx | After auth/query/ingest are healthy |

---

## Using the Chatbot

### Web Interface
Navigate to: **https://localhost** (or your server IP)

> Accept the browser warning for the self-signed certificate in development.

### API (Direct)

**Login to get a JWT token**:
```powershell
$response = Invoke-WebRequest -Uri https://localhost/auth/login `
    -Method POST `
    -Body '{"username":"hr_user","password":"YourUserPassword456!"}' `
    -ContentType "application/json" `
    -SkipCertificateCheck
$token = ($response.Content | ConvertFrom-Json).access_token
```

**Submit a query**:
```powershell
Invoke-WebRequest -Uri https://localhost/api/query `
    -Method POST `
    -Body '{"query":"How many days of annual leave am I entitled to?"}' `
    -ContentType "application/json" `
    -Headers @{Authorization="Bearer $token"} `
    -SkipCertificateCheck
```

The response is Server-Sent Events (SSE). Each line is a JSON event:
- `event: token` — one per generated word/token
- `event: sources` — citations after the last token
- `event: done` — end of stream

### Ask About a Specific Document
```powershell
$body = '{"query":"What is the leave policy?","document_id":"<uuid-from-upload>"}'
Invoke-WebRequest -Uri https://localhost/api/query `
    -Method POST -Body $body -ContentType "application/json" `
    -Headers @{Authorization="Bearer $token"} -SkipCertificateCheck
```

---

## Administration

### Uploading Documents

Documents can be uploaded via the API (admin role required):

```powershell
# Login as admin
$response = Invoke-WebRequest -Uri https://localhost/auth/login `
    -Method POST `
    -Body '{"username":"hr_admin","password":"YourAdminPassword123!"}' `
    -ContentType "application/json" -SkipCertificateCheck
$admin_token = ($response.Content | ConvertFrom-Json).access_token

# Upload a document (PDF, DOCX, XLSX, PPTX, or TXT)
$form = @{
    file = Get-Item "path\to\leave_policy.pdf"
}
Invoke-WebRequest -Uri https://localhost/ingest/upload `
    -Method POST -Form $form `
    -Headers @{Authorization="Bearer $admin_token"} `
    -SkipCertificateCheck
```

**Supported formats**: PDF, DOCX, XLSX, PPTX, TXT (max 200 MB)
**Languages**: English and Arabic (Arabic OCR supported for scanned PDFs)

### Monitoring Document Processing
```powershell
# List all documents and their status
Invoke-WebRequest -Uri https://localhost/ingest/documents `
    -Headers @{Authorization="Bearer $admin_token"} `
    -SkipCertificateCheck | Select-Object -ExpandProperty Content | ConvertFrom-Json
```

Document status values:
- `pending` — Uploaded, waiting for Celery worker
- `processing` — Worker is converting, chunking, embedding
- `ready` — Available for queries
- `failed` — Processing error (check logs)

### Deleting Documents
```powershell
$doc_id = "your-document-uuid"
Invoke-WebRequest -Uri https://localhost/ingest/document/$doc_id `
    -Method DELETE `
    -Headers @{Authorization="Bearer $admin_token"} `
    -SkipCertificateCheck
```

This deletes: Qdrant vectors + MinIO files + PostgreSQL record.

---

## Monitoring

### Grafana Dashboard
Open: **http://localhost:3000**

Default credentials: `admin` / (value of `GF_SECURITY_ADMIN_PASSWORD` in `.env`)

The pre-built dashboard shows:
- Query latency: P50, P95, P99
- Cache hit rate (target: > 40%)
- Query throughput (RPS)
- AI model inference latency
- Ingest queue depth
- Per-service RAM usage

### Prometheus (Raw Metrics)
Open: **http://localhost:9090**

Useful queries:
```promql
# Query P95 latency over last 5 minutes
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket{service="query-svc"}[5m]))

# Cache hit rate
rate(semantic_cache_hits_total[5m]) / (rate(semantic_cache_hits_total[5m]) + rate(semantic_cache_misses_total[5m]))

# Error rate
rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])
```

### Viewing Logs
```powershell
# All services
docker compose logs -f --tail=100

# Single service
docker compose logs -f --tail=200 query-svc

# Filter for errors
docker compose logs query-svc 2>&1 | Select-String "ERROR"

# Structured JSON logs (if installed jq via Git Bash)
docker compose logs query-svc 2>&1 | python -c "import sys,json; [print(json.dumps(json.loads(l), indent=2)) for l in sys.stdin if l.startswith('{')]"
```

---

## Troubleshooting

### Services Not Starting

**Symptom**: `docker compose ps` shows containers in "starting" or "unhealthy" state.

**Check logs**:
```powershell
docker compose logs <service-name>
```

**Common causes**:

| Service | Common Cause | Fix |
|---------|-------------|-----|
| postgres | Port 5432 in use on host | Change `POSTGRES_PORT` in `.env` |
| embedding-svc | Model download failed | Check internet connection; rebuild: `docker compose build embedding-svc` |
| llm-server | Model file missing | Run `.\services\llm\Download-Model.ps1` |
| query-svc | Dependency unhealthy | Wait for embedding-svc to fully load (3-5 min) |

### Authentication Fails (401)

1. Verify your `.env` has `ADMIN_PASSWORD_HASH` / `USER_PASSWORD_HASH` set to valid bcrypt hashes.
2. Regenerate hashes: `python utils\hash_password.py YourPassword`
3. After changing `.env`, restart auth-svc: `docker compose restart auth-svc`

### Document Upload Fails

1. Check admin role: only `hr_admin` can upload documents.
2. Check file size: limit is 200 MB.
3. Check ingest-worker is running: `docker compose ps ingest-worker`
4. Check worker logs: `docker compose logs ingest-worker`

### Queries Return No Results

1. Verify documents have been uploaded and are in `ready` status.
2. Check Qdrant collection: open http://localhost:6333/dashboard (dev mode).
3. Verify embedding-svc and qdrant are healthy: `.\utils\Health-Check.ps1`

### RAM Issues (Out of Memory)

Default memory allocation for AI models:
- llm-server: 12 GB
- embedding-svc: 2 GB
- reranker-svc: 2 GB

If the server has less than 24 GB total RAM, reduce limits in `docker-compose.yml`:
- Reduce `llm-server` memory from `12g` to `8g` (use Q4_K_M model instead of Q5_K_M)
- Disable the reranker service and set `RERANKER_SVC_URL=` empty in `.env`

### Performance is Slow

1. Check CPU: LLM is CPU-only. Each query takes 5-30 seconds depending on answer length.
2. Check cache: review Grafana cache hit rate panel. Low hit rate means many unique queries.
3. Check RAM: if containers are swapping to disk, performance degrades dramatically.

---

## Architecture Summary

### RAG Pipeline (per query, steps 1-7)
1. **Cache check**: Redis semantic cache lookup (cosine similarity ≥ 0.92)
2. **Embedding**: BGE-M3 → 1024-dim dense + sparse vectors
3. **Hybrid retrieval**: Qdrant prefetch dense + sparse → RRF fusion → top-20 chunks
4. **Reranking**: BGE-Reranker-v2-m3 cross-encoder → top-5 chunks
5. **Prompt building**: Mistral-7B system prompt + context + user question
6. **LLM generation**: llama.cpp streaming → token SSE events → client
7. **Cache store**: Save answer + embeddings in Redis for future use

### Key Design Decisions
- **Convert-to-Markdown first**: All documents converted to Markdown before chunking/embedding — improves heading extraction and section attribution
- **GGML_NATIVE=ON**: llama.cpp compiled with host CPU SIMD (AVX2/AVX512) for 2-3× faster inference vs generic build
- **Deterministic point IDs**: `uuid5(NAMESPACE_DNS, f"{doc_id}:{chunk_idx}")` for safe Celery task retry
- **Same image for ingest-svc + ingest-worker**: Reduces image count; `command:` override selects API vs worker mode

---

*Generated by HR RAG Chatbot project — Architecture v2.0, Feb 2026*
