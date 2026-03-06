"""
============================================================================
FILE: services/ingest/app/chunker.py
PURPOSE: Structure-aware chunking for normalized documents with compatibility
         fallback for markdown-only input.
ARCHITECTURE REF: §2 (Chunking), §3.1 — Ingestion Pipeline
DEPENDENCIES: tiktoken, nltk
============================================================================
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from shared.document_core.models import NormalizedDocument

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    chunk_index: int
    text: str
    token_count: int
    section_heading: str = ""
    page_number: int = 1
    page_start: int = 1
    page_end: int = 1
    heading_path: list[str] = field(default_factory=list)
    content_type: str = "paragraph"
    chunk_type: str = "paragraph"
    source_format: str = ""
    parser_used: str = ""
    quality_score: float = 1.0
    quality_flags: list[str] = field(default_factory=list)
    table_id: str | None = None
    row_index: int | None = None
    parent_chunk_id: str | None = None

    evidence_tags: list[str] = field(default_factory=list)
    contains_currency: bool = False
    contains_steps: bool = False
    contains_ranges: bool = False


def _get_tokenizer():
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str, tokenizer) -> int:
    return len(tokenizer.encode(text))


def _split_into_sentences(text: str) -> list[str]:
    try:
        import nltk

        try:
            nltk.data.find("tokenizers/punkt_tab")
        except LookupError:
            nltk.download("punkt_tab", quiet=True)

        return nltk.sent_tokenize(text)
    except Exception:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in sentences if s.strip()]


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 3


def _is_list_line(line: str) -> bool:
    return bool(re.match(r"^\s*(?:[-*]\s+|\d+\.\s+)", line.strip()))


def _infer_content_metadata(text: str) -> tuple[str, list[str], bool, bool, bool]:
    cleaned = (text or "").strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    content_type = "paragraph"
    if any(_is_table_line(line) for line in lines):
        content_type = "table"
    elif any(_is_list_line(line) for line in lines):
        content_type = "list"

    contains_currency = bool(re.search(r"[$€£]\s*\d", cleaned))
    contains_steps = bool(
        re.search(r"\b(step|steps|process|procedure|apply|approval)\b", cleaned, flags=re.IGNORECASE)
        or sum(1 for line in lines if _is_list_line(line)) >= 2
    )
    contains_ranges = bool(
        re.search(
            r"[$€£]?\s*\d[\d,]*(?:\.\d+)?\s*(?:-|to)\s*[$€£]?\s*\d[\d,]*(?:\.\d+)?",
            cleaned,
            flags=re.IGNORECASE,
        )
    )

    evidence_tags: list[str] = []
    if content_type != "paragraph":
        evidence_tags.append(content_type)
    if contains_currency:
        evidence_tags.append("currency")
    if contains_steps:
        evidence_tags.append("steps")
    if contains_ranges:
        evidence_tags.append("range")

    return content_type, evidence_tags, contains_currency, contains_steps, contains_ranges


def _make_chunk(
    *,
    chunk_index: int,
    text: str,
    section_heading: str,
    page_start: int,
    page_end: int,
    heading_path: list[str],
    chunk_type: str,
    source_format: str,
    parser_used: str,
    quality_score: float,
    quality_flags: list[str],
    tokenizer,
    table_id: str | None = None,
    row_index: int | None = None,
    parent_chunk_id: str | None = None,
) -> DocumentChunk:
    content_type, evidence_tags, contains_currency, contains_steps, contains_ranges = _infer_content_metadata(text)
    return DocumentChunk(
        chunk_index=chunk_index,
        text=text,
        token_count=_count_tokens(text, tokenizer),
        section_heading=section_heading,
        page_number=page_start,
        page_start=page_start,
        page_end=page_end,
        heading_path=heading_path.copy(),
        content_type=content_type,
        chunk_type=chunk_type,
        source_format=source_format,
        parser_used=parser_used,
        quality_score=quality_score,
        quality_flags=quality_flags.copy(),
        table_id=table_id,
        row_index=row_index,
        parent_chunk_id=parent_chunk_id,
        evidence_tags=evidence_tags,
        contains_currency=contains_currency,
        contains_steps=contains_steps,
        contains_ranges=contains_ranges,
    )


def _chunk_text_units(text: str, chunk_size: int, overlap: int, tokenizer) -> list[str]:
    units = _split_into_sentences(text.strip())
    if not units:
        return []

    chunks: list[str] = []
    buffer: list[str] = []
    buffer_tokens = 0

    def flush() -> None:
        nonlocal buffer, buffer_tokens
        if not buffer:
            return
        chunks.append(" ".join(buffer).strip())
        overlap_units: list[str] = []
        overlap_tokens = 0
        for unit in reversed(buffer):
            unit_tokens = _count_tokens(unit, tokenizer)
            if overlap_tokens + unit_tokens <= overlap:
                overlap_units.insert(0, unit)
                overlap_tokens += unit_tokens
            else:
                break
        buffer = overlap_units
        buffer_tokens = overlap_tokens

    for unit in units:
        unit_tokens = _count_tokens(unit, tokenizer)
        if buffer and buffer_tokens + unit_tokens > chunk_size:
            flush()
        buffer.append(unit)
        buffer_tokens += unit_tokens

    flush()
    return chunks


def chunk_normalized_document(
    normalized: NormalizedDocument,
    chunk_size: int = 256,
    overlap: int = 64,
) -> list[DocumentChunk]:
    tokenizer = _get_tokenizer()
    chunks: list[DocumentChunk] = []
    chunk_index = 0

    for block in normalized.blocks:
        heading_path = block.heading_path or []
        section_heading = block.section_heading or (heading_path[-1] if heading_path else "")
        page_start = max(1, block.page_start)
        page_end = max(page_start, block.page_end)
        block_text = (block.markdown or block.text or "").strip()
        if not block_text:
            continue

        # Table handling: add one full table chunk + row-level chunks for precision.
        if block.block_type == "table":
            full_chunk = _make_chunk(
                chunk_index=chunk_index,
                text=block_text,
                section_heading=section_heading,
                page_start=page_start,
                page_end=page_end,
                heading_path=heading_path,
                chunk_type="table_full",
                source_format=normalized.source_format,
                parser_used=normalized.parser_used,
                quality_score=normalized.quality_score,
                quality_flags=normalized.quality_flags,
                tokenizer=tokenizer,
                table_id=block.block_id,
            )
            chunks.append(full_chunk)
            parent_chunk_id = str(chunk_index)
            chunk_index += 1

            table_json = block.table_json or {}
            headers = table_json.get("headers") or []
            rows = table_json.get("rows") or []
            for row_index, row in enumerate(rows):
                pairs: list[str] = []
                for idx, cell in enumerate(row):
                    header = headers[idx] if idx < len(headers) else f"col_{idx + 1}"
                    cell_text = str(cell).strip()
                    if cell_text:
                        pairs.append(f"{header}: {cell_text}")
                row_text = " | ".join(pairs).strip()
                if not row_text:
                    continue
                row_chunk = _make_chunk(
                    chunk_index=chunk_index,
                    text=row_text,
                    section_heading=section_heading,
                    page_start=page_start,
                    page_end=page_end,
                    heading_path=heading_path,
                    chunk_type="table_row",
                    source_format=normalized.source_format,
                    parser_used=normalized.parser_used,
                    quality_score=normalized.quality_score,
                    quality_flags=normalized.quality_flags,
                    tokenizer=tokenizer,
                    table_id=block.block_id,
                    row_index=row_index,
                    parent_chunk_id=parent_chunk_id,
                )
                chunks.append(row_chunk)
                chunk_index += 1
            continue

        if block.block_type == "list":
            list_items = [line.strip() for line in block_text.splitlines() if line.strip()]
            for item in list_items:
                if _count_tokens(item, tokenizer) <= chunk_size:
                    chunks.append(
                        _make_chunk(
                            chunk_index=chunk_index,
                            text=item,
                            section_heading=section_heading,
                            page_start=page_start,
                            page_end=page_end,
                            heading_path=heading_path,
                            chunk_type="list_item",
                            source_format=normalized.source_format,
                            parser_used=normalized.parser_used,
                            quality_score=normalized.quality_score,
                            quality_flags=normalized.quality_flags,
                            tokenizer=tokenizer,
                        )
                    )
                    chunk_index += 1
                else:
                    for unit_chunk in _chunk_text_units(item, chunk_size, overlap, tokenizer):
                        chunks.append(
                            _make_chunk(
                                chunk_index=chunk_index,
                                text=unit_chunk,
                                section_heading=section_heading,
                                page_start=page_start,
                                page_end=page_end,
                                heading_path=heading_path,
                                chunk_type="list_item",
                                source_format=normalized.source_format,
                                parser_used=normalized.parser_used,
                                quality_score=normalized.quality_score,
                                quality_flags=normalized.quality_flags,
                                tokenizer=tokenizer,
                            )
                        )
                        chunk_index += 1
            continue

        for unit_chunk in _chunk_text_units(block_text, chunk_size, overlap, tokenizer):
            chunks.append(
                _make_chunk(
                    chunk_index=chunk_index,
                    text=unit_chunk,
                    section_heading=section_heading,
                    page_start=page_start,
                    page_end=page_end,
                    heading_path=heading_path,
                    chunk_type="paragraph",
                    source_format=normalized.source_format,
                    parser_used=normalized.parser_used,
                    quality_score=normalized.quality_score,
                    quality_flags=normalized.quality_flags,
                    tokenizer=tokenizer,
                )
            )
            chunk_index += 1

    logger.info(
        "Normalized chunking complete",
        extra={
            "document_id": normalized.document_id,
            "chunks": len(chunks),
            "avg_tokens": round(sum(chunk.token_count for chunk in chunks) / max(len(chunks), 1), 1),
        },
    )
    return chunks


def chunk_markdown(
    markdown_text: str,
    chunk_size: int = 256,
    overlap: int = 64,
) -> list[DocumentChunk]:
    """
    Backward-compatible markdown chunking entrypoint.
    """
    pseudo_doc = NormalizedDocument(
        document_id="legacy",
        source_filename="legacy.md",
        source_format="md",
        parser_used="legacy_markdown",
        page_count=1,
        quality_score=1.0,
        quality_flags=[],
        blocks=[],
    )

    # Lightweight markdown-to-block fallback for legacy callers.
    current_page = 1
    section_heading = ""
    heading_path: list[str] = []
    block_idx = 0
    buffer: list[str] = []
    buffer_type = "paragraph"

    def flush() -> None:
        nonlocal block_idx, buffer, buffer_type
        if not buffer:
            return
        content = "\n".join(buffer).strip()
        if not content:
            buffer = []
            return
        pseudo_doc.blocks.append(
            type("Block", (), {
                "block_id": f"legacy-block-{block_idx}",
                "page_start": current_page,
                "page_end": current_page,
                "block_type": buffer_type,
                "heading_path": heading_path.copy(),
                "section_heading": section_heading,
                "text": content,
                "markdown": content,
                "table_json": None,
            })
        )
        block_idx += 1
        buffer = []
        buffer_type = "paragraph"

    clean = re.sub(r"^---\n.*?\n---\n?", "", markdown_text or "", flags=re.DOTALL)
    for raw_line in clean.splitlines():
        line = raw_line.strip()
        page_match = re.match(r"<!-- PAGE_BREAK: page_(\d+) -->", line)
        if page_match:
            flush()
            current_page = int(page_match.group(1))
            continue

        if not line:
            flush()
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)", line)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            section_heading = heading_match.group(2).strip()
            while len(heading_path) < level:
                heading_path.append("")
            heading_path = heading_path[: level - 1] + [section_heading]
            continue

        line_type = "table" if _is_table_line(line) else "list" if _is_list_line(line) else "paragraph"
        if buffer and line_type != buffer_type:
            flush()
        buffer_type = line_type
        buffer.append(line)

    flush()
    return chunk_normalized_document(pseudo_doc, chunk_size=chunk_size, overlap=overlap)
