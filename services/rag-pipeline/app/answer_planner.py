from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.evidence_extractor import (
    citation_line,
    dedupe_chunks,
    extract_fee_items,
    extract_program_rows,
    format_money,
    money_values,
    month_values,
    pick_calc_support,
)


@dataclass
class AnswerPlan:
    question_type: str
    high_confidence: bool = False
    answer_path: str = "llm"
    facts: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    final_answer: str = ""
    citation_chunks: list[dict[str, Any]] = field(default_factory=list)
    deterministic_confidence: float = 0.0


def classify_question(query: str) -> str:
    normalized = " ".join((query or "").lower().split())

    if _looks_like_calc(normalized):
        return "calc"
    if _looks_like_list(normalized):
        return "list"
    if any(token in normalized for token in ("explain", "summary", "summarize", "why ", "how does", "process")):
        return "explain"
    return "fact"


def plan_answer(
    query: str,
    retrieved_chunks: list[dict[str, Any]],
    reranked_chunks: list[dict[str, Any]],
) -> AnswerPlan:
    question_type = classify_question(query)
    chunks = dedupe_chunks(reranked_chunks, retrieved_chunks)

    if question_type == "calc" and settings.deterministic_answers_enabled and settings.deterministic_calc_enabled:
        return _plan_calc_answer(query, chunks)
    if question_type == "list" and settings.deterministic_answers_enabled and settings.deterministic_list_enabled:
        return _plan_list_answer(query, chunks)

    return AnswerPlan(question_type=question_type)


def render_answer_plan(plan: AnswerPlan) -> str:
    lines = ["### Answer", ""]
    if plan.final_answer:
        lines.append(plan.final_answer.strip())
        lines.append("")

    if plan.steps:
        for idx, step in enumerate(plan.steps, start=1):
            lines.append(f"{idx}. {step}")
        lines.append("")
    elif plan.facts:
        for idx, fact in enumerate(plan.facts, start=1):
            lines.append(f"{idx}. {fact}")
        lines.append("")

    if plan.citation_chunks:
        lines.append(citation_line(plan.citation_chunks[0]))

    return "\n".join(line for line in lines if line is not None).strip()


def _plan_calc_answer(query: str, chunks: list[dict[str, Any]]) -> AnswerPlan:
    plan = AnswerPlan(question_type="calc")
    amounts = money_values(query)
    months = month_values(query)
    support_chunk = pick_calc_support(query, chunks)

    if len(amounts) < 2 or not months or support_chunk is None:
        return plan

    highest = max(amounts)
    lowest = min(amounts)
    months_count = months[0]
    installment = highest / months_count
    total = installment + lowest

    plan.steps = [
        f"**Past-due installment:** {format_money(highest)} / {months_count} = **{format_money(installment)}** per month.",
        f"**Current monthly bill:** **{format_money(lowest)}**.",
        f"**Total monthly payment:** {format_money(installment)} + {format_money(lowest)} = **{format_money(total)} per month**.",
    ]
    plan.final_answer = f"The customer will pay **{format_money(total)} per month** under the {months_count}-month DPA."
    plan.citation_chunks = [support_chunk]
    plan.deterministic_confidence = 0.95
    plan.high_confidence = plan.deterministic_confidence >= settings.deterministic_confidence_threshold
    plan.answer_path = "deterministic" if plan.high_confidence else "llm"
    return plan


def _plan_list_answer(query: str, chunks: list[dict[str, Any]]) -> AnswerPlan:
    normalized = " ".join((query or "").lower().split())
    if "reconnection" in normalized and "fee" in normalized:
        return _plan_reconnection_fees(chunks)

    if any(token in normalized for token in ("program", "programs", "financial assistance", "benefit", "application")):
        return _plan_program_overview(chunks)

    return AnswerPlan(question_type="list")


def _plan_reconnection_fees(chunks: list[dict[str, Any]]) -> AnswerPlan:
    plan = AnswerPlan(question_type="list")
    fee_items = extract_fee_items(chunks)
    if len(fee_items) < 2:
        return plan

    plan.final_answer = "The reconnection fees are listed below."
    plan.facts = [
        f"**{item['amount']}**: {item['label']}."
        for item in fee_items
    ]
    plan.citation_chunks = [fee_items[0]["source"]]
    plan.deterministic_confidence = 0.9 if len(fee_items) >= 3 else 0.8
    plan.high_confidence = plan.deterministic_confidence >= settings.deterministic_confidence_threshold
    plan.answer_path = "deterministic" if plan.high_confidence else "llm"
    return plan


def _plan_program_overview(chunks: list[dict[str, Any]]) -> AnswerPlan:
    plan = AnswerPlan(question_type="list")
    rows = extract_program_rows(chunks)
    if len(rows) < 4:
        return plan

    facts: list[str] = []
    primary_source = rows[0]["source"]
    for row in rows:
        detail_bits: list[str] = []
        if row["benefit"]:
            detail_bits.append(f"Typical benefits: {row['benefit']}.")
        if row["application"]:
            detail_bits.append(f"Application process: {row['application']}.")
        facts.append(f"**{row['name']}**: {' '.join(detail_bits).strip()}")

    plan.final_answer = "The main financial assistance programs and their typical benefits/application processes are listed below."
    plan.facts = facts
    plan.citation_chunks = [primary_source]
    plan.deterministic_confidence = 0.92
    plan.high_confidence = plan.deterministic_confidence >= settings.deterministic_confidence_threshold
    plan.answer_path = "deterministic" if plan.high_confidence else "llm"
    return plan


def _looks_like_calc(normalized_query: str) -> bool:
    if "how much" not in normalized_query and "monthly" not in normalized_query and "pay" not in normalized_query:
        return False
    return len(money_values(normalized_query)) >= 2 and bool(month_values(normalized_query))


def _looks_like_list(normalized_query: str) -> bool:
    list_tokens = (
        normalized_query.startswith("what are"),
        normalized_query.startswith("which are"),
        normalized_query.startswith("list"),
        " main " in f" {normalized_query} ",
        " all " in f" {normalized_query} ",
        "fees" in normalized_query,
        "programs" in normalized_query,
        "benefits and application" in normalized_query,
    )
    return any(list_tokens)
