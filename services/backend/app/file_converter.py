"""
============================================================================
FILE: services/backend/app/file_converter.py
PURPOSE: Convert uploaded documents (PDF, DOCX, XLSX, PPTX, TXT, MD) to
         structured Markdown for downstream chunking and citation quality.
ARCHITECTURE REF: §3.1 — Convert-to-Markdown Before Embedding
DEPENDENCIES: docling, PyMuPDF (fitz)
============================================================================
"""

import logging
import re
import tempfile
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

# Supported formats
DOCLING_FORMATS = {"docx", "xlsx", "pptx"}
TEXT_FORMATS = {"txt", "md"}


def convert_to_markdown(file_bytes: bytes, filename: str) -> tuple[str, int]:
    """
    Convert an uploaded file to Markdown text.

    Uses structured PyMuPDF extraction for PDF, Docling for DOCX/XLSX/PPTX,
    and plain decode for TXT/MD.

    Args:
        file_bytes: Raw file content.
        filename: Original filename with extension.

    Returns:
        (markdown_text, page_count)
    """
    suffix = Path(filename).suffix.lower().lstrip(".")

    logger.info("Converting document to markdown", extra={
        "doc_filename": filename,
        "format": suffix,
        "size_bytes": len(file_bytes),
    })

    if suffix == "pdf":
        return _convert_pdf_with_fitz(file_bytes, filename)
    if suffix in DOCLING_FORMATS:
        return _convert_with_docling(file_bytes, filename, suffix)
    if suffix in TEXT_FORMATS:
        text = file_bytes.decode("utf-8", errors="ignore")
        return _prepend_frontmatter(text, filename, suffix, 1), 1

    raise ValueError(
        f"Unsupported file format: .{suffix}. "
        f"Supported: pdf, docx, xlsx, pptx, txt, md"
    )


def _build_frontmatter(filename: str, fmt: str, page_count: int | None = None) -> str:
    lines = [
        "---",
        f"filename: {filename}",
        f"format: {fmt}",
        f"upload_date: {date.today().isoformat()}",
    ]
    if page_count is not None:
        lines.append(f"page_count: {page_count}")
    lines.append("---")
    return "\n".join(lines)


def _prepend_frontmatter(
    markdown_text: str,
    filename: str,
    fmt: str,
    page_count: int | None = None,
) -> str:
    body = (markdown_text or "").strip()
    frontmatter = _build_frontmatter(filename, fmt, page_count)
    if not body:
        return frontmatter
    return f"{frontmatter}\n\n{body}"


def _convert_with_docling(
    file_bytes: bytes,
    filename: str,
    suffix: str,
) -> tuple[str, int]:
    """
    Use docling's DocumentConverter to convert rich documents to Markdown.
    """
    try:
        from docling.document_converter import DocumentConverter

        with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        converter = DocumentConverter()
        result = converter.convert(tmp_path)
        markdown_text = result.document.export_to_markdown()
        page_count = _estimate_page_count(markdown_text, suffix)
        markdown_text = _prepend_frontmatter(markdown_text, filename, suffix, page_count)

        logger.info("Docling conversion successful", extra={
            "doc_filename": filename,
            "format": suffix,
            "markdown_chars": len(markdown_text),
            "pages": page_count,
        })

        try:
            Path(tmp_path).unlink()
        except OSError:
            pass

        return markdown_text, page_count

    except Exception as exc:
        logger.warning("Docling conversion failed", extra={
            "doc_filename": filename,
            "format": suffix,
            "error": str(exc),
        })
        raise RuntimeError(f"Failed to convert {filename}: {exc}") from exc


