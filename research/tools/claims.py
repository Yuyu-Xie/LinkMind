from __future__ import annotations

from django.db import transaction

from research.models import Claim, ClaimEvidence, Evidence, SubQuestion, normalized_hash
from research.tools.base import ToolContext, ToolError, ToolResult


def _get_sub_question(ctx: ToolContext, sub_question_id: int | None):
    if sub_question_id is None:
        return None
    sub_question = SubQuestion.objects.filter(
        task=ctx.task, pk=sub_question_id
    ).first()
    if sub_question is None:
        raise ToolError("sub_question_not_found", f"子问题 {sub_question_id} 不存在")
    return sub_question


def add_claim(
    ctx: ToolContext,
    text: str,
    evidence_ids: list[int] | None = None,
    sub_question_id: int | None = None,
    confidence: float = 0.6,
) -> ToolResult:
    evidence_ids = evidence_ids or []
    evidence = list(Evidence.objects.filter(task=ctx.task, id__in=evidence_ids))
    found_ids = {item.id for item in evidence}
    missing = sorted(set(evidence_ids) - found_ids)
    if missing:
        raise ToolError(
            "evidence_not_found",
            f"证据不存在或不属于当前任务: {missing}",
            "先用 extract_evidence 创建证据，再引用它的 evidence_id。",
        )

    sub_question = _get_sub_question(ctx, sub_question_id)
    if not evidence:
        confidence = min(confidence, 0.35)

    with transaction.atomic():
        claim, created = Claim.objects.get_or_create(
            task=ctx.task,
            normalized_hash=normalized_hash(text),
            defaults={
                "text": text,
                "sub_question": sub_question,
                "confidence": confidence,
            },
        )
        if not created:
            claim.confidence = max(claim.confidence, confidence)
            if sub_question and not claim.sub_question_id:
                claim.sub_question = sub_question
            claim.save(update_fields=["confidence", "sub_question", "updated_at"])

        ClaimEvidence.objects.bulk_create(
            [
                ClaimEvidence(claim=claim, evidence=item, relation=ClaimEvidence.REL_SUPPORTS)
                for item in evidence
            ],
            ignore_conflicts=True,
        )
        claim.refresh_status()

    if sub_question and sub_question.status == SubQuestion.STATUS_PENDING:
        sub_question.status = SubQuestion.STATUS_IN_PROGRESS
        sub_question.save(update_fields=["status", "updated_at"])

    return ToolResult(
        ok=True,
        data={
            "claim_id": claim.id,
            "status": claim.status,
            "confidence": claim.confidence,
            "evidence_ids": sorted(found_ids),
        },
        message="主张已记录" if created else "主张已合并",
        hint="继续补充其他子问题的证据，完成后调用 answer_subquestion。",
    )


def answer_subquestion(
    ctx: ToolContext, sub_question_id: int, status: str, answer: str = ""
) -> ToolResult:
    sub_question = _get_sub_question(ctx, sub_question_id)
    if status not in {SubQuestion.STATUS_ANSWERED, SubQuestion.STATUS_INSUFFICIENT}:
        raise ToolError("invalid_status", "status 只能是 answered 或 insufficient")
    if status == SubQuestion.STATUS_ANSWERED and not answer.strip():
        raise ToolError(
            "answer_required",
            "标记 answered 时必须提供 answer",
            "写一句基于证据的结论，或改为 insufficient。",
        )

    sub_question.status = status
    sub_question.answer = answer.strip()
    sub_question.save(update_fields=["status", "answer", "updated_at"])

    return ToolResult(
        ok=True,
        data={
            "sub_question_id": sub_question.id,
            "status": sub_question.status,
            "answer": sub_question.answer,
        },
        message="子问题状态已更新",
        hint="所有子问题都处理完后调用 finish_research。",
    )
