from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from research.forms import ResearchTaskForm
from research.models import Claim, ResearchTask
from research.services.rendering import render_markdown
from research.tasks import run_research_task


def _task_for(request, pk: int) -> ResearchTask:
    return get_object_or_404(ResearchTask, pk=pk, owner=request.user)


@login_required
def task_list(request):
    status_filter = request.GET.get("status", "")
    queryset = ResearchTask.objects.filter(owner=request.user)
    if status_filter:
        queryset = queryset.filter(status=status_filter)
    return render(
        request,
        "research/list.html",
        {
            "tasks": queryset[:100],
            "form": ResearchTaskForm(),
            "status_filter": status_filter,
            "status_choices": ResearchTask.STATUS_CHOICES,
        },
    )


@login_required
@require_POST
def task_create(request):
    form = ResearchTaskForm(request.POST)
    if not form.is_valid():
        messages.error(request, "创建失败：检查研究问题与步数")
        return redirect("research-list")

    task = ResearchTask.objects.create(
        owner=request.user,
        question=form.cleaned_data["question"],
        strategy=form.cleaned_data["strategy"],
        max_steps=form.cleaned_data.get("max_steps") or ResearchTask._meta.get_field(
            "max_steps"
        ).default,
        options=form.to_options(),
    )
    task_id = task.pk
    transaction.on_commit(lambda: run_research_task(task_id))
    messages.success(request, "研究任务已创建，正在排队执行")
    return redirect("research-detail", pk=task_id)


def _detail_context(task: ResearchTask) -> dict:
    report = None
    try:
        report = task.report
    except ResearchTask.report.RelatedObjectDoesNotExist:  # type: ignore[attr-defined]
        report = None

    claims = list(task.claims.prefetch_related("links").all())
    claim_rows = []
    for claim in claims:
        evidence_items = [
            link.evidence
            for link in claim.links.select_related("evidence__source").all()
        ]
        claim_rows.append({"claim": claim, "evidence": evidence_items})

    usage = list(task.llm_usage.all())
    return {
        "task": task,
        "sub_questions": task.sub_questions.all(),
        "evidence": task.evidence.select_related("source").order_by("id")[:200],
        "sources": task.sources.all()[:100],
        "claim_rows": claim_rows,
        "report": report,
        "report_html": render_markdown(report.content_md) if report else "",
        "steps": task.steps.all()[:200],
        "events": task.events.all()[:100],
        "usage": usage,
        "total_tokens": sum(item.total_tokens for item in usage),
    }


@login_required
def task_detail(request, pk: int):
    task = _task_for(request, pk)
    return render(request, "research/detail.html", _detail_context(task))


@login_required
def task_status(request, pk: int):
    task = _task_for(request, pk)
    last = request.GET.get("last", "")
    if last and last != task.status and task.is_terminal:
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response
    return render(request, "research/_status.html", {"task": task})


@login_required
@require_POST
def task_cancel(request, pk: int):
    task = _task_for(request, pk)
    if task.is_terminal:
        messages.info(request, "任务已经结束，无需取消")
    else:
        task.request_cancel()
        messages.success(request, "已请求取消，将在下一个安全点停止")
    return redirect("research-detail", pk=task.pk)


@login_required
@require_POST
def task_retry(request, pk: int):
    task = _task_for(request, pk)
    if task.status != ResearchTask.STATUS_FAILED:
        messages.error(request, "只有失败的任务可以重试")
        return redirect("research-detail", pk=task.pk)

    task.transition(ResearchTask.STATUS_PENDING, reason="手动重试")
    ResearchTask.objects.filter(pk=task.pk).update(
        attempt=0,
        error="",
        completion_reason="",
        is_partial=False,
        finished_at=None,
        deadline_at=None,
        cancel_requested_at=None,
        phase=ResearchTask.PHASE_PLANNING,
    )
    task_id = task.pk
    transaction.on_commit(lambda: run_research_task(task_id))
    messages.success(request, "任务已重新排队")
    return redirect("research-detail", pk=task_id)


@login_required
def claim_list(request):
    claims = (
        Claim.objects.filter(task__owner=request.user)
        .select_related("task", "sub_question")
        .prefetch_related("links__evidence__source")[:200]
    )
    return render(request, "research/claims.html", {"claims": claims})
