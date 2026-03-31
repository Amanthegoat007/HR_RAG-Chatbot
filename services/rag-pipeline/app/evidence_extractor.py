import math
import re
from typing import Any


def money_values(text: str) -> list[float]:
    values: list[float] = []
    for match in re.findall(r"[$]\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text or ""):
        values.append(float(match.replace(",", "")))
    return values


def month_values(text: str) -> list[int]:
    values: list[int] = []
    for match in re.findall(r"(\d+)\s*[- ]?\s*months?\b", (text or "").lower()):
        values.append(int(match))
    return values


def format_money(amount: float) -> str:
    rounded = round(amount + 1e-9, 2)
    if math.isclose(rounded, int(rounded), abs_tol=1e-9):
        return f"${int(rounded):,}"
    return f"${rounded:,.2f}".rstrip("0").rstrip(".")


def dedupe_chunks(*chunk_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for chunk_list in chunk_lists:
        for chunk in chunk_list:
            key = (
                chunk.get("point_id")
                or f"{chunk.get('document_id', '')}:{chunk.get('chunk_index', '')}:{chunk.get('page_number', '')}"
            )
            if not key:
                key = chunk.get("text", "")[:160]
            if key in seen:
                continue
            seen.add(key)
            merged.append(chunk)
    return merged


def citation_line(source: dict[str, Any]) -> str:
    filename = source.get("filename") or "Unknown"
    section = source.get("section") or "Unknown Section"
    page = source.get("page_number") or source.get("page_start") or "?"
    return f"(Source: {filename} | Section: {section} | Page: {page})"


def extract_markdown_tables(text: str) -> list[dict[str, Any]]:
    lines = (text or "").splitlines()
    groups: list[list[str]] = []
    current_group: list[str] = []

    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("|") and line.endswith("|") and line.count("|") >= 3:
            current_group.append(line)
            continue
        if current_group:
            groups.append(current_group)
            current_group = []

    if current_group:
        groups.append(current_group)

    tables: list[dict[str, Any]] = []
    for group in groups:
        rows = [_parse_table_line(line) for line in group]
        rows = [row for row in rows if row]
        if len(rows) < 2:
            continue

        headers = rows[0]
        data_rows: list[list[str]] = []
        for row in rows[1:]:
            if _is_separator_row(row):
                continue
            if len(row) < len(headers):
                row = row + [""] * (len(headers) - len(row))
            data_rows.append(row[: len(headers)])

        if data_rows:
            tables.append({"headers": headers, "rows": data_rows})

    return tables


def extract_program_rows(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[tuple[int, list[str], list[list[str]], dict[str, Any]]] = []
    for chunk in chunks:
        for table in extract_markdown_tables(chunk.get("text", "")):
            headers = [_normalize_header(header) for header in table["headers"]]
            if len(headers) < 2:
                continue
            score = _program_table_score(headers, table["rows"])
            if score <= 0:
                continue
            candidates.append((score, headers, table["rows"], chunk))

    if not candidates:
        return []

    _, headers, rows, chunk = max(
        candidates,
        key=lambda item: (
            item[0],
            len(item[2]),
            item[3].get("rerank_score", item[3].get("score", 0.0)),
        ),
    )

    items: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row:
            continue

        raw_name = row[0].strip()
        name = _canonical_program_name(raw_name)
        normalized_name = _normalize_label(name)
        if not normalized_name or normalized_name in {"program", "programs"}:
            continue

        benefit = ""
        application = ""

        for idx, header in enumerate(headers[1:], start=1):
            value = row[idx].strip() if idx < len(row) else ""
            if not value:
                continue

            if any(token in header for token in ("benefit", "assistance", "support")):
                benefit = _merge_nonempty(benefit, value)
            elif any(token in header for token in ("application", "apply", "approval", "process", "contact")):
                application = _merge_nonempty(application, value)

        if not benefit and len(row) >= 2:
            benefit = row[1].strip()
        if not application and len(row) >= 3:
            application = row[-1].strip()

        if not (benefit or application):
            continue

        items[normalized_name] = {
            "name": name,
            "benefit": benefit,
            "application": application,
            "source": chunk,
        }

    return list(items.values())


def extract_fee_items(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        for line in (chunk.get("text", "") or "").splitlines():
            stripped = line.strip().strip("|")
            if not stripped:
                continue
            if "reconnection" not in stripped.lower() and "fee" not in stripped.lower():
                continue

            amount_matches = list(re.finditer(r"[$]\s*[0-9][0-9,]*(?:\.[0-9]+)?", stripped))
            if not amount_matches:
                continue

            for idx, match in enumerate(amount_matches):
                amount = match.group(0).replace(" ", "")
                label_start = match.end()
                label_end = amount_matches[idx + 1].start() if idx + 1 < len(amount_matches) else len(stripped)
                label = re.sub(r"\s+", " ", stripped[label_start:label_end]).strip(" ,.;:-")
                label = _trim_fee_label(label)
                if not label:
                    continue
                if "reconnection" not in label.lower() and "fee" not in label.lower():
                    continue

                key = f"{amount}:{_normalize_label(label)}"
                results[key] = {
                    "amount": amount,
                    "label": label,
                    "source": chunk,
                }

    return sorted(results.values(), key=lambda item: money_values(item["amount"])[0] if money_values(item["amount"]) else 0.0)


def pick_calc_support(
    query: str,
    chunks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    query_amounts = money_values(query)
    query_months = month_values(query)
    lowered_query = (query or "").lower()
    best_chunk: dict[str, Any] | None = None
    best_score = -1

    for chunk in chunks:
        text = chunk.get("text", "")
        lowered = text.lower()
        score = 0

        for amount in query_amounts:
            if format_money(amount) in text:
                score += 2
        for months in query_months:
            if f"{months}-month" in lowered or f"{months} month" in lowered:
                score += 2
        if "installment" in lowered:
            score += 2
        if "current" in lowered and "bill" in lowered:
            score += 1
        if "dpa" in lowered_query and "dpa" in lowered:
            score += 2
        if "deferred payment agreement" in lowered_query and "deferred payment agreement" in lowered:
            score += 2

        if score > best_score:
            best_score = score
            best_chunk = chunk

    return best_chunk if best_score >= 5 else None


def extract_range_phrase(text: str) -> str | None:
    match = re.search(
        r"([$]\s*[0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:-|to)\s*([$]\s*[0-9][0-9,]*(?:\.[0-9]+)?)",
        text or "",
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    left = match.group(1).replace(" ", "")
    right = match.group(2).replace(" ", "")
    return f"{left} to {right}"


def _parse_table_line(line: str) -> list[str]:
    parts = [part.strip() for part in line.strip().strip("|").split("|")]
    return [part for part in parts]


def _is_separator_row(row: list[str]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in row)


def _normalize_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (header or "").lower()).strip()


def _normalize_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (label or "").lower()).strip()


def _merge_nonempty(left: str, right: str) -> str:
    left = (left or "").strip()
    right = (right or "").strip()
    if left and right and right not in left:
        return f"{left} {right}".strip()
    return left or right


def _trim_fee_label(label: str) -> str:
    trimmed = re.split(r"\s*,\s*\(\d+\)\s+", label, maxsplit=1)[0]
    trimmed = re.split(r"\s*[.;]\s+", trimmed, maxsplit=1)[0]
    trimmed = re.sub(r"\s+", " ", trimmed).strip(" ,.;:-")
    return trimmed


def _looks_like_program_table(headers: list[str], rows: list[list[str]]) -> bool:
    return _program_table_score(headers, rows) > 0


def _program_table_score(headers: list[str], rows: list[list[str]]) -> int:
    header_text = " ".join(headers)
    if (
        "program" in header_text
        and any(token in header_text for token in ("benefit", "best for", "assistance"))
        and any(token in header_text for token in ("application", "process", "approval"))
    ):
        base = 100
    else:
        base = 0

    hits = 0
    for row in rows:
        if not row:
            continue
        if _canonical_program_name(row[0]):
            hits += 1
    if base == 0 and hits < 3:
        return 0
    return base + hits


def _canonical_program_name(label: str) -> str | None:
    normalized = _normalize_label(label)
    if not normalized:
        return None

    blacklist = (
        "setup",
        "enrollment",
        "information",
        "info",
        "referral",
        "prevention",
        "contact",
        "hotline",
    )
    if any(token in normalized for token in blacklist):
        return None

    if "deferred payment agreement" in normalized or normalized == "dpa":
        return "Deferred Payment Agreement (DPA)"
    if "extended payment plan" in normalized or normalized == "epp":
        return "Extended Payment Plan (EPP)"
    if "budget billing" in normalized:
        return "Budget Billing Program"
    if "liheap" in normalized:
        return "LIHEAP (Federal)"
    if "utilitypro care fund" in normalized or "care fund" in normalized:
        return "UtilityPro Care Fund"
    if "weatherization assistance" in normalized or normalized == "weatherization":
        return "Weatherization Assistance"
    if "medical payment protection" in normalized:
        return "Medical Payment Protection"

    return None
