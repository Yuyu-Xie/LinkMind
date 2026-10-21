from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from bookmarks.models import Bookmark
from research.agent.fake_client import FakeLLMClient, tool_call, tool_response
from research.models import (
    Claim,
    ClaimEvidence,
    Evidence,
    ResearchTask,
    Source,
    SubQuestion,
    TaskEvent,
)
from research.services.runner import run_task

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def owner():
    return get_user_model().objects.create_user(username="owner", password="x")


@pytest.fixture
def task(owner):
    return ResearchTask.objects.create(owner=owner, question="测试问题")


def _source(
    task,
    text="PostgreSQL 的默认索引类型是 B-tree。Hash 索引只支持等值比较。",
):
    bookmark = Bookmark.objects.create(
        owner=task.owner, url=f"https://example.com/{task.pk}", title="资料"
    )
    return Source.objects.create(
        task=task,
        bookmark=bookmark,
        source_type=Source.TYPE_BOOKMARK,
        source_key=f"bookmark:{bookmark.pk}",
        url=bookmark.url,
        title="资料",
        content_text=text,
        fetch_status=Source.FETCH_READY,
    )


def test_legal_transition_records_event(task):
    task.transition(ResearchTask.STATUS_RUNNING, reason="开始")
    task.transition(ResearchTask.STATUS_COMPLETED, reason="完成")

    task.refresh_from_db()
    assert task.status == ResearchTask.STATUS_COMPLETED
    assert task.finished_at is not None
    assert task.phase == ResearchTask.PHASE_DONE
    assert TaskEvent.objects.filter(task=task, kind="status").count() == 2


def test_illegal_transition_raises(task):
    with pytest.raises(ValueError):
        task.transition(ResearchTask.STATUS_COMPLETED)


def test_terminal_task_cannot_restart(task):
    task.transition(ResearchTask.STATUS_RUNNING)
    task.transition(ResearchTask.STATUS_COMPLETED)
    with pytest.raises(ValueError):
        task.transition(ResearchTask.STATUS_PENDING)


def test_evidence_quote_must_exist_in_source(task):
    source = _source(task)
    evidence = Evidence.objects.create(task=task, source=source, quote="默认索引类型是 B-tree")
    assert evidence.char_start == 12
    assert evidence.locator["strategy"] == "normalized_substring"

    with pytest.raises(ValidationError):
        Evidence.objects.create(task=task, source=source, quote="这段文字不在正文中")


def test_claim_status_follows_evidence_links(task):
    source = _source(task)
    evidence = Evidence.objects.create(task=task, source=source, quote="默认索引类型是 B-tree")
    claim = Claim.objects.create(task=task, text="B-tree 是默认索引")

    assert claim.status == Claim.STATUS_PROPOSED
    ClaimEvidence.objects.create(claim=claim, evidence=evidence)
    claim.refresh_status()
    assert claim.status == Claim.STATUS_SUPPORTED

    refuting = Evidence.objects.create(
        task=task, source=source, quote="Hash 索引只支持等值比较"
    )
    ClaimEvidence.objects.create(
        claim=claim, evidence=refuting, relation=ClaimEvidence.REL_REFUTES
    )
    claim.refresh_status()
    assert claim.status == Claim.STATUS_CONTRADICTED


def test_sub_questions_are_unique_per_order(task):
    SubQuestion.objects.create(task=task, order=1, question="A")
    with pytest.raises(IntegrityError):
        SubQuestion.objects.create(task=task, order=1, question="B")


def test_cancel_request_stops_at_next_safe_point(task):
    def handler(messages, tools):
        return tool_response(tool_call("search_bookmarks", query="PostgreSQL"))

    task.request_cancel()
    result = run_task(task.pk, llm=FakeLLMClient(handler=handler), retry_enabled=False)

    task.refresh_from_db()
    assert result == ResearchTask.STATUS_CANCELED
    assert task.status == ResearchTask.STATUS_CANCELED
    assert task.is_partial is True


def test_expired_deadline_marks_timed_out(task):
    task.deadline_at = timezone.now() - timedelta(seconds=1)
    task.save(update_fields=["deadline_at"])

    def handler(messages, tools):
        return tool_response(tool_call("search_bookmarks", query="PostgreSQL"))

    result = run_task(task.pk, llm=FakeLLMClient(handler=handler), retry_enabled=False)

    task.refresh_from_db()
    assert result == ResearchTask.STATUS_TIMED_OUT
    assert task.status == ResearchTask.STATUS_TIMED_OUT
    assert task.completion_reason == ResearchTask.COMPLETION_DEADLINE
