from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import settings
from app.llm_client import generate_text

logger = logging.getLogger(__name__)

InteractionType = Literal[
    "knowledge_request",
    "capability",
    "greeting",
    "acknowledgement",
    "closing",
    "document_request",
    "clarify",
]

AssistantResponseStyle = Literal[
    "greeting_warm",
    "capability_overview",
    "acknowledgement_positive",
    "closing_helpful",
]

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

DOCUMENT_REFERENCE_MARKERS = (
    "document",
    "file",
    "upload",
    "uploaded",
    "attachment",
    "attached",
    "screenshot",
    "pdf",
    "image",
    "bill",
    "invoice",
)

DOCUMENT_UNDERSTANDING_MARKERS = (
    "explain",
    "summarize",
    "summary",
    "understand",
    "analyze",
    "analyse",
    "what is",
    "what does",
    "what do",
    "tell me about",
)

PROCESSING_STATUSES = {"pending", "normalizing", "processing", "embedding"}
STATUS_ONLY_STATUSES = PROCESSING_STATUSES | {"needs_review", "failed"}

GREETING_PHRASES = (
    "good morning",
    "good afternoon",
    "good evening",
    "good night",
    "hello there",
    "hey there",
    "what's up",
    "whats up",
    "hi",
    "hello",
    "hey",
    "yo",
    "hiya",
    "sup",
)

ACKNOWLEDGEMENT_PHRASES = (
    "thank you so much",
    "thank you",
    "thanks a lot",
    "many thanks",
    "ok thanks",
    "okay thanks",
    "that's good",
    "thats good",
    "sounds good",
    "thanks",
    "got it",
    "okay",
    "ok",
    "cool",
    "great",
    "nice",
    "hmm",
    "hmmm",
)

CLOSING_PHRASES = (
    "see you later",
    "talk later",
    "goodbye",
    "see you",
    "bye",
)

CAPABILITY_PATTERNS = (
    "who are you",
    "what can you do",
    "how can you help",
    "how do you help",
    "what do you do",
    "tell me what you can do",
    "tell me what you can overall do",
)

HR_DOMAIN_TERMS = (
    "policy",
    "policies",
    "leave",
    "pto",
    "paid time off",
    "benefit",
    "benefits",
    "payroll",
    "probation",
    "onboarding",
    "notice",
    "overtime",
    "salary",
    "insurance",
    "medical",
    "holiday",
    "ticket",
    "gratuity",
    "reimbursement",
    "allowance",
    "contract",
    "offer",
    "document",
    "file",
    "upload",
    "uploaded",
)

