import re
from typing import Any

from app.services.response_formatter import normalize_markdown_answer


_QUESTION_OPENERS = (
    "what is ",
    "what are ",
    "can ",
    "could ",
    "should ",
    "would ",
    "is ",
    "are ",
    "do ",
    "does ",
    "did ",
    "am ",
    "will ",
    "how ",
    "why ",
    "when ",
    "where ",
)


def build_assistant_message_metadata(
    question: str,
    answer_text: str,
    sources: list[dict[str, Any]] | None = None,
    upstream_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cleaned_text = normalize_markdown_answer(answer_text, sources)
    meta = dict(upstream_meta or {})
    response_payload = build_response_payload(
        question=question,
        answer_text=cleaned_text,
        sources=sources or [],
        upstream_meta=meta,
    )
    effective_reasoning_mode = (
        meta.get("effective_reasoning_mode")
        or meta.get("reasoning_mode")
        or "fast"
    )
    requested_reasoning_mode = (
        meta.get("requested_reasoning_mode")
        or effective_reasoning_mode
    )
    metadata: dict[str, Any] = {
        "sources": sources or [],
        "reasoningMode": effective_reasoning_mode,
        "requestedReasoningMode": requested_reasoning_mode,
        "effectiveReasoningMode": effective_reasoning_mode,
        "questionType": response_payload.get("questionType", "fact") if response_payload else meta.get("question_type", "fact"),
        "answerPath": meta.get("answer_path", "llm"),
        "deterministicConfidence": meta.get("deterministic_confidence", 0.0),
        "deepFallbackApplied": bool(meta.get("deep_fallback_applied", False)),
    }
    if response_payload:
        metadata["responsePayload"] = response_payload
        metadata["questionType"] = response_payload.get("questionType", metadata["questionType"])
    if meta.get("deep_fallback_reason"):
        metadata["deepFallbackReason"] = meta["deep_fallback_reason"]
    if meta.get("turn_context"):
        turn_context = meta["turn_context"]
        metadata["turnContext"] = {
            "activeSubject": turn_context.get("active_subject"),
            "latestTopicReference": turn_context.get("latest_topic_reference"),
            "recentSummary": turn_context.get("recent_summary"),
            "questionType": turn_context.get("question_type"),
            "unresolvedReferences": turn_context.get("unresolved_references", []),
        }
    if meta.get("context_resolution"):
        context_resolution = meta["context_resolution"]
        metadata["contextResolution"] = {
            "resolutionMode": context_resolution.get("resolution_mode"),
            "standaloneQuery": context_resolution.get("standalone_query"),
            "confidence": context_resolution.get("confidence", 0.0),
            "activeSubject": context_resolution.get("active_subject"),
            "latestTopicReference": context_resolution.get("latest_topic_reference"),
            "recentAnswerSummary": context_resolution.get("recent_answer_summary"),
            "unresolvedReferences": context_resolution.get("unresolved_references", []),
            "clarificationQuestion": context_resolution.get("clarification_question"),
            "source": context_resolution.get("source"),
        }
    for upstream_key, metadata_key in (
        ("visible_token_count", "visibleTokenCount"),
        ("reasoning_token_count", "reasoningTokenCount"),
        ("first_visible_token_latency_ms", "firstVisibleTokenLatencyMs"),
        ("generation_latency_ms", "generationLatencyMs"),
    ):
        if upstream_key in meta:
            metadata[metadata_key] = meta[upstream_key]

    return metadata


def build_response_payload(
    question: str,
    answer_text: str,
    sources: list[dict[str, Any]],
    upstream_meta: dict[str, Any],
) -> dict[str, Any] | None:
    question_type = upstream_meta.get("question_type", "fact")
    reasoning_mode = (
        upstream_meta.get("effective_reasoning_mode")
        or upstream_meta.get("reasoning_mode")
        or "fast"
    )
    title, body = _extract_title(answer_text)
    body_lines = [line.rstrip() for line in body.splitlines()]

    ordered_items, bullet_items, paragraphs = _split_body(body_lines)
    summary = _extract_summary(paragraphs, bullet_items)
    comparison_rows = _extract_comparison_rows(bullet_items)
    residual_paragraphs = _trim_summary_paragraphs(paragraphs, summary)

    if not title:
        title = _suggest_title(question, question_type, summary)

    blocks: list[dict[str, Any]] = []
    if title:
        blocks.append({"type": "title", "content": title})
    if summary:
        blocks.append({"type": "summary", "content": summary})

    if comparison_rows and question_type == "compare":
        blocks.append({"type": "comparison", "rows": comparison_rows})

    list_items = ordered_items or (
        [] if comparison_rows and question_type == "compare" else bullet_items
    )
    if list_items:
        blocks.append(
            {
                "type": "list",
                "title": _list_title_for(question_type, bool(ordered_items)),
                "items": list_items,
                "ordered": bool(ordered_items),
            }
        )
    elif residual_paragraphs:
        blocks.append(
            {
                "type": "list",
                "title": _list_title_for(question_type, False),
                "items": residual_paragraphs,
                "ordered": False,
            }
        )

    note = _build_note(cleaned_text=answer_text, question_type=question_type)
    if note:
        blocks.append(note)

    payload = {
        "version": 1,
        "questionType": question_type,
        "reasoningMode": reasoning_mode,
        "blocks": blocks,
        "sources": sources,
    }
    if not any(block.get("type") != "title" for block in blocks):
        return None
    return payload


def _extract_title(answer_text: str) -> tuple[str | None, str]:
    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*(?:\n+|$)", answer_text)
    if not match:
        return None, answer_text.strip()
    title = match.group(1).strip()
    body = answer_text[match.end():].strip()
    return title, body


def _split_body(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    ordered_items: list[str] = []
    bullet_items: list[str] = []
    paragraphs: list[str] = []
    current_paragraph: list[str] = []

    def flush_paragraph() -> None:
        if current_paragraph:
            paragraphs.append(" ".join(current_paragraph).strip())
            current_paragraph.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            continue

        ordered_match = re.match(r"^\d+\.\s+(.*)$", line)
        if ordered_match:
            flush_paragraph()
            ordered_items.append(ordered_match.group(1).strip())
            continue

        bullet_match = re.match(r"^[-*]\s+(.*)$", line)
        if bullet_match:
            flush_paragraph()
            bullet_items.append(bullet_match.group(1).strip())
            continue

        current_paragraph.append(line)

    flush_paragraph()
    return ordered_items, bullet_items, paragraphs


def _extract_summary(paragraphs: list[str], bullet_items: list[str]) -> str:
    if paragraphs:
        return paragraphs[0]
    if bullet_items:
        return bullet_items[0]
    return ""


def _trim_summary_paragraphs(paragraphs: list[str], summary: str) -> list[str]:
    if not paragraphs:
        return []
    if summary and paragraphs[0] == summary:
        return paragraphs[1:]
    return paragraphs


def _extract_comparison_rows(items: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in items:
        plain = re.sub(r"^\*\*(.+?)\*\*$", r"\1", item).strip()
        match = re.match(r"^\**([^:*]{2,60})\**:\s*(.+)$", plain)
        if not match:
            return []
        rows.append({"label": match.group(1).strip(), "content": match.group(2).strip()})
    return rows if len(rows) >= 2 else []


def _list_title_for(question_type: str, ordered: bool) -> str:
    if question_type == "calc":
        return "Steps"
    if question_type in {"compare", "eligibility"}:
        return "Key Points"
    if ordered:
        return "Steps"
    return "Key Points"


def _suggest_title(question: str, question_type: str, summary: str) -> str:
    for prefix in _QUESTION_OPENERS:
        lowered = question.lower().strip()
        if lowered.startswith(prefix):
            question = question[len(prefix):]
            break

    cleaned_question = re.sub(r"\s+", " ", question).strip(" ?.!").strip()
    if cleaned_question:
        normalized = cleaned_question[:72].strip()
        return normalized[:1].upper() + normalized[1:]

    if question_type == "compare":
        return "Policy Comparison"
    if question_type == "eligibility":
        return "Eligibility Assessment"
    if question_type == "calc":
        return "Calculation Summary"
    if summary:
        return summary[:72]
    return "Answer"


def _build_note(cleaned_text: str, question_type: str) -> dict[str, str] | None:
    lowered = cleaned_text.lower()
    if "not available in the current hr knowledge base" in lowered:
        return {
            "type": "note",
            "tone": "warning",
            "content": "The current HR knowledge base does not contain a direct policy answer for this question.",
        }

    if question_type == "eligibility" and cleaned_text.startswith("No"):
        return {
            "type": "note",
            "tone": "neutral",
            "content": "Review the policy conditions carefully if your situation has any exceptions or additional context.",
        }

    return None
