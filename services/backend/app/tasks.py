"""
============================================================================
FILE: services/ingest/app/tasks.py
PURPOSE: Celery tasks for async document processing and deletion.
         process_document: the full ingestion pipeline for one document
         delete_document: remove document from MinIO + Qdrant + PostgreSQL
ARCHITECTURE REF: §3 — Document Ingestion Pipeline (Celery worker side)
DEPENDENCIES: celery_app.py, file_converter.py, chunker.py, minio_client.py,
              qdrant_client_wrapper.py, db.py, embedding_client (via httpx)
============================================================================

process_document pipeline:
━━━━━━━━━━━━━━━━━━━━━━━━━
1. Download original file from MinIO
2. Convert to Markdown (★ signature optimization)
3. Upload Markdown to MinIO (for audit/debug)
4. Chunk the Markdown (256-token, sentence-aligned, 64-overlap)
5. Call embedding-svc for each chunk (dense + sparse vectors)
6. Upsert vectors to Qdrant with chunk metadata
7. Update document status to 'ready' in PostgreSQL

Error handling:
- Each major step is wrapped in try/except
- On failure: status set to 'failed', error_message recorded
- Celery tracks the task result for 24 hours (result_expires)
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any

import asyncpg
import httpx
import redis.asyncio as aioredis

from app.celery_app import celery_app
from app.config import settings
from app.file_converter import convert_to_markdown
from app.chunker import chunk_markdown, DocumentChunk
from app.metadata_extractor import build_document_metadata, build_chunk_payload
from app.minio_client import (
    get_minio_client, download_file, upload_markdown, delete_document_files
)
from app.qdrant_client_wrapper import (
    get_qdrant_client, upsert_chunks, delete_document_vectors
)

logger = logging.getLogger(__name__)

# Batch size for embedding API calls
# Sending all chunks in one batch is most efficient, but caps at 128 (embedding-svc limit)
EMBED_BATCH_SIZE = 32


def _get_event_loop() -> asyncio.AbstractEventLoop:
    """Get or create an asyncio event loop for the synchronous Celery worker context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("Event loop is closed")
        return loop
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


async def _embed_chunks(
    chunks: list[DocumentChunk],
    http_client: httpx.AsyncClient,
) -> list[dict[str, Any]]:
    """
    Call embedding-svc to get dense and sparse vectors for all chunks.

    Sends chunks in batches to respect the 128-item limit per request.
    Returns a flat list with one dict per chunk in the same order as input.

    Args:
        chunks: List of DocumentChunk objects.
        http_client: Shared httpx.AsyncClient for connection reuse.

    Returns:
        List of dicts: [{"dense": [...], "sparse": {...}}, ...]
    """
    all_results = []

    # Process in batches of EMBED_BATCH_SIZE
    for batch_start in range(0, len(chunks), EMBED_BATCH_SIZE):
        batch = chunks[batch_start:batch_start + EMBED_BATCH_SIZE]
        texts = [chunk.text for chunk in batch]

        response = await http_client.post(
            f"{settings.embedding_svc_url}/embed",
            json={"texts": texts},
            timeout=120.0,  # Embedding can be slow for large batches on CPU
        )
        response.raise_for_status()

        embed_data = response.json()
        all_results.extend(embed_data["results"])

    return all_results


async def _invalidate_semantic_cache() -> None:
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    try:
        cursor = 0
        while True:
            cursor, keys = await redis_client.scan(
                cursor=cursor,
                match="semantic_cache:*",
                count=100,
            )
            if keys:
                await redis_client.delete(*keys)
            if cursor == 0:
                break
    finally:
        await redis_client.close()


