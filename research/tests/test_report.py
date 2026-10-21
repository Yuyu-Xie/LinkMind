from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from bookmarks.models import Bookmark
from research.models import Evidence, ResearchTask, Source
from research.services.report import generate_report, persist_report_content

pytestmark = pytest.mark.django_db


@pytest.fixture
def task():
    user = get_user_model().objects.create_user(username="report", password="x")
    task = ResearchTask.objects.create(owner=user, question="问题")
    bookmark = Bookmark.objects.create(owner=user, url="https://a.test/1", title="资料")
    source = Source.objects.create(
        task=task,
        bookmark=bookmark,
        source_type=Source.TYPE_BOOKMARK,
        source_key="bookmark:1",
        url=bookmark.url,
        title=bookmark.title,
        content_text="PostgreSQL 的默认索引类型是 B-tree。",
        fetch_status=Source.FETCH_READY,
    )
    Evidence.objects.create(
        task=task, source=source, quote="默认索引类型是 B-tree"
    )
    return task


def test_persist_report_keeps_valid_citation(task):
    evidence = task.evidence.get()
    report = persist_report_content(
        task, f"## 结论\nB-tree 是默认索引 [e:{evidence.id}]。", model="fake"
    )

    assert report.citations[0]["evidence_id"] == evidence.id
    assert report.validation["invalid_citations"] == []


def test_persist_report_strips_unknown_citation(task):
    evidence = task.evidence.get()
    report = persist_report_content(
        task,
        f"## 结论\n有效 [e:{evidence.id}]，无效 [e:99999]。",
        model="fake",
    )

    assert "[e:99999]" not in report.content_md
    assert report.validation["invalid_citations"] == [99999]
    assert report.validation["citation_count"] == 1


def test_generate_report_without_llm_uses_evidence_fallback(task):
    report = generate_report(task, llm=None, reason="测试")

    assert "参考证据" in report.content_md
    assert report.citations
    assert report.validation["model_report"] is False
