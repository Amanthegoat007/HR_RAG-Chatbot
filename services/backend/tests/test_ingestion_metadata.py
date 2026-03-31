import os
import sys

import fitz

os.environ.setdefault("JWT_SECRET", "test_secret_at_least_256bits_long_for_testing")
os.environ.setdefault("POSTGRES_DSN", "postgresql://test:test@localhost/test")
os.environ.setdefault("MINIO_ROOT_PASSWORD", "minioadmin")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "$2b$12$testhashtesthashhh")
os.environ.setdefault("USER_PASSWORD_HASH", "$2b$12$testhashhh")

sys.path.insert(0, "/home/ubuntu/HR_Chatbot/hr-rag-chatbot/services/backend")


def _build_pdf() -> bytes:
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Utility Program Overview")
    page1.insert_text((72, 96), "Deferred Payment Agreement")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "$75 standard reconnection")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_pdf_conversion_emits_frontmatter_and_page_breaks():
    from app.file_converter import convert_to_markdown

    markdown, page_count = convert_to_markdown(_build_pdf(), "utility.pdf")

    assert page_count == 2
    assert markdown.startswith("---")
    assert "filename: utility.pdf" in markdown
    assert "page_count: 2" in markdown
    assert "<!-- PAGE_BREAK: page_2 -->" in markdown


def test_chunker_flushes_on_page_boundaries():
    from app.chunker import chunk_markdown

    markdown = (
        "---\nfilename: utility.pdf\nformat: pdf\npage_count: 2\n---\n\n"
        "# Page One\n\nDeferred Payment Agreement helps with balances.\n\n"
        "<!-- PAGE_BREAK: page_2 -->\n\n"
        "# Page Two\n\n$75 standard reconnection\n"
    )

    chunks = chunk_markdown(markdown, chunk_size=64, overlap=16)

    assert len(chunks) >= 2
    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert all(chunk.page_start == chunk.page_end for chunk in chunks)
    assert any(chunk.contains_currency for chunk in chunks if chunk.page_number == 2)


def test_chunk_payload_includes_evidence_metadata():
    from app.chunker import chunk_markdown
    from app.metadata_extractor import build_chunk_payload

    markdown = (
        "---\nfilename: utility.pdf\nformat: pdf\npage_count: 1\n---\n\n"
        "| Program | Benefit | Application |\n"
        "| --- | --- | --- |\n"
        "| DPA | 6-month plan | Apply by phone |\n"
    )

    chunks = chunk_markdown(markdown, chunk_size=128, overlap=16)
    payload = build_chunk_payload(chunks[0], "doc-1", "utility.pdf")

    assert payload["content_type"] == "table"
    assert payload["page_start"] == 1
    assert payload["page_end"] == 1
    assert "table" in payload["evidence_tags"]


def test_chunker_keeps_table_block_together():
    from app.chunker import chunk_markdown

    markdown = (
        "---\nfilename: utility.pdf\nformat: pdf\npage_count: 1\n---\n\n"
        "## Financial Assistance Overview\n\n"
        "| Program | Benefit | Application |\n"
        "| --- | --- | --- |\n"
        "| Deferred Payment Agreement | 3-6 month plan | Apply online |\n"
        "| Extended Payment Plan | 6-12 month plan | Apply by phone |\n"
        "| Budget Billing | Average monthly payment | Enroll online |\n"
        "| LIHEAP | Seasonal energy grant | Apply through community agency |\n"
        "| UtilityPro Care Fund | $300-$500 one-time grant | Partner agency referral |\n"
    )

    chunks = chunk_markdown(markdown, chunk_size=32, overlap=8)
    table_chunks = [chunk for chunk in chunks if chunk.content_type == "table"]

    assert len(table_chunks) == 1
    assert "Deferred Payment Agreement" in table_chunks[0].text
    assert "UtilityPro Care Fund" in table_chunks[0].text


def test_table_cell_normalization_removes_embedded_newlines():
    from app.file_converter import _normalize_table_cell

    assert _normalize_table_cell("UtilityPro Care Fund\nEmergency/crisis") == "UtilityPro Care Fund Emergency/crisis"