def _convert_pdf_with_fitz(file_bytes: bytes, filename: str) -> tuple[str, int]:
    """
    Structured PDF conversion using PyMuPDF.

    The output preserves:
    - frontmatter with page count
    - page break markers for chunk attribution
    - heading structure inferred from relative font size
    - markdown tables when PyMuPDF detects tabular content
    """
    try:
        import fitz
    except ImportError as exc:
        raise ImportError("PyMuPDF (fitz) is required for PDF conversion") from exc

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    page_count = len(doc)
    markdown_parts = [_build_frontmatter(filename, "pdf", page_count)]

    try:
        for page_num, page in enumerate(doc, start=1):
            if page_num > 1:
                markdown_parts.append(f"\n<!-- PAGE_BREAK: page_{page_num} -->\n")

            page_markdown = _extract_pdf_page_markdown(page)
            if page_markdown:
                markdown_parts.append(page_markdown)
            else:
                markdown_parts.append(f"*(No extractable text on page {page_num})*")
    finally:
        doc.close()

    markdown_text = "\n\n".join(part for part in markdown_parts if part)
    logger.info("PyMuPDF conversion successful", extra={
        "doc_filename": filename,
        "pages": page_count,
        "markdown_chars": len(markdown_text),
    })
    return markdown_text, page_count


def _extract_pdf_page_markdown(page) -> str:
    import fitz

    page_dict = page.get_text("dict")
    font_sizes: list[float] = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span.get("text", "").strip():
                    font_sizes.append(float(span.get("size", 12.0)))

    font_sizes.sort()
    median_size = font_sizes[len(font_sizes) // 2] if font_sizes else 12.0

    tables = page.find_tables()
    table_items = list(tables.tables) if getattr(tables, "tables", None) else []
    table_bboxes = [fitz.Rect(table.bbox) for table in table_items]

    page_parts: list[str] = []
    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:
            continue

        block_rect = fitz.Rect(block["bbox"])
        if any(block_rect.intersects(table_bbox) for table_bbox in table_bboxes):
            continue

        block_text_parts: list[str] = []
        max_font_in_block = 0.0

        for line in block.get("lines", []):
            line_parts: list[str] = []
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue

                font_size = float(span.get("size", 12.0))
                max_font_in_block = max(max_font_in_block, font_size)
                flags = int(span.get("flags", 0))
                is_bold = bool(flags & 16)
                is_italic = bool(flags & 2)

                if is_bold and is_italic:
                    text = f"***{text}***"
                elif is_bold:
                    text = f"**{text}**"
                elif is_italic:
                    text = f"*{text}*"

                line_parts.append(text)

            if line_parts:
                block_text_parts.append(" ".join(line_parts))

        if not block_text_parts:
            continue

        block_text = " ".join(block_text_parts).strip()
        if not block_text:
            continue

        if max_font_in_block > median_size * 1.5:
            page_parts.append(f"# {block_text}")
        elif max_font_in_block > median_size * 1.3:
            page_parts.append(f"## {block_text}")
        elif max_font_in_block > median_size * 1.1:
            page_parts.append(f"### {block_text}")
        else:
            page_parts.append(block_text)

    for table in table_items:
        table_md = _pymupdf_table_to_markdown(table)
        if table_md:
            page_parts.append(table_md)

    return "\n\n".join(part for part in page_parts if part).strip()


def _pymupdf_table_to_markdown(table) -> str:
    try:
        rows = table.extract()
    except Exception as exc:
        logger.warning("Failed to extract table from PDF", extra={"error": str(exc)})
        return ""

    if not rows:
        return ""

    normalized_rows: list[list[str]] = []
    for row in rows:
        cells = [_normalize_table_cell(cell) for cell in row]
        if any(cells):
            normalized_rows.append(cells)

    if not normalized_rows:
        return ""

    markdown_rows: list[str] = []
    for idx, row in enumerate(normalized_rows):
        markdown_rows.append("| " + " | ".join(row) + " |")
        if idx == 0:
            markdown_rows.append("| " + " | ".join(["---"] * len(row)) + " |")

    return "\n".join(markdown_rows)


def _normalize_table_cell(cell: object) -> str:
    if cell is None:
        return ""

    text = str(cell).replace("|", "\\|")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _estimate_page_count(markdown_text: str, suffix: str) -> int:
    """Estimate page count from markdown content."""
    if suffix == "pdf":
        breaks = markdown_text.count("<!-- PAGE_BREAK")
        if breaks > 0:
            return breaks + 1
        return max(1, len(markdown_text) // 3000)
    if suffix == "pptx":
        slides = markdown_text.count("# Slide") or markdown_text.count("## Slide")
        return max(1, slides)
    return max(1, len(markdown_text) // 3000)
