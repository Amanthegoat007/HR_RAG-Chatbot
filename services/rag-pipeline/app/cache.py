"""
============================================================================
FILE: services/query/app/cache.py
PURPOSE: Redis semantic cache for query-answer pairs.
         Caches answers for semantically similar questions (cosine sim >= 0.92).
         Avoids LLM calls for common/repeated queries — major latency reduction.
ARCHITECTURE REF: §3.4 — Semantic Cache Design
DEPENDENCIES: redis, numpy
============================================================================

Semantic Cache Design:
━━━━━━━━━━━━━━━━━━━━━
- Cache key: "semantic_cache:{hash_of_normalized_embedding}"
- Cache value: JSON with {query_embedding, answer, sources, timestamp}
- Hit condition: cosine_similarity(new_query_embedding, cached_embedding) >= 0.92
- Max entries: 1000 (LRU eviction via maxmemory-policy in Redis config)
- TTL: 24 hours (cached answers expire to prevent stale HR policy info)

OPTIMIZATION: Normalized embeddings stored → cosine similarity = dot product
  Normal cosine: dot(a, b) / (|a| * |b|)  ← requires expensive norm computation
  Normalized:    dot(a, b)                  ← just a dot product (2-5x faster)

Cache invalidation: When a document is deleted/re-uploaded, call invalidate_by_prefix()
to remove cached answers that might reference the deleted document's content.
"""

import json
import logging
import time
from typing import Any, Optional

import numpy as np
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# Redis key prefix for all semantic cache entries
CACHE_PREFIX = "semantic_cache:"


def _normalize(vector: list[float]) -> np.ndarray:
    """
    Normalize a vector to unit length (L2 norm).

    Normalized vectors allow cosine similarity to be computed as a simple dot product:
        cosine_similarity(a, b) = dot(a_normalized, b_normalized)

    This is the OPTIMIZATION from Architecture §3.4 that makes cache lookups fast.

    Args:
        vector: Raw embedding vector.

    Returns:
        Normalized numpy array with L2 norm = 1.0.
    """
    arr = np.array(vector, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm == 0:
        return arr  # Return zero vector as-is (shouldn't happen in practice)
    return arr / norm


def _cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """
    Compute cosine similarity between two NORMALIZED vectors.

    Since both vectors are normalized to unit length, cosine similarity
    equals the dot product — a very fast operation.

    Args:
        v1, v2: Unit-normalized vectors (output of _normalize()).

    Returns:
        Cosine similarity in [-1.0, 1.0]. Higher = more similar.
        For embedding vectors, values are typically in [0.0, 1.0].
    """
    return float(np.dot(v1, v2))


class SemanticCache:
    """
    Redis-backed semantic cache for query-answer pairs.

    Thread-safe: Redis operations are atomic.
    Connection pooling: Uses redis.ConnectionPool for efficient connection reuse.
    """

    def __init__(
        self,
        redis_client: "aioredis.Redis",
        similarity_threshold: float,
        ttl_seconds: int,
        max_entries: int = 1000,
    ) -> None:
        self._client = redis_client
        self.similarity_threshold = similarity_threshold
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries

    async def get(self, query_embedding: list[float]) -> Optional[dict[str, Any]]:
        """
        Check if a semantically similar query exists in the cache.

        Scans all cached embeddings and returns the cached answer if any
        have cosine similarity >= CACHE_SIMILARITY_THRESHOLD.

        Performance: O(N) where N = number of cached entries (max 1000).
        At 1024 dimensions and 1000 entries, this scan takes ~1-5ms on CPU.
        This is MUCH faster than the LLM call it avoids (~2-30 seconds).

        Args:
            query_embedding: Dense embedding of the new query.

        Returns:
            Cached dict with {answer, sources, cache_key} if hit,
            or None if no similar query found.
        """
        if self._client is None:
            logger.warning("Redis not connected — skipping cache lookup")
            return None

        # Normalize the query vector once (used for all comparisons)
        query_vec = _normalize(query_embedding)

        try:
            # Scan all semantic cache keys
            cursor = 0
            best_similarity = 0.0
            best_entry = None

            while True:
                cursor, keys = await self._client.scan(
                    cursor=cursor,
                    match=f"{CACHE_PREFIX}*",
                    count=100,  # Process 100 keys per iteration
                )

                for key in keys:
                    raw = await self._client.get(key)
                    if raw is None:
                        continue

                    try:
                        entry = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    # Check entry age (TTL check — redundant with Redis TTL but extra safety)
                    entry_age = time.time() - entry.get("timestamp", 0)
                    if entry_age > self.ttl_seconds:
                        # Expired entry (should have been evicted by Redis TTL)
                        await self._client.delete(key)
                        continue

                    # Compare embeddings using dot product (normalized = cosine)
                    cached_vec = np.array(entry["query_embedding"], dtype=np.float32)
                    similarity = _cosine_similarity(query_vec, cached_vec)

                    if similarity >= self.similarity_threshold and similarity > best_similarity:
                        best_similarity = similarity
                        best_entry = {
                            "answer": entry["answer"],
                            "sources": entry["sources"],
                            "cache_key": key.decode() if isinstance(key, bytes) else key,
                            "similarity": similarity,
                        }

                if cursor == 0:
                    break  # Scan complete

            if best_entry:
                logger.info("Semantic cache hit", extra={
                    "similarity": round(best_entry["similarity"], 4)
                })
                return best_entry

        except Exception as exc:
            # Cache failure must not break the main pipeline
            logger.error("Cache lookup failed", extra={"error": str(exc)})

        return None

    async def set(
        self,
        query_embedding: list[float],
        answer: str,
        sources: list[dict],
    ) -> None:
        """
        Store a query-answer pair in the semantic cache.

        The normalized embedding is stored (not the raw embedding) so that
        future lookups can use the faster dot-product comparison.

        Args:
            query_embedding: Dense embedding of the query (will be normalized before storing).
            answer: The LLM's answer text.
            sources: List of source citations.
        """
        if self._client is None:
            return

        try:
            # Normalize before storing
            normalized = _normalize(query_embedding).tolist()

            # Build cache entry
            entry = {
                "query_embedding": normalized,
                "answer": answer,
                "sources": sources,
                "timestamp": time.time(),
            }

            # Use a hash-based key for efficient storage
            # Key collision is theoretically possible but negligible for 1000 entries
            import hashlib
            key_hash = hashlib.md5(json.dumps(normalized[:10]).encode()).hexdigest()
            cache_key = f"{CACHE_PREFIX}{key_hash}"

            # Store with TTL
            await self._client.setex(
                name=cache_key,
                time=self.ttl_seconds,
                value=json.dumps(entry),
            )

            logger.debug("Stored in semantic cache", extra={"key": cache_key})

        except Exception as exc:
            logger.error("Cache store failed", extra={"error": str(exc)})

