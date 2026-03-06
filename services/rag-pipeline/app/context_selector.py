import re
from typing import Any

from app.answer_planner import AnswerPlan
from app.config import settings
from app.evidence_extractor import dedupe_chunks


def select_context_chunks(
    question_type: str,
    query: str,
    retrieved_chunks: list[dict[str, Any]],
    reranked_chunks: list[dict[str, Any]],
    answer_plan: AnswerPlan | None = None,
) -> list[dict[str, Any]]:
    candidates = dedupe_chunks(
        answer_plan.citation_chunks if answer_plan else [],
        reranked_chunks,
        retrieved_chunks,
    )

    max_chunks = settings.prompt_max_chunks
    if question_type == "list":
        max_chunks = max(settings.prompt_max_chunks, settings.list_context_max_chunks)
    elif question_type == "calc":
        max_chunks = max(settings.prompt_max_chunks, settings.calc_context_max_chunks)

    selected: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    seen_sections: set[str] = set()
    seen_pages: set[str] = set()

    def add_chunk(chunk: dict[str, Any], require_unique_coverage: bool = False) -> bool:
        key = chunk.get("point_id") or f"{chunk.get('document_id', '')}:{chunk.get('chunk_index', '')}"
        if key in seen_keys:
            return False

        coverage_key = f"{chunk.get('section', '')}:{chunk.get('page_start', chunk.get('page_number', 1))}"
        if require_unique_coverage and coverage_key in seen_pages:
            return False

        selected.append(chunk)
        seen_keys.add(key)
        seen_sections.add(chunk.get("section", "") or "")
        seen_pages.add(coverage_key)
        return True

    if answer_plan and answer_plan.citation_chunks:
        for chunk in answer_plan.citation_chunks:
            add_chunk(chunk)

    if question_type == "calc":
        numeric_chunk = next((chunk for chunk in candidates if _contains_currency(chunk)), None)
        if numeric_chunk:
            add_chunk(numeric_chunk)

        supporting_chunk = next(
            (
                chunk for chunk in candidates
                if _contains_keyword(chunk, ("installment", "monthly", "current bill", "dpa"))
            ),
            None,
        )
        if supporting_chunk:
            add_chunk(supporting_chunk, require_unique_coverage=True)

    elif question_type == "list":
        table_chunk = next((chunk for chunk in candidates if _is_table_chunk(chunk)), None)
        if table_chunk:
            add_chunk(table_chunk)

        for chunk in candidates:
            if len(selected) >= max_chunks:
                break
            add_chunk(chunk, require_unique_coverage=True)

    if len(selected) < max_chunks:
        for chunk in reranked_chunks:
            if len(selected) >= max_chunks:
                break
            add_chunk(chunk)

    if not selected:
        selected = reranked_chunks[:max_chunks] or retrieved_chunks[:max_chunks]

    return selected[:max_chunks]


def _contains_currency(chunk: dict[str, Any]) -> bool:
    if chunk.get("contains_currency"):
        return True
    return bool(re.search(r"[$]\s*[0-9]", chunk.get("text", "")))


def _contains_keyword(chunk: dict[str, Any], keywords: tuple[str, ...]) -> bool:
    text = (chunk.get("text", "") or "").lower()
    return any(keyword in text for keyword in keywords)


def _is_table_chunk(chunk: dict[str, Any]) -> bool:
    if chunk.get("content_type") == "table":
        return True
    text = chunk.get("text", "") or ""
    return "|" in text and text.count("|") >= 6
