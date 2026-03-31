"""
============================================================================
FILE: services/rerank/app/reranker_service.py
PURPOSE: BGE-Reranker-v2-m3 cross-encoder model loading and inference.
         Scores query-document pairs to re-order retrieved chunks by relevance.
ARCHITECTURE REF: §4.2 — Reranking
DEPENDENCIES: FlagEmbedding, torch
============================================================================

Cross-Encoder vs Bi-Encoder:
- Bi-encoder (BGE-M3): encodes query and document SEPARATELY → fast but less accurate
- Cross-encoder (BGE-Reranker): encodes (query, document) TOGETHER → slower but more accurate

In our pipeline:
1. BGE-M3 (bi-encoder) retrieves 20 candidates quickly using pre-computed vectors
2. BGE-Reranker rescores all 20 pairs, picks top-5 — this is the accuracy boost

The cross-encoder sees the query and document at the same time, allowing it to
model complex relevance signals (exact term matches, semantic similarity, negation, etc.)
that bi-encoders miss because they encode independently.
"""

import logging
import time

import torch
from FlagEmbedding import FlagReranker

from app.config import settings

logger = logging.getLogger(__name__)


class RerankerService:
    """
    Singleton service that holds the BGE-Reranker-v2-m3 model and
    provides cross-encoder scoring for query-document pairs.
    """

    def __init__(self) -> None:
        self._model: FlagReranker | None = None
        self.start_time = time.time()

    def load_model(self) -> None:
        """
        Load the BGE-Reranker-v2-m3 cross-encoder model.

        Called once at application startup. Blocks until the model is loaded
        and warmed up.

        Raises:
            RuntimeError: If model loading fails.
        """
        logger.info("Loading BGE-Reranker-v2-m3 model", extra={
            "model": settings.reranker_model_name,
        })

        load_start = time.time()

        self._model = FlagReranker(
            model_name_or_path=settings.reranker_model_name,
            use_fp16=False,  # CPU: use FP32 for correctness
        )

        load_elapsed = time.time() - load_start
        logger.info("BGE-Reranker model loaded", extra={
            "load_time_seconds": round(load_elapsed, 2)
        })

        # Warm up to trigger JIT compilation on a dummy pair
        self._warm_up()
        logger.info("Reranker service ready")

    def _warm_up(self) -> None:
        """Run a dummy inference to pre-compile the model's computation graph."""
        logger.info("Warming up reranker model...")
        with torch.inference_mode():
            _ = self._model.compute_score(
                [["warmup query", "warmup document"]],
                max_length=settings.reranker_max_length,
                normalize=True,
            )
        logger.info("Warm-up complete")

    def rerank(
        self,
        query: str,
        documents: list[dict],
        top_n: int,
    ) -> list[dict]:
        """
        Score query-document pairs and return top-N by relevance score.

        The cross-encoder processes ALL pairs in one call, which is more efficient
        than calling it pair-by-pair. Results are sorted descending by score.

        Args:
            query: The user's question text.
            documents: List of dicts with keys: document_id, text, metadata.
            top_n: Number of top-scoring documents to return.

        Returns:
            List of dicts (top_n items) sorted by score descending, each containing:
            {
                "document_id": str,
                "text": str,
                "score": float,   # cross-encoder relevance score (higher = more relevant)
                "rank": int,      # 1-based rank (1 = most relevant)
                "metadata": dict,
            }

        Raises:
            RuntimeError: If the model is not loaded.
        """
        if self._model is None:
            raise RuntimeError("Reranker model not loaded. Call load_model() first.")

        if not documents:
            return []

        # Build pairs list: [[query, doc_text], [query, doc_text], ...]
        # The cross-encoder processes all pairs in one forward pass
        pairs = [[query, doc["text"]] for doc in documents]

        logger.debug("Reranking documents", extra={
            "query_length": len(query),
            "num_candidates": len(pairs),
            "top_n": top_n,
        })

        start = time.time()

        with torch.inference_mode():
            # compute_score returns a list of floats (one score per pair)
            # normalize=True: applies sigmoid to get scores in [0, 1] range
            scores = self._model.compute_score(
                sentence_pairs=pairs,
                max_length=settings.reranker_max_length,
                normalize=True,  # Sigmoid normalization: score in [0, 1]
                batch_size=settings.reranker_batch_size,
            )

        elapsed_ms = (time.time() - start) * 1000

        # scores is a list of floats; zip with documents to create scored pairs
        scored_docs = [
            {
                "document_id": doc["document_id"],
                "text": doc["text"],
                "score": float(score),
                "metadata": doc.get("metadata", {}),
            }
            for doc, score in zip(documents, scores)
        ]

        # Sort by score descending (highest relevance first)
        scored_docs.sort(key=lambda x: x["score"], reverse=True)

        # Add 1-based rank after sorting
        for rank_idx, doc in enumerate(scored_docs, start=1):
            doc["rank"] = rank_idx

        # Return only top-N results
        top_results = scored_docs[:top_n]

        logger.debug("Reranking complete", extra={
            "top_score": round(top_results[0]["score"], 4) if top_results else 0,
            "elapsed_ms": round(elapsed_ms, 1),
        })

        return top_results

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.start_time


# Module-level singleton
reranker_service = RerankerService()
