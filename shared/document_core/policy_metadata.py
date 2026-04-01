from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from typing import Any


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d.%m.%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
)

_OWNER_KEYS = (
    "owner",
    "policy_owner",
    "document_owner",
    "department",
    "function",
)

_EFFECTIVE_KEYS = (
    "effective_date",
    "effective",
    "effective_from",
    "valid_from",
    "revision_date",
)

_FAMILY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Public Holiday Policy", ("public holiday", "holiday calendar", "holiday policy", "holiday")),
    ("Leave Policy", ("annual leave", "sick leave", "paid time off", "pto", "leave policy", "leave")),
    ("Medical Benefits Policy", ("medical benefit", "medical coverage", "insurance", "dependent coverage", "benefits")),
    ("Payroll Policy", ("payroll", "salary", "pay cycle", "compensation", "deduction")),
    ("Probation Policy", ("probation",)),
    ("Onboarding Policy", ("onboarding", "joining process", "new employee", "induction")),
    ("Expense Reimbursement Policy", ("expense reimbursement", "expense claim", "reimbursement")),
    ("Travel and Air Ticket Policy", ("air ticket", "travel allowance", "travel policy", "flight allowance")),
    ("Remote Work Policy", ("remote work", "hybrid work", "work from home")),
    ("End of Service Policy", ("end of service", "gratuity")),
]

_JURISDICTION_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("UAE", ("uae", "united arab emirates", "dubai", "abu dhabi")),
    ("KSA", ("ksa", "saudi", "saudi arabia")),
    ("Qatar", ("qatar",)),
    ("Oman", ("oman",)),
    ("India", ("india",)),
    ("Group", ("group", "holding company", "holding companies")),
]


def _clean_text(value: str | None) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _clean_filename_title(filename: str | None) -> str:
    stem = Path(filename or "").stem
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", " ", stem)
    stem = re.sub(r"\bv(?:ersion)?\s*\d+(?:\.\d+)*\b", " ", stem, flags=re.IGNORECASE)
    stem = re.sub(r"\s+", " ", stem).strip(" -_()")
    return stem


def _choose_policy_title(headings: list[str], filename: str | None) -> str:
    for heading in headings:
        cleaned = _clean_text(heading)
        if cleaned and len(cleaned) >= 6:
            return cleaned
    return _clean_filename_title(filename)


def _leading_text(markdown_text: str | None, limit: int = 60) -> str:
    if not markdown_text:
        return ""
    lines = []
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            continue
        if line.startswith("<!--"):
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def _parse_iso_date(raw_value: str | None) -> str | None:
    value = _clean_text(raw_value)
    if not value:
        return None

    direct = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", value)
    if direct:
        return direct.group(1)

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _extract_version(*candidates: str) -> str | None:
    for candidate in candidates:
        text = _clean_text(candidate)
        if not text:
            continue

        explicit = re.search(
            r"\b(?:version|ver|rev|revision|v)\.?\s*([0-9]+(?:\.[0-9]+)*)\b",
            text,
            flags=re.IGNORECASE,
        )
        if explicit:
            return f"v{explicit.group(1)}"

        filename_match = re.search(r"[-_ ]v([0-9]+(?:\.[0-9]+)*)\b", text, flags=re.IGNORECASE)
        if filename_match:
            return f"v{filename_match.group(1)}"
    return None


def _extract_owner(frontmatter: dict[str, str], search_text: str) -> str | None:
    for key in _OWNER_KEYS:
        if frontmatter.get(key):
            return _clean_text(frontmatter[key])

    match = re.search(
        r"(?im)^(?:policy owner|document owner|owner|department|function)\s*[:\-]\s*(.+)$",
        search_text,
    )
    if match:
        return _clean_text(match.group(1))
    return None


def _extract_effective_date(frontmatter: dict[str, str], search_text: str, filename: str | None) -> str | None:
    for key in _EFFECTIVE_KEYS:
        parsed = _parse_iso_date(frontmatter.get(key))
        if parsed:
            return parsed

    match = re.search(
        r"(?im)^(?:effective(?:\s+date)?|effective\s+from|valid\s+from|revision\s+date|last\s+updated)\s*[:\-]\s*(.+)$",
        search_text,
    )
    if match:
        parsed = _parse_iso_date(match.group(1))
        if parsed:
            return parsed

    filename_date = re.search(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{4})\b", filename or "")
    if filename_date:
        return _parse_iso_date(filename_date.group(1))
    return None


def _infer_policy_family(*candidates: str) -> str | None:
    haystack = " ".join(_clean_text(candidate).lower() for candidate in candidates if candidate)
    if not haystack:
        return None

    for family, keywords in _FAMILY_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return family
    return None


def _infer_jurisdiction(*candidates: str) -> str | None:
    haystack = " ".join(_clean_text(candidate).lower() for candidate in candidates if candidate)
    if not haystack:
        return None

    for jurisdiction, keywords in _JURISDICTION_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return jurisdiction
    return None


def infer_policy_metadata(
    *,
    markdown_text: str | None = None,
    filename: str | None = None,
    frontmatter: dict[str, str] | None = None,
    headings: list[str] | None = None,
) -> dict[str, Any]:
    fm = dict(frontmatter or {})
    heading_list = [heading for heading in (headings or []) if _clean_text(heading)]
    top_text = _leading_text(markdown_text)

    policy_title = _clean_text(fm.get("policy_title")) or _choose_policy_title(heading_list, filename)
    policy_family = _clean_text(fm.get("policy_family")) or _infer_policy_family(
        policy_title,
        filename or "",
        " ".join(heading_list[:5]),
        top_text,
    )
    policy_version = _clean_text(fm.get("policy_version")) or _extract_version(
        fm.get("version", ""),
        policy_title,
        filename or "",
        top_text,
    )
    effective_date = _clean_text(fm.get("effective_date")) or _extract_effective_date(
        fm,
        top_text,
        filename,
    )
    owner = _clean_text(fm.get("owner")) or _extract_owner(fm, top_text)
    jurisdiction = _clean_text(fm.get("jurisdiction")) or _infer_jurisdiction(
        policy_title,
        filename or "",
        " ".join(heading_list[:5]),
        top_text,
    )

    return {
        "policy_title": policy_title or None,
        "policy_family": policy_family or None,
        "policy_version": policy_version or None,
        "effective_date": effective_date or None,
        "owner": owner or None,
        "jurisdiction": jurisdiction or None,
    }


def infer_policy_metadata_from_record(
    *,
    filename: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    doc_metadata = dict(metadata or {})
    headings = [
        _clean_text(item)
        for item in (doc_metadata.get("section_headings") or [])
        if _clean_text(item)
    ]

    inferred = infer_policy_metadata(
        markdown_text=None,
        filename=filename or doc_metadata.get("filename", ""),
        frontmatter={
            key: str(value)
            for key, value in doc_metadata.items()
            if isinstance(value, (str, int, float))
        },
        headings=headings,
    )

    for key in ("policy_title", "policy_family", "policy_version", "effective_date", "owner", "jurisdiction"):
        explicit_value = _clean_text(doc_metadata.get(key))
        if explicit_value:
            inferred[key] = explicit_value

    return inferred
