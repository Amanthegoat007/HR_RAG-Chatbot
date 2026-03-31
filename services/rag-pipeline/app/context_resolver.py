from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.llm_client import generate_text

logger = logging.getLogger(__name__)

REFERENCE_MARKERS = (
    "it",
    "they",
    "them",
    "that",
    "this",
    "these",
    "those",
    "same",
    "former",
    "latter",
    "what about",
    "how about",
    "and this",
    "and that",
)

FOLLOW_UP_HINTS = (
    "what about",
    "how about",
    "same",
    "same for",
    "what if",
    "and ",
    "and if",
    "tell me more",
    "more on",
    "can you expand",
)

DEFAULT_DOMAIN_EXAMPLES = """Example 1:
Conversation:
- User: Explain the probation policy.
- Assistant: Probation lasts 6 months and can be extended once with approval.
Latest query: Can it be extended?
Output:
{"resolution_mode":"resolved_follow_up","standalone_query":"Can the probation period be extended under the probation policy?","confidence":0.94,"active_subject":"Probation policy","latest_topic_reference":"Probation policy","recent_answer_summary":"Probation lasts 6 months and can be extended once with approval.","unresolved_references":["it"],"clarification_question":null}

Example 2:
Conversation:
- User: Tell me about leave.
- Assistant: I summarized annual leave only.
Latest query: What about that?
Output:
{"resolution_mode":"clarify","standalone_query":"","confidence":0.22,"active_subject":"Annual leave","latest_topic_reference":null,"recent_answer_summary":"I summarized annual leave only.","unresolved_references":["that"],"clarification_question":"Do you want annual leave, sick leave, or another leave policy?"}

Example 3:
Conversation:
- User: PTO policy?
Latest query: PTO policy?
Output:
{"resolution_mode":"direct","standalone_query":"Paid Time Off policy","confidence":0.97,"active_subject":"Paid Time Off policy","latest_topic_reference":null,"recent_answer_summary":null,"unresolved_references":[],"clarification_question":null}"""

HR_ABBREVIATIONS = {
    "wfh": "Work From Home",
    "pto": "Paid Time Off",
    "ot": "Overtime",
    "kpi": "Key Performance Indicator",
    "ctc": "Cost to Company",
    "lwp": "Leave Without Pay",
    "hr": "Human Resources",
    "sop": "Standard Operating Procedure",
    "nda": "Non-Disclosure Agreement",
    "hmo": "Health Maintenance Organization",
    "loa": "Leave of Absence",
    "np": "Notice Period",
}


class _ResolutionPayload(BaseModel):
    resolution_mode: Literal["direct", "resolved_follow_up", "clarify"]
    standalone_query: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    active_subject: str | None = None
    latest_topic_reference: str | None = None
    recent_answer_summary: str | None = None
    unresolved_references: list[str] = Field(default_factory=list)
    clarification_question: str | None = None


@dataclass
class ConversationContextResolution:
    resolution_mode: Literal["direct", "resolved_follow_up", "clarify"]
    standalone_query: str
    confidence: float
    active_subject: str | None = None
    latest_topic_reference: str | None = None
    recent_answer_summary: str | None = None
    unresolved_references: list[str] = field(default_factory=list)
    clarification_question: str | None = None
    source: Literal["llm", "cache", "fallback"] = "llm"
    context_window: str = ""

    @property
    def clarification_needed(self) -> bool:
        return self.resolution_mode == "clarify"

    @property
    def clarification_message(self) -> str | None:
        return self.clarification_question


def serialize_context_resolution(
    resolution: ConversationContextResolution,
) -> dict[str, Any]:
    return {
        "resolution_mode": resolution.resolution_mode,
        "standalone_query": resolution.standalone_query,
        "confidence": round(resolution.confidence, 4),
        "active_subject": resolution.active_subject,
        "latest_topic_reference": resolution.latest_topic_reference,
        "recent_answer_summary": resolution.recent_answer_summary,
        "unresolved_references": resolution.unresolved_references,
        "clarification_question": resolution.clarification_question,
        "source": resolution.source,
    }


def _normalize_query(query: str) -> str:
    return " ".join((query or "").split()).strip()


def _normalize_optional_text(value: str | None, *, limit: int = 240) -> str | None:
    cleaned = _normalize_query(value or "")
    if not cleaned:
        return None
    return cleaned[:limit]


def _expand_abbreviations(query: str) -> str:
    expanded_query = _normalize_query(query)
    for abbr, full_form in HR_ABBREVIATIONS.items():
        pattern = re.compile(rf"\b{abbr}\b", re.IGNORECASE)
        expanded_query = pattern.sub(full_form, expanded_query)
    return expanded_query


