from django.contrib import admin

from research.models import (
    AgentStep,
    Claim,
    ClaimEvidence,
    Evidence,
    LLMUsage,
    Report,
    ResearchTask,
    Source,
    SubQuestion,
    TaskEvent,
    ToolCallCache,
)


class SubQuestionInline(admin.TabularInline):
    model = SubQuestion
    extra = 0


class TaskEventInline(admin.TabularInline):
    model = TaskEvent
    extra = 0
    readonly_fields = ["kind", "message", "payload", "created_at"]
    can_delete = False


@admin.register(ResearchTask)
class ResearchTaskAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "question",
        "strategy",
        "status",
        "phase",
        "progress_pct",
        "tokens_used",
        "owner",
        "created_at",
    ]
    list_filter = ["status", "strategy", "completion_reason"]
    search_fields = ["question"]
    inlines = [SubQuestionInline, TaskEventInline]
    readonly_fields = ["created_at", "updated_at", "started_at", "finished_at"]


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ["id", "task", "source_type", "title", "fetch_status", "url"]
    list_filter = ["source_type", "fetch_status"]


@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    list_display = ["id", "task", "source", "sub_question", "quote"]
    search_fields = ["quote"]


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = ["id", "task", "text", "status", "confidence"]
    list_filter = ["status"]


admin.site.register(ClaimEvidence)
admin.site.register(Report)
admin.site.register(AgentStep)


@admin.register(TaskEvent)
class TaskEventAdmin(admin.ModelAdmin):
    list_display = ["id", "task", "kind", "message", "created_at"]
    list_filter = ["kind"]


admin.site.register(LLMUsage)
admin.site.register(ToolCallCache)