DEFAULT_DOMAIN_EXAMPLES = """Example 1:
Conversation:
- User: Explain the probation policy.
- Assistant: Probation lasts 6 months and can be extended once with approval.
Latest query: Can it be extended?
Output:
{"resolution_mode":"resolved_follow_up","standalone_query":"Can the probation period be extended under the probation policy?","confidence":0.94,"active_subject":"Probation policy","latest_topic_reference":"Probation policy","recent_answer_summary":"Probation lasts 6 months and can be extended once with approval.","unresolved_references":["it"],"clarification_question":null,"focus_type":"policy","focus_id":null,"focus_label":"Probation policy","action":"retrieve","interaction_type":"knowledge_request"}

Example 2:
Working set:
- Screenshot 2026-04-01.png [ready]
Latest query: Can you explain this uploaded document?
Output:
{"resolution_mode":"direct","standalone_query":"Explain and summarize the uploaded document Screenshot 2026-04-01.png, including what it is and what it is used for.","confidence":0.95,"active_subject":"Screenshot 2026-04-01.png","latest_topic_reference":null,"recent_answer_summary":null,"unresolved_references":["this"],"clarification_question":null,"focus_type":"document","focus_id":"Screenshot 2026-04-01.png","focus_label":"Screenshot 2026-04-01.png","action":"retrieve","interaction_type":"document_request"}

Example 3:
Working set:
- Offer_Letter.pdf [processing]
Latest query: Explain the uploaded file in this conversation.
Output:
{"resolution_mode":"direct","standalone_query":"","confidence":0.99,"active_subject":"Offer_Letter.pdf","latest_topic_reference":null,"recent_answer_summary":null,"unresolved_references":[],"clarification_question":null,"focus_type":"document","focus_id":"Offer_Letter.pdf","focus_label":"Offer_Letter.pdf","action":"status_only","interaction_type":"document_request"}

Example 4:
Conversation:
- User: Tell me about leave.
- Assistant: I summarized annual leave only.
Latest query: What about that?
Output:
{"resolution_mode":"clarify","standalone_query":"","confidence":0.22,"active_subject":"Annual leave","latest_topic_reference":null,"recent_answer_summary":"I summarized annual leave only.","unresolved_references":["that"],"clarification_question":"Do you want annual leave, sick leave, or another leave policy?","focus_type":"none","focus_id":null,"focus_label":null,"action":"clarify","interaction_type":"clarify"}

Example 5:
Working set:
- Offer_Letter.pdf [ready]
- Medical_Benefits.pdf [ready]
Latest query: Explain this uploaded document.
Output:
{"resolution_mode":"clarify","standalone_query":"","confidence":0.24,"active_subject":null,"latest_topic_reference":null,"recent_answer_summary":null,"unresolved_references":["this"],"clarification_question":"I found multiple uploaded documents in this conversation: Offer_Letter.pdf and Medical_Benefits.pdf. Which one should I explain?","focus_type":"none","focus_id":null,"focus_label":null,"action":"clarify","interaction_type":"clarify"}

Example 6:
Latest query: hello
Output:
{"resolution_mode":"direct","standalone_query":"hello","confidence":0.97,"active_subject":"HR copilot","latest_topic_reference":null,"recent_answer_summary":null,"unresolved_references":[],"clarification_question":null,"focus_type":"none","focus_id":null,"focus_label":null,"action":"direct_response","interaction_type":"greeting","assistant_response_style":"greeting_warm"}

Example 7:
Latest query: ok tell me what you can overall do
Output:
{"resolution_mode":"direct","standalone_query":"ok tell me what you can overall do","confidence":0.95,"active_subject":"HR copilot","latest_topic_reference":null,"recent_answer_summary":null,"unresolved_references":[],"clarification_question":null,"focus_type":"none","focus_id":null,"focus_label":null,"action":"direct_response","interaction_type":"capability","assistant_response_style":"capability_overview"}

Example 8:
Latest query: that's good
Output:
{"resolution_mode":"direct","standalone_query":"that's good","confidence":0.93,"active_subject":"HR copilot","latest_topic_reference":null,"recent_answer_summary":null,"unresolved_references":[],"clarification_question":null,"focus_type":"none","focus_id":null,"focus_label":null,"action":"direct_response","interaction_type":"acknowledgement","assistant_response_style":"acknowledgement_positive"}"""

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
    focus_type: Literal["topic", "policy", "document", "none"] = "none"
    focus_id: str | None = None
    focus_label: str | None = None
    action: Literal["direct_response", "retrieve", "clarify", "status_only", "resolve"] = "retrieve"
    interaction_type: InteractionType | None = None
    assistant_response_style: AssistantResponseStyle | None = None


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
    focus_type: Literal["topic", "policy", "document", "none"] = "none"
    focus_id: str | None = None
    focus_label: str | None = None
    action: Literal["direct_response", "retrieve", "clarify", "status_only"] = "retrieve"
    focus_source: str | None = None
    interaction_type: InteractionType = "knowledge_request"
    assistant_response_style: AssistantResponseStyle | None = None
    assistant_response: str | None = None

    @property
    def clarification_needed(self) -> bool:
        return self.action == "clarify" or self.resolution_mode == "clarify"

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
        "focus_type": resolution.focus_type,
        "focus_id": resolution.focus_id,
        "focus_label": resolution.focus_label,
        "action": resolution.action,
        "focus_source": resolution.focus_source,
        "interaction_type": resolution.interaction_type,
        "assistant_response_style": resolution.assistant_response_style,
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


def _normalize_interaction_text(value: str) -> str:
    cleaned = re.sub(r"[^\w\s]+", " ", (value or "").lower())
    return _normalize_query(cleaned)


def _is_capability_query(value: str) -> bool:
    normalized = _normalize_interaction_text(value)
    return any(
        normalized == pattern or normalized.startswith(f"{pattern} ")
        for pattern in CAPABILITY_PATTERNS
    )


def _is_greeting_like(value: str) -> bool:
    normalized = _normalize_interaction_text(value)
    return normalized in {_normalize_interaction_text(item) for item in GREETING_PHRASES}


