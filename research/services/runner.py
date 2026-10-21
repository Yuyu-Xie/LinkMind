from __future__ import annotations

import json
import logging
import os
import socket
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Max
from django.utils import timezone

from research.agent.context import ContextBuilder
from research.agent.llm_client import (
    LLMAuthError,
    LLMError,
    RetryableLLMError,
    get_llm_client,
)
from research.agent.prompts import PLAN_SYSTEM, plan_user_prompt
from research.agent.schemas import TOOL_SCHEMAS
from research.models import (
    AgentStep,
    ResearchTask,
    SubQuestion,
    TaskEvent,
)
from research.services.coverage import recompute_progress
from research.services.report import generate_report
from research.services.usage import record_usage
from research.tools.registry import execute_tool, tool_signature

logger = logging.getLogger("research")

RETRY_DELAYS = [15, 45, 135]
MAX_CONSECUTIVE_TOOL_ERRORS = 3
NO_PROGRESS_HINT_AT = 3
NO_PROGRESS_STOP_AT = 6


def _lease_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _next_step_no(task: ResearchTask) -> int:
    current = task.steps.aggregate(value=Max("step_no"))["value"] or 0
    return current + 1


def _add_step(task: ResearchTask, step_type: str, **kwargs) -> AgentStep:
    return AgentStep.objects.create(
        task=task, step_no=_next_step_no(task), step_type=step_type, **kwargs
    )


def heartbeat(task: ResearchTask) -> None:
    now = timezone.now()
    ResearchTask.objects.filter(pk=task.pk).update(
        heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=settings.RESEARCH_LEASE_SECONDS),
    )
    task.heartbeat_at = now
    task.lease_expires_at = now + timedelta(seconds=settings.RESEARCH_LEASE_SECONDS)


def release_lease(task: ResearchTask) -> None:
    ResearchTask.objects.filter(pk=task.pk).update(lease_owner="", lease_expires_at=None)


def claim_task(task_id: int) -> ResearchTask | None:
    task = ResearchTask.objects.filter(pk=task_id).first()
    if task is None or task.status != ResearchTask.STATUS_PENDING:
        return None

    now = timezone.now()
    owner = _lease_owner()
    update = {
        "status": ResearchTask.STATUS_RUNNING,
        "lease_owner": owner,
        "lease_expires_at": now + timedelta(seconds=settings.RESEARCH_LEASE_SECONDS),
        "heartbeat_at": now,
        "updated_at": now,
    }
    if task.started_at is None:
        update["started_at"] = now
    if task.deadline_at is None:
        update["deadline_at"] = now + timedelta(seconds=task.timeout_seconds)

    updated = ResearchTask.objects.filter(
        pk=task_id, status=ResearchTask.STATUS_PENDING
    ).update(**update)
    if not updated:
        return None

    task.refresh_from_db()
    TaskEvent.objects.create(
        task=task,
        kind="lease",
        message=f"worker {owner} 取得任务",
        payload={"attempt": task.attempt},
    )
    return task


