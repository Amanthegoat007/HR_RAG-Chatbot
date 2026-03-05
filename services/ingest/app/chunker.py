"""
============================================================================
FILE: services/ingest/app/chunker.py
PURPOSE: Semantic chunking of Markdown documents.
         Splits documents into 256-token chunks, sentence-aligned, with
         64-token overlap. Preserves section heading context in each chunk.
ARCHITECTURE REF: §2 (Key constraints: Chunking), §3.1 — Ingestion Pipeline
DEPENDENCIES: tiktoken, nltk
============================================================================

Chunking Strategy Rationale:
━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. TOKEN-BASED SIZE (256 tokens): Token counting (not character counting) is accurate
   for embedding model context windows. BGE-M3 handles up to 512 tokens per chunk.
   256 tokens gives a good balance of context vs. retrieval precision.

2. SENTENCE ALIGNMENT: Chunks end at sentence boundaries (not mid-sentence).
   This preserves semantic completeness — each chunk is a complete thought.
   Without this, chunks may end mid-sentence, reducing embedding quality.

3. 64-TOKEN OVERLAP: Adjacent chunks share 64 tokens of context.
   This ensures that information spanning two chunks (e.g., a policy that
   starts at the end of one chunk and continues into the next) is still
   retrievable by queries about either portion.

4. SECTION HEADING CONTEXT: Each chunk carries the path of headings above it
   (e.g., "HR Policy > Leave Policy > Annual Leave"). This becomes metadata
   attached to the vector, improving citation quality.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Generator

logger = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """
    A single chunk of text ready for embedding and upsert to Qdrant.

    Attributes:
        chunk_index: Position of this chunk in the document (0-based).
        text: The chunk text content (ready for embedding).
        token_count: Actual token count of this chunk.
        section_heading: The nearest section heading above this chunk.
        page_number: Page number extracted from PAGE_BREAK markers.
        heading_path: Full path from root → current section (for context).
    """
    chunk_index: int
    text: str
    token_count: int
    section_heading: str = ""
    page_number: int = 1
    heading_path: list[str] = field(default_factory=list)


def _get_tokenizer():
    """
    Get tiktoken tokenizer.

    Uses cl100k_base encoding (GPT-4/Mistral-compatible).
    Cached after first call for efficiency.
    """
    import tiktoken
    # cl100k_base is accurate for Mistral and most modern LLMs
    return tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str, tokenizer) -> int:
    """Count tokens in a text string."""
    return len(tokenizer.encode(text))


def _split_into_sentences(text: str) -> list[str]:
    """
    Split text into sentences using NLTK's Punkt tokenizer.

    Falls back to simple period-splitting if NLTK data is unavailable.

    Args:
        text: Text to split.

    Returns:
        List of sentence strings.
    """
    try:
        import nltk
        # Download punkt data if not present (happens on first run)
        try:
            nltk.data.find("tokenizers/punkt_tab")
        except LookupError:
            nltk.download("punkt_tab", quiet=True)

        return nltk.sent_tokenize(text)
    except Exception:
        # Fallback: split on sentence-ending punctuation
        # This handles the case where NLTK isn't available
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]


def chunk_markdown(
    markdown_text: str,
    chunk_size: int = 256,
    overlap: int = 64,
) -> list[DocumentChunk]:
    """
    Split a Markdown document into overlapping semantic chunks.

    This function processes the document in two passes:
    1. Parse structure: extract heading hierarchy and page numbers from markers
    2. Chunk content: split paragraphs into token-sized chunks, sentence-aligned

    Args:
        markdown_text: The full Markdown document (output of markdown_converter.py).
        chunk_size: Target tokens per chunk (default: 256 per architecture spec).
        overlap: Token overlap between adjacent chunks (default: 64 per spec).

    Returns:
        List of DocumentChunk objects, ready for embedding and Qdrant upsert.
    """
    tokenizer = _get_tokenizer()

    # Track state during parsing
    current_headings: list[str] = []    # Stack of active headings [H1, H2, H3, ...]
    current_page: int = 1
    chunks: list[DocumentChunk] = []
    chunk_index = 0

    # Buffer for accumulating text before chunking
    current_buffer: list[str] = []         # Sentence-level buffer
    current_buffer_tokens: int = 0
    overlap_buffer: list[str] = []         # Sentences to carry into next chunk for overlap

    def flush_chunk() -> None:
        """
        Create a DocumentChunk from the current buffer and reset.
        Called when the buffer reaches chunk_size tokens.
        """
        nonlocal current_buffer, current_buffer_tokens, chunk_index, overlap_buffer

        if not current_buffer:
            return

        chunk_text = " ".join(current_buffer).strip()
        if not chunk_text:
            return

        # Build section heading path as a readable breadcrumb
        # e.g., "HR Policy > Leave Policy > Annual Leave"
        heading_path = [h for h in current_headings if h]
        nearest_heading = heading_path[-1] if heading_path else ""

        chunks.append(DocumentChunk(
            chunk_index=chunk_index,
            text=chunk_text,
            token_count=_count_tokens(chunk_text, tokenizer),
            section_heading=nearest_heading,
            page_number=current_page,
            heading_path=heading_path.copy(),
        ))
        chunk_index += 1

        # Build overlap: keep the last N sentences for the next chunk
        # This ensures continuity between consecutive chunks
        overlap_sentences = []
        overlap_token_count = 0
        for sentence in reversed(current_buffer):
            sentence_tokens = _count_tokens(sentence, tokenizer)
            if overlap_token_count + sentence_tokens <= overlap:
                overlap_sentences.insert(0, sentence)
                overlap_token_count += sentence_tokens
            else:
                break

        current_buffer = overlap_sentences
        current_buffer_tokens = overlap_token_count

    # Strip YAML frontmatter (between the first two '---' lines)
    text_without_frontmatter = re.sub(
        r"^---\n.*?\n---\n", "", markdown_text, count=1, flags=re.DOTALL
    )

    # Process document line by line
    for line in text_without_frontmatter.split("\n"):
        # Handle page break markers
        page_match = re.match(r"<!-- PAGE_BREAK: page_(\d+) -->", line)
        if page_match:
            current_page = int(page_match.group(1))
            continue

        # Handle heading lines — update heading stack
        heading_match = re.match(r"^(#{1,6})\s+(.*)", line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()

            # Flush current buffer before starting a new section
            # Each section starts with a fresh chunk (better attribution)
            if current_buffer_tokens >= chunk_size // 4:
                flush_chunk()

            # Update heading stack at the current depth
            # Ensure stack is deep enough
            while len(current_headings) < level:
                current_headings.append("")
            # Truncate deeper levels (entering a new section at this level)
            current_headings = current_headings[:level - 1] + [heading_text]

            # Include heading text as context prefix in the next chunk
            # This ensures every chunk carries its section heading
            heading_tokens = _count_tokens(heading_text, tokenizer)
            current_buffer.insert(0, heading_text)
            current_buffer_tokens += heading_tokens
            continue

        # Skip empty lines
        stripped = line.strip()
        if not stripped:
            continue

        # Split the line into sentences and add to buffer
        sentences = _split_into_sentences(stripped)
        for sentence in sentences:
            sentence_tokens = _count_tokens(sentence, tokenizer)

            # If adding this sentence would exceed chunk_size, flush first
            if current_buffer_tokens + sentence_tokens > chunk_size and current_buffer:
                flush_chunk()

            current_buffer.append(sentence)
            current_buffer_tokens += sentence_tokens

    # Flush any remaining content in the buffer
    if current_buffer:
        flush_chunk()

    logger.info("Chunking complete", extra={
        "total_chunks": len(chunks),
        "avg_tokens": round(
            sum(c.token_count for c in chunks) / max(len(chunks), 1), 1
        ),
    })

    return chunks
