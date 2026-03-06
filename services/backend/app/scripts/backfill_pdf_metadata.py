import argparse
import asyncio
import logging
import uuid

import asyncpg

from app import db
from app.config import settings
from app.tasks import process_document_async

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)


async def _fetch_ready_pdfs(pool: asyncpg.Pool, limit: int | None) -> list[dict]:
    sql = """
        SELECT id::text AS id, filename
        FROM documents
        WHERE status = 'ready' AND original_format = 'pdf'
        ORDER BY uploaded_at ASC
    """
    params: list[object] = []
    if limit is not None:
        sql += " LIMIT $1"
        params.append(limit)

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return [dict(row) for row in rows]


async def _process_one_document(
    pool: asyncpg.Pool,
    document: dict,
    semaphore: asyncio.Semaphore,
) -> None:
    document_id = document["id"]
    task_id = str(uuid.uuid4())

    async with semaphore:
        await db.create_ingestion_job(pool, document_id, task_id)
        await db.update_document_status(pool, document_id, "pending", error_message=None)
        await db.write_audit_log(
            pool,
            "ingestion_start",
            role=None,
            username=None,
            ip_address=None,
            details={
                "mode": "metadata_backfill",
                "document_id": document_id,
                "filename": document["filename"],
                "task_id": task_id,
            },
        )

        try:
            result = await process_document_async(document_id, task_id)
        except Exception as exc:
            logger.exception("Backfill failed", extra={"document_id": document_id, "error": str(exc)})
            await db.write_audit_log(
                pool,
                "ingestion_failed",
                role=None,
                username=None,
                ip_address=None,
                details={
                    "mode": "metadata_backfill",
                    "document_id": document_id,
                    "filename": document["filename"],
                    "task_id": task_id,
                    "error": str(exc),
                },
            )
            return

        logger.info("Backfill complete", extra=result)
        await db.write_audit_log(
            pool,
            "ingestion_complete",
            role=None,
            username=None,
            ip_address=None,
            details={**result, "mode": "metadata_backfill"},
        )


async def _run(args: argparse.Namespace) -> int:
    if not args.all_ready:
        raise SystemExit("Pass --all-ready to confirm reprocessing all ready PDF documents.")

    pool = await asyncpg.create_pool(dsn=settings.postgres_dsn, min_size=1, max_size=4)
    try:
        documents = await _fetch_ready_pdfs(pool, args.limit)
        if not documents:
            logger.info("No ready PDF documents found for backfill")
            return 0

        logger.info("Starting PDF metadata backfill", extra={
            "documents": len(documents),
            "concurrency": args.concurrency,
        })

        semaphore = asyncio.Semaphore(max(1, args.concurrency))
        await asyncio.gather(*[
            _process_one_document(pool, document, semaphore)
            for document in documents
        ])
        logger.info("PDF metadata backfill finished", extra={"documents": len(documents)})
        return 0
    finally:
        await pool.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reprocess ready PDF documents with structured metadata.")
    parser.add_argument("--all-ready", action="store_true", dest="all_ready")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
