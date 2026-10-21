from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from bookmarks.models import Bookmark, DocumentContent
from research.agent.fake_client import FakeLLMClient, text_response, tool_call, tool_response
from research.agent.prompts import AGENT_SYSTEM, PLAN_SYSTEM, REPORT_SYSTEM
from research.models import Claim, Evidence, ResearchTask, SubQuestion
from research.services.runner import run_task
from research.tools.registry import execute_tool

pytestmark = pytest.mark.django_db(transaction=True)

DOCUMENT = (
    "PostgreSQL 提供多种索引类型。B-tree 适用于等值和范围查询，"
    "是默认索引类型。GIN 适合数组、JSONB 和全文检索。"
)


@pytest.fixture
def task_with_bookmark():
    user = get_user_model().objects.create_user(
        username="researcher", password="pass12345"
    )
    bookmark = Bookmark.objects.create(
        owner=user,
        url="https://example.com/postgres-index",
        title="PostgreSQL 索引类型",
        description="介绍 B-tree、GIN 与 GiST",
    )
    DocumentContent.objects.create(
        bookmark=bookmark,
        status=DocumentContent.STATUS_READY,
        text=DOCUMENT,
        content_hash="hash",
    )
    task = ResearchTask.objects.create(
        owner=user,
        question="PostgreSQL 的索引类型分别适合什么场景？",
        options={"offline": True},
        max_steps=12,
    )
    return task


def _scripted_handler(task):
    def handler(messages, tools):
        system = messages[0]["content"]
        if system == PLAN_SYSTEM:
            return text_response(
                json.dumps(
                    {
                        "sub_questions": [
                            "B-tree 索引适合哪些查询？",
                            "GIN 索引适合什么数据类型？",
                        ]
                    },
                    ensure_ascii=False,
                )
            )
        if system == REPORT_SYSTEM:
            evidence = Evidence.objects.filter(task=task).first()
            return text_response(
                f"## 结论\nB-tree 适合等值与范围查询 [e:{evidence.id}]。\n\n"
                f"## 参考证据\n- [e:{evidence.id}]"
            )

        assert system == AGENT_SYSTEM
        source = task.sources.first()
        evidence = task.evidence.first()
        sub_questions = list(task.sub_questions.order_by("order"))

        if source is None:
            return tool_response(tool_call("search_bookmarks", query="PostgreSQL 索引"))
        if not source.content_text:
            return tool_response(tool_call("read_document", source_id=source.id))
        if evidence is None:
            return tool_response(
                tool_call(
                    "extract_evidence",
                    source_id=source.id,
                    quote="B-tree 适用于等值和范围查询，是默认索引类型。",
                    sub_question_id=sub_questions[0].id,
                )
            )
        if not Claim.objects.filter(task=task).exists():
            return tool_response(
                tool_call(
                    "add_claim",
                    text="B-tree 是 PostgreSQL 的默认索引类型。",
                    evidence_ids=[evidence.id],
                    sub_question_id=sub_questions[0].id,
                )
            )
        pending = [
            item
            for item in sub_questions
            if item.status
            not in {SubQuestion.STATUS_ANSWERED, SubQuestion.STATUS_INSUFFICIENT}
        ]
        if pending:
            return tool_response(
                tool_call(
                    "answer_subquestion",
                    sub_question_id=pending[0].id,
                    status="answered",
                    answer="B-tree 适合等值和范围查询。",
                )
            )
        return tool_response(
            tool_call(
                "finish_research",
                summary="B-tree 适合等值和范围查询，GIN 适合数组与 JSONB。",
            )
        )

    return handler


def test_agent_loop_finishes_with_evidence_and_report(task_with_bookmark):
    task = task_with_bookmark
    fake = FakeLLMClient(handler=_scripted_handler(task))

    result = run_task(task.pk, llm=fake, retry_enabled=False)

    task.refresh_from_db()
    assert result == ResearchTask.STATUS_COMPLETED, task.error
    assert task.status == ResearchTask.STATUS_COMPLETED
    assert task.completion_reason == ResearchTask.COMPLETION_MODEL_FINISH
    assert task.is_partial is False
    assert task.progress_pct == 100
    assert task.tokens_used > 0

    assert task.sub_questions.count() == 2
    assert task.sub_questions.filter(status=SubQuestion.STATUS_ANSWERED).count() == 2
    assert task.evidence.count() == 1

    claim = task.claims.get()
    assert claim.status == Claim.STATUS_SUPPORTED

    report = task.report
    evidence = task.evidence.get()
    assert f"[e:{evidence.id}]" in report.content_md
    assert report.citations[0]["evidence_id"] == evidence.id
    assert report.validation["citation_count"] == 1

    tool_names = set(task.steps.values_list("tool_name", flat=True))
    assert {
        "search_bookmarks",
        "extract_evidence",
        "add_claim",
        "answer_subquestion",
        "finish_research",
    } <= tool_names


def test_duplicate_read_is_served_from_cache(task_with_bookmark):
    task = task_with_bookmark
    from research.services.sources import get_or_create_bookmark_source

    bookmark = Bookmark.objects.get(owner=task.owner)
    source = get_or_create_bookmark_source(task, bookmark)

    first, _ = execute_tool(task, "read_document", {"source_id": source.id})
    second, _ = execute_tool(task, "read_document", {"source_id": source.id})

    assert first.ok is True
    assert second.ok is True
    assert second.reused is True
    assert second.data["text"] == first.data["text"]


def test_invalid_tool_args_return_structured_error(task_with_bookmark):
    task = task_with_bookmark
    result, _ = execute_tool(task, "read_document", {"source_id": "abc"})

    assert result.ok is False
    assert result.error_code == "invalid_args"
    assert result.hint


def test_budget_exhaustion_produces_partial_report(task_with_bookmark):
    task = task_with_bookmark
    task.budget_tokens = 1
    task.save(update_fields=["budget_tokens"])
    fake = FakeLLMClient(handler=_scripted_handler(task))

    run_task(task.pk, llm=fake, retry_enabled=False)

    task.refresh_from_db()
    assert task.status == ResearchTask.STATUS_COMPLETED
    assert task.is_partial is True
    assert task.completion_reason == ResearchTask.COMPLETION_BUDGET
    assert task.report.content_md
