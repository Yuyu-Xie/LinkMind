from django.contrib import admin

from evaluation.models import EvaluationCaseResult, EvaluationRun


class EvaluationCaseResultInline(admin.TabularInline):
    model = EvaluationCaseResult
    extra = 0
    readonly_fields = [
        "case_key",
        "completed",
        "strict_completed",
        "citation_f1",
        "key_fact_coverage",
        "tokens",
        "latency_ms",
    ]


@admin.register(EvaluationRun)
class EvaluationRunAdmin(admin.ModelAdmin):
    list_display = ["id", "dataset", "strategy", "status", "run_index", "created_at"]
    list_filter = ["strategy", "status", "dataset"]
    inlines = [EvaluationCaseResultInline]


@admin.register(EvaluationCaseResult)
class EvaluationCaseResultAdmin(admin.ModelAdmin):
    list_display = ["case_key", "run", "completed", "citation_f1", "key_fact_coverage"]