def _is_acknowledgement_like(value: str) -> bool:
    normalized = _normalize_interaction_text(value)
    return normalized in {_normalize_interaction_text(item) for item in ACKNOWLEDGEMENT_PHRASES}


def _is_closing_like(value: str) -> bool:
    normalized = _normalize_interaction_text(value)
    return normalized in {_normalize_interaction_text(item) for item in CLOSING_PHRASES}


def _strip_leading_conversational_prefixes(query: str) -> str:
    cleaned = _normalize_query(query)
    prefixes = sorted(
        GREETING_PHRASES + ACKNOWLEDGEMENT_PHRASES + CLOSING_PHRASES,
        key=len,
        reverse=True,
    )
    changed = True
    while cleaned and changed:
        changed = False
        for phrase in prefixes:
            match = re.match(
                rf"^\s*{re.escape(phrase)}(?=$|[\s,!.:;?-])",
                cleaned,
                flags=re.IGNORECASE,
            )
            if not match:
                continue
            remainder = cleaned[match.end() :].lstrip(" ,.!?:;-")
            cleaned = _normalize_query(remainder)
            changed = True
            break
    return cleaned


def _default_interaction_type(
    *,
    focus_type: Literal["topic", "policy", "document", "none"],
    action: Literal["direct_response", "retrieve", "clarify", "status_only"],
) -> InteractionType:
    if action == "clarify":
        return "clarify"
    if focus_type == "document":
        return "document_request"
    return "knowledge_request"


def _interaction_type_from_style(
    style: AssistantResponseStyle | None,
) -> InteractionType | None:
    if style == "greeting_warm":
        return "greeting"
    if style == "capability_overview":
        return "capability"
    if style == "acknowledgement_positive":
        return "acknowledgement"
    if style == "closing_helpful":
        return "closing"
    return None


def _assistant_response_style_for_fallback(query: str) -> tuple[InteractionType, AssistantResponseStyle] | None:
    normalized = _normalize_interaction_text(query)
    if not normalized:
        return None
    if _is_capability_query(normalized):
        return ("capability", "capability_overview")
    if _is_closing_like(normalized):
        return ("closing", "closing_helpful")
    if _is_acknowledgement_like(normalized):
        return ("acknowledgement", "acknowledgement_positive")
    if _is_greeting_like(normalized):
        return ("greeting", "greeting_warm")
    return None


def _fallback_direct_resolution(query: str) -> ConversationContextResolution | None:
    direct = _assistant_response_style_for_fallback(query)
    if not direct:
        return None
    interaction_type, response_style = direct
    return ConversationContextResolution(
        resolution_mode="direct",
        standalone_query=_normalize_query(query),
        confidence=1.0,
        active_subject="HR copilot",
        source="fallback",
        focus_type="none",
        action="direct_response",
        interaction_type=interaction_type,
        assistant_response_style=response_style,
    )


def _normalize_working_set(working_set: Any | None) -> dict[str, Any]:
    if working_set is None:
        return {}
    if hasattr(working_set, "model_dump"):
        payload = working_set.model_dump()
        return payload if isinstance(payload, dict) else {}
    if isinstance(working_set, dict):
        return dict(working_set)
    return {}


def _working_set_documents(working_set: dict[str, Any] | None) -> list[dict[str, Any]]:
    documents = (working_set or {}).get("session_documents") or []
    return [document for document in documents if isinstance(document, dict)]


def _document_by_id(
    working_set: dict[str, Any] | None,
    document_id: str | None,
) -> dict[str, Any] | None:
    if not document_id:
        return None
    for document in _working_set_documents(working_set):
        if document.get("document_id") == document_id:
            return document
    return None


def _normalize_document_name(value: str | None) -> str:
    stem = Path(value or "").stem or (value or "")
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip().lower()
    return stem


def _document_label(document: dict[str, Any] | None) -> str | None:
    if not document:
        return None
    return _normalize_optional_text(document.get("display_name"), limit=160)


