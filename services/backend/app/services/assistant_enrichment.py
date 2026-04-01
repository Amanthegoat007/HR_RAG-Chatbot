from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any

import asyncpg

from app import db
from app.services.assistant_response_builder import build_assistant_message_metadata
from app.services.policy_metadata import infer_policy_metadata_from_record

logger = logging.getLogger(__name__)

_SUGGESTION_LIMIT = 3
_MIN_GROUNDED_SCORE = 0.58


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _humanize_filename(filename: str | None) -> str:
    stem = Path(filename or "").stem
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", " ", stem)
    stem = re.sub(r"\bv(?:ersion)?\s*\d+(?:\.\d+)*\b", " ", stem, flags=re.IGNORECASE)
    return _clean_text(stem)


def _coerce_document_metadata(raw_value: Any) -> dict[str, Any]:
    if isinstance(raw_value, dict):
        return dict(raw_value)
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_topic_label(value: str | None) -> str:
    topic = _clean_text(value)
    if not topic:
        return ""
    topic = re.sub(r"\bpolicy\b$", "", topic, flags=re.IGNORECASE).strip(" ,.-")
    return topic or _clean_text(value)


def _format_display_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%b %d, %Y")
    except ValueError:
        return value


def _relative_freshness_label(document_date: datetime | None) -> tuple[str | None, str | None]:
    if document_date is None:
        return None, None

    now = datetime.now(timezone.utc)
    reference = document_date
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)

    age_days = max(0, int((now - reference).total_seconds() // 86400))
    if age_days <= 1:
        return "Updated today", "fresh"
    if age_days < 30:
        return f"Updated {age_days}d ago", "fresh"
    if age_days < 365:
        months = max(1, age_days // 30)
        return f"Updated {months}mo ago", "recent"
    years = max(1, age_days // 365)
    return f"Updated {years}y ago", "stale"


def _grounding_label(top_score: float) -> str:
    if top_score >= 0.85:
        return "High grounding"
    if top_score >= 0.7:
        return "Grounded"
    return "Light grounding"


def _primary_source(sources: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not sources:
        return None
    return max(
        sources,
        key=lambda source: float(source.get("score") or 0.0),
    )


def build_trust_summary(
    sources: list[dict[str, Any]],
    document_records: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not sources:
        return None

    primary_source = _primary_source(sources)
    if primary_source is None:
        return None

    top_score = float(primary_source.get("score") or 0.0)
    doc_records = document_records or {}
    doc_insights: dict[str, dict[str, Any]] = {}
    family_versions: dict[str, set[str]] = {}
    family_dates: dict[str, set[str]] = {}

    for source in sources:
        document_id = source.get("document_id") or ""
        record = doc_records.get(document_id)
        record_metadata = _coerce_document_metadata((record or {}).get("metadata"))
        inferred = infer_policy_metadata_from_record(
            filename=(record or {}).get("filename") or source.get("filename"),
            metadata=record_metadata,
        )
        title = inferred.get("policy_title") or _humanize_filename(source.get("filename"))
        family = inferred.get("policy_family") or _normalize_topic_label(title)
        version = inferred.get("policy_version")
        effective_date = inferred.get("effective_date")
        doc_insights[document_id] = {
            "policy_title": title,
            "policy_family": family,
            "policy_version": version,
            "effective_date": effective_date,
            "owner": inferred.get("owner"),
            "jurisdiction": inferred.get("jurisdiction"),
            "document_updated_at": (record or {}).get("processed_at") or (record or {}).get("uploaded_at"),
        }
        if family:
            if version:
                family_versions.setdefault(family, set()).add(version)
            if effective_date:
                family_dates.setdefault(family, set()).add(effective_date)

    primary_doc_id = primary_source.get("document_id") or ""
    primary_insight = doc_insights.get(primary_doc_id, {})
    primary_title = primary_insight.get("policy_title") or _humanize_filename(primary_source.get("filename"))
    primary_family = primary_insight.get("policy_family") or _normalize_topic_label(primary_title)
    versions = family_versions.get(primary_family or "", set())
    dates = family_dates.get(primary_family or "", set())

    conflict_label = None
    if len(versions) > 1:
        conflict_label = "Version mismatch across cited sources"
    elif len(dates) > 1:
        conflict_label = "Effective dates differ across cited sources"

    freshness_label, freshness_tone = _relative_freshness_label(
        primary_insight.get("document_updated_at"),
    )

    summary = {
        "policyTitle": primary_title or None,
        "policyFamily": primary_family or None,
        "policyVersion": primary_insight.get("policy_version"),
        "effectiveDate": primary_insight.get("effective_date"),
        "effectiveDateLabel": _format_display_date(primary_insight.get("effective_date")),
        "owner": primary_insight.get("owner"),
        "jurisdiction": primary_insight.get("jurisdiction"),
        "freshnessLabel": freshness_label,
        "freshnessTone": freshness_tone,
        "groundingLabel": _grounding_label(top_score),
        "groundingScore": round(top_score, 3),
        "hasConflict": bool(conflict_label),
        "conflictLabel": conflict_label,
        "sourceCount": len(sources),
    }
    return {key: value for key, value in summary.items() if value is not None}


def _topic_from_context(
    *,
    question: str,
    trust_summary: dict[str, Any] | None,
    context_resolution: dict[str, Any] | None,
    sources: list[dict[str, Any]],
) -> str:
    topic = _clean_text((context_resolution or {}).get("activeSubject"))
    if topic:
        return topic
    topic = _clean_text((context_resolution or {}).get("latestTopicReference"))
    if topic:
        return topic
    topic = _clean_text((trust_summary or {}).get("policyTitle"))
    if topic:
        return topic
    top_section = _clean_text((sources[0] if sources else {}).get("section"))
    if top_section and top_section.lower() != "unknown section":
        return top_section
    return _normalize_topic_label(question)


def _family_key(trust_summary: dict[str, Any] | None, topic: str) -> str:
    family = _clean_text((trust_summary or {}).get("policyFamily") or topic).lower()
    return family


def _add_suggestion(
    suggestions: list[dict[str, str]],
    seen_prompts: set[str],
    *,
    label: str,
    prompt: str,
) -> None:
    normalized_prompt = _clean_text(prompt).lower()
    if not normalized_prompt or normalized_prompt in seen_prompts:
        return
    suggestions.append({"label": label, "prompt": _clean_text(prompt)})
    seen_prompts.add(normalized_prompt)


def build_related_suggestions(
    *,
    question: str,
    user_role: str,
    metadata: dict[str, Any],
    sources: list[dict[str, Any]],
    trust_summary: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    if not sources:
        return []

    answer_path = metadata.get("answerPath")
    if answer_path in {"clarification", "no_context"}:
        return []

    top_score = float((_primary_source(sources) or {}).get("score") or 0.0)
    if top_score < _MIN_GROUNDED_SCORE:
        return []

    context_resolution = metadata.get("contextResolution") or {}
    topic = _topic_from_context(
        question=question,
        trust_summary=trust_summary,
        context_resolution=context_resolution,
        sources=sources,
    )
    if not topic:
        return []

    family = _family_key(trust_summary, topic)
    suggestions: list[dict[str, str]] = []
    seen_prompts: set[str] = set()
    topic_label = _normalize_topic_label((trust_summary or {}).get("policyTitle") or topic)
    topic_subject = topic_label or "this policy"

    if "holiday" in family:
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Holiday overlap",
            prompt="What happens if a public holiday falls during approved leave?",
        )
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Entity coverage",
            prompt=f"Who follows {topic_subject}, and are there entity-specific exceptions I should know about?",
        )
    elif "leave" in family:
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Docs and approvals",
            prompt=f"What documents, approvals, or notice requirements apply to {topic_subject}?",
        )
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Exceptions",
            prompt=f"What exceptions, carry-forward, payout, or deadline rules apply to {topic_subject}?",
        )
    elif "benefit" in family or "medical" in family:
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Eligibility",
            prompt=f"Who is eligible for {topic_subject}, and when does coverage start?",
        )
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Required docs",
            prompt=f"What documents are required to add, remove, or update coverage under {topic_subject}?",
        )
    elif "payroll" in family:
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Payroll timing",
            prompt=f"When does {topic_subject} affect payroll, and what cutoff dates apply?",
        )
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Evidence needed",
            prompt=f"What evidence or documentation is usually required for {topic_subject}?",
        )
    elif "probation" in family:
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Approvals",
            prompt=f"What approvals or decision points apply to {topic_subject}?",
        )
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Exceptions",
            prompt=f"What exceptions or extension rules apply to {topic_subject}?",
        )
    else:
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Eligibility",
            prompt=f"What eligibility rules or scope limits apply to {topic_subject}?",
        )
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Docs and deadlines",
            prompt=f"What documents, approvals, or deadlines should I know about for {topic_subject}?",
        )

    role_key = (user_role or "employee").lower()
    if role_key == "admin":
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="HR summary",
            prompt=f"Give me an HR operations summary for {topic_subject}, including exceptions and edge cases.",
        )
    elif role_key == "manager":
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="Manager view",
            prompt=f"Summarize {topic_subject} for a manager who needs to approve or communicate a decision.",
        )
    else:
        _add_suggestion(
            suggestions,
            seen_prompts,
            label="What next",
            prompt=f"What are the next steps an employee should take for {topic_subject}?",
        )

    return suggestions[:_SUGGESTION_LIMIT]


