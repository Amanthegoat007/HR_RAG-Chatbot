"""
============================================================================
FILE: services/ingest/app/celery_app.py
PURPOSE: Celery application configuration — Redis Streams broker,
         task routing, serialization settings.
ARCHITECTURE REF: §3 — Document Ingestion Pipeline (async via Celery)
DEPENDENCIES: celery[redis]
============================================================================

Celery Architecture in this System:
- Broker: Redis DB 1 (separate from the semantic cache on DB 0)
- Result Backend: Redis DB 2 (stores task results for status queries)
- Queue: "document_processing" — single queue for all ingest tasks
- Concurrency: 2 workers (set via docker-compose.yml command)
- max-tasks-per-child: 50 — recycles workers to prevent memory leaks
  (document processing libraries like PyMuPDF can accumulate memory)

Task flow:
1. FastAPI (ingest-svc) calls process_document.delay(document_id) → Celery queues
2. ingest-worker picks up the task from Redis
3. Worker downloads file from MinIO, converts to markdown, chunks, embeds, upserts
4. Worker updates document status in PostgreSQL
"""

from celery import Celery

from app.config import settings

# Create Celery application
# First argument is the "namespace" — used for task auto-discovery
celery_app = Celery(
    "ingest_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# ---------------------------------------------------------------------------
# CELERY CONFIGURATION
# ---------------------------------------------------------------------------
celery_app.conf.update(
    # Task serialization — JSON is human-readable and debuggable
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone — use UTC for consistency
    timezone="UTC",
    enable_utc=True,

    # Route all tasks to the "document_processing" queue
    # This allows future addition of separate queues (e.g., high-priority)
    task_routes={
        "app.tasks.process_document": {"queue": "document_processing"},
        "app.tasks.delete_document": {"queue": "document_processing"},
    },

    # Task retry settings (individual tasks also have their own retry logic)
    task_acks_late=True,   # Acknowledge task only after completion (prevents data loss if worker crashes)
    task_reject_on_worker_lost=True,  # Re-queue task if worker dies mid-execution

    # Result expiry — keep results for 24 hours (for status queries)
    result_expires=86400,

    # Worker settings
    worker_prefetch_multiplier=1,  # Don't prefetch; each worker processes one task at a time
    # This is important for long-running tasks (document processing can take minutes)

    # Prevent tasks from being held in memory indefinitely
    task_soft_time_limit=3600,  # 60 minutes: trigger SoftTimeLimitExceeded
    task_time_limit=3800,       # ~63 minutes: force kill if still running
)

# Auto-discover tasks in the app.tasks module
celery_app.autodiscover_tasks(["app"])