def create_plan(task: ResearchTask, llm) -> None:
    messages = [
        {"role": "system", "content": PLAN_SYSTEM},
        {"role": "user", "content": plan_user_prompt(task.question)},
    ]
    try:
        response = llm.chat(
            messages,
            temperature=0,
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        record_usage(task, "plan", response)
        payload = json.loads(response.content)
        items = payload.get("sub_questions") or []
        questions = [str(item).strip() for item in items if str(item).strip()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("plan generation failed, falling back: %s", exc)
        questions = [task.question]
        payload = {"fallback": True, "error": str(exc)[:300]}

    if not questions:
        questions = [task.question]
    questions = questions[:5]

    SubQuestion.objects.filter(task=task).delete()
    SubQuestion.objects.bulk_create(
        [
            SubQuestion(task=task, order=index + 1, question=question)
            for index, question in enumerate(questions)
        ]
    )
    task.plan_raw = payload if isinstance(payload, dict) else {"raw": payload}
    task.phase = ResearchTask.PHASE_RESEARCHING
    task.save(update_fields=["plan_raw", "phase", "updated_at"])
    TaskEvent.objects.create(
        task=task,
        kind="plan",
        message=f"生成 {len(questions)} 个子问题",
        payload={"questions": questions},
    )
    recompute_progress(task)


def _canceled(task: ResearchTask) -> bool:
    task.refresh_from_db(fields=["cancel_requested_at", "status"])
    return bool(task.cancel_requested_at) or task.status == ResearchTask.STATUS_CANCELED


def _finalize_canceled(task: ResearchTask) -> None:
    task.completion_reason = ResearchTask.COMPLETION_CANCELED
    task.is_partial = True
    task.save(update_fields=["completion_reason", "is_partial", "updated_at"])
    try:
        generate_report(task, llm=None, reason="用户取消")
        recompute_progress(task, has_report=True)
    except Exception:  # noqa: BLE001
        logger.exception("fallback report failed during cancel")
    task.transition(ResearchTask.STATUS_CANCELED, reason="用户取消")


def _finalize_timed_out(task: ResearchTask) -> None:
    task.completion_reason = ResearchTask.COMPLETION_DEADLINE
    task.is_partial = True
    task.save(update_fields=["completion_reason", "is_partial", "updated_at"])
    try:
        generate_report(task, llm=None, reason="任务超时")
        recompute_progress(task, has_report=True)
    except Exception:  # noqa: BLE001
        logger.exception("fallback report failed during timeout")
    task.transition(ResearchTask.STATUS_TIMED_OUT, reason="超过执行时限")


def _finalize_completed(task: ResearchTask, reason: str, llm) -> None:
    task.completion_reason = reason
    task.is_partial = reason != ResearchTask.COMPLETION_MODEL_FINISH
    task.save(update_fields=["completion_reason", "is_partial", "updated_at"])
    try:
        generate_report(task, llm=llm, reason=reason)
        recompute_progress(task, has_report=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("report generation failed")
        task.error = f"报告生成失败: {exc}"
        task.save(update_fields=["error", "updated_at"])
    task.transition(ResearchTask.STATUS_COMPLETED, reason=reason)


def _finalize_failed(task: ResearchTask, error: str) -> None:
    task.refresh_from_db(fields=["status"])
    if task.status == ResearchTask.STATUS_CANCELED:
        return
    task.completion_reason = ResearchTask.COMPLETION_ERROR
    task.is_partial = True
    task.save(update_fields=["completion_reason", "is_partial", "updated_at"])
    try:
        generate_report(task, llm=None, reason=f"任务失败：{error[:200]}")
        recompute_progress(task, has_report=True)
    except Exception:  # noqa: BLE001
        logger.exception("fallback report failed during failure")
    task.transition(ResearchTask.STATUS_FAILED, reason="任务失败", error=error)


def schedule_retry(task: ResearchTask, error: str, retry_enabled: bool = True) -> None:
    task.refresh_from_db()
    attempt = task.attempt + 1
    if attempt >= task.max_attempts:
        _finalize_failed(task, f"重试次数耗尽：{error}")
        return

    if not retry_enabled:
        _finalize_failed(task, error)
        return

    task.transition(ResearchTask.STATUS_PENDING, reason=f"第 {attempt} 次重试")
    ResearchTask.objects.filter(pk=task.pk).update(
        attempt=attempt,
        error=error[:4000],
        lease_owner="",
        lease_expires_at=None,
    )
    delay = RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
    TaskEvent.objects.create(
        task=task,
        kind="retry",
        message=f"{delay}s 后重试：{error[:300]}",
        payload={"attempt": attempt, "delay": delay},
    )
    logger.warning("task %s scheduled retry %s in %ss: %s", task.pk, attempt, delay, error)

    from research.tasks import run_research_task

    transaction.on_commit(
        lambda: run_research_task.schedule(args=(task.pk,), delay=delay)
    )


def _sub_question_state(task: ResearchTask) -> tuple[int, int, int]:
    return (
        task.evidence.count(),
        task.claims.count(),
        task.sub_questions.exclude(status=SubQuestion.STATUS_PENDING).count(),
    )


def _run_loop(task: ResearchTask, llm, retry_enabled: bool) -> str:
    no_progress = 0
    consecutive_tool_errors = 0
    completion_reason = ""

    while True:
        close_old_connections()
        task.refresh_from_db()
        if _canceled(task):
            _finalize_canceled(task)
            return ResearchTask.STATUS_CANCELED

        if task.deadline_at and timezone.now() >= task.deadline_at:
            _finalize_timed_out(task)
            return ResearchTask.STATUS_TIMED_OUT

        turns_used = task.steps.filter(step_type=AgentStep.TYPE_THOUGHT).count()
        if turns_used >= task.max_steps:
            completion_reason = ResearchTask.COMPLETION_MAX_STEPS
            break
        if task.tokens_used >= task.budget_tokens:
            completion_reason = ResearchTask.COMPLETION_BUDGET
            break

        heartbeat(task)
        before = _sub_question_state(task)
        messages = ContextBuilder(task).build()

        try:
            response = llm.chat(
                messages,
                tools=TOOL_SCHEMAS,
                temperature=0,
                max_tokens=1500,
            )
        except RetryableLLMError as exc:
            schedule_retry(task, str(exc), retry_enabled=retry_enabled)
            return "retry"
        except LLMAuthError as exc:
            _finalize_failed(task, str(exc))
            return ResearchTask.STATUS_FAILED
        except LLMError as exc:
            _finalize_failed(task, str(exc))
            return ResearchTask.STATUS_FAILED

        thought = _add_step(
            task,
            AgentStep.TYPE_THOUGHT,
            output={"content": response.content, "tool_calls": len(response.tool_calls)},
        )
        record_usage(task, "agent", response, step=thought)

        calls = response.tool_calls[:2]
        if not calls:
            no_progress += 1
            if no_progress >= NO_PROGRESS_HINT_AT:
                TaskEvent.objects.create(
                    task=task,
                    kind="recovery_hint",
                    message="模型没有调用工具。请选择一个工具推进当前子问题，或调用 finish_research。",
                )
            if no_progress >= NO_PROGRESS_STOP_AT:
                completion_reason = ResearchTask.COMPLETION_NO_PROGRESS
                break
            continue

        finish_ok = False
        for call in calls:
            if call.parse_error:
                _add_step(
                    task,
                    AgentStep.TYPE_TOOL_CALL,
                    tool_name=call.name,
                    tool_signature=tool_signature(call.name, call.arguments),
                    input={"raw": call.raw_arguments},
                    status=AgentStep.STATUS_ERROR,
                    error=f"参数 JSON 解析失败: {call.parse_error}",
                )
                consecutive_tool_errors += 1
                no_progress += 1
                continue

            signature = tool_signature(call.name, call.arguments)
            _add_step(
                task,
                AgentStep.TYPE_TOOL_CALL,
                tool_name=call.name,
                tool_signature=signature,
                input=call.arguments,
            )

            if _canceled(task):
                _finalize_canceled(task)
                return ResearchTask.STATUS_CANCELED

            result, latency_ms = execute_tool(
                task,
                call.name,
                call.arguments,
                offline=bool(task.options.get("offline")),
            )
            _add_step(
                task,
                AgentStep.TYPE_TOOL_RESULT,
                tool_name=call.name,
                tool_signature=signature,
                input=call.arguments,
                output=result.to_dict(),
                status=(
                    AgentStep.STATUS_REUSED
                    if result.reused
                    else AgentStep.STATUS_OK
                    if result.ok
                    else AgentStep.STATUS_ERROR
                ),
                error="" if result.ok else result.message,
                latency_ms=latency_ms,
            )

            if result.ok:
                consecutive_tool_errors = 0
                if call.name == "finish_research":
                    finish_ok = True
            else:
                consecutive_tool_errors += 1
                no_progress += 1
                TaskEvent.objects.create(
                    task=task,
                    kind="tool_error",
                    message=f"{call.name} 失败：{result.message} {result.hint}".strip(),
                    payload={"error_code": result.error_code},
                )

            if consecutive_tool_errors >= MAX_CONSECUTIVE_TOOL_ERRORS:
                _finalize_failed(task, "连续 3 次工具调用失败")
                return ResearchTask.STATUS_FAILED

        if finish_ok:
            completion_reason = ResearchTask.COMPLETION_MODEL_FINISH
            break

        after = _sub_question_state(task)
        if after > before:
            no_progress = 0
        else:
            no_progress += 1
            if no_progress == NO_PROGRESS_HINT_AT:
                TaskEvent.objects.create(
                    task=task,
                    kind="recovery_hint",
                    message=(
                        "连续几步没有新增证据或主张。改写检索词、读取新来源，"
                        "或把当前子问题标记为 insufficient 后继续其他子问题。"
                    ),
                )
            if no_progress >= NO_PROGRESS_STOP_AT:
                completion_reason = ResearchTask.COMPLETION_NO_PROGRESS
                break

        recompute_progress(task)

    _finalize_completed(task, completion_reason, llm)
    return ResearchTask.STATUS_COMPLETED


def run_task(task_id: int, llm=None, retry_enabled: bool = True) -> str | None:
    task = claim_task(task_id)
    if task is None:
        logger.info("task %s is not pending, skip", task_id)
        return None

    llm = llm or get_llm_client()
    try:
        if task.phase == ResearchTask.PHASE_PLANNING:
            create_plan(task, llm)
        return _run_loop(task, llm, retry_enabled)
    except RetryableLLMError as exc:
        schedule_retry(task, str(exc), retry_enabled=retry_enabled)
        return "retry"
    except Exception as exc:  # noqa: BLE001
        logger.exception("task %s crashed", task_id)
        _finalize_failed(task, str(exc))
        return ResearchTask.STATUS_FAILED
    finally:
        release_lease(task)
        close_old_connections()


def recover_stale_tasks() -> int:
    now = timezone.now()
    stale = ResearchTask.objects.filter(
        status=ResearchTask.STATUS_RUNNING, lease_expires_at__lt=now
    )
    count = 0
    for task in stale:
        logger.warning("recovering stale task %s", task.pk)
        attempt = task.attempt + 1
        if attempt >= task.max_attempts:
            _finalize_failed(
                task, f"worker 租约过期且重试次数耗尽（{attempt}/{task.max_attempts}）"
            )
            continue
        task.transition(
            ResearchTask.STATUS_PENDING, reason="worker 租约过期，重新排队"
        )
        ResearchTask.objects.filter(pk=task.pk).update(
            attempt=attempt,
            lease_owner="",
            lease_expires_at=None,
            error="worker 租约过期",
        )
        TaskEvent.objects.create(
            task=task, kind="recovery", message="检测到租约过期，重新入队"
        )
        from research.tasks import run_research_task

        transaction.on_commit(lambda pk=task.pk: run_research_task(pk))
        count += 1
    return count
