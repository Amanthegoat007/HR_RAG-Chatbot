from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any


PAGE_BREAK_RE = re.compile(r"<!-- PAGE_BREAK: page_(\d+) -->", flags=re.IGNORECASE)
TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
HEADING_RE = re.compile(r"^\s*#{1,6}\s+")
LIST_RE = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+)")


@dataclass
class QualityResult:
    score: float
    flags: list[str]
    metrics: dict[str, float]


def score_markdown_quality(
    markdown_text: str,
    page_count: int,
    parser_errors: list[str] | None = None,
    ocr_used: bool = False,
) -> QualityResult:
    parser_errors = parser_errors or []
    pages = _split_pages(markdown_text, page_count)
    cleaned_pages = [_strip_frontmatter(page).strip() for page in pages]

    non_empty_pages = sum(1 for page in cleaned_pages if _visible_char_count(page) > 0)
    empty_page_ratio = 1.0 - (non_empty_pages / max(len(cleaned_pages), 1))
    char_counts = [_visible_char_count(page) for page in cleaned_pages]
    page_text_density = sum(char_counts) / max(len(cleaned_pages), 1)

    all_lines = [line.strip() for page in cleaned_pages for line in page.splitlines() if line.strip()]
    heading_lines = sum(1 for line in all_lines if HEADING_RE.match(line))
    heading_density = heading_lines / max(len(all_lines), 1)
    orphan_line_ratio = _orphan_line_ratio(all_lines)
    duplicate_header_footer_ratio = _duplicate_line_ratio(all_lines)
    broken_table_ratio = _broken_table_ratio(all_lines)
    malformed_markdown_ratio = _malformed_markdown_ratio(all_lines)

    score = 1.0
    score -= min(0.35, empty_page_ratio * 0.50)
    score -= _piecewise_penalty(page_text_density, points=((120, 0.0), (80, 0.08), (45, 0.18), (20, 0.30)))
    score -= min(0.18, duplicate_header_footer_ratio * 0.45)
    score -= min(0.22, broken_table_ratio * 0.60)
    score -= min(0.16, malformed_markdown_ratio * 0.45)
    score -= min(0.16, orphan_line_ratio * 0.30)
    if heading_density < 0.01:
        score -= 0.06
    if parser_errors:
        score -= min(0.20, 0.06 * len(parser_errors))
    if ocr_used:
        score -= 0.03

    score = max(0.0, min(1.0, round(score, 4)))

    flags: list[str] = []
    if page_text_density < 45:
        flags.append("low_text_density")
    if empty_page_ratio > 0.20:
        flags.append("page_coverage_low")
    if duplicate_header_footer_ratio > 0.15:
        flags.append("duplicate_headers_detected")
    if broken_table_ratio > 0.12:
        flags.append("table_structure_unstable")
    if malformed_markdown_ratio > 0.15:
        flags.append("markdown_structure_unstable")
    if heading_density < 0.01:
        flags.append("heading_structure_weak")
    if orphan_line_ratio > 0.25:
        flags.append("fragmented_line_layout")
    if ocr_used:
        flags.append("ocr_used")
    if parser_errors:
        flags.append("parser_error")

    metrics = {
        "page_text_density": round(page_text_density, 2),
        "broken_table_ratio": round(broken_table_ratio, 4),
        "duplicate_header_footer_ratio": round(duplicate_header_footer_ratio, 4),
        "empty_page_ratio": round(empty_page_ratio, 4),
        "heading_density": round(heading_density, 4),
        "orphan_line_ratio": round(orphan_line_ratio, 4),
        "malformed_markdown_ratio": round(malformed_markdown_ratio, 4),
    }

    return QualityResult(score=score, flags=flags, metrics=metrics)


def _split_pages(markdown_text: str, page_count: int) -> list[str]:
    without_frontmatter = _strip_frontmatter(markdown_text)
    raw_pages = PAGE_BREAK_RE.split(without_frontmatter)

    pages: list[str] = []
    if len(raw_pages) == 1:
        pages = [without_frontmatter]
    else:
        pages = [raw_pages[0]]
        for idx in range(1, len(raw_pages), 2):
            if idx + 1 < len(raw_pages):
                pages.append(raw_pages[idx + 1])

    if not pages:
        pages = [""]

    # Keep metric denominator stable when parser under-reports breaks.
    while len(pages) < max(page_count, 1):
        pages.append("")
    return pages


def _strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\n.*?\n---\n?", "", text or "", flags=re.DOTALL)


def _visible_char_count(text: str) -> int:
    visible = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("<!-- PAGE_BREAK"):
            continue
        visible.append(line)
    return sum(len(line) for line in visible)


def _duplicate_line_ratio(lines: list[str]) -> float:
    if not lines:
        return 0.0
    frequent_candidates = [line for line in lines if len(line) >= 12]
    if not frequent_candidates:
        return 0.0

    counts = Counter(frequent_candidates)
    repeated = sum(count for _, count in counts.items() if count >= 3)
    return repeated / max(len(lines), 1)


def _broken_table_ratio(lines: list[str]) -> float:
    table_lines = [line for line in lines if TABLE_LINE_RE.match(line)]
    if not table_lines:
        return 0.0

    valid = 0
    for line in table_lines:
        # Require at least 3 separators (2+ cells).
        if line.count("|") >= 3:
            valid += 1
    return 1.0 - (valid / max(len(table_lines), 1))


def _malformed_markdown_ratio(lines: list[str]) -> float:
    if not lines:
        return 0.0

    malformed = 0
    for line in lines:
        # Detect suspicious hanging markdown punctuation patterns.
        if line.count("**") % 2 == 1:
            malformed += 1
        elif line.count("`") % 2 == 1:
            malformed += 1
    return malformed / max(len(lines), 1)


def _orphan_line_ratio(lines: list[str]) -> float:
    if not lines:
        return 0.0

    orphan = 0
    for line in lines:
        if HEADING_RE.match(line) or LIST_RE.match(line) or TABLE_LINE_RE.match(line):
            continue
        words = line.split()
        if len(words) <= 2 and len(line) <= 20:
            orphan += 1
    return orphan / max(len(lines), 1)


def _piecewise_penalty(value: float, points: tuple[tuple[float, float], ...]) -> float:
    for threshold, penalty in points:
        if value >= threshold:
            return penalty
    return points[-1][1]

