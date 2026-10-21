from __future__ import annotations

from django.db import models


class EvaluationRun(models.Model):
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "排队中"),
        (STATUS_RUNNING, "执行中"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_FAILED, "失败"),
    ]

    STRATEGY_BASELINE = "baseline"
    STRATEGY_AGENT = "agent"
    STRATEGY_CHOICES = [
        (STRATEGY_BASELINE, "基线检索"),
        (STRATEGY_AGENT, "动态研究"),
    ]

    dataset = models.CharField(max_length=128)
    dataset_hash = models.CharField(max_length=64, blank=True)
    strategy = models.CharField(max_length=16, choices=STRATEGY_CHOICES)
    model = models.CharField(max_length=64, blank=True)
    run_index = models.PositiveSmallIntegerField(default=1)
    settings = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    summary = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"eval:{self.pk} {self.dataset}/{self.strategy}"


class EvaluationCaseResult(models.Model):
    run = models.ForeignKey(
        EvaluationRun, on_delete=models.CASCADE, related_name="cases"
    )
    case_key = models.CharField(max_length=64)
    question = models.TextField(blank=True)
    task = models.ForeignKey(
        "research.ResearchTask",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evaluation_cases",
    )
    completed = models.BooleanField(default=False)
    strict_completed = models.BooleanField(default=False)
    citation_precision = models.FloatField(default=0.0)
    citation_recall = models.FloatField(default=0.0)
    citation_f1 = models.FloatField(default=0.0)
    claim_support_rate = models.FloatField(default=0.0)
    key_fact_coverage = models.FloatField(default=0.0)
    tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["case_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["run", "case_key"], name="uniq_eval_run_case"
            )
        ]

    def __str__(self) -> str:
        return f"eval:{self.run_id} {self.case_key}"
