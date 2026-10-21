from __future__ import annotations

from research.models import Claim, Report, ResearchTask, SubQuestion


def coverage_summary(task: ResearchTask) -> dict:
    sub_questions = list(task.sub_questions.all())
    total = len(sub_questions)
    terminal = sum(
        1
        for item in sub_questions
        if item.status in {SubQuestion.STATUS_ANSWERED, SubQuestion.STATUS_INSUFFICIENT}
    )
    answered = sum(
        1 for item in sub_questions if item.status == SubQuestion.STATUS_ANSWERED
    )
    claims = list(task.claims.all())
    supported = sum(1 for item in claims if item.status == Claim.STATUS_SUPPORTED)
    return {
        "sub_questions": total,
        "terminal": terminal,
        "answered": answered,
        "insufficient": terminal - answered,
        "claims": len(claims),
        "supported_claims": supported,
        "evidence": task.evidence.count(),
        "sources": task.sources.count(),
    }


def recompute_progress(task: ResearchTask, has_report: bool | None = None) -> int:
    summary = coverage_summary(task)
    total = summary["sub_questions"]
    terminal = summary["terminal"]
    claims = summary["claims"]
    supported = summary["supported_claims"]

    if has_report is None:
        has_report = Report.objects.filter(task=task).exists()

    plan_score = 10 if total else 0
    sub_score = round(55 * terminal / total) if total else 0
    claim_score = round(20 * supported / claims) if claims else 0
    report_score = 15 if has_report else 0
    percent = min(100, plan_score + sub_score + claim_score + report_score)

    task.progress_pct = percent
    task.progress_detail = {
        "plan": plan_score,
        "sub_questions": sub_score,
        "claims": claim_score,
        "report": report_score,
        **summary,
    }
    task.save(update_fields=["progress_pct", "progress_detail", "updated_at"])
    return percent
