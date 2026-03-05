"""
============================================================================
FILE: services/backend/app/file_converter.py
PURPOSE: Convert uploaded documents (PDF, DOCX, XLSX, PPTX, TXT, MD) to
         Markdown using the docling library for rich format support,
         with PyMuPDF fallback for PDFs.
ARCHITECTURE REF: §3.1 — Convert-to-Markdown Before Embedding
DEPENDENCIES: docling, PyMuPDF (fitz)
============================================================================
"""

import io
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Supported formats
# Keep PDF on a simple PyMuPDF path to avoid heavy Docling model downloads.
DOCLING_FORMATS = {"docx", "xlsx", "pptx"}
TEXT_FORMATS = {"txt", "md"}


def convert_to_markdown(file_bytes: bytes, filename: str) -> tuple[str, int]:
    """
    Convert an uploaded file to Markdown text.

    Uses PyMuPDF for PDF, Docling for DOCX/XLSX/PPTX, plain decode for TXT/MD.

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
    elif suffix in DOCLING_FORMATS:
        return _convert_with_docling(file_bytes, filename, suffix)
    elif suffix in TEXT_FORMATS:
        text = file_bytes.decode("utf-8", errors="ignore")
        return text, 1
    else:
        raise ValueError(
            f"Unsupported file format: .{suffix}. "
            f"Supported: pdf, docx, xlsx, pptx, txt, md"
        )


def _convert_with_docling(file_bytes: bytes, filename: str, suffix: str) -> tuple[str, int]:
    """
    Use docling's DocumentConverter to convert rich documents to Markdown.

    Falls back to PyMuPDF for PDFs if docling fails.
    """
    try:
        from docling.document_converter import DocumentConverter

        # Docling needs a file path, so write bytes to a temp file
        with tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        converter = DocumentConverter()
        result = converter.convert(tmp_path)

        markdown_text = result.document.export_to_markdown()

        # Estimate page count
        page_count = _estimate_page_count(markdown_text, suffix)

        logger.info("Docling conversion successful", extra={
            "doc_filename": filename,
            "format": suffix,
            "markdown_chars": len(markdown_text),
            "pages": page_count,
        })

        # Clean up temp file
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass

        return markdown_text, page_count

    except Exception as exc:
        logger.warning(f"Docling conversion failed, trying fallback: {exc}")

        if suffix == "pdf":
            return _convert_pdf_with_fitz(file_bytes, filename)

        # For non-PDF formats, re-raise since we have no fallback
        raise RuntimeError(f"Failed to convert {filename}: {exc}") from exc


def _convert_pdf_with_fitz(file_bytes: bytes, filename: str) -> tuple[str, int]:
    """
    Fallback PDF converter using PyMuPDF (fitz) for direct text extraction.
    """
    try:
        import fitz
    except ImportError:
        raise ImportError("PyMuPDF (fitz) is required for PDF fallback conversion")

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    text_parts = []
    page_count = len(doc)

    for i, page in enumerate(doc):
        text = page.get_text()
        if text.strip():
            text_parts.append(text)
        else:
            text_parts.append(f"*(No extractable text on page {i+1})*")

    doc.close()

    markdown_text = "\n\n".join(text_parts)
    logger.info("PyMuPDF fallback conversion successful", extra={
        "doc_filename": filename,
        "pages": page_count,
        "markdown_chars": len(markdown_text),
    })
    return markdown_text, page_count


def _estimate_page_count(markdown_text: str, suffix: str) -> int:
    """Estimate page count from markdown content."""
    if suffix == "pdf":
        # Count page break markers if docling inserted them
        breaks = markdown_text.count("<!-- PAGE_BREAK")
        if breaks > 0:
            return breaks + 1
        # Estimate: ~3000 chars per page
        return max(1, len(markdown_text) // 3000)
    elif suffix == "pptx":
        # Each slide is roughly a page
        slides = markdown_text.count("# Slide") or markdown_text.count("## Slide")
        return max(1, slides)
    else:
        # For DOCX/XLSX, estimate
        return max(1, len(markdown_text) // 3000)