def _ready_documents(working_set: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [
        document
        for document in _working_set_documents(working_set)
        if document.get("status") == "ready"
    ]


def _latest_ready_document(working_set: dict[str, Any] | None) -> dict[str, Any] | None:
    explicit_id = (working_set or {}).get("latest_ready_document_id")
    explicit = _document_by_id(working_set, explicit_id)
    if explicit:
        return explicit
    ready_documents = _ready_documents(working_set)
    return ready_documents[0] if ready_documents else None


def _latest_uploaded_document(working_set: dict[str, Any] | None) -> dict[str, Any] | None:
    documents = _working_set_documents(working_set)
    return documents[0] if documents else None


def _query_mentions_document_reference(query: str) -> bool:
    lowered = (query or "").lower()
    return any(marker in lowered for marker in DOCUMENT_REFERENCE_MARKERS)


def _query_looks_like_document_understanding(query: str) -> bool:
    lowered = (query or "").lower()
    return any(marker in lowered for marker in DOCUMENT_UNDERSTANDING_MARKERS)


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
    document_focus = metadata.get("documentFocus") or {}
    focus = metadata.get("focus") or {}

    title = _extract_title_from_payload(response_payload) or _extract_title(message.get("content", ""))
    summary = (
        turn_context.get("recent_summary")
        or turn_context.get("recentSummary")
        or context_resolution.get("recent_answer_summary")
        or context_resolution.get("recentAnswerSummary")
        or _extract_summary_from_payload(response_payload)
        or _extract_summary(message.get("content", ""))
    )
    document_label = (
        document_focus.get("displayName")
        or context_resolution.get("focus_label")
        or context_resolution.get("focusLabel")
        or focus.get("label")
    )
    document_id = (
        document_focus.get("documentId")
        or context_resolution.get("focus_id")
        or context_resolution.get("focusId")
        or focus.get("id")
    )
    active_subject = (
        turn_context.get("active_subject")
        or turn_context.get("activeSubject")
        or context_resolution.get("active_subject")
        or context_resolution.get("activeSubject")
        or document_label
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
        "document_id": str(document_id) if document_id else None,
        "document_label": _normalize_optional_text(document_label, limit=160),
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
            content = (
                snapshot.get("summary")
                or snapshot.get("document_label")
                or snapshot.get("active_subject")
                or content
            )
        lines.append(f"[{index}] {role}: {content}")
        if snapshot.get("active_subject"):
            lines.append(f"    active_subject: {snapshot['active_subject']}")
        if snapshot.get("topic_reference"):
            lines.append(f"    latest_topic_reference: {snapshot['topic_reference']}")
        if snapshot.get("document_label"):
            lines.append(f"    document_focus: {snapshot['document_label']}")
        if snapshot.get("sources"):
            lines.append(f"    recent_sources: {snapshot['sources']}")
    return "\n".join(lines)


def _collect_recent_documents(
    recent_messages: list[dict[str, Any]],
    working_set: dict[str, Any] | None = None,
) -> list[str]:
    documents: list[str] = []
    for message in reversed(recent_messages):
        snapshot = _extract_turn_snapshot(message)
        for candidate in (
            snapshot.get("document_label"),
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

    for document in _working_set_documents(working_set):
        label = _document_label(document)
        if label and label not in documents:
            documents.append(label)
        if len(documents) >= 5:
            break
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


def _latest_document_focus(
    recent_messages: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    for message in reversed(recent_messages):
        snapshot = _extract_turn_snapshot(message)
        if snapshot.get("document_id"):
            return snapshot.get("document_id"), snapshot.get("document_label")
    return None, None


def _working_set_summary(working_set: dict[str, Any] | None) -> str:
    lines: list[str] = []
    documents = _working_set_documents(working_set)
    if not documents:
        lines.append("No session documents.")
        return "\n".join(lines)

    active_attachment = _document_by_id(
        working_set,
        (working_set or {}).get("active_attachment_document_id"),
    )
    last_focused = _document_by_id(
        working_set,
        (working_set or {}).get("last_focused_document_id"),
    )

    for document in documents[:6]:
        label = _document_label(document) or "Uploaded document"
        status = document.get("status") or "unknown"
        parts = [f"- {label} [{status}]"]
        if document.get("source_format"):
            parts.append(f"format={document['source_format']}")
        if document.get("page_count") is not None:
            parts.append(f"pages={document['page_count']}")
        lines.append(" ".join(parts))
    if active_attachment:
        lines.append(f"Active attachment hint: {_document_label(active_attachment)}")
    if last_focused:
        lines.append(f"Last focused document: {_document_label(last_focused)}")
    latest_ready = _latest_ready_document(working_set)
    if latest_ready:
        lines.append(f"Latest ready document: {_document_label(latest_ready)}")
    return "\n".join(lines)


def _build_context_window(
    resolution: ConversationContextResolution,
    recent_documents: list[str] | None = None,
    *,
    session_scope_active: bool = False,
    working_set: dict[str, Any] | None = None,
) -> str:
    lines: list[str] = []
    if resolution.active_subject:
        lines.append(f"ACTIVE SUBJECT: {resolution.active_subject}")
    if resolution.latest_topic_reference:
        lines.append(f"LATEST POLICY/TOPIC REFERENCE: {resolution.latest_topic_reference}")
    if resolution.recent_answer_summary:
        lines.append(f"RECENT ANSWER SUMMARY: {resolution.recent_answer_summary}")
    if resolution.focus_type != "none":
        lines.append(
            f"FOCUS: {resolution.focus_type} | {resolution.focus_label or resolution.focus_id or 'unspecified'}"
        )
    if recent_documents:
        lines.append("RECENT DOCUMENTS:")
        lines.extend(f"- {document}" for document in recent_documents[:5])
    if session_scope_active:
        lines.append("SESSION-SCOPED DOCUMENTS: Active for this conversation.")
        lines.append(_working_set_summary(working_set))
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
    working_set: dict[str, Any] | None,
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

You must also decide:
- interaction_type: knowledge_request | capability | greeting | acknowledgement | closing | document_request | clarify
- focus_type: topic | policy | document | none
- action: direct_response | retrieve | clarify | status_only

Use this domain as the default context:
- Name: {settings.context_resolution_domain_name}
- Description: {settings.context_resolution_domain_description}

Rules:
1. Output one JSON object only.
2. Do not answer the user's HR question. You are only routing the turn.
3. Use "direct_response" for greeting, acknowledgement, closing, or capability-only turns. These should skip retrieval.
4. Use "retrieve" for real HR knowledge requests, including mixed conversational turns like "hi, explain sick leave".
5. Use "resolved_follow_up" when prior turns or the working set clearly identify the subject.
6. Use "clarify" only when ambiguity remains unsafe after considering the working set.
7. When the user refers to an uploaded document and there is one clear session-document candidate, resolve it instead of asking a generic clarification.
8. When multiple ready session documents exist and the user makes a generic uploaded-document reference, clarify with the actual document names instead of guessing.
9. Use "status_only" when the relevant uploaded document exists but is still processing, needs review, or failed parsing.
10. Never invent policy names, document titles, or facts not supported by the conversation or working set.
11. Make standalone_query concise, retrieval-ready, and self-contained when action is "retrieve".
12. For direct_response turns, choose assistant_response_style from: greeting_warm | capability_overview | acknowledgement_positive | closing_helpful.
13. Confidence must be between 0 and 1 and should reflect trust in the routing decision, not truth of the final answer.

Required JSON shape:
{{
  "resolution_mode": "direct | resolved_follow_up | clarify",
  "standalone_query": "string",
  "confidence": 0.0,
  "active_subject": "string | null",
  "latest_topic_reference": "string | null",
  "recent_answer_summary": "string | null",
  "unresolved_references": ["string"],
  "clarification_question": "string | null",
  "focus_type": "topic | policy | document | none",
  "focus_id": "string | null",
  "focus_label": "string | null",
  "action": "direct_response | retrieve | clarify | status_only",
  "interaction_type": "knowledge_request | capability | greeting | acknowledgement | closing | document_request | clarify",
  "assistant_response_style": "greeting_warm | capability_overview | acknowledgement_positive | closing_helpful | null"
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

Conversation working set:
{_working_set_summary(working_set)}

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


def _default_focus_type(
    active_subject: str | None,
    latest_topic_reference: str | None,
) -> Literal["topic", "policy", "document", "none"]:
    reference = f"{active_subject or ''} {latest_topic_reference or ''}".lower()
    if "policy" in reference:
        return "policy"
    if active_subject or latest_topic_reference:
        return "topic"
    return "none"


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
    action = payload.action
    focus_type = payload.focus_type
    focus_id = _normalize_optional_text(payload.focus_id, limit=160)
    focus_label = _normalize_optional_text(payload.focus_label, limit=160)
    interaction_type = payload.interaction_type
    assistant_response_style = payload.assistant_response_style
    if not interaction_type:
        interaction_type = _interaction_type_from_style(assistant_response_style)

    if action == "resolve":
        action = "retrieve"
    if action == "direct_response" and (not interaction_type or not assistant_response_style):
        fallback_direct = _assistant_response_style_for_fallback(expanded_query)
        if fallback_direct:
            fallback_interaction, fallback_style = fallback_direct
            interaction_type = interaction_type or fallback_interaction
            assistant_response_style = assistant_response_style or fallback_style

    if focus_type == "none":
        focus_type = _default_focus_type(active_subject, latest_topic_reference)
    if action == "clarify" or resolution_mode == "clarify":
        resolution_mode = "clarify"
        action = "clarify"
        standalone_query = ""
        if not clarification_question:
            clarification_question = (
                "I can help with that, but I need a little more context. "
                "Please mention the policy, benefit, document, or topic you want me to continue with."
            )
    elif action == "status_only":
        standalone_query = ""
    elif action == "direct_response":
        resolution_mode = "direct"
        if not active_subject:
            active_subject = "HR copilot"
        if focus_type == "none":
            focus_label = None
    elif not standalone_query:
        resolution_mode = "direct"
        standalone_query = expanded_query

    if (
        resolution_mode == "resolved_follow_up"
        and confidence < settings.context_resolution_confidence_threshold
        and (unresolved_references or not active_subject)
        and focus_type != "document"
        and action == "retrieve"
    ):
        resolution_mode = "clarify"
        action = "clarify"
        standalone_query = ""
        clarification_question = (
            clarification_question
            or "I can help with that, but I need a little more context. Which policy, benefit, document, or topic should I continue with?"
        )

    return ConversationContextResolution(
        resolution_mode=resolution_mode,
        standalone_query=standalone_query,
        confidence=confidence,
        active_subject=active_subject,
        latest_topic_reference=latest_topic_reference,
        recent_answer_summary=recent_answer_summary,
        unresolved_references=unresolved_references,
        clarification_question=clarification_question,
        source=source,
        focus_type=focus_type,
        focus_id=focus_id,
        focus_label=focus_label,
        action=action,
        interaction_type=interaction_type
        or _default_interaction_type(focus_type=focus_type, action=action),
        assistant_response_style=assistant_response_style,
    )


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


def _document_clarification_question(documents: list[dict[str, Any]]) -> str:
    labels = [_document_label(document) or "Uploaded document" for document in documents[:3]]
    if not labels:
        return (
            "I found multiple uploaded documents in this conversation. "
            "Which one should I explain?"
        )
    if len(labels) == 1:
        return f"Do you want me to explain {labels[0]}?"
    if len(labels) == 2:
        return (
            f"I found multiple uploaded documents in this conversation: {labels[0]} and {labels[1]}. "
            "Which one should I explain?"
        )
    leading = ", ".join(labels[:-1])
    return (
        f"I found multiple uploaded documents in this conversation: {leading}, and {labels[-1]}. "
        "Which one should I explain?"
    )


def _match_document_by_query(
    query: str,
    documents: list[dict[str, Any]],
) -> dict[str, Any] | None:
    lowered = (query or "").lower()
    best_document = None
    best_length = 0
    for document in documents:
        label = _document_label(document)
        normalized_label = _normalize_document_name(label)
        if not normalized_label:
            continue
        candidates = {normalized_label}
        raw_label = (label or "").lower()
        if raw_label:
            candidates.add(raw_label)
        for candidate in candidates:
            if candidate and candidate in lowered and len(candidate) > best_length:
                best_document = document
                best_length = len(candidate)
    return best_document


def _build_document_standalone_query(query: str, label: str | None) -> str:
    normalized_query = _normalize_query(query)
    document_label = label or "the uploaded document"
    if not normalized_query:
        return f"Explain and summarize the uploaded document {document_label}."

    lowered = normalized_query.lower()
    if _query_mentions_document_reference(normalized_query):
        if _query_looks_like_document_understanding(normalized_query):
            return _normalize_query(
                f"Explain and summarize the uploaded document {document_label}, including what it is and what it is used for."
            )
        return _normalize_query(f"For the uploaded document {document_label}: {normalized_query}")

    return _normalize_query(f"For the uploaded document {document_label}: {normalized_query}")


def _document_resolution(
    query: str,
    recent_messages: list[dict[str, Any]],
    working_set: dict[str, Any] | None,
) -> ConversationContextResolution | None:
    normalized_query = _normalize_query(query)
    unresolved_references = _collect_unresolved_references(normalized_query)
    documents = _working_set_documents(working_set)
    explicit_match = _match_document_by_query(normalized_query, documents)
    document_reference_requested = explicit_match is not None or _query_mentions_document_reference(normalized_query)
    context_dependent = _looks_context_dependent(normalized_query, unresolved_references)

    last_focused_document = _document_by_id(
        working_set,
        (working_set or {}).get("last_focused_document_id"),
    )
    active_attachment_document = _document_by_id(
        working_set,
        (working_set or {}).get("active_attachment_document_id"),
    )

    should_consider_document = document_reference_requested or (
        bool(last_focused_document)
        and context_dependent
        and _query_looks_like_document_understanding(normalized_query)
    )
    if not should_consider_document:
        return None

    ready_documents = _ready_documents(working_set)
    selected = None
    resolution_source = "conversation_memory"
    if explicit_match:
        selected = explicit_match
        resolution_source = "explicit_match"
    elif active_attachment_document and (
        document_reference_requested or _query_looks_like_document_understanding(normalized_query)
    ):
        selected = active_attachment_document
        resolution_source = "composer"
    elif last_focused_document and context_dependent:
        selected = last_focused_document
        resolution_source = "conversation_memory"
    elif len(ready_documents) == 1:
        selected = ready_documents[0]
        resolution_source = "latest_upload"
    elif len(ready_documents) > 1:
        return ConversationContextResolution(
            resolution_mode="clarify",
            standalone_query="",
            confidence=0.24,
            active_subject=None,
            latest_topic_reference=None,
            recent_answer_summary=_latest_recent_summary(recent_messages),
            unresolved_references=unresolved_references,
            clarification_question=_document_clarification_question(ready_documents),
            source="fallback",
            focus_type="none",
            action="clarify",
            interaction_type="clarify",
        )
    else:
        selected = _latest_uploaded_document(working_set)
        resolution_source = "latest_upload"

    label = _document_label(selected) if selected else "uploaded document"
    document_id = selected.get("document_id") if selected else None
    status = selected.get("status") if selected else None
    action: Literal["retrieve", "clarify", "status_only"] = (
        "retrieve" if status == "ready" else "status_only"
    )

    return ConversationContextResolution(
        resolution_mode="resolved_follow_up" if context_dependent else "direct",
        standalone_query=_build_document_standalone_query(normalized_query, label) if action == "retrieve" else "",
        confidence=0.99 if action == "status_only" else 0.92,
        active_subject=label,
        latest_topic_reference=None,
        recent_answer_summary=_latest_recent_summary(recent_messages),
        unresolved_references=unresolved_references,
        clarification_question=None,
        source="fallback",
        focus_type="document",
        focus_id=document_id or label,
        focus_label=label,
        action=action,
        focus_source=resolution_source,
        interaction_type="document_request",
    )


def _finalize_resolution(
    resolution: ConversationContextResolution,
    *,
    query: str,
    recent_messages: list[dict[str, Any]],
    working_set: dict[str, Any] | None,
) -> ConversationContextResolution:
    document_resolution = _document_resolution(query, recent_messages, working_set)
    if document_resolution:
        return document_resolution

    if resolution.focus_type == "none":
        resolution.focus_type = _default_focus_type(
            resolution.active_subject,
            resolution.latest_topic_reference,
        )
        if resolution.focus_type in {"topic", "policy"}:
            resolution.focus_label = resolution.active_subject or resolution.latest_topic_reference

    if resolution.action == "clarify":
        resolution.resolution_mode = "clarify"
        resolution.standalone_query = ""
        resolution.interaction_type = "clarify"
    elif resolution.focus_type == "document":
        if resolution.action == "direct_response":
            resolution.action = "retrieve"
        resolution.interaction_type = "document_request"

    return resolution


def _fallback_resolution(
    query: str,
    recent_messages: list[dict[str, Any]],
    *,
    session_scope_active: bool = False,
    working_set: dict[str, Any] | None = None,
) -> ConversationContextResolution:
    expanded_query = _expand_abbreviations(query)

    document_resolution = _document_resolution(
        expanded_query,
        recent_messages,
        working_set,
    )
    if document_resolution:
        document_resolution.context_window = _build_context_window(
            document_resolution,
            _collect_recent_documents(recent_messages, working_set),
            session_scope_active=session_scope_active,
            working_set=working_set,
        )
        return document_resolution

    unresolved_references = _collect_unresolved_references(expanded_query)
    active_subject = _latest_active_subject(recent_messages)
    latest_topic_reference = _latest_topic_reference(recent_messages)
    recent_answer_summary = _latest_recent_summary(recent_messages)
    needs_clarification = _looks_context_dependent(expanded_query, unresolved_references) and not active_subject

    direct_resolution = _fallback_direct_resolution(expanded_query)
    if direct_resolution:
        direct_resolution.context_window = _build_context_window(
            direct_resolution,
            _collect_recent_documents(recent_messages, working_set),
            session_scope_active=session_scope_active,
            working_set=working_set,
        )
        return direct_resolution

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
            focus_type="none",
            action="clarify",
            interaction_type="clarify",
        )
    else:
        resolution_mode: Literal["direct", "resolved_follow_up", "clarify"] = (
            "resolved_follow_up" if _looks_context_dependent(expanded_query, unresolved_references) else "direct"
        )
        focus_type = _default_focus_type(active_subject, latest_topic_reference)
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
            focus_type=focus_type,
            focus_label=active_subject or latest_topic_reference,
            action="retrieve",
            interaction_type=_default_interaction_type(
                focus_type=focus_type,
                action="retrieve",
            ),
        )

    resolution.context_window = _build_context_window(
        resolution,
        _collect_recent_documents(recent_messages, working_set),
        session_scope_active=session_scope_active,
        working_set=working_set,
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
    conversation_working_set: Any | None = None,
) -> ConversationContextResolution:
    normalized_query = _normalize_query(query)
    expanded_query = _expand_abbreviations(normalized_query)
    recent_messages = conversation_history[-(settings.context_resolution_history_turns * 2) :]
    working_set = _normalize_working_set(conversation_working_set)
    recent_documents = _collect_recent_documents(recent_messages, working_set)

    if cache and conversation_id:
        cached_entry = await cache.get(
            conversation_id=conversation_id,
            query=expanded_query,
            recent_messages=recent_messages,
            conversation_working_set=working_set,
        )
        if cached_entry:
            cached_resolution = _parse_resolution_response(
                json.dumps(cached_entry),
                expanded_query=expanded_query,
                recent_messages=recent_messages,
                source="cache",
            )
            if cached_resolution:
                cached_resolution = _finalize_resolution(
                    cached_resolution,
                    query=expanded_query,
                    recent_messages=recent_messages,
                    working_set=working_set,
                )
                cached_resolution.context_window = _build_context_window(
                    cached_resolution,
                    recent_documents,
                    session_scope_active=session_scope_active,
                    working_set=working_set,
                )
                return cached_resolution

    llm_messages = _build_resolver_messages(
        raw_query=normalized_query,
        expanded_query=expanded_query,
        recent_messages=recent_messages,
        recent_documents=recent_documents,
        session_scope_active=session_scope_active,
        working_set=working_set,
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
                working_set=working_set,
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
            working_set=working_set,
        )
        logger.warning(
            "Using fallback conversation context resolution",
            extra={"query": normalized_query, "source": fallback.source},
        )
        return fallback

    parsed_resolution = _finalize_resolution(
        parsed_resolution,
        query=expanded_query,
        recent_messages=recent_messages,
        working_set=working_set,
    )
    parsed_resolution.context_window = _build_context_window(
        parsed_resolution,
        recent_documents,
        session_scope_active=session_scope_active,
        working_set=working_set,
    )

    if cache and conversation_id:
        await cache.set(
            conversation_id=conversation_id,
            query=expanded_query,
            recent_messages=recent_messages,
            conversation_working_set=working_set,
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
    active_subject = (
        title
        or (context_resolution.focus_label if context_resolution and context_resolution.focus_type == "document" else None)
        or (context_resolution.active_subject if context_resolution else None)
        or _derive_subject_from_text(question)
    )
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
        "focus_type": context_resolution.focus_type if context_resolution else "none",
        "focus_id": context_resolution.focus_id if context_resolution else None,
        "focus_label": context_resolution.focus_label if context_resolution else None,
        "interaction_type": context_resolution.interaction_type if context_resolution else "knowledge_request",
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
