from __future__ import annotations

from rest_framework import serializers

from research.models import (
    AgentStep,
    Claim,
    Evidence,
    LLMUsage,
    Report,
    ResearchTask,
    Source,
    SubQuestion,
    TaskEvent,
)


class ResearchTaskListSerializer(serializers.ModelSerializer):
    duration_ms = serializers.IntegerField(read_only=True)

    class Meta:
        model = ResearchTask
        fields = [
            "id",
            "question",
            "strategy",
            "status",
            "phase",
            "progress_pct",
            "completion_reason",
            "is_partial",
            "tokens_used",
            "created_at",
            "started_at",
            "finished_at",
            "duration_ms",
        ]


class ResearchTaskDetailSerializer(ResearchTaskListSerializer):
    counts = serializers.SerializerMethodField()

    class Meta(ResearchTaskListSerializer.Meta):
        fields = ResearchTaskListSerializer.Meta.fields + [
            "options",
            "max_steps",
            "budget_tokens",
            "timeout_seconds",
            "deadline_at",
            "attempt",
            "max_attempts",
            "cancel_requested_at",
            "error",
            "plan_raw",
            "progress_detail",
            "updated_at",
            "counts",
        ]

    def get_counts(self, obj) -> dict:
        return {
            "sub_questions": obj.sub_questions.count(),
            "sources": obj.sources.count(),
            "evidence": obj.evidence.count(),
            "claims": obj.claims.count(),
            "steps": obj.steps.count(),
        }


class ResearchTaskCreateSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=4000)
    strategy = serializers.ChoiceField(
        choices=ResearchTask.STRATEGY_CHOICES, default=ResearchTask.STRATEGY_AGENT
    )
    options = serializers.JSONField(required=False, default=dict)
    max_steps = serializers.IntegerField(required=False, min_value=1, max_value=40)
    budget_tokens = serializers.IntegerField(
        required=False, min_value=2000, max_value=500000
    )
    timeout_seconds = serializers.IntegerField(
        required=False, min_value=30, max_value=3600
    )

    def create(self, validated_data):
        owner = self.context["request"].user
        return ResearchTask.objects.create(owner=owner, **validated_data)


class SubQuestionSerializer(serializers.ModelSerializer):
    evidence_count = serializers.IntegerField(source="evidence.count", read_only=True)

    class Meta:
        model = SubQuestion
        fields = [
            "id",
            "order",
            "question",
            "status",
            "answer",
            "evidence_count",
            "created_at",
            "updated_at",
        ]


class SourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Source
        fields = [
            "id",
            "sub_question",
            "bookmark",
            "source_type",
            "source_key",
            "url",
            "title",
            "snippet",
            "content_hash",
            "fetch_status",
            "http_status",
            "fetched_at",
            "created_at",
        ]


class EvidenceSerializer(serializers.ModelSerializer):
    source_url = serializers.CharField(source="source.url", read_only=True)
    source_title = serializers.CharField(source="source.title", read_only=True)

    class Meta:
        model = Evidence
        fields = [
            "id",
            "source",
            "source_url",
            "source_title",
            "sub_question",
            "quote",
            "char_start",
            "char_end",
            "locator",
            "created_at",
        ]


class ClaimSerializer(serializers.ModelSerializer):
    evidence_ids = serializers.SerializerMethodField()

    class Meta:
        model = Claim
        fields = [
            "id",
            "sub_question",
            "text",
            "status",
            "confidence",
            "evidence_ids",
            "created_at",
            "updated_at",
        ]

    def get_evidence_ids(self, obj) -> list[int]:
        return [link.evidence_id for link in obj.links.all()]


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = [
            "version",
            "content_md",
            "citations",
            "validation",
            "model",
            "generated_at",
        ]


class AgentStepSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentStep
        fields = [
            "step_no",
            "step_type",
            "tool_name",
            "tool_signature",
            "input",
            "output",
            "status",
            "error",
            "latency_ms",
            "created_at",
        ]


class TaskEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskEvent
        fields = ["id", "kind", "message", "payload", "created_at"]


class LLMUsageSerializer(serializers.ModelSerializer):
    total_tokens = serializers.IntegerField(read_only=True)

    class Meta:
        model = LLMUsage
        fields = [
            "id",
            "purpose",
            "model",
            "prompt_tokens",
            "completion_tokens",
            "cached_tokens",
            "total_tokens",
            "latency_ms",
            "ok",
            "created_at",
        ]
