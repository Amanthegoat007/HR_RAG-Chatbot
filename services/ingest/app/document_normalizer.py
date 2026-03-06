from __future__ import annotations

import json
import logging
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.file_converter import convert_to_markdown as legacy_convert_to_markdown
from app.markdown_converter import (
    _build_frontmatter,
    docx_to_markdown,
    pdf_to_markdown,
    pptx_to_markdown,
    txt_to_markdown,
    xlsx_to_markdown,
)
from shared.document_core.models import (
    ArtifactPaths,
    NormalizedBlock,
    NormalizedDocument,
    ParseReport,
    ParserAttempt,
)
from shared.document_core.quality import score_markdown_quality

logger = logging.getLogger(__name__)

PAGE_BREAK_RE = re.compile(r"<!-- PAGE_BREAK: page_(\d+) -->", flags=re.IGNORECASE)
TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
LIST_LINE_RE = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+)")
HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.*)")


@dataclass
class _Candidate:
    parser: str
    strategy: str
    markdown: str
    page_count: int
    quality_score: float
    quality_flags: list[str]
    quality_metrics: dict[str, float]
    ocr_used: bool
    timings_ms: dict[str, float]
    error: str | None = None


def normalize_document(
    file_bytes: bytes,
    filename: str,
    document_id: str,
) -> NormalizedDocument:
    suffix = Path(filename).suffix.lower().lstrip(".")
    attempts: list[ParserAttempt] = []
    candidates: list[_Candidate] = []
    errors: list[str] = []

    # 1) Primary: Docling (where available).
    if settings.enable_docling_parser and suffix in {"pdf", "docx", "xlsx", "pptx"}:
        candidate = _attempt_docling(file_bytes, filename, suffix)
        _record_attempt(candidate, attempts, errors)
        if candidate.error is None:
            candidates.append(candidate)

    # 2) Fallback path by format.
    if suffix == "pdf":
        native_pdf = _attempt_native_pdf(file_bytes, filename)
        _record_attempt(native_pdf, attempts, errors)
        if native_pdf.error is None:
            candidates.append(native_pdf)

        if settings.enable_unstructured_fallback:
            unstructured_pdf = _attempt_unstructured_pdf(file_bytes, filename)
            _record_attempt(unstructured_pdf, attempts, errors)
            if unstructured_pdf.error is None:
                candidates.append(unstructured_pdf)
    elif suffix in {"docx", "xlsx", "pptx", "txt", "md"}:
        native_doc = _attempt_native_office_or_text(file_bytes, filename, suffix)
        _record_attempt(native_doc, attempts, errors)
        if native_doc.error is None:
            candidates.append(native_doc)
    else:
        fallback = _attempt_legacy_dispatch(file_bytes, filename, suffix)
        _record_attempt(fallback, attempts, errors)
        if fallback.error is None:
            candidates.append(fallback)

    if not candidates:
        raise RuntimeError(f"No parser succeeded for {filename}: {'; '.join(errors) if errors else 'unknown error'}")

    selected = max(
        candidates,
        key=lambda c: (c.quality_score, -len(c.quality_flags), c.page_count),
    )

    report = ParseReport(
        parser_attempts=attempts,
        selected_parser=selected.parser,
        selected_strategy=selected.strategy,
        quality_score=selected.quality_score,
        quality_flags=selected.quality_flags,
        ocr_used=selected.ocr_used,
        ocr_pages=[],
        page_text_density=selected.quality_metrics.get("page_text_density", 0.0),
        broken_table_ratio=selected.quality_metrics.get("broken_table_ratio", 0.0),
        duplicate_header_footer_ratio=selected.quality_metrics.get("duplicate_header_footer_ratio", 0.0),
        empty_page_ratio=selected.quality_metrics.get("empty_page_ratio", 0.0),
        timings_ms=selected.timings_ms,
        errors=errors,
    )

    blocks = _markdown_to_blocks(selected.markdown)

    return NormalizedDocument(
        document_id=document_id,
        source_filename=filename,
        source_format=suffix,
        parser_used=selected.parser,
        parser_version="n/a",
        parse_strategy=selected.strategy,
        ocr_used=selected.ocr_used,
        ocr_languages=settings.tesseract_lang if selected.ocr_used else "",
        page_count=max(selected.page_count, 1),
        quality_score=selected.quality_score,
        quality_flags=selected.quality_flags,
        blocks=blocks,
        artifacts=ArtifactPaths(),
        parse_report=report,
    )


