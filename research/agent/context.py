from __future__ import annotations

import json

from django.utils import timezone

from research.agent.prompts import (
    AGENT_SYSTEM,
    BASELINE_SYSTEM,
    REPORT_SYSTEM,
    baseline_user_prompt,
    report_user_prompt,
)
from research.models import Evidence, ResearchTask, TaskEvent

MAX_INPUT_TOKENS_ESTIMATE = 30000


def estimate_tokens(text: str) -> int:
    cjk = sum(1 for char in text if "一" <= char <= "鿿")
    other = len(text) - cjk
    return int(cjk + other / 3.5)


def clip(text: str, length: int) -> str:
    text = (text or "").strip()
    if len(text) <= length:
        return text
    return text[:length] + "…"


def _json_summary(value, length: int = 160) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False)
    except TypeError:
        text = str(value)
    return clip(text, length)


def _select_evidence(task: ResearchTask, limit: int = 24) -> list[Evidence]:
    queryset = (
        Evidence.objects.filter(task=task)
        .select_related("source", "sub_question")
        .order_by("-id")
    )
    evidence = list(queryset[: limit * 2])
    per_sub: dict[int, int] = {}
    selected: list[Evidence] = []
    for item in evidence:
        key = item.sub_question_id or 0
        if key and per_sub.get(key, 0) >= 2:
            continue
        per_sub[key] = per_sub.get(key, 0) + 1
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _state_text(task: ResearchTask, compact: bool = False) -> str:
    sub_questions = list(task.sub_questions.all())
    claims = list(task.claims.all()[:24])
    evidence = _select_evidence(task, 12 if compact else 24)
    steps = list(task.steps.order_by("-step_no")[:4 if compact else 6])
    steps.reverse()

    lines: list[str] = [f"研究问题：{task.question}", f"阶段：{task.phase}"]

    lines.append("子问题：")
    if not sub_questions:
        lines.append("- （尚未生成计划）")
    for item in sub_questions:
        answer = f"，答案：{clip(item.answer, 120)}" if item.answer else ""
        lines.append(f"- [S{item.id}] {item.question}（状态={item.status}{answer}）")

    lines.append("主张：")
    if not claims:
        lines.append("- （暂无）")
    for claim in claims:
        evidence_ids = [
            link.evidence_id for link in claim.links.all() if link.relation == "supports"
        ]
        lines.append(
            f"- [C{claim.id}] {clip(claim.text, 160)}（置信度={claim.confidence:.2f}，"
            f"状态={claim.status}，证据={evidence_ids or '无'}）"
        )

    lines.append("关键证据：")
    if not evidence:
        lines.append("- （暂无）")
    quote_len = 120 if compact else 220
    for item in evidence:
        lines.append(
            f"- [e{item.id}] 来源={item.source_id}《{clip(item.source.title or item.source.url, 60)}》"
            f" \"{clip(item.quote, quote_len)}\""
        )

    lines.append("最近步骤：")
    if not steps:
        lines.append("- （暂无）")
    for step in steps:
        if step.step_type == "tool_result":
            status = "命中缓存" if step.status == "reused" else step.status
            lines.append(
                f"- #{step.step_no} {step.tool_name} -> {status} "
                f"{_json_summary(step.output, 140)}"
            )
        elif step.step_type == "thought":
            lines.append(f"- #{step.step_no} 模型思考：{clip(step.output.get('content', ''), 120)}")
        else:
            lines.append(f"- #{step.step_no} {step.step_type} {step.error}")

    hint_events = TaskEvent.objects.filter(
        task=task, kind__in=["recovery_hint", "recovery", "tool_error"]
    ).order_by("-id")[:2]
    if hint_events:
        lines.append("恢复提示：")
        for event in reversed(hint_events):
            lines.append(f"- {clip(event.message, 240)}")

    turns_used = task.steps.filter(step_type="thought").count()
    remaining_steps = max(0, task.max_steps - turns_used)
    remaining_tokens = max(0, task.budget_tokens - task.tokens_used)
    remaining_seconds = 0
    if task.deadline_at:
        remaining_seconds = max(0, int((task.deadline_at - timezone.now()).total_seconds()))
    lines.append(
        f"剩余预算：steps {remaining_steps}/{task.max_steps}，"
        f"tokens {remaining_tokens}/{task.budget_tokens}，"
        f"time {remaining_seconds}s"
    )
    return "\n".join(lines)


class ContextBuilder:
    def __init__(self, task: ResearchTask):
        self.task = task

    def build(self) -> list[dict]:
        task = self.task
        state = _state_text(task)
        if estimate_tokens(state) > MAX_INPUT_TOKENS_ESTIMATE:
            state = _state_text(task, compact=True)
        return [
            {"role": "system", "content": AGENT_SYSTEM},
            {"role": "system", "content": f"<structured_state>\n{state}\n</structured_state>"},
            {
                "role": "user",
                "content": "请选择下一步工具。证据足够且所有子问题已处理时，调用 finish_research。",
            },
        ]

    def build_report_state(self) -> tuple[list[dict], list[Evidence]]:
        task = self.task
        sub_questions = list(task.sub_questions.all())
        claims = list(task.claims.prefetch_related("links").all()[:40])
        evidence = _select_evidence(task, 60)

        lines = [f"研究问题：{task.question}", "", "子问题与状态："]
        for item in sub_questions:
            lines.append(
                f"- [S{item.id}] {item.question}\n  状态={item.status}\n"
                f"  答案={clip(item.answer, 500) or '无'}"
            )

        lines.append("")
        lines.append("研究主张：")
        for claim in claims:
            evidence_ids = [
                link.evidence_id for link in claim.links.all() if link.relation == "supports"
            ]
            lines.append(
                f"- [C{claim.id}] {claim.text}（状态={claim.status}，置信度={claim.confidence:.2f}，"
                f"证据={evidence_ids or '无'}）"
            )

        lines.append("")
        lines.append("可用证据（只能引用这些 ID）：")
        for item in evidence:
            lines.append(
                f"- [e{item.id}] 来源：{item.source.title or item.source.url}"
                f"（{item.source.url}）\n  原文：{clip(item.quote, 500)}"
            )

        messages = [
            {"role": "system", "content": REPORT_SYSTEM},
            {"role": "user", "content": report_user_prompt("\n".join(lines))},
        ]
        return messages, evidence

    def build_baseline_messages(self, evidences: list[Evidence]) -> list[dict]:
        lines = []
        for item in evidences:
            lines.append(
                f"[e{item.id}] {item.source.title or item.source.url}\n"
                f"来源：{item.source.url}\n原文：{clip(item.quote, 700)}"
            )
        return [
            {"role": "system", "content": BASELINE_SYSTEM},
            {
                "role": "user",
                "content": baseline_user_prompt(self.task.question, "\n\n".join(lines)),
            },
        ]
