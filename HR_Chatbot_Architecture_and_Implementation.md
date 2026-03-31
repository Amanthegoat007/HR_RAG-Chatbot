# HR RAG Chatbot: Comprehensive Implementation & Architecture Analysis

## 1. Executive Summary
The HR RAG Chatbot is a sophisticated, microservices-based Retrieval-Augmented Generation (RAG) system. It enables users to ask HR-related questions and receive accurate, context-grounded answers extracted from uploaded HR policy documents. The system leverages state-of-the-art retrieval methodologies (hybrid dense and sparse search, reciprocal rank fusion, and cross-encoder reranking) with a robust ingestion pipeline and a fallback-capable LLM architecture.

---

## 2. Technology Stack
* **Frontend:** React, Vite (Single Page Application).
* **API Gateway / Proxy:** NGINX (SSL termination, rate limiting, SSE streaming configuration).
* **Backend Monolith & Microservices:** Python 3.11, FastAPI, Uvicorn.
* **Databases & Caching:**
  * **Relational DB:** PostgreSQL (Stores documents, ingestion jobs, conversational history, messages, audit logs).
  * **Vector DB:** Qdrant (Stores dense and sparse vectors for Hybrid Search).
  * **Semantic Cache / Message Broker:** Redis (Valkey) handled via `redis-py` (Caches semantically similar queries; Celery broker & backend).
  * **Object Storage:** MinIO (Stores original uploaded documents and parsed markdown artifacts).
* **Document Processing & Background Jobs:** Celery, NLTK, TikToken.
* **Machine Learning & AI Models (In-Process & Dedicated):**
  * **Embedding Model:** BAAI/bge-m3 (In-process inference using `FlagEmbedding` and CPU PyTorch without FP16).
  * **Cross-Encoder Reranker:** BAAI/bge-reranker-v2-m3 (In-process `FlagReranker`).
  * **LLM Server:** llama.cpp (HTTP server) running `Mistral-7B-Instruct-v0.3 Q5_K_M` locally, falling back to Azure OpenAI automatically if unavailable.
* **DevOps & Infrastructure:** Docker, Docker Compose (10 containerized services), Prometheus & Grafana (Monitoring stack).

---

## 3. High-Level Architecture & Microservices
The system relies on 10 interconnected Docker containers defined in `docker-compose.yml`:
1. **frontend:** Serves the Vite React single-page application.
2. **nginx:** Reverse proxy routing requests to `auth-svc`, `query-svc`, `ingest-svc`, and serving static frontend files.
3. **auth-svc (Auth Service):** Handles user authentication using static accounts, issuing JWT tokens in secure HttpOnly cookies.
4. **query-svc (Backend / BFF):** Manages conversations, proxies chats to the RAG pipeline, tracks messages in Postgres, and manages SSE streaming.
5. **ingest-svc (Ingest API):** FastAPI service handling document uploads to MinIO and queuing background processing.
6. **ingest-worker:** Celery async worker converting documents, generating embeddings, and upserting data to Qdrant.
7. **rag-pipeline:** The core intelligence orchestration service (retrieval, reranking, caching, LLM integration, and answer planning).
8. **postgres:** Relational state storage database.
9. **redis:** Cache and task broker.
10. **qdrant:** The vector database engine.
11. **minio:** S3-compatible object bucket for documents.
12. **monitoring:** (Optional) Prometheus observability stack.

---

## 4. Key Components and Subsystems

### 4.1 Authentication & Security (`auth-svc`)
* **Mechanism:** Relies on stateless JWT authentication. Includes short-lived access tokens and longer-lived refresh tokens securely delivered in `HttpOnly`, `SameSite=Lax` cookies to mitigate XSS attacks.
* **Role-Based Access Control (RBAC):** Two predefined static accounts (`hr_user` and `hr_admin`) with hashed passwods (bcrypt, cost 12).
* **IDOR Protection:** The Backend validates conversation ownership directly from Postgres before allowing message reads/writes.
* **Audit Logging:** Every login attempt, document upload, and deletion is recorded securely in an `audit_log` table.

