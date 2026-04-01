from __future__ import annotations

from typing import Any, List


async def summarize_expenses_with_llm(
    expenses: List[dict],
    *,
    llm_service_cls: Any,
    generate_with_main_llm_async,
    build_stop_tokens,
) -> str:
    if not expenses:
        return ""

    llm_service = llm_service_cls.get_instance()
    if not llm_service.is_loaded():
        return ""

    expense_lines = [f"- {expense['merchant']}: {abs(expense['amount']):,.0f}원 ({expense['category']})" for expense in expenses]
    prompt = (
        "You are a financial assistant. Analyze the following payment records and provide a short, "
        "witty one-sentence analysis in Korean about the user's spending patterns or characteristics.\n"
        "Start directly with the result without any introductory phrases or greetings.\n\n"
        "[Payments]\n"
        + "\n".join(expense_lines)
    )
    result = await generate_with_main_llm_async(
        [{"role": "user", "content": prompt}],
        max_tokens=256,
        stop=build_stop_tokens(),
        enable_thinking=False,
    )
    return (result or "").strip()
