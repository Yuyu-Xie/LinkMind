from __future__ import annotations

import hashlib
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


def normalized_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_quote(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


class ResearchTask(models.Model):
    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_TIMED_OUT = "timed_out"
    STATUS_CANCELED = "canceled"
    STATUS_CHOICES = [
        (STATUS_PENDING, "排队中"),
        (STATUS_RUNNING, "执行中"),
        (STATUS_COMPLETED, "已完成"),
        (STATUS_FAILED, "失败"),
        (STATUS_TIMED_OUT, "超时"),
        (STATUS_CANCELED, "已取消"),
    ]
    TERMINAL_STATUSES = {STATUS_COMPLETED, STATUS_FAILED, STATUS_TIMED_OUT, STATUS_CANCELED}
    ALLOWED_TRANSITIONS = {
        STATUS_PENDING: {STATUS_RUNNING, STATUS_CANCELED},
        STATUS_RUNNING: {
            STATUS_COMPLETED,
            STATUS_FAILED,
            STATUS_TIMED_OUT,
            STATUS_CANCELED,
            STATUS_PENDING,
        },
        STATUS_FAILED: {STATUS_PENDING},
        STATUS_COMPLETED: set(),
        STATUS_TIMED_OUT: set(),
        STATUS_CANCELED: set(),
    }

    PHASE_PLANNING = "planning"
    PHASE_RESEARCHING = "researching"
    PHASE_REPORTING = "reporting"
    PHASE_DONE = "done"

    STRATEGY_AGENT = "agent"
    STRATEGY_BASELINE = "baseline"
    STRATEGY_CHOICES = [(STRATEGY_AGENT, "动态研究"), (STRATEGY_BASELINE, "基线检索")]

    COMPLETION_MODEL_FINISH = "model_finish"
    COMPLETION_MAX_STEPS = "max_steps"
    COMPLETION_BUDGET = "budget"
    COMPLETION_DEADLINE = "deadline"
    COMPLETION_INSUFFICIENT = "insufficient_evidence"
    COMPLETION_NO_PROGRESS = "no_progress"
    COMPLETION_ERROR = "error"
    COMPLETION_CANCELED = "canceled"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="research_tasks",
    )
    question = models.TextField()
    strategy = models.CharField(
        max_length=16, choices=STRATEGY_CHOICES, default=STRATEGY_AGENT
    )
    options = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    phase = models.CharField(max_length=16, default=PHASE_PLANNING)
    progress_pct = models.PositiveSmallIntegerField(default=0)
    progress_detail = models.JSONField(default=dict, blank=True)

    max_steps = models.PositiveIntegerField(default=settings.RESEARCH_MAX_STEPS)
    budget_tokens = models.PositiveIntegerField(default=settings.RESEARCH_BUDGET_TOKENS)
    timeout_seconds = models.PositiveIntegerField(
        default=settings.RESEARCH_TIMEOUT_SECONDS
    )
    deadline_at = models.DateTimeField(null=True, blank=True)

    attempt = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    lease_owner = models.CharField(max_length=128, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)

    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    completion_reason = models.CharField(max_length=32, blank=True)
    is_partial = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    plan_raw = models.JSONField(default=dict, blank=True)
    tokens_used = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["owner", "status", "-created_at"], name="rt_owner_status_idx"),
            models.Index(fields=["status", "lease_expires_at"], name="rt_status_lease_idx"),
        ]

    def __str__(self) -> str:
        return f"task:{self.pk} {self.question[:40]}"

    @property
    def is_terminal(self) -> bool:
        return self.status in self.TERMINAL_STATUSES

    @property
    def duration_ms(self) -> int | None:
        if not self.started_at or not self.finished_at:
            return None
        return int((self.finished_at - self.started_at).total_seconds() * 1000)

    def transition(self, to_status: str, reason: str = "", error: str = "") -> bool:
        """Validate and persist a status transition. Returns False if illegal."""
        with transaction.atomic():
            task = ResearchTask.objects.select_for_update().get(pk=self.pk)
            if to_status == task.status:
                return True
            allowed = self.ALLOWED_TRANSITIONS.get(task.status, set())
            if to_status not in allowed:
                raise ValueError(f"非法状态迁移: {task.status} -> {to_status}")

            task.status = to_status
            if to_status == self.STATUS_RUNNING and not task.started_at:
                task.started_at = timezone.now()
            if to_status in self.TERMINAL_STATUSES:
                task.finished_at = timezone.now()
                task.phase = self.PHASE_DONE
                task.lease_owner = ""
                task.lease_expires_at = None
            if error:
                task.error = error[:4000]
            task.save(
                update_fields=[
                    "status",
                    "started_at",
                    "finished_at",
                    "phase",
                    "lease_owner",
                    "lease_expires_at",
                    "error",
                    "updated_at",
                ]
            )

        for field in (
            "status",
            "started_at",
            "finished_at",
            "phase",
            "lease_owner",
            "lease_expires_at",
            "error",
            "updated_at",
        ):
            setattr(self, field, getattr(task, field))

        TaskEvent.objects.create(
            task_id=self.pk,
            kind="status",
            message=reason or f"{task.status}",
            payload={"to": to_status, "reason": reason},
        )
        return True

    def request_cancel(self) -> None:
        if self.is_terminal:
            return
        ResearchTask.objects.filter(pk=self.pk).update(cancel_requested_at=timezone.now())
        TaskEvent.objects.create(task_id=self.pk, kind="cancel", message="用户请求取消")


