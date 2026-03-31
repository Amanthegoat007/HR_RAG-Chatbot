"""
============================================================================
FILE: shared/logging_config.py
PURPOSE: Shared structured logging configuration for all HR RAG Chatbot services.
         Produces JSON-formatted logs in production (Grafana-ready) and
         human-readable text logs in development.
ARCHITECTURE REF: §9.1 — Code Quality, §10 — Monitoring Configuration
DEPENDENCIES: Python stdlib (logging, json), no external dependencies
============================================================================

Structured logging design:
- JSON format: every log entry is a valid JSON object on one line
- Fields: timestamp, level, service, correlation_id, message, + custom fields
- correlation_id: passed via context variable for request tracing
- Compatible with Grafana Loki for log aggregation

Usage (in any service):
    from shared.logging_config import setup_logging, get_logger
    setup_logging(service_name="query-svc", log_level="INFO", log_format="json")
    logger = get_logger(__name__)
    logger.info("Cache hit", extra={"correlation_id": req_id, "similarity": 0.95})
"""

import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Context variable to carry correlation_id across async tasks
# Set this at the start of each request; it propagates through async calls
# ---------------------------------------------------------------------------
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


class JSONFormatter(logging.Formatter):
    """
    Custom logging formatter that outputs log records as single-line JSON.

    Each JSON log entry contains:
        - timestamp: ISO 8601 UTC
        - level: DEBUG/INFO/WARNING/ERROR/CRITICAL
        - service: name of the microservice
        - logger: Python logger name (usually module path)
        - correlation_id: request trace ID (from context variable)
        - message: the log message
        - extra fields: any additional fields passed via logging.extra
        - exc_info: exception traceback as string (if applicable)

    This format is compatible with Grafana Loki's JSON log parsing.
    """

    def __init__(self, service_name: str) -> None:
        """
        Args:
            service_name: Name of the microservice (e.g., "query-svc", "auth-svc").
                          Included in every log record for multi-service log aggregation.
        """
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        """
        Format a log record as a single-line JSON string.

        Args:
            record: The log record to format.

        Returns:
            JSON string representation of the log record.
        """
        # Build the base log entry
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "correlation_id": correlation_id_var.get(""),
            "message": record.getMessage(),
        }

        # Include exception traceback if present
        if record.exc_info:
            log_entry["exc_info"] = self.formatException(record.exc_info)

        # Merge any extra fields passed via logger.info(..., extra={...})
        # Filter out standard LogRecord attributes to avoid clutter
        standard_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname",
            "filename", "module", "exc_info", "exc_text", "stack_info",
            "lineno", "funcName", "created", "msecs", "relativeCreated",
            "thread", "threadName", "processName", "process", "message",
            "taskName",  # asyncio task name (Python 3.12+)
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                log_entry[key] = value

        return json.dumps(log_entry, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """
    Human-readable formatter for development environments.
    Format: [TIMESTAMP] LEVEL service correlation_id — message
    """

    LEVEL_COLORS = {
        "DEBUG":    "\033[36m",   # Cyan
        "INFO":     "\033[32m",   # Green
        "WARNING":  "\033[33m",   # Yellow
        "ERROR":    "\033[31m",   # Red
        "CRITICAL": "\033[35m",   # Magenta
    }
    RESET = "\033[0m"

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        corr = correlation_id_var.get("")
        corr_str = f" [{corr[:8]}]" if corr else ""
        color = self.LEVEL_COLORS.get(record.levelname, "")
        msg = record.getMessage()

        formatted = (
            f"{ts} {color}{record.levelname:8}{self.RESET} "
            f"{self.service_name}{corr_str} — {msg}"
        )

        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)

        return formatted


def setup_logging(
    service_name: str,
    log_level: str = "INFO",
    log_format: str = "json",
) -> None:
    """
    Configure the root logger for a microservice.

    Call this once at application startup (in main.py lifespan or at module level).

    Args:
        service_name: Name identifying this service in logs (e.g., "query-svc").
        log_level: Logging level string ("DEBUG", "INFO", "WARNING", "ERROR").
        log_format: Output format — "json" for production, "text" for development.
    """
    # Parse log level string to int (handles unknown levels gracefully)
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Select formatter based on format preference
    if log_format.lower() == "json":
        formatter: logging.Formatter = JSONFormatter(service_name=service_name)
    else:
        formatter = TextFormatter(service_name=service_name)

    # Configure root logger (affects all loggers in the process)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicate log lines
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Silence noisy third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("celery").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger.

    Args:
        name: Usually __name__ of the calling module.

    Returns:
        Standard Python Logger instance.
    """
    return logging.getLogger(name)


def set_correlation_id(correlation_id: str) -> None:
    """
    Set the correlation ID for the current async context.

    Call this at the start of each HTTP request handler.
    The correlation ID will be automatically included in all log messages
    emitted during that request's execution, including in async sub-tasks.

    Args:
        correlation_id: Unique identifier for the request (usually from X-Request-ID header
                       or generated via uuid4()).
    """
    correlation_id_var.set(correlation_id)
