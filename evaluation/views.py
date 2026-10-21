from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from evaluation.models import EvaluationRun


@login_required
def run_list(request):
    runs = EvaluationRun.objects.all()[:50]
    return render(request, "evaluation/list.html", {"runs": runs})


@login_required
def run_detail(request, pk: int):
    run = get_object_or_404(EvaluationRun, pk=pk)
    return render(
        request,
        "evaluation/detail.html",
        {"run": run, "cases": run.cases.all()},
    )
