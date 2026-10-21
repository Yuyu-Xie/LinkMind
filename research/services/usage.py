from django.db.models import F

from research.models import AgentStep, LLMUsage, ResearchTask


def record_usage(
    task: ResearchTask,
    purpose: str,
    response,
    step: AgentStep | None = None,
    ok: bool = True,
) -> LLMUsage:
    usage = response.usage
    record = LLMUsage.objects.create(
        task=task,
        step=step,
        purpose=purpose,
        model=response.model,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        cached_tokens=usage.cached_tokens,
        latency_ms=response.latency_ms,
        ok=ok,
    )
    ResearchTask.objects.filter(pk=task.pk).update(
        tokens_used=F("tokens_used") + usage.total
    )
    task.refresh_from_db(fields=["tokens_used"])
    return record