### 4.2 Document Ingestion Pipeline (`ingest-svc` & `ingest-worker`)
* **API Entry:** Admins POST `/ingest/upload` to the ingress API. Files are stored in MinIO immediately, creating a `pending` metadata entry in PostgreSQL.
* **Asynchronous Processing (Celery):** The worker picks up the job.
* **Normalization & Chunking:** Documents are converted to structured Markdown. The intelligent chunker preserves heading paths and handles specialized chunks (e.g., Table rows, Lists) independently to maintain contextual structure.
* **Contextual Headers:** Applies Anthropic’s Contextual Retrieval strategy by prepending the chunk hierarchy (Document > Section > Page > Table/Row) directly into the chunk text before embedding.
* **Embedding & Indexing:** Pushes chunks to the Embedding Service to compute Dense vectors and Sparse weights simultaneously, then stores them in **Qdrant** with unique UUIDs.

### 4.3 RAG Retrieval Pipeline (`rag-pipeline`)
The core orchestrator implements an advanced 7-step approach:
1. **Query Normalization:** Extracts core intent from user messages.
2. **Semantic Cache Check:** Computes the query's embedding and checks Redis using normalized cosine similarity dot-products. If similarity $\ge 0.92$, the pipeline short-circuits and answers instantly.
3. **Embedding Generation:** Uses local `BAAI/bge-m3` directly in the python process.
4. **Hybrid Search (Qdrant):** Simultaneously executes Dense ANN (semantic) and Sparse BM25 (exact term) queries. Merges the results via **Reciprocal Rank Fusion (RRF)** (using $k=60$) to balance conceptual matching and keyword importance.
5. **Cross-Encoder Reranking:** Re-scores the top 20 retrieved candidates using `BAAI/bge-reranker-v2-m3` for high-precision context filtering, passing the top 5 to the LLM.
6. **Sentence Window Retrieval:** Automatically fetches neighboring chunks around highly ranked chunks to expand the context window implicitly.
7. **Answer Planning:** Pre-evaluates deterministic questions (e.g., "what is the reconnection fee", simple aggregations). If confidence is high, it bypasses the LLM for perfectly reliable answers ("calc" or "list" pathways).

### 4.4 LLM Generation & Circuit Breaker (`query-svc` & `llm-server`)
* **Llama.cpp integration:** Calls a local `llama-server` mimicking OpenAI's `v1/chat/completions` API utilizing Server-Sent Events (SSE).
* **Resilience:** Implements a localized **Circuit Breaker** pattern. If the local GPU/CPU llama.cpp server fails 3 consecutive times, the breaker trips to 'OPEN' state and automatically routes subsequent requests to a fallback **Azure OpenAI** endpoint for 60 seconds.
* **Streaming Proxy:** The Backend Proxy (`query-proxy.py`) natively catches SSE payloads, yielding them back to the React UI in real-time, significantly eliminating Time-To-First-Token (TTFT) latency overheads.

### 4.5 NGINX Reverse Proxy (`nginx.conf`)
* **Rate Limiting:** Protects `/auth/` and `/query` endpoints via memory zones restricting IPs to 10 requests per second.
* **SSE Specific Rules:** Buffering and caching are explicitly set to `off` for the `/query` endpoint. Without this, NGINX would buffer the streaming tokens and destroy the real-time UX.
* **Security Headers:** Enforces HSTS, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`.

---

## 5. Storage Ecosystem & Schema Outline
1. **PostgreSQL** handles normalized tabular data:
   * `documents`: Tracks lifecycle (pending $\rightarrow$ normalizing $\rightarrow$ embedding $\rightarrow$ ready), chunk counts, and file locations.
   * `conversations` & `messages`: Stores Chat History for LLM context replay.
   * `ingestion_jobs`: Links to Celery Task IDs.
2. **Qdrant**: Runs with a single unified collection indexing 1024-dimensional continuous arrays (Dense) alongside index mapping values (Sparse).
3. **MinIO**: Replaces traditional filesystem storage, persisting both the raw binary `.pdf` and the normalized `.md`/`.json` artifacts for audit and debugging purposes.

## 6. Closing Remarks
The implemented codebase achieves an optimal local-first, privacy-respecting HR tool design. By running LLMs, Encoders, and Rerankers statically within containerized infrastructure, the organization eliminates external data privacy risks. The system further maximizes performance on CPU/Limited environments by utilizing clever architectural decisions such as semantic caching, reciprocal rank fusion, and hybrid cross-encoder inference optimization.
