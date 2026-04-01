from __future__ import annotations

from typing import Any

import asyncpg

from app import db


def _extract_last_document_focus(
    recent_messages: list[dict[str, Any]] | None,
) -> tuple[str | None, str | None]:
    for message in reversed(recent_messages or []):
        metadata = message.get("metadata") or {}
        document_focus = metadata.get("documentFocus") or {}
        document_id = document_focus.get("documentId")
        display_name = document_focus.get("displayName")
        if document_id:
            return str(document_id), str(display_name or "")
    return None, None


def _serialize_session_document(document: dict[str, Any]) -> dict[str, Any]:
    metadata = document.get("metadata") or {}
    parser_used = metadata.get("parser_used")
    page_count = document.get("page_count")
    chunk_count = document.get("chunk_count")
    uploaded_at = document.get("uploaded_at")

    payload = {
        "document_id": str(document["id"]),
        "display_name": document.get("filename") or "Uploaded document",
        "status": document.get("status") or "processing",
        "source_format": document.get("original_format"),
        "page_count": page_count if isinstance(page_count, int) else None,
        "chunk_count": chunk_count if isinstance(chunk_count, int) else None,
        "uploaded_at": uploaded_at.isoformat() if uploaded_at else None,
        "parser_used": parser_used if isinstance(parser_used, str) else None,
    }
    return {key: value for key, value in payload.items() if value is not None}


async def build_conversation_working_set(
    pool: asyncpg.Pool,
    conversation_id: str,
    *,
    recent_messages: list[dict[str, Any]] | None = None,
    active_attachment_document_id: str | None = None,
) -> dict[str, Any]:
    documents = await db.list_session_documents_for_conversation(pool, conversation_id)
    serialized_documents = [_serialize_session_document(document) for document in documents]

    latest_ready_document_id = next(
        (
            document["document_id"]
            for document in serialized_documents
            if document.get("status") == "ready"
        ),
        None,
    )

    known_document_ids = {document["document_id"] for document in serialized_documents}
    normalized_active_attachment_id = (
        active_attachment_document_id
        if active_attachment_document_id in known_document_ids
        else None
    )
    last_focused_document_id, last_focused_document_label = _extract_last_document_focus(
        recent_messages,
    )
    if last_focused_document_id not in known_document_ids:
        last_focused_document_id = None
        last_focused_document_label = None

    return {
        "session_documents": serialized_documents,
        "latest_ready_document_id": latest_ready_document_id,
        "active_attachment_document_id": normalized_active_attachment_id,
        "last_focused_document_id": last_focused_document_id,
        "last_focused_document_label": last_focused_document_label,
    }