def _collect_unresolved_references(query: str) -> list[str]:
    lowered = (query or "").lower()
    return [marker for marker in REFERENCE_MARKERS if marker in lowered]


def _extract_title_from_payload(response_payload: dict[str, Any]) -> str | None:
    for block in response_payload.get("blocks", []):
        if block.get("type") == "title":
            return _normalize_optional_text(block.get("content"))
    return None


def _extract_summary_from_payload(response_payload: dict[str, Any]) -> str | None:
    for block in response_payload.get("blocks", []):
        if block.get("type") == "summary":
            return _normalize_optional_text(block.get("content"))
    return None


def _extract_title(answer_text: str) -> str | None:
    match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*(?:\n+|$)", answer_text or "")
    return _normalize_optional_text(match.group(1)) if match else None


def _extract_summary(answer_text: str) -> str | None:
    lines = [line.strip() for line in (answer_text or "").splitlines() if line.strip()]
    for line in lines:
        if line.startswith("#"):
            continue
        normalized = re.sub(r"^[-*]\s+", "", line)
        return _normalize_optional_text(normalized)
    return None


def _extract_turn_snapshot(message: dict[str, Any]) -> dict[str, str | None]:
    metadata = message.get("metadata") or {}
    turn_context = metadata.get("turnContext") or metadata.get("turn_context") or {}
    context_resolution = metadata.get("contextResolution") or metadata.get("context_resolution") or {}
    response_payload = metadata.get("responsePayload") or {}

    title = _extract_title_from_payload(response_payload) or _extract_title(message.get("content", ""))
    summary = (
        turn_context.get("recent_summary")
        or turn_context.get("recentSummary")
        or context_resolution.get("recent_answer_summary")
        or context_resolution.get("recentAnswerSummary")
        or _extract_summary_from_payload(response_payload)
        or _extract_summary(message.get("content", ""))
    )
    active_subject = (
        turn_context.get("active_subject")
        or turn_context.get("activeSubject")
        or context_resolution.get("active_subject")
        or context_resolution.get("activeSubject")
        or title
    )
    topic_reference = (
        turn_context.get("latest_topic_reference")
        or turn_context.get("latestTopicReference")
        or context_resolution.get("latest_topic_reference")
        or context_resolution.get("latestTopicReference")
    )

    source_names: list[str] = []
    for source in metadata.get("sources") or []:
        filename = _normalize_optional_text(source.get("filename"), limit=120)
        if filename and filename not in source_names:
            source_names.append(filename)

    return {
        "role": message.get("role"),
        "active_subject": _normalize_optional_text(active_subject),
        "topic_reference": _normalize_optional_text(topic_reference),
        "summary": _normalize_optional_text(summary),
        "sources": ", ".join(source_names[:3]) if source_names else None,
    }


def _build_prompt_history(recent_messages: list[dict[str, Any]]) -> str:
    if not recent_messages:
        return "No prior conversation."

    lines: list[str] = []
    turn_snapshots = [_extract_turn_snapshot(message) for message in recent_messages]
    for index, (message, snapshot) in enumerate(zip(recent_messages, turn_snapshots), start=1):
        role = "User" if message.get("role") == "user" else "Assistant"
        content = _normalize_optional_text(message.get("content"), limit=320) or ""
        if role == "Assistant":
            content = snapshot.get("summary") or snapshot.get("active_subject") or content
        lines.append(f"[{index}] {role}: {content}")
        if snapshot.get("active_subject"):
            lines.append(f"    active_subject: {snapshot['active_subject']}")
        if snapshot.get("topic_reference"):
            lines.append(f"    latest_topic_reference: {snapshot['topic_reference']}")
        if snapshot.get("sources"):
            lines.append(f"    recent_sources: {snapshot['sources']}")
    return "\n".join(lines)


def _collect_recent_documents(recent_messages: list[dict[str, Any]]) -> list[str]:
    documents: list[str] = []
    for message in reversed(recent_messages):
        snapshot = _extract_turn_snapshot(message)
        for candidate in (
            snapshot.get("topic_reference"),
            snapshot.get("sources"),
        ):
            if not candidate:
                continue
            for token in [piece.strip() for piece in candidate.split(",")]:
                if token and token not in documents:
                    documents.append(token)
                if len(documents) >= 5:
                    return documents
    return documents


