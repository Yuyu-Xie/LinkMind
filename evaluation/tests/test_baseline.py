from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model

from bookmarks.models import DocumentContent
from bookmarks.services import bookmarks as bookmark_service
from evaluation.services.bm25 import BM25Index, Passage
from evaluation.services.dataset import load_corpus, load_dataset
from evaluation.services.metrics import evaluate_task
from evaluation.services.runner import _execute_case, run_evaluation
from evaluation.services.strategies import build_index, run_baseline
from research.agent.fake_client import FakeLLMClient, text_response
from research.models import ResearchTask, Source, SubQuestion

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def owner():
    user = get_user_model().objects.create_user(username="evaluser", password="x")
    for document in load_corpus():
        bookmark, _ = bookmark_service.create_bookmark(
            owner=user,
            url=document["url"],
            title=document["title"],
            tag_names=document.get("tags", []),
        )
        DocumentContent.objects.create(
            bookmark=bookmark,
            text=document["text"],
            status=DocumentContent.STATUS_READY,
            content_hash=document["key"],
        )
    return user


def test_bm25_ranks_relevant_document_first(owner):
    index = build_index(owner)
    hits = index.search("Redis RDB AOF 持久化 快照", limit=5)

    assert hits
    assert hits[0].url == "https://eval.local/redis/persistence"


def test_bm25_empty_index_returns_nothing():
    index = BM25Index([])
    assert index.search("anything") == []


def test_bm25_passage_scoring():
    passages = [
        Passage(1, "a", "A", "Redis RDB 持久化 快照 恢复"),
        Passage(2, "b", "B", "Django ORM 查询优化"),
    ]
    hits = BM25Index(passages).search("RDB 快照")
    assert [item.bookmark_id for item in hits] == [1]


def test_baseline_generates_cited_report(owner):
    case = next(
        item for item in load_dataset().cases if item["key"] == "redis-persistence-choice"
    )
    task = ResearchTask.objects.create(
        owner=owner,
        question=case["question"],
        strategy=ResearchTask.STRATEGY_BASELINE,
        options={"offline": True},
    )

    def handler(messages, tools):
        prompt = messages[-1]["content"]
        marker = re.search(r"\[e(\d+)\]", prompt)
        assert marker, prompt
        return text_response(
            "## 结论\nRDB 生成快照，恢复速度快，可能丢失两次快照之间的数据 "
            f"[e:{marker.group(1)}]。"
        )

    run_baseline(task, FakeLLMClient(handler=handler))
    task.refresh_from_db()

    assert task.status == ResearchTask.STATUS_COMPLETED
    assert task.report.citations
    assert task.sources.filter(source_type=Source.TYPE_BOOKMARK).exists()
    assert task.evidence.count() == 5


def test_metrics_count_matching_citation(owner):
    case = next(
        item for item in load_dataset().cases if item["key"] == "redis-persistence-choice"
    )
    task = ResearchTask.objects.create(
        owner=owner,
        question=case["question"],
        strategy=ResearchTask.STRATEGY_BASELINE,
        options={"offline": True},
    )

    def handler(messages, tools):
        marker = re.search(r"\[e(\d+)\]", messages[-1]["content"])
        return text_response(
            "## 结论\nRDB 生成数据快照，文件紧凑，恢复速度快 [e:"
            f"{marker.group(1)}]。"
        )

    run_baseline(task, FakeLLMClient(handler=handler))
    metrics = evaluate_task(task, case)

    assert metrics["completed"] is True
    assert metrics["citation_precision"] == 1.0
    assert metrics["citation_recall"] > 0
    assert metrics["details"]["citations"]["evidence_total"] == 5


def test_agent_case_runs_offline_with_fake_llm(owner):
    case = {
        "key": "fake-case",
        "question": "Redis 的 RDB 有什么特点？",
        "reference_sources": ["https://eval.local/redis/persistence"],
        "reference_evidence": [
            {
                "url": "https://eval.local/redis/persistence",
                "quote": "RDB 在指定时间间隔生成数据快照",
                "key_facts": ["RDB"],
            }
        ],
        "reference_answer": "RDB 生成快照。",
    }
    dataset = load_dataset()

    def handler(messages, tools):
        from research.agent.fake_client import tool_call, tool_response
        from research.agent.prompts import PLAN_SYSTEM, REPORT_SYSTEM
        from research.models import SubQuestion

        system = messages[0]["content"]
        if system == PLAN_SYSTEM:
            return text_response('{"sub_questions": ["RDB 的特点"]}')
        if system == REPORT_SYSTEM:
            return text_response("## 结论\nRDB 生成快照。")
        sub_question = SubQuestion.objects.filter(task__question=case["question"]).first()
        if sub_question and sub_question.status == SubQuestion.STATUS_PENDING:
            return tool_response(
                tool_call(
                    "answer_subquestion",
                    sub_question_id=sub_question.id,
                    status="insufficient",
                    answer="离线语料不足",
                )
            )
        return tool_response(
            tool_call("finish_research", summary="证据不足")
        )

    task = _execute_case(
        case, ResearchTask.STRATEGY_AGENT, owner, FakeLLMClient(handler=handler), dataset
    )
    assert task.status == ResearchTask.STATUS_COMPLETED
    assert task.sub_questions.filter(status=SubQuestion.STATUS_INSUFFICIENT).exists()


def test_run_evaluation_writes_summary_and_output(owner, tmp_path):
    def handler(messages, tools):
        prompt = messages[-1]["content"]
        marker = re.search(r"\[e(\d+)\]", prompt)
        if marker:
            return text_response(
                "## 结论\n根据资料，该问题与索引、缓存和持久化有关 "
                f"[e:{marker.group(1)}]。"
            )
        return text_response("## 结论\n没有找到资料。")

    runs = run_evaluation(
        dataset_name="linkmind_v1",
        strategies=["baseline"],
        runs=1,
        owner=owner,
        llm=FakeLLMClient(handler=handler),
        output_dir=str(tmp_path),
    )

    assert len(runs) == 1
    run = runs[0]
    assert run.status == "completed"
    assert run.summary["cases"] == 10
    assert "completion_rate" in run.summary
    assert run.cases.count() == 10
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    assert run.dataset_hash in files[0].read_text(encoding="utf-8")
