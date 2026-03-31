"""
============================================================================
FILE: services/ingest/app/metadata_extractor.py
PURPOSE: Extract metadata for PostgreSQL document records and Qdrant payloads.
ARCHITECTURE REF: §3.1 — Ingestion Pipeline (metadata preservation)
============================================================================
"""

from __future__ import annotations

import re
from typing import Any

from shared.document_core.models import NormalizedDocument


def extract_frontmatter(markdown_text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---", markdown_text or "", re.DOTALL)
    if not match:
        return {}

    frontmatter: dict[str, str] = {}
    for line in match.group(1).split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            frontmatter[key.strip()] = value.strip()
    return frontmatter


def extract_section_headings(markdown_text: str) -> list[str]:
    headings: list[str] = []
    for line in (markdown_text or "").split("\n"):
        match = re.match(r"^(#{1,6})\s+(.*)", line)
        if match:
            headings.append(match.group(2).strip())
    return headings


def build_document_metadata(
    markdown_text: str,
    filename: str,
    file_size_bytes: int,
    chunk_count: int = 0,
    normalized_document: NormalizedDocument | None = None,
    parse_report: dict[str, Any] | None = None,
    artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    frontmatter = extract_frontmatter(markdown_text)
    headings = extract_section_headings(markdown_text)

    metadata: dict[str, Any] = {
        "filename": filename,
        "format": frontmatter.get("format", "unknown"),
        "upload_date": frontmatter.get("upload_date", ""),
        "page_count": int(frontmatter.get("page_count", 0) or 0),
        "chunk_count": chunk_count,
        "file_size_bytes": file_size_bytes,
        "section_headings": headings[:100],
        "heading_count": len(headings),
    }

    if normalized_document is not None:
        metadata.update(
            {
                "source_format": normalized_document.source_format,
                "parser_used": normalized_document.parser_used,
                "parser_version": normalized_document.parser_version,
                "parse_strategy": normalized_document.parse_strategy,
                "quality_score": normalized_document.quality_score,
                "quality_flags": normalized_document.quality_flags,
                "ocr_used": normalized_document.ocr_used,
                "ocr_languages": normalized_document.ocr_languages,
            }
        )

    if parse_report:
        metadata["parse_report"] = parse_report

    if artifacts:
        metadata["artifacts"] = artifacts

    return metadata


def build_chunk_payload(
    chunk,
    document_id: str,
    filename: str,
) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "filename": filename,
        "section": chunk.section_heading,
        "page_number": chunk.page_number,
        "page_start": getattr(chunk, "page_start", chunk.page_number),
        "page_end": getattr(chunk, "page_end", chunk.page_number),
        "chunk_index": chunk.chunk_index,
        "heading_path": " > ".join(chunk.heading_path) if chunk.heading_path else "",
        "source_format": getattr(chunk, "source_format", ""),
        "parser_used": getattr(chunk, "parser_used", ""),
        "chunk_type": getattr(chunk, "chunk_type", "paragraph"),
        "content_type": getattr(chunk, "content_type", "paragraph"),
        "token_count": chunk.token_count,
        "quality_score": getattr(chunk, "quality_score", 1.0),
        "quality_flags": getattr(chunk, "quality_flags", []),
        "table_id": getattr(chunk, "table_id", None),
        "row_index": getattr(chunk, "row_index", None),
        "parent_chunk_id": getattr(chunk, "parent_chunk_id", None),
        "contains_currency": getattr(chunk, "contains_currency", False),
        "contains_steps": getattr(chunk, "contains_steps", False),
        "contains_ranges": getattr(chunk, "contains_ranges", False),
        "evidence_tags": getattr(chunk, "evidence_tags", []),
        "text": chunk.text,
    }