def _record_attempt(
    candidate: _Candidate,
    attempts: list[ParserAttempt],
    errors: list[str],
) -> None:
    attempts.append(
        ParserAttempt(
            parser=candidate.parser,
            strategy=candidate.strategy,
            success=candidate.error is None,
            quality_score=candidate.quality_score,
            quality_flags=candidate.quality_flags,
            timings_ms=candidate.timings_ms,
            error=candidate.error,
        )
    )
    if candidate.error:
        errors.append(f"{candidate.parser}:{candidate.strategy}:{candidate.error}")


def _attempt_docling(file_bytes: bytes, filename: str, suffix: str) -> _Candidate:
    started = time.perf_counter()
    try:
        from docling.document_converter import DocumentConverter

        with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        converter = DocumentConverter()
        result = converter.convert(tmp_path)
        markdown = result.document.export_to_markdown() or ""
        page_count = _estimate_page_count(markdown, suffix)
        markdown = _ensure_frontmatter(markdown, filename, suffix, page_count)
        quality = score_markdown_quality(markdown, page_count)
        return _Candidate(
            parser="docling",
            strategy="standard",
            markdown=markdown,
            page_count=page_count,
            quality_score=quality.score,
            quality_flags=quality.flags,
            quality_metrics=quality.metrics,
            ocr_used=False,
            timings_ms={"parse": round((time.perf_counter() - started) * 1000, 2)},
        )
    except Exception as exc:
        return _Candidate(
            parser="docling",
            strategy="standard",
            markdown="",
            page_count=0,
            quality_score=0.0,
            quality_flags=["parser_error"],
            quality_metrics={},
            ocr_used=False,
            timings_ms={"parse": round((time.perf_counter() - started) * 1000, 2)},
            error=str(exc),
        )


def _attempt_native_pdf(file_bytes: bytes, filename: str) -> _Candidate:
    started = time.perf_counter()
    try:
        markdown, page_count = pdf_to_markdown(file_bytes, filename)
        quality = score_markdown_quality(markdown, page_count)
        return _Candidate(
            parser="pymupdf",
            strategy="native_pdf",
            markdown=markdown,
            page_count=page_count,
            quality_score=quality.score,
            quality_flags=quality.flags,
            quality_metrics=quality.metrics,
            ocr_used=False,
            timings_ms={"parse": round((time.perf_counter() - started) * 1000, 2)},
        )
    except Exception as exc:
        return _Candidate(
            parser="pymupdf",
            strategy="native_pdf",
            markdown="",
            page_count=0,
            quality_score=0.0,
            quality_flags=["parser_error"],
            quality_metrics={},
            ocr_used=False,
            timings_ms={"parse": round((time.perf_counter() - started) * 1000, 2)},
            error=str(exc),
        )


def _attempt_native_office_or_text(file_bytes: bytes, filename: str, suffix: str) -> _Candidate:
    started = time.perf_counter()
    try:
        if suffix == "docx":
            markdown, page_count = docx_to_markdown(file_bytes, filename)
            parser = "python-docx"
            strategy = "native_docx"
        elif suffix == "xlsx":
            markdown, page_count = xlsx_to_markdown(file_bytes, filename)
            parser = "openpyxl"
            strategy = "native_xlsx"
        elif suffix == "pptx":
            markdown, page_count = pptx_to_markdown(file_bytes, filename)
            parser = "python-pptx"
            strategy = "native_pptx"
        else:
            markdown, page_count = txt_to_markdown(file_bytes, filename)
            parser = "plain_text"
            strategy = "native_text"

        quality = score_markdown_quality(markdown, page_count)
        return _Candidate(
            parser=parser,
            strategy=strategy,
            markdown=markdown,
            page_count=page_count,
            quality_score=quality.score,
            quality_flags=quality.flags,
            quality_metrics=quality.metrics,
            ocr_used=False,
            timings_ms={"parse": round((time.perf_counter() - started) * 1000, 2)},
        )
    except Exception as exc:
        return _Candidate(
            parser="native",
            strategy=f"native_{suffix}",
            markdown="",
            page_count=0,
            quality_score=0.0,
            quality_flags=["parser_error"],
            quality_metrics={},
            ocr_used=False,
            timings_ms={"parse": round((time.perf_counter() - started) * 1000, 2)},
            error=str(exc),
        )