class SubQuestion(models.Model):
    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_ANSWERED = "answered"
    STATUS_INSUFFICIENT = "insufficient"
    STATUS_CHOICES = [
        (STATUS_PENDING, "待研究"),
        (STATUS_IN_PROGRESS, "进行中"),
        (STATUS_ANSWERED, "已回答"),
        (STATUS_INSUFFICIENT, "证据不足"),
    ]

    task = models.ForeignKey(
        ResearchTask, on_delete=models.CASCADE, related_name="sub_questions"
    )
    order = models.PositiveSmallIntegerField()
    question = models.TextField()
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    answer = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(fields=["task", "order"], name="uniq_subq_task_order")
        ]

    def __str__(self) -> str:
        return f"S{self.order} {self.question[:40]}"


class Source(models.Model):
    TYPE_BOOKMARK = "bookmark"
    TYPE_WEB = "web"
    TYPE_DOCUMENT = "document"
    TYPE_CHOICES = [
        (TYPE_BOOKMARK, "书签"),
        (TYPE_WEB, "网页"),
        (TYPE_DOCUMENT, "文档"),
    ]

    FETCH_PENDING = "pending"
    FETCH_READY = "ready"
    FETCH_FAILED = "failed"

    task = models.ForeignKey(ResearchTask, on_delete=models.CASCADE, related_name="sources")
    sub_question = models.ForeignKey(
        SubQuestion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sources",
    )
    bookmark = models.ForeignKey(
        "bookmarks.Bookmark",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="research_sources",
    )
    source_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    source_key = models.CharField(max_length=255)
    url = models.CharField(max_length=2048, blank=True)
    url_normalized = models.CharField(max_length=2048, blank=True)
    title = models.CharField(max_length=512, blank=True)
    snippet = models.TextField(blank=True)
    content_text = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    fetch_status = models.CharField(max_length=16, default=FETCH_PENDING)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["task", "source_key"], name="uniq_source_key")
        ]
        indexes = [models.Index(fields=["task", "source_type"], name="src_task_type_idx")]

    def __str__(self) -> str:
        return f"source:{self.pk} {self.title[:40]}"

    @property
    def is_readable(self) -> bool:
        return self.fetch_status == self.FETCH_READY and bool(self.content_text)


class Evidence(models.Model):
    task = models.ForeignKey(ResearchTask, on_delete=models.CASCADE, related_name="evidence")
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="evidence")
    sub_question = models.ForeignKey(
        SubQuestion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evidence",
    )
    quote = models.TextField()
    quote_hash = models.CharField(max_length=64, blank=True)
    char_start = models.PositiveIntegerField(null=True, blank=True)
    char_end = models.PositiveIntegerField(null=True, blank=True)
    locator = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "quote_hash"], name="uniq_evidence_source_quote"
            )
        ]
        indexes = [models.Index(fields=["task", "sub_question"], name="ev_task_subq_idx")]

    def __str__(self) -> str:
        return f"evidence:{self.pk}"

    def save(self, *args, **kwargs):
        self.quote = normalize_quote(self.quote)
        if not self.quote:
            raise ValidationError("证据引文不能为空")
        self.quote_hash = hashlib.sha256(self.quote.encode("utf-8")).hexdigest()
        content = self.source.content_text or ""
        if content:
            index = re.sub(r"\s+", " ", content).find(self.quote)
            if index == -1:
                raise ValidationError("引文未在来源正文中找到，拒绝创建证据")
            self.char_start = index
            self.char_end = index + len(self.quote)
            self.locator = {
                "strategy": "normalized_substring",
                "char_start": index,
                "char_end": index + len(self.quote),
            }
        super().save(*args, **kwargs)


