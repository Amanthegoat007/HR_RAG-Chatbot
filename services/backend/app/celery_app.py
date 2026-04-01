"""
============================================================================
FILE: services/backend/app/celery_app.py
PURPOSE: Celery application configuration for backend maintenance jobs.
DEPENDENCIES: celery[redis]
============================================================================
"""

from celery import Celery

from app.config import settings

# Create Celery application
celery_app = Celery(
    "backend_maintenance",
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

    task_routes={
        "app.maintenance.generate_conversation_title": {"queue": "backend-maintenance"},
        "app.maintenance.cleanup_expired_session_documents": {"queue": "backend-maintenance"},
    },

    # Task retry settings (individual tasks also have their own retry logic)
    task_acks_late=True,   # Acknowledge task only after completion (prevents data loss if worker crashes)
    task_reject_on_worker_lost=True,  # Re-queue task if worker dies mid-execution

    # Result expiry — keep results for 24 hours for diagnostics
    result_expires=86400,

    worker_prefetch_multiplier=1,

    task_soft_time_limit=300,
    task_time_limit=360,
    beat_schedule={
        "cleanup-expired-session-documents": {
            "task": "app.maintenance.cleanup_expired_session_documents",
            "schedule": 900.0,
        },
    },
    imports=("app.maintenance",),
)
