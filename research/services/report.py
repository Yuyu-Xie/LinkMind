from __future__ import annotations

import logging
import re

from django.utils import timezone

from research.agent.context import ContextBuilder
from research.models import Evidence, Report, ResearchTask
from research.services.usage import record_usage

logger = logging.getLogger("research")

CITATION_RE = re.compile(r"\[e:(\d+)\]")


def _fallback_markdown(task: ResearchTask, reason: str) -> str:
    lines = ["## 结论", ""]
    lines.append("本次研究未能生成模型报告，以下内容来自已收集的结构化结果。")
    lines.append("")
    lines.append("## 分问题发现")
    for item in task.sub_questions.all():
        lines.append(f"### {item.question}")
        lines.append(item.answer or f"状态：{item.status}，没有形成结论。")
        lines.append("")
    lines.append("## 争议与局限")
    lines.append(f"研究结束原因：{reason or '未说明'}。")
    lines.append("")
    lines.append("## 参考证据")
    for evidence in task.evidence.select_related("source").all()[:30]:
        title = evidence.source.title or evidence.source.url
        lines.append(f"- [e:{evidence.id}] {title}：{evidence.quote[:200]}")
    return "\n".join(lines)


def _extract_citations(content: str, allowed_ids: set[int]) -> tuple[list[int], list[int]]:
    found = [int(match) for match in CITATION_RE.findall(content)]
    valid = [item for item in found if item in allowed_ids]
    invalid = [item for item in found if item not in allowed_ids]
    return valid, invalid


def _build_citations(valid_ids: list[int], evidence_map: dict[int, Evidence]) -> list[dict]:
    seen: set[int] = set()
    citations = []
    for evidence_id in valid_ids:
        if evidence_id in seen:
            continue
        seen.add(evidence_id)
        evidence = evidence_map.get(evidence_id)
        if not evidence:
            continue
        citations.append(
            {
                "evidence_id": evidence.id,
                "source_id": evidence.source_id,
                "url": evidence.source.url,
                "title": evidence.source.title or evidence.source.url,
                "quote": evidence.quote,
            }
        )
    return citations


def persist_report_content(
    task: ResearchTask, content: str, model: str = "", reason: str = ""
) -> Report:
    """Validate citations and persist an externally produced report body."""
    evidence = list(task.evidence.select_related("source"))
    evidence_map = {item.id: item for item in evidence}
    allowed_ids = set(evidence_map)
    content = content.strip() or _fallback_markdown(task, reason)

    valid, invalid = _extract_citations(content, allowed_ids)
    for bad_id in set(invalid):
        content = content.replace(f"[e:{bad_id}]", "")

    citations = _build_citations(valid, evidence_map)
    validation = {
        "model_report": bool(model),
        "invalid_citations": invalid,
        "citation_count": len(citations),
        "evidence_count": len(evidence),
        "stripped": bool(invalid),
    }
    previous = Report.objects.filter(task=task).first()
    version = (previous.version + 1) if previous else 1
    report, _ = Report.objects.update_or_create(
        task=task,
        defaults={
            "version": version,
            "content_md": content,
            "citations": citations,
            "validation": validation,
            "model": model,
            "generated_at": timezone.now(),
        },
    )
    task.phase = ResearchTask.PHASE_REPORTING
    task.save(update_fields=["phase", "updated_at"])
    return report


def generate_report(task: ResearchTask, llm=None, reason: str = "") -> Report:
    task.phase = ResearchTask.PHASE_REPORTING
    task.save(update_fields=["phase", "updated_at"])

    evidence = list(task.evidence.select_related("source"))
    evidence_map = {item.id: item for item in evidence}
    allowed_ids = set(evidence_map)

    content = ""
    validation: dict = {"model_report": False, "invalid_citations": []}
    model_name = ""

    if llm is not None and evidence:
        messages, _ = ContextBuilder(task).build_report_state()
        try:
            response = llm.chat(messages, temperature=0, max_tokens=3000)
            record_usage(task, "report", response)
            content = response.content.strip()
            model_name = response.model
            validation["model_report"] = bool(content)
        except Exception as exc:  # noqa: BLE001
            logger.exception("report generation failed")
            validation["error"] = str(exc)[:500]

    if content:
        valid, invalid = _extract_citations(content, allowed_ids)
        if invalid:
            validation["invalid_citations"] = invalid
            repair_messages = messages + [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "你引用了不存在的证据 ID："
                        + ", ".join(str(item) for item in invalid)
                        + "。请只使用给定证据 ID 重写报告，直接输出正文，不要解释。"
                    ),
                },
            ]
            try:
                repaired = llm.chat(repair_messages, temperature=0, max_tokens=3000)
                record_usage(task, "report", repaired)
                repaired_content = repaired.content.strip()
                if repaired_content:
                    repaired_valid, repaired_invalid = _extract_citations(
                        repaired_content, allowed_ids
                    )
                    if len(repaired_invalid) < len(invalid):
                        content = repaired_content
                        valid, invalid = repaired_valid, repaired_invalid
                        validation["invalid_citations"] = invalid
            except Exception:  # noqa: BLE001
                logger.exception("citation repair failed")

        if invalid:
            for bad_id in set(invalid):
                content = content.replace(f"[e:{bad_id}]", "")
            validation["stripped"] = True
    else:
        content = _fallback_markdown(task, reason)

    valid, _ = _extract_citations(content, allowed_ids)
    citations = _build_citations(valid, evidence_map)
    validation["citation_count"] = len(citations)
    validation["evidence_count"] = len(evidence)

    previous = Report.objects.filter(task=task).first()
    version = (previous.version + 1) if previous else 1
    report, _ = Report.objects.update_or_create(
        task=task,
        defaults={
            "version": version,
            "content_md": content,
            "citations": citations,
            "validation": validation,
            "model": model_name,
            "generated_at": timezone.now(),
        },
    )
    return report