async def process_document_async(
    document_id: str,
    task_id: str,
) -> dict[str, Any]:
    """
    Shared document processing pipeline used by Celery and the manual backfill script.
    """
    task_start = time.time()
    db_pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=3)
    minio_client = get_minio_client()
    qdrant_client = get_qdrant_client()

    try:
        from app.db import get_document, update_document_status, update_ingestion_job, write_audit_log

        doc = await get_document(db_pool, document_id)
        if not doc:
            raise ValueError(f"Document not found: {document_id}")

        filename = doc["filename"]
        minio_path = doc["minio_path"]

        await update_document_status(db_pool, document_id, "processing", error_message=None)
        await update_ingestion_job(
            db_pool,
            task_id,
            "processing",
            started_at=datetime.utcnow(),
        )

        logger.info("Downloading file from MinIO", extra={"path": minio_path})
        file_bytes = download_file(minio_client, minio_path)

        step_start = time.time()
        logger.info("Converting document to Markdown", extra={"doc_filename": filename})
        markdown_text, page_count = convert_to_markdown(file_bytes, filename)
        conversion_time = time.time() - step_start

        logger.info("Markdown conversion complete", extra={
            "doc_filename": filename,
            "pages": page_count,
            "markdown_chars": len(markdown_text),
            "time_s": round(conversion_time, 2),
        })

        markdown_path = upload_markdown(minio_client, document_id, markdown_text)

        step_start = time.time()
        chunks = chunk_markdown(
            markdown_text,
            chunk_size=settings.chunk_size_tokens,
            overlap=settings.chunk_overlap_tokens,
        )
        chunking_time = time.time() - step_start

        logger.info("Chunking complete", extra={
            "chunk_count": len(chunks),
            "time_s": round(chunking_time, 2),
        })

        if not chunks:
            raise ValueError("No chunks generated — document may be empty or unreadable")

        document_metadata = build_document_metadata(
            markdown_text=markdown_text,
            filename=filename,
            file_size_bytes=doc["file_size_bytes"],
            chunk_count=len(chunks),
        )

        step_start = time.time()
        async with httpx.AsyncClient(timeout=120.0) as http_client:
            embed_results = await _embed_chunks(chunks, http_client)
        embedding_time = time.time() - step_start

        logger.info("Embedding complete", extra={
            "chunk_count": len(chunks),
            "time_s": round(embedding_time, 2),
        })

        step_start = time.time()
        delete_document_vectors(qdrant_client, document_id)

        points = []
        for chunk, embed_result in zip(chunks, embed_results):
            payload = build_chunk_payload(chunk, document_id, filename)
            points.append({
                "point_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{document_id}:{chunk.chunk_index}")),
                "dense_vector": embed_result["dense"]["values"],
                "sparse_indices": embed_result["sparse"]["indices"],
                "sparse_values": embed_result["sparse"]["values"],
                "payload": payload,
            })

        upserted = upsert_chunks(qdrant_client, points)
        upsert_time = time.time() - step_start

        logger.info("Qdrant upsert complete", extra={
            "upserted": upserted,
            "time_s": round(upsert_time, 2),
        })

        total_time = time.time() - task_start
        await update_document_status(
            db_pool,
            document_id,
            "ready",
            markdown_path=markdown_path,
            page_count=page_count,
            chunk_count=len(chunks),
            metadata=document_metadata,
        )
        await update_ingestion_job(
            db_pool,
            task_id,
            "completed",
            completed_at=datetime.utcnow(),
            processing_time_seconds=round(total_time, 2),
        )

        await write_audit_log(
            db_pool,
            "ingestion_complete",
            role=None,
            username=None,
            ip_address=None,
            details={
                "document_id": document_id,
                "filename": filename,
                "chunk_count": len(chunks),
                "processing_time_s": round(total_time, 2),
            },
        )
        await _invalidate_semantic_cache()

        result = {
            "status": "completed",
            "document_id": document_id,
            "chunks": len(chunks),
            "pages": page_count,
            "time_s": round(total_time, 2),
        }
        logger.info("Document processing complete", extra=result)
        return result

    except Exception as exc:
        error_msg = str(exc)
        logger.error("Document processing failed", extra={
            "document_id": document_id,
            "error": error_msg,
        })

        from app.db import update_document_status, update_ingestion_job, write_audit_log
        await update_document_status(
            db_pool,
            document_id,
            "failed",
            error_message=error_msg,
        )
        await update_ingestion_job(
            db_pool,
            task_id,
            "failed",
            completed_at=datetime.utcnow(),
            error_message=error_msg,
            processing_time_seconds=round(time.time() - task_start, 2),
        )
        await write_audit_log(
            db_pool,
            "ingestion_failed",
            role=None,
            username=None,
            ip_address=None,
            details={"document_id": document_id, "error": error_msg},
        )
        raise

    finally:
        await db_pool.close()


