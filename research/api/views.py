from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from research.api.serializers import (
    AgentStepSerializer,
    ClaimSerializer,
    EvidenceSerializer,
    LLMUsageSerializer,
    ReportSerializer,
    ResearchTaskCreateSerializer,
    ResearchTaskDetailSerializer,
    ResearchTaskListSerializer,
    SourceSerializer,
    SubQuestionSerializer,
    TaskEventSerializer,
)
from research.models import Report, ResearchTask
from research.tasks import run_research_task


class ResearchTaskViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    def get_queryset(self):
        queryset = ResearchTask.objects.filter(owner=self.request.user)
        status_filter = self.request.query_params.get("status", "")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        strategy = self.request.query_params.get("strategy", "")
        if strategy:
            queryset = queryset.filter(strategy=strategy)
        return queryset

    def get_serializer_class(self):
        if self.action == "create":
            return ResearchTaskCreateSerializer
        if self.action == "list":
            return ResearchTaskListSerializer
        return ResearchTaskDetailSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save()
        task_id = task.pk
        transaction.on_commit(lambda: run_research_task(task_id))
        output = ResearchTaskDetailSerializer(task).data
        return Response(output, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        task = self.get_object()
        if task.is_terminal:
            return Response(
                {"detail": f"任务已处于终态 {task.status}，无法取消"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        task.request_cancel()
        return Response({"status": task.status, "cancel_requested": True})

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        task = self.get_object()
        if task.status != ResearchTask.STATUS_FAILED:
            return Response(
                {"detail": f"只有失败的任务可以重试，当前为 {task.status}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
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
        task.refresh_from_db()
        task_id = task.pk
        transaction.on_commit(lambda: run_research_task(task_id))
        return Response(ResearchTaskDetailSerializer(task).data)

    @action(detail=True, methods=["get"])
    def steps(self, request, pk=None):
        task = self.get_object()
        queryset = task.steps.all()
        page = self.paginate_queryset(queryset)
        serializer = AgentStepSerializer(page or queryset, many=True)
        return (
            self.get_paginated_response(serializer.data)
            if page is not None
            else Response(serializer.data)
        )

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        task = self.get_object()
        return Response(TaskEventSerializer(task.events.all(), many=True).data)

    @action(detail=True, methods=["get"])
    def subquestions(self, request, pk=None):
        task = self.get_object()
        return Response(
            SubQuestionSerializer(task.sub_questions.all(), many=True).data
        )

    @action(detail=True, methods=["get"])
    def sources(self, request, pk=None):
        task = self.get_object()
        return Response(SourceSerializer(task.sources.all(), many=True).data)

    @action(detail=True, methods=["get"])
    def evidence(self, request, pk=None):
        task = self.get_object()
        queryset = task.evidence.select_related("source").all()
        return Response(EvidenceSerializer(queryset, many=True).data)

    @action(detail=True, methods=["get"])
    def claims(self, request, pk=None):
        task = self.get_object()
        queryset = task.claims.prefetch_related("links").all()
        return Response(ClaimSerializer(queryset, many=True).data)

    @action(detail=True, methods=["get"])
    def report(self, request, pk=None):
        task = self.get_object()
        report = get_object_or_404(Report, task=task)
        return Response(ReportSerializer(report).data)

    @action(detail=True, methods=["get"])
    def usage(self, request, pk=None):
        task = self.get_object()
        return Response(LLMUsageSerializer(task.llm_usage.all(), many=True).data)