def _attempt_unstructured_pdf(file_bytes: bytes, filename: str) -> _Candidate:
    started = time.perf_counter()
    try:
        from unstructured.partition.pdf import partition_pdf

        strategy = (settings.unstructured_pdf_strategy or "fast").strip().lower()
        if strategy not in {"fast", "hi_res", "ocr_only"}:
            strategy = "fast"

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        partition_kwargs: dict[str, Any] = {
            "filename": tmp_path,
            "strategy": strategy,
        }
        if strategy == "hi_res":
            partition_kwargs["infer_table_structure"] = True

        elements = partition_pdf(**partition_kwargs)
        page_map: dict[int, list[str]] = {}
        for element in elements:
            text = (getattr(element, "text", "") or "").strip()
            if not text:
                continue
            metadata = getattr(element, "metadata", None)
            page_number = getattr(metadata, "page_number", 1) if metadata else 1
            page_idx = int(page_number or 1)
            page_map.setdefault(page_idx, []).append(text)

        if not page_map:
            raise RuntimeError("Unstructured produced no text")

        max_page = max(page_map.keys())
        markdown_parts = [_build_frontmatter(filename, "pdf", max_page)]
        for page in range(1, max_page + 1):
            if page > 1:
                markdown_parts.append(f"\n<!-- PAGE_BREAK: page_{page} -->\n")
            content = "\n\n".join(page_map.get(page, [])) or f"*(No extractable text on page {page})*"
            markdown_parts.append(content)

        markdown = "\n\n".join(markdown_parts)
        ocr_used = strategy in {"hi_res", "ocr_only"}
        quality = score_markdown_quality(markdown, max_page, ocr_used=ocr_used)
        return _Candidate(
            parser="unstructured",
            strategy=f"pdf_{strategy}",
            markdown=markdown,
            page_count=max_page,
            quality_score=quality.score,
            quality_flags=quality.flags + ["parser_fallback_used"],
            quality_metrics=quality.metrics,
            ocr_used=ocr_used,
            timings_ms={"parse": round((time.perf_counter() - started) * 1000, 2)},
        )
    except Exception as exc:
        return _Candidate(
            parser="unstructured",
            strategy="pdf_hi_res",
            markdown="",
            page_count=0,
            quality_score=0.0,
            quality_flags=["parser_error"],
            quality_metrics={},
            ocr_used=False,
            timings_ms={"parse": round((time.perf_counter() - started) * 1000, 2)},
            error=str(exc),
        )


def _attempt_legacy_dispatch(file_bytes: bytes, filename: str, suffix: str) -> _Candidate:
    started = time.perf_counter()
    try:
        markdown, page_count = legacy_convert_to_markdown(file_bytes, filename)
        quality = score_markdown_quality(markdown, page_count)
        return _Candidate(
            parser="legacy_dispatch",
            strategy=f"legacy_{suffix or 'unknown'}",
            markdown=markdown,
            page_count=page_count,
            quality_score=quality.score,
            quality_flags=quality.flags + ["parser_fallback_used"],
            quality_metrics=quality.metrics,
            ocr_used=False,
            timings_ms={"parse": round((time.perf_counter() - started) * 1000, 2)},
        )
    except Exception as exc:
        return _Candidate(
            parser="legacy_dispatch",
            strategy=f"legacy_{suffix or 'unknown'}",
            markdown="",
            page_count=0,
            quality_score=0.0,
            quality_flags=["parser_error"],
            quality_metrics={},
            ocr_used=False,
            timings_ms={"parse": round((time.perf_counter() - started) * 1000, 2)},
            error=str(exc),
        )


