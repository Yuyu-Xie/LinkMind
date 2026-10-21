from __future__ import annotations

import difflib
import hashlib
import re

from django.core.exceptions import ValidationError

from research.models import Evidence, Source, SubQuestion
from research.tools.base import ToolContext, ToolError, ToolResult


def _quote_hash(quote: str) -> str:
    normalized = re.sub(r"\s+", " ", quote).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _suggest_quotes(content: str, quote: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n+", content) if len(p.strip()) >= 10]
    return [
        item[:300]
        for item in difflib.get_close_matches(quote, paragraphs, n=3, cutoff=0.25)
    ]


def extract_evidence(
    ctx: ToolContext,
    source_id: int,
    quote: str,
    sub_question_id: int | None = None,
) -> ToolResult:
    source = Source.objects.filter(task=ctx.task, pk=source_id).first()
    if source is None:
        raise ToolError("source_not_found", f"来源 {source_id} 不属于当前任务")
    if not source.content_text:
        raise ToolError(
            "source_not_read",
            "该来源还没有正文",
            "先调用 read_document(source_id) 读取正文，再从正文中摘取 quote。",
        )

    sub_question = None
    if sub_question_id is not None:
        sub_question = SubQuestion.objects.filter(
            task=ctx.task, pk=sub_question_id
        ).first()
        if sub_question is None:
            raise ToolError("sub_question_not_found", f"子问题 {sub_question_id} 不存在")

    existing = Evidence.objects.filter(
        source=source, quote_hash=_quote_hash(quote)
    ).first()
    if existing:
        return ToolResult(
            ok=True,
            data={"evidence_id": existing.id, "source_id": source.id, "quote": existing.quote},
            message="该证据已存在，直接复用",
            hint="用 add_claim 绑定这个 evidence_id。",
        )

    try:
        evidence = Evidence.objects.create(
            task=ctx.task,
            source=source,
            sub_question=sub_question,
            quote=quote,
        )
    except ValidationError:
        suggestions = _suggest_quotes(source.content_text, re.sub(r"\s+", " ", quote).strip())
        return ToolResult(
            ok=False,
            error_code="quote_not_found",
            message="quote 不是来源正文中的连续片段",
            hint="从 read_document 返回的 text 中逐字复制一段连续文字，不要改写。",
            data={"suggestions": suggestions},
        )

    if sub_question and sub_question.status == SubQuestion.STATUS_PENDING:
        sub_question.status = SubQuestion.STATUS_IN_PROGRESS
        sub_question.save(update_fields=["status", "updated_at"])

    return ToolResult(
        ok=True,
        data={
            "evidence_id": evidence.id,
            "source_id": source.id,
            "quote": evidence.quote,
            "char_start": evidence.char_start,
            "char_end": evidence.char_end,
        },
        message="证据已记录",
        hint="用 add_claim 把这个 evidence_id 绑定到主张。",
    )
