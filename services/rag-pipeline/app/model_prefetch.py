"""
Model prefetch helpers for faster and more reliable startup.

Downloads required Hugging Face repositories into the shared cache volume
before model initialization starts.
"""

import logging
import os
import time
from pathlib import Path

from huggingface_hub import snapshot_download

from app.config import settings

logger = logging.getLogger(__name__)


def _is_local_path(model_name_or_path: str) -> bool:
    """Return True when the configured model value is a local filesystem path."""
    return os.path.isabs(model_name_or_path) or Path(model_name_or_path).exists()


def _prefetch_model(model_name_or_path: str, label: str) -> str:
    """
    Ensure a model is available locally and return the path to load from.

    For repo IDs, this downloads/updates the snapshot in HF cache.
    For local paths, this is a no-op.
    """
    if _is_local_path(model_name_or_path):
        logger.info("Using local model path", extra={"model": label, "path": model_name_or_path})
        return model_name_or_path

    start = time.time()
    logger.info(
        "Prefetching model from Hugging Face",
        extra={
            "model": label,
            "repo_id": model_name_or_path,
            "workers": settings.model_download_workers,
        },
    )

    local_snapshot_path = snapshot_download(
        repo_id=model_name_or_path,
        max_workers=settings.model_download_workers,
    )

    elapsed = time.time() - start
    logger.info(
        "Model prefetch complete",
        extra={
            "model": label,
            "repo_id": model_name_or_path,
            "snapshot_path": local_snapshot_path,
            "time_s": round(elapsed, 2),
        },
    )
    return local_snapshot_path


def prefetch_required_models() -> tuple[str, str]:
    """
    Prefetch embedding and reranker models, returning local load paths.
    """
    if not settings.model_prefetch_on_startup:
        return settings.embedding_model_name, settings.reranker_model_name

    embedding_path = _prefetch_model(settings.embedding_model_name, "embedding")
    reranker_path = _prefetch_model(settings.reranker_model_name, "reranker")
    return embedding_path, reranker_path