@celery_app.task(
    name="app.tasks.process_document",
    bind=True,
    max_retries=2,
    default_retry_delay=30,  # Wait 30s before retry (gives services time to recover)
)
def process_document(self, document_id: str) -> dict[str, Any]:
    """
    Full document processing pipeline — convert, chunk, embed, index.

    Called by ingest-svc after upload. Runs in the ingest-worker container.

    Pipeline:
    1. Fetch document record from PostgreSQL
    2. Download file from MinIO
    3. Convert to Markdown (file_converter.py)
    4. Upload Markdown to MinIO (for audit trail)
    5. Chunk Markdown (chunker.py)
    6. Embed all chunks (embedding-svc)
    7. Upsert to Qdrant (qdrant_client_wrapper.py)
    8. Update document record to 'ready'

    Args:
        document_id: UUID of the document to process.

    Returns:
        Dict with processing summary: {"chunks": N, "pages": N, "time_s": T}

    Raises:
        Celery retries on transient errors (network timeouts, service restarts).
    """
    logger.info("Processing document", extra={
        "document_id": document_id,
        "task_id": self.request.id,
    })

    loop = _get_event_loop()
    try:
        return loop.run_until_complete(process_document_async(document_id, self.request.id))
    except Exception as exc:
        # Retry on transient errors (network issues, service restarts)
        if self.request.retries < self.max_retries:
            logger.warning("Retrying document processing", extra={
                "document_id": document_id,
                "attempt": self.request.retries + 1,
                "error": str(exc),
            })
            raise self.retry(exc=exc)
        raise


@celery_app.task(
    name="app.tasks.delete_document",
    bind=True,
    max_retries=2,
)
def delete_document(self, document_id: str, filename: str) -> dict[str, Any]:
    """
    Delete a document from MinIO, Qdrant, and PostgreSQL.

    Called by DELETE /ingest/document/{id}.
    Order matters: delete from Qdrant first, then MinIO, then PostgreSQL
    (so if deletion fails mid-way, we can retry without orphaned data).

    Args:
        document_id: UUID of the document to delete.
        filename: Filename (for audit log).

    Returns:
        Dict confirming deletion.
    """
    logger.info("Deleting document", extra={"document_id": document_id})

    loop = _get_event_loop()

    async def _run_delete():
        minio_client = get_minio_client()
        qdrant_client = get_qdrant_client()
        db_pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=3)

        try:
            # Delete Qdrant vectors first
            vectors_deleted = delete_document_vectors(qdrant_client, document_id)

            # Delete MinIO files
            minio_deleted = delete_document_files(minio_client, document_id)

            # Delete PostgreSQL record (cascade deletes ingestion_jobs)
            from app.db import delete_document_record, write_audit_log
            await delete_document_record(db_pool, document_id)

            await write_audit_log(
                db_pool, "document_delete",
                role=None, username=None, ip_address=None,
                details={"document_id": document_id, "filename": filename},
            )
            await _invalidate_semantic_cache()

            logger.info("Document deleted successfully", extra={"document_id": document_id})
            return {
                "status": "deleted",
                "document_id": document_id,
                "vectors_deleted": vectors_deleted,
                "minio_deleted": minio_deleted,
            }

        finally:
            await db_pool.close()

    try:
        return loop.run_until_complete(_run_delete())
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        raise