class Claim(models.Model):
    STATUS_PROPOSED = "proposed"
    STATUS_SUPPORTED = "supported"
    STATUS_INSUFFICIENT = "insufficient"
    STATUS_CONTRADICTED = "contradicted"
    STATUS_CHOICES = [
        (STATUS_PROPOSED, "待验证"),
        (STATUS_SUPPORTED, "有证据支持"),
        (STATUS_INSUFFICIENT, "证据不足"),
        (STATUS_CONTRADICTED, "存在反证"),
    ]

    task = models.ForeignKey(ResearchTask, on_delete=models.CASCADE, related_name="claims")
    sub_question = models.ForeignKey(
        SubQuestion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claims",
    )
    text = models.TextField()
    normalized_hash = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PROPOSED
    )
    confidence = models.FloatField(default=0.5)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(fields=["task", "normalized_hash"], name="uniq_claim_hash")
        ]

    def __str__(self) -> str:
        return f"claim:{self.pk} {self.text[:40]}"

    def save(self, *args, **kwargs):
        self.normalized_hash = normalized_hash(self.text)
        super().save(*args, **kwargs)

    def refresh_status(self) -> None:
        supports = self.links.filter(relation=ClaimEvidence.REL_SUPPORTS).count()
        refutes = self.links.filter(relation=ClaimEvidence.REL_REFUTES).count()
        if refutes:
            self.status = self.STATUS_CONTRADICTED
        elif supports:
            self.status = self.STATUS_SUPPORTED
        elif self.status == self.STATUS_SUPPORTED:
            self.status = self.STATUS_PROPOSED
        self.save(update_fields=["status", "updated_at"])


class ClaimEvidence(models.Model):
    REL_SUPPORTS = "supports"
    REL_REFUTES = "refutes"
    REL_CHOICES = [(REL_SUPPORTS, "支持"), (REL_REFUTES, "反驳")]

    claim = models.ForeignKey(Claim, on_delete=models.CASCADE, related_name="links")
    evidence = models.ForeignKey(Evidence, on_delete=models.CASCADE, related_name="claim_links")
    relation = models.CharField(
        max_length=16, choices=REL_CHOICES, default=REL_SUPPORTS
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["claim", "evidence"], name="uniq_claim_evidence")
        ]


class Report(models.Model):
    task = models.OneToOneField(
        ResearchTask, on_delete=models.CASCADE, related_name="report"
    )
    version = models.PositiveSmallIntegerField(default=1)
    content_md = models.TextField()
    citations = models.JSONField(default=list, blank=True)
    validation = models.JSONField(default=dict, blank=True)
    model = models.CharField(max_length=64, blank=True)
    generated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"report:{self.task_id}"


class AgentStep(models.Model):
    TYPE_THOUGHT = "thought"
    TYPE_TOOL_CALL = "tool_call"
    TYPE_TOOL_RESULT = "tool_result"
    TYPE_ERROR = "error"
    TYPE_CHOICES = [
        (TYPE_THOUGHT, "思考"),
        (TYPE_TOOL_CALL, "工具调用"),
        (TYPE_TOOL_RESULT, "工具结果"),
        (TYPE_ERROR, "错误"),
    ]

    STATUS_OK = "ok"
    STATUS_ERROR = "error"
    STATUS_REUSED = "reused"

    task = models.ForeignKey(ResearchTask, on_delete=models.CASCADE, related_name="steps")
    step_no = models.PositiveIntegerField()
    step_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    tool_name = models.CharField(max_length=64, blank=True)
    tool_signature = models.CharField(max_length=64, blank=True, db_index=True)
    input = models.JSONField(default=dict, blank=True)
    output = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, default=STATUS_OK)
    error = models.TextField(blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["step_no"]
        constraints = [
            models.UniqueConstraint(fields=["task", "step_no"], name="uniq_step_no")
        ]

    def __str__(self) -> str:
        return f"step:{self.task_id}#{self.step_no}"


class TaskEvent(models.Model):
    task = models.ForeignKey(ResearchTask, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=32)
    message = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["task", "-created_at"], name="evt_task_time_idx")]


class LLMUsage(models.Model):
    PURPOSE_PLAN = "plan"
    PURPOSE_AGENT = "agent"
    PURPOSE_REPORT = "report"
    PURPOSE_BASELINE = "baseline"
    PURPOSE_CHOICES = [
        (PURPOSE_PLAN, "规划"),
        (PURPOSE_AGENT, "研究循环"),
        (PURPOSE_REPORT, "报告"),
        (PURPOSE_BASELINE, "基线回答"),
    ]

    task = models.ForeignKey(ResearchTask, on_delete=models.CASCADE, related_name="llm_usage")
    step = models.ForeignKey(
        AgentStep, on_delete=models.SET_NULL, null=True, blank=True, related_name="usage"
    )
    purpose = models.CharField(max_length=16, choices=PURPOSE_CHOICES)
    model = models.CharField(max_length=64, blank=True)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    cached_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    ok = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ToolCallCache(models.Model):
    task = models.ForeignKey(
        ResearchTask, on_delete=models.CASCADE, related_name="tool_cache"
    )
    tool_name = models.CharField(max_length=64)
    args_hash = models.CharField(max_length=64)
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["task", "tool_name", "args_hash"], name="uniq_tool_cache"
            )
        ]
