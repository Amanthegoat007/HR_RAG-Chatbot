import sys

sys.path.insert(0, "/home/ubuntu/HR_Chatbot/hr-rag-chatbot/services/rag-pipeline")


def test_calc_planner_returns_250_monthly():
    from app.answer_planner import plan_answer

    chunk = {
        "filename": "utility.pdf",
        "section": "Deferred Payment Agreement",
        "page_number": 2,
        "page_start": 2,
        "page_end": 2,
        "chunk_index": 3,
        "text": (
            "$600 past due with $150 current monthly bill. "
            "6-month DPA = $100 installment + $150 current = $250/month for 6 months."
        ),
        "contains_currency": True,
        "content_type": "paragraph",
    }

    plan = plan_answer(
        query="If a customer has a $600 past-due balance and a $150 monthly bill under a 6-month DPA, how much will they pay?",
        retrieved_chunks=[chunk],
        reranked_chunks=[chunk],
    )

    assert plan.question_type == "calc"
    assert plan.high_confidence is True
    assert "$250" in plan.final_answer
    assert len(plan.steps) == 3


def test_list_planner_extracts_all_reconnection_fees():
    from app.answer_planner import plan_answer

    chunk = {
        "filename": "utility.pdf",
        "section": "Reconnection Fees",
        "page_number": 6,
        "page_start": 6,
        "page_end": 6,
        "chunk_index": 7,
        "text": "$75 standard reconnection\n$150 same-day reconnection\n$200 after-hours reconnection",
        "contains_currency": True,
        "content_type": "list",
    }

    plan = plan_answer(
        query="What are the reconnection fees?",
        retrieved_chunks=[chunk],
        reranked_chunks=[chunk],
    )

    assert plan.question_type == "list"
    assert plan.high_confidence is True
    assert len(plan.facts) == 3
    assert any("$200" in fact for fact in plan.facts)


def test_list_planner_trims_reconnection_fee_paragraph_labels():
    from app.answer_planner import plan_answer

    chunk = {
        "filename": "utility.pdf",
        "section": "Reconnection Fees",
        "page_number": 6,
        "page_start": 6,
        "page_end": 6,
        "chunk_index": 7,
        "text": (
            "Pay reconnection fee: $75 standard reconnection (next business day), "
            "$150 same-day reconnection (if requested before 2PM), "
            "$200 after-hours reconnection (weekends/holidays), "
            "(3) Call Customer Care to schedule reconnection once payment received."
        ),
        "contains_currency": True,
        "content_type": "paragraph",
    }

    plan = plan_answer(
        query="What are the reconnection fees?",
        retrieved_chunks=[chunk],
        reranked_chunks=[chunk],
    )

    assert plan.high_confidence is True
    assert any("after-hours reconnection (weekends/holidays)." in fact for fact in plan.facts)
    assert not any("Call Customer Care" in fact for fact in plan.facts)


def test_list_planner_extracts_program_table_rows():
    from app.answer_planner import plan_answer

    table_chunk = {
        "filename": "utility.pdf",
        "section": "Financial Assistance Overview",
        "page_number": 1,
        "page_start": 1,
        "page_end": 1,
        "chunk_index": 0,
        "text": "\n".join([
            "| Program | Typical Benefit | Application Process |",
            "| --- | --- | --- |",
            "| Deferred Payment Agreement (DPA) | 3-6 month installment plan | Apply online or by phone |",
            "| Extended Payment Plan (EPP) | 6-12 month interest-free plan | Apply by phone |",
            "| Budget Billing | Fixed monthly average | Enroll online |",
            "| LIHEAP | Seasonal bill assistance | Apply through community agency |",
            "| UtilityPro Care Fund | $300-$500 emergency grant | Call customer care |",
            "| Weatherization | Home efficiency support | Referral-based application |",
            "| Medical Payment Protection | Delay shutoff for medical need | Submit medical certification |",
        ]),
        "content_type": "table",
    }

    plan = plan_answer(
        query="What are the typical benefits and application processes for the main financial assistance programs?",
        retrieved_chunks=[table_chunk],
        reranked_chunks=[table_chunk],
    )

    assert plan.question_type == "list"
    assert plan.high_confidence is True
    assert len(plan.facts) == 7
    assert any("UtilityPro Care Fund" in fact for fact in plan.facts)
    assert any("Medical Payment Protection" in fact for fact in plan.facts)
