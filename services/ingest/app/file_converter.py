"""
============================================================================
FILE: services/ingest/app/file_converter.py
PURPOSE: Format dispatcher — routes uploaded files to the correct converter
         in markdown_converter.py. Also handles Tesseract OCR fallback for
         scanned PDFs that yield no extractable text.
ARCHITECTURE REF: §3.1 — Convert-to-Markdown Before Embedding
DEPENDENCIES: markdown_converter.py, pytesseract, PyMuPDF
============================================================================

OCR Fallback Strategy:
- PDFs can be digital (text extractable) or scanned (image-only, needs OCR)
- We detect scanned pages by checking if PyMuPDF extracts very little text (<50 chars/page)
- If detected as scanned, we fall back to Tesseract OCR for text extraction
- Tesseract supports both English (eng) and Arabic (ara) — configured via TESSERACT_LANG env var
- OCR is significantly slower than text extraction (10-30s/page vs <1s/page)
"""

import logging
from pathlib import Path

from app.config import settings
from shared.document_core.quality import score_markdown_quality

logger = logging.getLogger(__name__)

# Minimum characters per page to consider a PDF as "digitally extractable"
# If average is below this, we assume scanned pages and fall back to OCR
MIN_CHARS_PER_PAGE_THRESHOLD = 50
OCR_IMAGE_MIN_WIDTH = 1600
OCR_IMAGE_CONFIGS = (
    ("block", "--oem 3 --psm 6"),
    ("sparse", "--oem 3 --psm 11 preserve_interword_spaces=1"),
)


def _ocr_language_candidates() -> list[str]:
    primary = (settings.tesseract_lang or "eng").strip()
    candidates = [primary]
    primary_parts = [part.strip() for part in primary.split("+") if part.strip()]
    if "eng" in primary_parts and primary != "eng":
        candidates.append("eng")
    return list(dict.fromkeys(candidates))


def _select_best_ocr_candidate(
    candidates: list[tuple[str, str]],
) -> tuple[str, str, float]:
    if not candidates:
        raise ValueError("No OCR candidates provided")

    scored: list[tuple[float, int, str, str]] = []
    for label, markdown in candidates:
        quality = score_markdown_quality(markdown, 1, ocr_used=True)
        scored.append((quality.score, len(markdown), label, markdown))

    best_score, _, best_label, best_markdown = max(
        scored,
        key=lambda item: (item[0], item[1]),
    )
    return best_label, best_markdown, best_score


def convert_to_markdown(file_bytes: bytes, filename: str) -> tuple[str, int]:
    """
    Dispatch file to the appropriate markdown converter based on file extension.

    This is the single entry point for all document conversions. The caller
    does not need to know about the underlying converter — just pass bytes + filename.

    Conversion chain:
        PDF  → pdf_to_markdown() → OCR fallback if needed
        DOCX → docx_to_markdown()
        XLSX → xlsx_to_markdown()
        PPTX → pptx_to_markdown()
        Images → OCR image to markdown
        TXT  → txt_to_markdown()
        MD   → txt_to_markdown() (just adds frontmatter)

    Args:
        file_bytes: Raw file content in bytes.
        filename: Original filename including extension (e.g., "HR_Policy.pdf").

    Returns:
        Tuple of (markdown_content: str, page_count: int).

    Raises:
        ValueError: If the file format is not supported.
        RuntimeError: If conversion fails.
    """
    suffix = Path(filename).suffix.lower().lstrip(".")

    logger.info("Converting document to markdown", extra={
        "doc_filename": filename,
        "format": suffix,
        "size_bytes": len(file_bytes),
    })

    if suffix == "pdf":
        return _convert_pdf_with_ocr_fallback(file_bytes, filename)
    elif suffix == "docx":
        from app.markdown_converter import docx_to_markdown
        return docx_to_markdown(file_bytes, filename)
    elif suffix == "xlsx":
        from app.markdown_converter import xlsx_to_markdown
        return xlsx_to_markdown(file_bytes, filename)
    elif suffix == "pptx":
        from app.markdown_converter import pptx_to_markdown
        return pptx_to_markdown(file_bytes, filename)
    elif suffix in ("png", "jpg", "jpeg", "webp"):
        return _ocr_image(file_bytes, filename)
    elif suffix in ("txt", "md"):
        from app.markdown_converter import txt_to_markdown
        return txt_to_markdown(file_bytes, filename)
    else:
        raise ValueError(
            f"Unsupported file format: .{suffix}. "
            f"Supported: pdf, docx, xlsx, pptx, txt, md, png, jpg, jpeg, webp"
        )


def _convert_pdf_with_ocr_fallback(file_bytes: bytes, filename: str) -> tuple[str, int]:
    """
    Convert a PDF to markdown, falling back to OCR for scanned pages.

    Process:
    1. Try standard PyMuPDF text extraction (fast, ~<1s per page)
    2. Check text density — if very low, this is likely a scanned PDF
    3. If scanned: extract pages as images and run Tesseract OCR

    Args:
        file_bytes: Raw PDF bytes.
        filename: Original filename.

    Returns:
        Tuple of (markdown_content, page_count).
    """
    from app.markdown_converter import pdf_to_markdown, _build_frontmatter

    # First attempt: standard text extraction
    markdown_text, page_count = pdf_to_markdown(file_bytes, filename)

    # Measure text density (excluding frontmatter)
    content_lines = [
        line for line in markdown_text.split("\n")
        if not line.startswith("---") and not line.startswith("<!--") and line.strip()
    ]
    total_chars = sum(len(line) for line in content_lines)
    chars_per_page = total_chars / max(page_count, 1)

    if chars_per_page >= MIN_CHARS_PER_PAGE_THRESHOLD:
        # Sufficient text extracted — digital PDF
        logger.info("PDF text extraction successful", extra={
            "doc_filename": filename,
            "pages": page_count,
            "chars_per_page": round(chars_per_page, 1),
        })
        return markdown_text, page_count

    # Low text density — likely a scanned PDF, fall back to OCR
    logger.info("Scanned PDF detected, falling back to OCR", extra={
        "doc_filename": filename,
        "chars_per_page": round(chars_per_page, 1),
        "threshold": MIN_CHARS_PER_PAGE_THRESHOLD,
    })

    return _ocr_pdf(file_bytes, filename, page_count)