async def build_enriched_assistant_message_metadata(
    *,
    question: str,
    answer_text: str,
    sources: list[dict[str, Any]] | None = None,
    upstream_meta: dict[str, Any] | None = None,
    user_role: str = "employee",
    db_pool: asyncpg.Pool | None = None,
) -> dict[str, Any]:
    grounded_sources = sources or []
    metadata = build_assistant_message_metadata(
        question=question,
        answer_text=answer_text,
        sources=grounded_sources,
        upstream_meta=upstream_meta,
    )

    if not grounded_sources:
        return metadata

    document_records: dict[str, dict[str, Any]] = {}
    if db_pool is not None:
        document_ids = [
            source.get("document_id")
            for source in grounded_sources
            if source.get("document_id")
        ]
        if document_ids:
            try:
                document_records = await db.get_documents_by_ids(db_pool, document_ids)
            except Exception as exc:
                logger.warning("Failed to load document metadata for assistant enrichments", extra={"error": str(exc)})

    trust_summary = build_trust_summary(grounded_sources, document_records=document_records)
    if trust_summary:
        metadata["trustSummary"] = trust_summary

    related_suggestions = build_related_suggestions(
        question=question,
        user_role=user_role,
        metadata=metadata,
        sources=grounded_sources,
        trust_summary=trust_summary,
    )
    if related_suggestions:
        metadata["relatedSuggestions"] = related_suggestions

    return metadata
