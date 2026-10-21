from __future__ import annotations

import hashlib
import re

from bookmarks.models import Bookmark
from evaluation.services.bm25 import BM25Index, Passage
from evaluation.services.text import split_passages
from research.agent.context import ContextBuilder
from research.models import Evidence, ResearchTask
from research.services.report import persist_report_content
from research.services.runner import claim_task, release_lease
from research.services.sources import get_or_create_bookmark_source
from research.services.usage import record_usage


def _quote_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_index(owner) -> BM25Index:
    bookmarks = (
        Bookmark.objects.filter(
            owner=owner, is_archived=False, content__status="ready"
        )
        .select_related("content")
        .order_by("id")
    )
    passages: list[Passage] = []
    for bookmark in bookmarks:
        text = bookmark.content.text or ""
        for block in split_passages(text):
            passages.append(
                Passage(
                    bookmark_id=bookmark.id,
                    url=bookmark.url,
                    title=bookmark.resolved_title,
                    text=block,
                )
            )
    return BM25Index(passages)


def run_baseline(task: ResearchTask, llm, top_k: int = 5) -> ResearchTask:
    claimed = claim_task(task.pk)
    if claimed is None:
        raise RuntimeError(f"任务 {task.pk} 无法进入运行状态")
    task = claimed
    try:
        index = build_index(task.owner)
        hits = index.search(task.question, limit=top_k)

        evidences: list[Evidence] = []
        for hit in hits:
            bookmark = Bookmark.objects.filter(pk=hit.bookmark_id).first()
            if bookmark is None:
                continue
            source = get_or_create_bookmark_source(task, bookmark)
            evidence, _ = Evidence.objects.get_or_create(
                task=task,
                source=source,
                quote_hash=_quote_hash(hit.text),
                defaults={"quote": hit.text},
            )
            evidences.append(evidence)

        task.plan_raw = {
            "strategy": "bm25",
            "top_k": top_k,
            "hits": [
                {
                    "bookmark_id": hit.bookmark_id,
                    "url": hit.url,
                    "score": round(hit.score, 4),
                }
                for hit in hits
            ],
        }
        task.phase = ResearchTask.PHASE_REPORTING
        task.save(update_fields=["plan_raw", "phase", "updated_at"])

        if not evidences:
            content = "## 结论\n本地语料中没有检索到相关资料，无法回答该问题。"
            persist_report_content(task, content, model="", reason="baseline_empty")
        else:
            messages = ContextBuilder(task).build_baseline_messages(evidences)
            response = llm.chat(messages, temperature=0, max_tokens=2000)
            record_usage(task, "baseline", response)
            persist_report_content(
                task, response.content, model=response.model, reason="baseline"
            )

        task.refresh_from_db()
        task.completion_reason = ResearchTask.COMPLETION_MODEL_FINISH
        task.is_partial = False
        task.progress_pct = 100
        task.save(
            update_fields=[
                "completion_reason",
                "is_partial",
                "progress_pct",
                "updated_at",
            ]
        )
        task.transition(ResearchTask.STATUS_COMPLETED, reason="baseline 完成")
        return task
    except Exception:
        task.refresh_from_db()
        if task.status == ResearchTask.STATUS_RUNNING:
            task.transition(ResearchTask.STATUS_FAILED, reason="baseline 失败")
        raise
    finally:
        release_lease(task)
