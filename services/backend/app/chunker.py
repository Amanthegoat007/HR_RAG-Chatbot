"""
============================================================================
FILE: services/backend/app/chunker.py
PURPOSE: Semantic chunking of Markdown documents with page-safe attribution.
ARCHITECTURE REF: §2 (Chunking), §3.1 — Ingestion Pipeline
DEPENDENCIES: tiktoken, nltk
============================================================================
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """
    A single chunk of text ready for embedding and upsert to Qdrant.
    """

    chunk_index: int
    text: str
    token_count: int
    section_heading: str = ""
    page_number: int = 1
    page_start: int = 1
    page_end: int = 1
    heading_path: list[str] = field(default_factory=list)
    content_type: str = "paragraph"
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
    stripped = line.strip()
    return bool(re.match(r"^([-*]\s+|\d+\.\s+)", stripped))


def _is_table_block(block: str) -> bool:
    lines = [line.strip() for line in (block or "").splitlines() if line.strip()]
    return bool(lines) and all(_is_table_line(line) for line in lines)


def _split_line_units(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped:
        return []
    if _is_table_line(stripped) or _is_list_line(stripped):
        return [stripped]
    return _split_into_sentences(stripped)


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
        re.search(r"[$€£]?\s*\d[\d,]*(?:\.\d+)?\s*(?:-|to)\s*[$€£]?\s*\d[\d,]*(?:\.\d+)?", cleaned, flags=re.IGNORECASE)
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


def _iter_markdown_blocks(markdown_text: str) -> list[str]:
    blocks: list[str] = []
    lines = markdown_text.split("\n")
    idx = 0

    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()

        if _is_table_line(stripped):
            table_lines = [stripped]
            idx += 1
            while idx < len(lines) and _is_table_line(lines[idx].strip()):
                table_lines.append(lines[idx].strip())
                idx += 1
            blocks.append("\n".join(table_lines))
            continue

        blocks.append(line)
        idx += 1

    return blocks


def chunk_markdown(
    markdown_text: str,
    chunk_size: int = 256,
    overlap: int = 64,
) -> list[DocumentChunk]:
    tokenizer = _get_tokenizer()

    current_headings: list[str] = []
    current_page = 1
    current_chunk_page_start = 1
    chunks: list[DocumentChunk] = []
    chunk_index = 0

    current_buffer: list[str] = []
    current_buffer_tokens = 0

    def buffer_is_heading_only() -> bool:
        if not current_buffer:
            return False
        active_headings = {heading for heading in current_headings if heading}
        return bool(active_headings) and all(unit.strip() in active_headings for unit in current_buffer if unit.strip())

    def flush_chunk(carry_overlap: bool = True) -> None:
        nonlocal current_buffer
        nonlocal current_buffer_tokens
        nonlocal chunk_index
        nonlocal current_chunk_page_start

        if not current_buffer:
            return

        chunk_text = "\n".join(current_buffer).strip()
        if not chunk_text:
            current_buffer = []
            current_buffer_tokens = 0
            current_chunk_page_start = current_page
            return

        heading_path = [heading for heading in current_headings if heading]
        nearest_heading = heading_path[-1] if heading_path else ""
        content_type, evidence_tags, contains_currency, contains_steps, contains_ranges = (
            _infer_content_metadata(chunk_text)
        )

        chunks.append(DocumentChunk(
            chunk_index=chunk_index,
            text=chunk_text,
            token_count=_count_tokens(chunk_text, tokenizer),
            section_heading=nearest_heading,
            page_number=current_chunk_page_start,
            page_start=current_chunk_page_start,
            page_end=current_page,
            heading_path=heading_path.copy(),
            content_type=content_type,
            evidence_tags=evidence_tags,
            contains_currency=contains_currency,
            contains_steps=contains_steps,
            contains_ranges=contains_ranges,
        ))
        chunk_index += 1

        overlap_units: list[str] = []
        overlap_token_count = 0
        if carry_overlap:
            for unit in reversed(current_buffer):
                unit_tokens = _count_tokens(unit, tokenizer)
                if overlap_token_count + unit_tokens <= overlap:
                    overlap_units.insert(0, unit)
                    overlap_token_count += unit_tokens
                else:
                    break

        current_buffer = overlap_units
        current_buffer_tokens = overlap_token_count
        current_chunk_page_start = current_page

    text_without_frontmatter = re.sub(
        r"^---\n.*?\n---\n", "", markdown_text, count=1, flags=re.DOTALL
    )

    for block in _iter_markdown_blocks(text_without_frontmatter):
        page_match = re.match(r"<!-- PAGE_BREAK: page_(\d+) -->", block.strip())
        if page_match:
            flush_chunk(carry_overlap=False)
            current_page = int(page_match.group(1))
            current_chunk_page_start = current_page
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)", block)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()

            if current_buffer_tokens >= chunk_size // 4:
                flush_chunk(carry_overlap=False)

            while len(current_headings) < level:
                current_headings.append("")
            current_headings = current_headings[:level - 1] + [heading_text]

            if not current_buffer:
                current_chunk_page_start = current_page
            current_buffer.append(heading_text)
            current_buffer_tokens += _count_tokens(heading_text, tokenizer)
            continue

        if _is_table_block(block):
            if current_buffer_tokens + _count_tokens(block, tokenizer) > chunk_size and current_buffer and not buffer_is_heading_only():
                flush_chunk(carry_overlap=False)

            if not current_buffer:
                current_chunk_page_start = current_page

            current_buffer.append(block)
            current_buffer_tokens += _count_tokens(block, tokenizer)
            flush_chunk(carry_overlap=False)
            continue

        units = _split_line_units(block)
        for unit in units:
            if not current_buffer:
                current_chunk_page_start = current_page

            unit_tokens = _count_tokens(unit, tokenizer)
            if current_buffer_tokens + unit_tokens > chunk_size and current_buffer:
                flush_chunk(carry_overlap=True)
                if not current_buffer:
                    current_chunk_page_start = current_page

            current_buffer.append(unit)
            current_buffer_tokens += unit_tokens

    flush_chunk(carry_overlap=False)

    logger.info("Chunking complete", extra={
        "total_chunks": len(chunks),
        "avg_tokens": round(
            sum(chunk.token_count for chunk in chunks) / max(len(chunks), 1), 1
        ),
    })

    return chunks
