from __future__ import annotations

import json
import logging
import platform
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import django
from django.conf import settings
from django.utils import timezone

from evaluation.models import EvaluationCaseResult, EvaluationRun
from evaluation.services.dataset import Dataset, load_dataset
from evaluation.services.metrics import evaluate_task
from evaluation.services.strategies import run_baseline
from research.agent.llm_client import get_llm_client
from research.models import ResearchTask
from research.services.runner import run_task

logger = logging.getLogger("research")

METRIC_KEYS = [
    "completed",
    "strict_completed",
    "citation_precision",
    "citation_recall",
    "citation_f1",
    "claim_support_rate",
    "key_fact_coverage",
    "tokens",
    "latency_ms",
]


def _task_options(dataset: Dataset, case: dict) -> dict:
    return {
        "offline": True,
        "dataset": dataset.version,
        "case_key": case["key"],
    }


def _execute_case(
    case: dict, strategy: str, owner, llm, dataset: Dataset
) -> ResearchTask:
    task = ResearchTask.objects.create(
        owner=owner,
        question=case["question"],
        strategy=strategy,
        options=_task_options(dataset, case),
        max_steps=settings.RESEARCH_MAX_STEPS,
        budget_tokens=settings.RESEARCH_BUDGET_TOKENS,
        timeout_seconds=settings.RESEARCH_TIMEOUT_SECONDS,
    )
    if strategy == ResearchTask.STRATEGY_BASELINE:
        run_baseline(task, llm)
    else:
        run_task(task.pk, llm=llm, retry_enabled=False)
    task.refresh_from_db()
    return task


def _aggregate(results: list[EvaluationCaseResult]) -> dict:
    total = len(results)
    if not total:
        return {"cases": 0}

    def mean(field: str) -> float:
        return round(sum(getattr(item, field) for item in results) / total, 4)

    summary = {
        "cases": total,
        "errors": sum(1 for item in results if item.error),
        "completion_rate": mean("completed"),
        "strict_completion_rate": mean("strict_completed"),
        "citation_precision": mean("citation_precision"),
        "citation_recall": mean("citation_recall"),
        "citation_f1": mean("citation_f1"),
        "claim_support_rate": mean("claim_support_rate"),
        "key_fact_coverage": mean("key_fact_coverage"),
        "avg_tokens": int(mean("tokens")),
        "avg_latency_ms": int(mean("latency_ms")),
        "total_tokens": sum(item.tokens for item in results),
    }
    return summary


def _run_one(
    dataset: Dataset,
    strategy: str,
    run_index: int,
    owner,
    llm,
    model_name: str,
) -> EvaluationRun:
    run = EvaluationRun.objects.create(
        dataset=dataset.version,
        dataset_hash=dataset.sha256,
        strategy=strategy,
        model=model_name,
        run_index=run_index,
        status=EvaluationRun.STATUS_RUNNING,
        started_at=timezone.now(),
        settings={
            "max_steps": settings.RESEARCH_MAX_STEPS,
            "budget_tokens": settings.RESEARCH_BUDGET_TOKENS,
            "timeout_seconds": settings.RESEARCH_TIMEOUT_SECONDS,
            "temperature": 0,
        },
    )

    results: list[EvaluationCaseResult] = []
    for case in dataset.cases:
        try:
            task = _execute_case(case, strategy, owner, llm, dataset)
            metrics = evaluate_task(task, case)
            result, _ = EvaluationCaseResult.objects.update_or_create(
                run=run,
                case_key=case["key"],
                defaults={
                    "question": case["question"],
                    "task": task,
                    "completed": metrics["completed"],
                    "strict_completed": metrics["strict_completed"],
                    "citation_precision": metrics["citation_precision"],
                    "citation_recall": metrics["citation_recall"],
                    "citation_f1": metrics["citation_f1"],
                    "claim_support_rate": metrics["claim_support_rate"],
                    "key_fact_coverage": metrics["key_fact_coverage"],
                    "tokens": metrics["tokens"],
                    "latency_ms": metrics["latency_ms"],
                    "details": metrics["details"],
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("evaluation case %s failed", case["key"])
            result, _ = EvaluationCaseResult.objects.update_or_create(
                run=run,
                case_key=case["key"],
                defaults={
                    "question": case["question"],
                    "error": f"{type(exc).__name__}: {exc}"[:2000],
                    "details": {},
                },
            )
        results.append(result)
        logger.info(
            "eval %s/%s case %s completed=%s f1=%.2f coverage=%.2f",
            strategy,
            run_index,
            case["key"],
            result.completed,
            result.citation_f1,
            result.key_fact_coverage,
        )

    run.summary = _aggregate(results)
    run.status = EvaluationRun.STATUS_COMPLETED
    run.finished_at = timezone.now()
    run.save(update_fields=["summary", "status", "finished_at"])
    return run


def _settings_snapshot() -> dict:
    return {
        "python": platform.python_version(),
        "django": django.get_version(),
        "model": settings.DEEPSEEK_MODEL,
        "web_search_provider": settings.WEB_SEARCH_PROVIDER,
        "max_steps": settings.RESEARCH_MAX_STEPS,
        "budget_tokens": settings.RESEARCH_BUDGET_TOKENS,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


def _write_output(run: EvaluationRun, dataset: Dataset, output_dir: str) -> Path:
    directory = Path(output_dir)
    if not directory.is_absolute():
        directory = Path(settings.BASE_DIR) / directory
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (
        f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{run.dataset}-"
        f"{run.strategy}-r{run.run_index}-{run.pk}.json"
    )
    payload = {
        "run_id": run.pk,
        "dataset": asdict(dataset),
        "strategy": run.strategy,
        "model": run.model,
        "run_index": run.run_index,
        "settings": run.settings,
        "environment": _settings_snapshot(),
        "summary": run.summary,
        "cases": [
            {
                "case_key": item.case_key,
                "question": item.question,
                "completed": item.completed,
                "strict_completed": item.strict_completed,
                "citation_precision": item.citation_precision,
                "citation_recall": item.citation_recall,
                "citation_f1": item.citation_f1,
                "claim_support_rate": item.claim_support_rate,
                "key_fact_coverage": item.key_fact_coverage,
                "tokens": item.tokens,
                "latency_ms": item.latency_ms,
                "error": item.error,
                "details": item.details,
            }
            for item in run.cases.all()
        ],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def run_evaluation(
    dataset_name: str = "linkmind_v1",
    strategies: list[str] | None = None,
    runs: int = 1,
    owner=None,
    llm=None,
    output_dir: str | None = "evaluation/results",
) -> list[EvaluationRun]:
    if owner is None:
        raise ValueError("run_evaluation 需要 owner")

    dataset = load_dataset(dataset_name)
    strategies = strategies or [
        EvaluationRun.STRATEGY_BASELINE,
        EvaluationRun.STRATEGY_AGENT,
    ]
    llm = llm or get_llm_client()
    model_name = getattr(llm, "model", settings.DEEPSEEK_MODEL)

    completed_runs: list[EvaluationRun] = []
    for strategy in strategies:
        for run_index in range(1, runs + 1):
            run = _run_one(dataset, strategy, run_index, owner, llm, model_name)
            if output_dir:
                path = _write_output(run, dataset, output_dir)
                logger.info("evaluation output written to %s", path)
            completed_runs.append(run)
    return completed_runs
