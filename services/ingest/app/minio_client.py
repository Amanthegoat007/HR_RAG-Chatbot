"""
============================================================================
FILE: services/ingest/app/minio_client.py
PURPOSE: MinIO object storage operations — upload original files and
         intermediate markdown, download for processing, delete on removal.
ARCHITECTURE REF: §5.3 — Object Storage
DEPENDENCIES: minio
============================================================================

MinIO Bucket Layout:
    hr-documents/
    ├── originals/
    │   ├── {document_id}/original.{ext}   ← uploaded file
    │   └── {document_id}/markdown.md      ← converted markdown (for audit/debug)

Both the original and converted markdown are stored.
This allows admins to inspect conversion quality and re-process if needed.
"""

import io
import logging
from typing import Optional

from minio import Minio
from minio.error import S3Error
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings

logger = logging.getLogger(__name__)


def get_minio_client() -> Minio:
    """
    Create a MinIO client using the configured endpoint and credentials.

    Returns:
        Minio client instance.
    """
    # Parse host:port from the endpoint URL
    endpoint = settings.minio_endpoint_url.replace("http://", "").replace("https://", "")
    secure = settings.minio_endpoint_url.startswith("https://")

    return Minio(
        endpoint=endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        secure=secure,
    )


def ensure_bucket_exists(client: Minio, bucket_name: str) -> None:
    """
    Create the MinIO bucket if it doesn't exist.

    Called at service startup to ensure the bucket is ready before
    the first upload attempt.

    Args:
        client: Minio client instance.
        bucket_name: Name of the bucket to create if missing.
    """
    try:
        if not client.bucket_exists(bucket_name):
            client.make_bucket(bucket_name)
            logger.info("MinIO bucket created", extra={"bucket": bucket_name})
        else:
            logger.info("MinIO bucket already exists", extra={"bucket": bucket_name})
    except S3Error as exc:
        logger.error("Failed to create MinIO bucket", extra={"error": str(exc)})
        raise


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def upload_file(
    client: Minio,
    document_id: str,
    filename: str,
    file_bytes: bytes,
    content_type: str,
) -> str:
    """
    Upload the original file to MinIO.

    Args:
        client: Minio client.
        document_id: UUID of the document record (used as path prefix).
        filename: Original filename (for metadata, not used in path).
        file_bytes: Raw file content.
        content_type: MIME type (e.g., "application/pdf").

    Returns:
        MinIO object path (e.g., "originals/{document_id}/original.pdf").

    Raises:
        S3Error: If upload fails after retries.
    """
    # Extract extension from filename to preserve it
    from pathlib import Path
    ext = Path(filename).suffix  # e.g., ".pdf"
    object_name = f"originals/{document_id}/original{ext}"

    client.put_object(
        bucket_name=settings.minio_bucket_name,
        object_name=object_name,
        data=io.BytesIO(file_bytes),
        length=len(file_bytes),
        content_type=content_type,
        metadata={"original_filename": filename, "document_id": document_id},
    )

    logger.info("File uploaded to MinIO", extra={
        "document_id": document_id,
        "object_name": object_name,
        "size_bytes": len(file_bytes),
    })
    return object_name


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def upload_markdown(
    client: Minio,
    document_id: str,
    markdown_content: str,
) -> str:
    """
    Upload the intermediate markdown conversion to MinIO.

    Stored for debugging and audit purposes — admins can inspect the
    markdown to verify extraction quality.

    Args:
        client: Minio client.
        document_id: UUID of the document.
        markdown_content: The converted markdown text.

    Returns:
        MinIO object path (e.g., "originals/{document_id}/markdown.md").
    """
    object_name = f"originals/{document_id}/markdown.md"
    markdown_bytes = markdown_content.encode("utf-8")

    client.put_object(
        bucket_name=settings.minio_bucket_name,
        object_name=object_name,
        data=io.BytesIO(markdown_bytes),
        length=len(markdown_bytes),
        content_type="text/markdown; charset=utf-8",
        metadata={"document_id": document_id, "type": "markdown_intermediate"},
    )

    logger.info("Markdown uploaded to MinIO", extra={
        "document_id": document_id,
        "object_name": object_name,
        "size_bytes": len(markdown_bytes),
    })
    return object_name


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
def upload_text_artifact(
    client: Minio,
    document_id: str,
    relative_name: str,
    content: str,
    content_type: str,
    artifact_type: str,
) -> str:
    """
    Upload a text-based artifact related to normalization/parsing.

    Example object names:
      originals/{document_id}/normalized.md
      originals/{document_id}/normalized.json
      originals/{document_id}/parse_report.json
    """
    object_name = f"originals/{document_id}/{relative_name}"
    payload = (content or "").encode("utf-8")

    client.put_object(
        bucket_name=settings.minio_bucket_name,
        object_name=object_name,
        data=io.BytesIO(payload),
        length=len(payload),
        content_type=content_type,
        metadata={"document_id": document_id, "type": artifact_type},
    )

    logger.info(
        "Artifact uploaded to MinIO",
        extra={
            "document_id": document_id,
            "object_name": object_name,
            "artifact_type": artifact_type,
            "size_bytes": len(payload),
        },
    )
    return object_name


def download_file(client: Minio, object_name: str) -> bytes:
    """
    Download a file from MinIO.

    Args:
        client: Minio client.
        object_name: Full MinIO object path.

    Returns:
        Raw file bytes.

    Raises:
        S3Error: If object not found or download fails.
    """
    response = client.get_object(settings.minio_bucket_name, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def delete_document_files(client: Minio, document_id: str) -> bool:
    """
    Delete all MinIO objects associated with a document.

    Removes both the original file and the markdown intermediate.
    Called when a document is deleted via DELETE /ingest/document/{id}.

    Args:
        client: Minio client.
        document_id: UUID of the document to delete.

    Returns:
        True if files were deleted, False if no files found.
    """
    prefix = f"originals/{document_id}/"

    # List all objects with this prefix
    objects = list(client.list_objects(settings.minio_bucket_name, prefix=prefix))

    if not objects:
        logger.warning("No MinIO objects found for document", extra={"document_id": document_id})
        return False

    # Delete each object
    from minio.deleteobjects import DeleteObject
    delete_list = [DeleteObject(obj.object_name) for obj in objects]

    errors = list(client.remove_objects(settings.minio_bucket_name, delete_list))
    if errors:
        for err in errors:
            logger.error("MinIO delete error", extra={
                "document_id": document_id,
                "object": err.name,
                "error": str(err),
            })
        return False

    logger.info("MinIO files deleted", extra={
        "document_id": document_id,
        "count": len(delete_list),
    })
    return True
