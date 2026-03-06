from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ArtifactPaths(BaseModel):
    original_path: str = ""
    normalized_markdown_path: str = ""
    normalized_json_path: str = ""
    parse_report_path: str = ""


class NormalizedBlock(BaseModel):
    block_id: str
    page_start: int = 1
    page_end: int = 1
    block_type: str = "paragraph"  # paragraph | list | table | heading
    heading_path: list[str] = Field(default_factory=list)
    section_heading: str = ""
    text: str = ""
    markdown: str = ""
    table_json: dict[str, Any] | None = None
    bbox: dict[str, float] | None = None
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedChunk(BaseModel):
    chunk_id: str
    document_id: str
    chunk_index: int
    chunk_type: str = "paragraph"  # paragraph | list_item | table_full | table_row | section_parent
    page_start: int = 1
    page_end: int = 1
    heading_path: list[str] = Field(default_factory=list)
    section_heading: str = ""
    content_type: str = "paragraph"  # paragraph | list | table
    text: str = ""
    display_markdown: str = ""
    token_count: int = 0
    quality_score: float = 1.0
    quality_flags: list[str] = Field(default_factory=list)
    table_id: str | None = None
    row_index: int | None = None
    parent_chunk_id: str | None = None


class ParserAttempt(BaseModel):
    parser: str
    strategy: str
    success: bool
    quality_score: float = 0.0
    quality_flags: list[str] = Field(default_factory=list)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    error: str | None = None


class ParseReport(BaseModel):
    parser_attempts: list[ParserAttempt] = Field(default_factory=list)
    selected_parser: str = ""
    selected_strategy: str = ""
    quality_score: float = 0.0
    quality_flags: list[str] = Field(default_factory=list)
    ocr_used: bool = False
    ocr_pages: list[int] = Field(default_factory=list)
    page_text_density: float = 0.0
    broken_table_ratio: float = 0.0
    duplicate_header_footer_ratio: float = 0.0
    empty_page_ratio: float = 0.0
    timings_ms: dict[str, float] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class NormalizedDocument(BaseModel):
    document_id: str
    source_filename: str
    source_format: str
    parser_used: str = ""
    parser_version: str = ""
    parse_strategy: str = ""
    ocr_used: bool = False
    ocr_languages: str = ""
    page_count: int = 1
    quality_score: float = 0.0
    quality_flags: list[str] = Field(default_factory=list)
    blocks: list[NormalizedBlock] = Field(default_factory=list)
    artifacts: ArtifactPaths = Field(default_factory=ArtifactPaths)
    parse_report: ParseReport = Field(default_factory=ParseReport)