def _ensure_frontmatter(markdown: str, filename: str, suffix: str, page_count: int) -> str:
    body = (markdown or "").strip()
    if body.startswith("---\n"):
        return body
    return f"{_build_frontmatter(filename, suffix, page_count)}\n\n{body}" if body else _build_frontmatter(filename, suffix, page_count)


def _estimate_page_count(markdown_text: str, suffix: str) -> int:
    breaks = len(PAGE_BREAK_RE.findall(markdown_text or ""))
    if breaks > 0:
        return breaks + 1
    if suffix == "pptx":
        slides = (markdown_text or "").count("# Slide") + (markdown_text or "").count("## Slide")
        return max(1, slides)
    return max(1, len((markdown_text or "").splitlines()) // 80)


def _markdown_to_blocks(markdown_text: str) -> list[NormalizedBlock]:
    blocks: list[NormalizedBlock] = []
    text = re.sub(r"^---\n.*?\n---\n?", "", markdown_text or "", flags=re.DOTALL)

    page = 1
    heading_path: list[str] = []
    buffer: list[str] = []
    buffer_type = "paragraph"
    block_idx = 0

    def flush() -> None:
        nonlocal buffer, block_idx, buffer_type
        if not buffer:
            return
        content = "\n".join(buffer).strip()
        if not content:
            buffer = []
            return

        table_json: dict[str, Any] | None = None
        if buffer_type == "table":
            table_json = _parse_markdown_table(buffer)

        blocks.append(
            NormalizedBlock(
                block_id=f"block-{block_idx}",
                page_start=page,
                page_end=page,
                block_type=buffer_type,
                heading_path=heading_path.copy(),
                section_heading=heading_path[-1] if heading_path else "",
                text=content,
                markdown=content,
                table_json=table_json,
                confidence=1.0,
                metadata={},
            )
        )
        block_idx += 1
        buffer = []
        buffer_type = "paragraph"

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        page_match = PAGE_BREAK_RE.match(stripped)
        if page_match:
            flush()
            page = int(page_match.group(1))
            continue

        if not stripped:
            flush()
            continue

        heading_match = HEADING_RE.match(stripped)
        if heading_match:
            flush()
            level = len(heading_match.group(1))
            heading = heading_match.group(2).strip()
            while len(heading_path) < level:
                heading_path.append("")
            heading_path = heading_path[: level - 1] + [heading]
            blocks.append(
                NormalizedBlock(
                    block_id=f"block-{block_idx}",
                    page_start=page,
                    page_end=page,
                    block_type="heading",
                    heading_path=heading_path.copy(),
                    section_heading=heading,
                    text=heading,
                    markdown=stripped,
                    confidence=1.0,
                    metadata={"level": level},
                )
            )
            block_idx += 1
            continue

        line_type = "paragraph"
        if TABLE_LINE_RE.match(stripped):
            line_type = "table"
        elif LIST_LINE_RE.match(stripped):
            line_type = "list"

        if buffer and line_type != buffer_type:
            flush()
        buffer_type = line_type
        buffer.append(stripped)

    flush()
    return blocks


def _parse_markdown_table(lines: list[str]) -> dict[str, Any]:
    rows: list[list[str]] = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells:
            rows.append(cells)
    if not rows:
        return {"headers": [], "rows": []}

    headers = rows[0]
    data_rows: list[list[str]] = []
    for row in rows[1:]:
        if all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in row):
            continue
        if len(row) < len(headers):
            row = row + [""] * (len(headers) - len(row))
        data_rows.append(row[: len(headers)])

    return {"headers": headers, "rows": data_rows}


def normalized_document_to_json(normalized: NormalizedDocument) -> str:
    return normalized.model_dump_json(indent=2)


def parse_report_to_json(report: ParseReport) -> str:
    return report.model_dump_json(indent=2)