def _latest_active_subject(recent_messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(recent_messages):
        snapshot = _extract_turn_snapshot(message)
        if snapshot.get("active_subject"):
            return snapshot["active_subject"]
    return _derive_subject_from_recent_user_turns(recent_messages)


def _latest_topic_reference(recent_messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(recent_messages):
        snapshot = _extract_turn_snapshot(message)
        if snapshot.get("topic_reference"):
            return snapshot["topic_reference"]
    return None


def _latest_recent_summary(recent_messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(recent_messages):
        snapshot = _extract_turn_snapshot(message)
        if snapshot.get("summary"):
            return snapshot["summary"]
    return None


def _build_context_window(
    resolution: ConversationContextResolution,
    recent_documents: list[str] | None = None,
    *,
    session_scope_active: bool = False,
) -> str:
    lines: list[str] = []
    if resolution.active_subject:
        lines.append(f"ACTIVE SUBJECT: {resolution.active_subject}")
    if resolution.latest_topic_reference:
        lines.append(f"LATEST POLICY/TOPIC REFERENCE: {resolution.latest_topic_reference}")
    if resolution.recent_answer_summary:
        lines.append(f"RECENT ANSWER SUMMARY: {resolution.recent_answer_summary}")
    if recent_documents:
        lines.append("RECENT DOCUMENTS:")
        lines.extend(f"- {document}" for document in recent_documents[:5])
    if session_scope_active:
        lines.append("SESSION-SCOPED DOCUMENTS: Active for this conversation.")
    if resolution.unresolved_references:
        lines.append("UNRESOLVED REFERENCES:")
        lines.extend(f"- {reference}" for reference in resolution.unresolved_references[:5])
    return "\n".join(lines)


def _build_resolver_messages(
    *,
    raw_query: str,
    expanded_query: str,
    recent_messages: list[dict[str, Any]],
    recent_documents: list[str],
    session_scope_active: bool,
    strict_retry: bool = False,
) -> list[dict[str, str]]:
    examples = settings.context_resolution_domain_examples or DEFAULT_DOMAIN_EXAMPLES
    strict_suffix = (
        "\nYour previous response was invalid. Return one valid JSON object only. No markdown fences."
        if strict_retry
        else ""
    )
    system_prompt = f"""You are ConversationContextResolver, a structured pre-retrieval resolver for grounded assistants.

Resolve the latest user query into one of:
- direct
- resolved_follow_up
- clarify

Use this domain as the default context:
- Name: {settings.context_resolution_domain_name}
- Description: {settings.context_resolution_domain_description}

Rules:
1. Output one JSON object only.
2. Do not answer the user's question.
3. Use "direct" when the query already stands alone.
4. Use "resolved_follow_up" only when prior turns clearly identify the subject.
5. Use "clarify" when ambiguity remains or the subject cannot be bound safely.
6. Never invent policy names, document titles, or facts not supported by the conversation.
7. Make standalone_query concise, retrieval-ready, and self-contained.
8. Confidence must be between 0 and 1.

Required JSON shape:
{{
  "resolution_mode": "direct | resolved_follow_up | clarify",
  "standalone_query": "string",
  "confidence": 0.0,
  "active_subject": "string | null",
  "latest_topic_reference": "string | null",
  "recent_answer_summary": "string | null",
  "unresolved_references": ["string"],
  "clarification_question": "string | null"
}}

Examples:
{examples}{strict_suffix}"""

    recent_documents_text = (
        "\n".join(f"- {document}" for document in recent_documents)
        if recent_documents
        else "None"
    )
    user_prompt = f"""Latest user query: {raw_query}
Expanded query: {expanded_query}
Session-scoped documents active: {"yes" if session_scope_active else "no"}

Recent conversation:
{_build_prompt_history(recent_messages)}

Recent documents:
{recent_documents_text}

Return the JSON object now."""
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _extract_json_object(raw_text: str) -> str | None:
    text = (raw_text or "").strip()
    if not text:
        return None
    if text.startswith("{") and text.endswith("}"):
        return text

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _coerce_resolution_payload(
    payload: _ResolutionPayload,
    *,
    expanded_query: str,
    recent_messages: list[dict[str, Any]],
    source: Literal["llm", "cache"],
) -> ConversationContextResolution:
    unresolved_references = [
        _normalize_query(reference)
        for reference in payload.unresolved_references
        if _normalize_query(reference)
    ]
    active_subject = _normalize_optional_text(payload.active_subject) or _latest_active_subject(recent_messages)
    latest_topic_reference = _normalize_optional_text(payload.latest_topic_reference) or _latest_topic_reference(recent_messages)
    recent_answer_summary = _normalize_optional_text(payload.recent_answer_summary) or _latest_recent_summary(recent_messages)
    clarification_question = _normalize_optional_text(payload.clarification_question)
    standalone_query = _normalize_query(payload.standalone_query or expanded_query)
    resolution_mode = payload.resolution_mode
    confidence = max(0.0, min(1.0, float(payload.confidence)))

    if resolution_mode == "clarify":
        standalone_query = ""
        if not clarification_question:
            clarification_question = (
                "I can help with that, but I need a little more context. "
                "Please mention the policy, benefit, document, or topic you want me to continue with."
            )
    elif not standalone_query:
        resolution_mode = "direct"
        standalone_query = expanded_query

    if (
        resolution_mode == "resolved_follow_up"
        and confidence < settings.context_resolution_confidence_threshold
        and (unresolved_references or not active_subject)
    ):
        resolution_mode = "clarify"
        standalone_query = ""
        clarification_question = (
            clarification_question
            or "I can help with that, but I need a little more context. Which policy, benefit, document, or topic should I continue with?"
        )

    resolution = ConversationContextResolution(
        resolution_mode=resolution_mode,
        standalone_query=standalone_query,
        confidence=confidence,
        active_subject=active_subject,
        latest_topic_reference=latest_topic_reference,
        recent_answer_summary=recent_answer_summary,
        unresolved_references=unresolved_references,
        clarification_question=clarification_question,
        source=source,
    )
    return resolution


def _parse_resolution_response(
    raw_text: str,
    *,
    expanded_query: str,
    recent_messages: list[dict[str, Any]],
    source: Literal["llm", "cache"],
) -> ConversationContextResolution | None:
    json_payload = _extract_json_object(raw_text)
    if not json_payload:
        return None

    try:
        parsed = _ResolutionPayload.model_validate(json.loads(json_payload))
    except (json.JSONDecodeError, ValidationError):
        return None

    return _coerce_resolution_payload(
        parsed,
        expanded_query=expanded_query,
        recent_messages=recent_messages,
        source=source,
    )


def _looks_context_dependent(query: str, unresolved_references: list[str]) -> bool:
    lowered = (query or "").lower().strip()
    return bool(unresolved_references) or any(lowered.startswith(prefix) for prefix in FOLLOW_UP_HINTS)


def _build_fallback_standalone_query(query: str, active_subject: str | None) -> str:
    normalized_query = _normalize_query(query)
    if not active_subject:
        return normalized_query
    if active_subject.lower() in normalized_query.lower():
        return normalized_query
    return _normalize_query(f"{active_subject}: {normalized_query}")


def _fallback_resolution(
    query: str,
    recent_messages: list[dict[str, Any]],
    *,
    session_scope_active: bool = False,
) -> ConversationContextResolution:
    expanded_query = _expand_abbreviations(query)
    unresolved_references = _collect_unresolved_references(expanded_query)
    active_subject = _latest_active_subject(recent_messages)
    latest_topic_reference = _latest_topic_reference(recent_messages)
    recent_answer_summary = _latest_recent_summary(recent_messages)
    needs_clarification = _looks_context_dependent(expanded_query, unresolved_references) and not active_subject

    if needs_clarification:
        resolution = ConversationContextResolution(
            resolution_mode="clarify",
            standalone_query="",
            confidence=0.0,
            active_subject=active_subject,
            latest_topic_reference=latest_topic_reference,
            recent_answer_summary=recent_answer_summary,
            unresolved_references=unresolved_references,
            clarification_question=(
                "I can help with that, but I need a little more context. "
                "Please mention the policy, benefit, document, or topic you want me to continue with."
            ),
            source="fallback",
        )
    else:
        resolution_mode: Literal["direct", "resolved_follow_up", "clarify"] = (
            "resolved_follow_up" if _looks_context_dependent(expanded_query, unresolved_references) else "direct"
        )
        resolution = ConversationContextResolution(
            resolution_mode=resolution_mode,
            standalone_query=_build_fallback_standalone_query(expanded_query, active_subject),
            confidence=0.35 if resolution_mode == "resolved_follow_up" else 0.55,
            active_subject=active_subject,
            latest_topic_reference=latest_topic_reference,
            recent_answer_summary=recent_answer_summary,
            unresolved_references=unresolved_references,
            clarification_question=None,
            source="fallback",
        )

    resolution.context_window = _build_context_window(
        resolution,
        _collect_recent_documents(recent_messages),
        session_scope_active=session_scope_active,
    )
    return resolution


async def resolve_conversation_context(
    query: str,
    conversation_history: list[dict[str, Any]],
    *,
    http_client: httpx.AsyncClient,
    cache: Any | None = None,
    conversation_id: str | None = None,
    session_scope_active: bool = False,
) -> ConversationContextResolution:
    normalized_query = _normalize_query(query)
    expanded_query = _expand_abbreviations(normalized_query)
    recent_messages = conversation_history[-(settings.context_resolution_history_turns * 2) :]
    recent_documents = _collect_recent_documents(recent_messages)

    if cache and conversation_id:
        cached_entry = await cache.get(
            conversation_id=conversation_id,
            query=expanded_query,
            recent_messages=recent_messages,
        )
        if cached_entry:
            cached_resolution = _parse_resolution_response(
                json.dumps(cached_entry),
                expanded_query=expanded_query,
                recent_messages=recent_messages,
                source="cache",
            )
            if cached_resolution:
                cached_resolution.context_window = _build_context_window(
                    cached_resolution,
                    recent_documents,
                    session_scope_active=session_scope_active,
                )
                return cached_resolution

    llm_messages = _build_resolver_messages(
        raw_query=normalized_query,
        expanded_query=expanded_query,
        recent_messages=recent_messages,
        recent_documents=recent_documents,
        session_scope_active=session_scope_active,
    )

    raw_response = ""
    parsed_resolution: ConversationContextResolution | None = None
    try:
        raw_response = await generate_text(
            client=http_client,
            messages=llm_messages,
            max_tokens=settings.context_resolution_max_tokens,
            temperature=0.0,
            enable_thinking=False,
        )
        parsed_resolution = _parse_resolution_response(
            raw_response,
            expanded_query=expanded_query,
            recent_messages=recent_messages,
            source="llm",
        )

        if not parsed_resolution:
            retry_messages = _build_resolver_messages(
                raw_query=normalized_query,
                expanded_query=expanded_query,
                recent_messages=recent_messages,
                recent_documents=recent_documents,
                session_scope_active=session_scope_active,
                strict_retry=True,
            )
            raw_response = await generate_text(
                client=http_client,
                messages=retry_messages,
                max_tokens=settings.context_resolution_max_tokens,
                temperature=0.0,
                enable_thinking=False,
            )
            parsed_resolution = _parse_resolution_response(
                raw_response,
                expanded_query=expanded_query,
                recent_messages=recent_messages,
                source="llm",
            )
    except Exception as exc:
        logger.warning("LLM-first context resolution failed", extra={"error": str(exc)})

    if not parsed_resolution:
        fallback = _fallback_resolution(
            expanded_query,
            recent_messages,
            session_scope_active=session_scope_active,
        )
        logger.warning(
            "Using fallback conversation context resolution",
            extra={"query": normalized_query, "source": fallback.source},
        )
        return fallback

    parsed_resolution.context_window = _build_context_window(
        parsed_resolution,
        recent_documents,
        session_scope_active=session_scope_active,
    )

    if cache and conversation_id:
        await cache.set(
            conversation_id=conversation_id,
            query=expanded_query,
            recent_messages=recent_messages,
            resolution=serialize_context_resolution(parsed_resolution),
        )

    return parsed_resolution


def build_turn_context(
    *,
    question: str,
    answer_text: str,
    question_type: str,
    source_chunks: list[dict[str, Any]] | None = None,
    context_resolution: ConversationContextResolution | None = None,
) -> dict[str, Any]:
    title = _extract_title(answer_text)
    summary = _extract_summary(answer_text)
    active_subject = title or (context_resolution.active_subject if context_resolution else None) or _derive_subject_from_text(question)
    topic_reference = (
        context_resolution.latest_topic_reference
        if context_resolution and context_resolution.latest_topic_reference
        else _derive_topic_reference(source_chunks or [])
    )
    return {
        "active_subject": active_subject,
        "latest_topic_reference": topic_reference,
        "recent_summary": summary,
        "question_type": question_type,
        "unresolved_references": context_resolution.unresolved_references if context_resolution else [],
    }


def _derive_subject_from_recent_user_turns(
    recent_messages: list[dict[str, Any]],
) -> str | None:
    for message in reversed(recent_messages):
        if message.get("role") != "user":
            continue
        subject = _derive_subject_from_text(message.get("content", ""))
        if subject:
            return subject
    return None


def _derive_subject_from_text(text: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip(" ?.!").strip()
    if not cleaned:
        return None
    lowered = cleaned.lower()
    for prefix in (
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
        "how ",
        "why ",
        "when ",
        "where ",
    ):
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    return _normalize_optional_text(cleaned, limit=80)


def _derive_topic_reference(source_chunks: list[dict[str, Any]]) -> str | None:
    if not source_chunks:
        return None
    first = source_chunks[0]
    filename = _normalize_optional_text(first.get("filename"), limit=120)
    section = _normalize_optional_text(first.get("section"), limit=120)
    if filename and section:
        return f"{filename} — {section}"
    return filename or section
