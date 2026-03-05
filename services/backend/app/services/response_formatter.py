import re
from typing import Any


def _format_source_line(source: dict[str, Any]) -> str:
    filename = source.get("filename") or "Unknown"
    section = source.get("section") or "Unknown Section"
    page = source.get("page_number") or "?"
    return f"(Source: {filename} | Section: {section} | Page: {page})"


def _canonical_citation_line(raw_citation: str, sources: list[dict[str, Any]] | None) -> str:
    inner_match = re.search(r"\(Source:\s*(.*?)\)\s*$", raw_citation.strip(), flags=re.IGNORECASE)
    if not inner_match:
        return _format_source_line((sources or [{}])[0])

    inner = inner_match.group(1).strip()
    filename = "Unknown"
    section = "Unknown Section"
    page = "?"

    if "|" in inner:
        parts = [p.strip() for p in inner.split("|")]
        if parts:
            filename = parts[0] or filename
        for part in parts[1:]:
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            k = key.strip().lower()
            v = value.strip()
            if k == "section" and v:
                section = v
            elif k == "page" and v:
                page = v
    else:
        pieces = [p.strip() for p in inner.split(",") if p.strip()]
        if pieces:
            filename = pieces[0]
        for piece in pieces[1:]:
            page_match = re.search(r"page\s*([0-9?]+)", piece, flags=re.IGNORECASE)
            if page_match:
                page = page_match.group(1)
                break

    if (section == "Unknown Section" or page == "?") and sources:
        src = sources[0]
        section = section if section != "Unknown Section" else (src.get("section") or "Unknown Section")
        page = page if page != "?" else (src.get("page_number") or "?")

    return f"(Source: {filename} | Section: {section} | Page: {page})"


def _normalize_lists(text: str) -> str:
    # Put each numbered item on its own line if the model merges them.
    text = re.sub(r"([.!?])\s+(\d+\.\s+)", r"\1\n\n\2", text)
    text = re.sub(r"\s+(\d+\.\s+)\*\*", r"\n\1**", text)
    text = re.sub(r"(\d+\.)\s+—\s+", r"\1 ", text)
    return text


def normalize_markdown_answer(text: str, sources: list[dict[str, Any]] | None = None) -> str:
    """
    Enforce a stable assistant markdown schema:
    1) Heading
    2) Body/list
    3) Single citation line
    """
    cleaned = (text or "")
    cleaned = cleaned.replace("\r\n", "\n").replace("\u00a0", " ")
    cleaned = cleaned.replace("<END_ANSWER>", "")
    cleaned = _normalize_lists(cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    citation_matches = re.findall(r"\(Source:[^)]+\)", cleaned)
    cleaned = re.sub(r"\n?\(Source:[^)]+\)\s*", "\n", cleaned).strip()

    citation_line = ""
    if citation_matches:
        citation_line = _canonical_citation_line(citation_matches[0], sources)
    elif sources:
        citation_line = _format_source_line(sources[0])

    if cleaned and not cleaned.lstrip().startswith("#"):
        cleaned = f"### Answer\n\n{cleaned}"

    if citation_line:
        cleaned = f"{cleaned}\n\n{citation_line}".strip()

    return cleaned
