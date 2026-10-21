from research.models import SubQuestion
from research.tools.base import ToolContext, ToolResult


def finish_research(
    ctx: ToolContext, summary: str, unresolved_question_ids: list[int] | None = None
) -> ToolResult:
    unresolved_question_ids = unresolved_question_ids or []
    sub_questions = list(ctx.task.sub_questions.all())
    if not sub_questions:
        return ToolResult(
            ok=False,
            error_code="no_plan",
            message="还没有研究计划，不能结束",
            hint="先补充子问题并收集证据。",
        )

    valid_ids = {item.id for item in sub_questions}
    unresolved = set(unresolved_question_ids) & valid_ids
    if unresolved:
        SubQuestion.objects.filter(pk__in=unresolved).update(
            status=SubQuestion.STATUS_INSUFFICIENT
        )
        for item in sub_questions:
            if item.id in unresolved:
                item.status = SubQuestion.STATUS_INSUFFICIENT

    remaining = [
        item
        for item in sub_questions
        if item.status not in {SubQuestion.STATUS_ANSWERED, SubQuestion.STATUS_INSUFFICIENT}
    ]
    if remaining:
        return ToolResult(
            ok=False,
            error_code="coverage_incomplete",
            message=f"还有 {len(remaining)} 个子问题未处理",
            hint="逐个调用 answer_subquestion 标记 answered 或 insufficient，再结束。",
            data={
                "unresolved": [
                    {"sub_question_id": item.id, "question": item.question}
                    for item in remaining
                ]
            },
        )

    answered = sum(1 for item in sub_questions if item.status == SubQuestion.STATUS_ANSWERED)
    return ToolResult(
        ok=True,
        data={
            "summary": summary,
            "answered": answered,
            "insufficient": len(sub_questions) - answered,
            "total": len(sub_questions),
        },
        message="研究可以结束",
        hint="接下来生成报告。",
    )