def _ocr_pdf(file_bytes: bytes, filename: str, page_count: int) -> tuple[str, int]:
    """
    Extract text from a scanned PDF using Tesseract OCR.

    Each page is rendered as a high-DPI image (300 DPI) and sent to Tesseract.
    The OCR results are assembled into a markdown document.

    Args:
        file_bytes: Raw PDF bytes.
        filename: Original filename.
        page_count: Number of pages (already computed).

    Returns:
        Tuple of (markdown_content, page_count).
    """
    try:
        import fitz          # PyMuPDF — for rendering pages as images
        import pytesseract
        from PIL import Image
        import io
    except ImportError as e:
        raise ImportError(f"OCR dependencies missing: {e}")

    from app.markdown_converter import _build_frontmatter

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    md_parts = [_build_frontmatter(filename, "pdf", page_count)]

    for page_num, page in enumerate(doc, start=1):
        if page_num > 1:
            md_parts.append(f"\n<!-- PAGE_BREAK: page_{page_num} -->\n")

        # Render page to image at 300 DPI for good OCR accuracy
        # Matrix(3.0, 3.0) = 3× scale factor → 72 DPI × 3 = 216 DPI (good balance of quality/speed)
        matrix = fitz.Matrix(3.0, 3.0)
        pixmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB)

        # Convert pixmap to PIL Image for Tesseract
        img_bytes = pixmap.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes))

        # Run Tesseract OCR
        # lang: "eng+ara" supports both English and Arabic (UAE HR documents)
        # config: --psm 1 (automatic page segmentation with OSD)
        try:
            ocr_text = pytesseract.image_to_string(
                img,
                lang=settings.tesseract_lang,
                config="--psm 1",
            ).strip()

            if ocr_text:
                md_parts.append(ocr_text)
            else:
                md_parts.append(f"*(No text extracted from page {page_num})*")

        except Exception as exc:
            logger.warning(f"OCR failed for page {page_num}", extra={"error": str(exc)})
            md_parts.append(f"*(OCR failed for page {page_num}: {exc})*")

        logger.debug(f"OCR page {page_num}/{page_count} complete")

    doc.close()
    return "\n\n".join(md_parts), page_count


def _ocr_image(file_bytes: bytes, filename: str) -> tuple[str, int]:
    try:
        import io

        import pytesseract
        from PIL import Image, ImageFilter, ImageOps
    except ImportError as e:
        raise ImportError(f"OCR dependencies missing: {e}")

    from app.markdown_converter import _build_frontmatter

    def _prepare_image_for_ocr(image: Image.Image) -> Image.Image:
        if image.mode in {"RGBA", "LA"} or (
            image.mode == "P" and image.info.get("transparency") is not None
        ):
            flattened = Image.new("RGBA", image.size, "white")
            flattened.alpha_composite(image.convert("RGBA"))
            image = flattened.convert("RGB")
        else:
            image = image.convert("RGB")

        prepared = ImageOps.autocontrast(image.convert("L"))
        if prepared.width < OCR_IMAGE_MIN_WIDTH:
            scale = OCR_IMAGE_MIN_WIDTH / max(prepared.width, 1)
            prepared = prepared.resize(
                (
                    max(1, int(prepared.width * scale)),
                    max(1, int(prepared.height * scale)),
                ),
                Image.Resampling.LANCZOS,
            )
        return prepared.filter(ImageFilter.SHARPEN)

    img = Image.open(io.BytesIO(file_bytes))
    prepared = _prepare_image_for_ocr(img)
    frontmatter = _build_frontmatter(
        filename,
        Path(filename).suffix.lower().lstrip("."),
        1,
    )

    markdown_candidates: list[tuple[str, str]] = []
    errors: list[str] = []

    for language in _ocr_language_candidates():
        for config_name, config_value in OCR_IMAGE_CONFIGS:
            try:
                text = pytesseract.image_to_string(
                    prepared,
                    lang=language,
                    config=config_value,
                ).strip()
                markdown_body = text or "*(No text extracted from image)*"
                markdown_candidates.append(
                    (
                        f"{language}:{config_name}",
                        f"{frontmatter}\n\n{markdown_body}",
                    ),
                )
            except Exception as exc:
                errors.append(f"{language}:{config_name}:{exc}")

    if not markdown_candidates:
        raise RuntimeError(
            f"Image OCR failed for {filename}: {'; '.join(errors) if errors else 'unknown error'}",
        )

    selected_label, selected_markdown, selected_score = _select_best_ocr_candidate(
        markdown_candidates,
    )
    logger.info(
        "Selected OCR image candidate",
        extra={
            "doc_filename": filename,
            "candidate": selected_label,
            "quality_score": round(selected_score, 3),
            "attempts": len(markdown_candidates),
        },
    )
    return selected_markdown, 1
