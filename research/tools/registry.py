from __future__ import annotations

import hashlib
import json
import logging
import time

from pydantic import ValidationError

from research.agent.schemas import ARG_MODELS
from research.models import ToolCallCache
from research.tools import bookmarks, claims, evidence, finish, reader, web
from research.tools.base import ToolContext, ToolError, ToolResult

logger = logging.getLogger("research")

HANDLERS = {
    "search_bookmarks": (bookmarks.search_bookmarks, True),
    "web_search": (web.search_web, True),
    "read_document": (reader.read_document, True),
    "extract_evidence": (evidence.extract_evidence, True),
    "add_claim": (claims.add_claim, False),
    "answer_subquestion": (claims.answer_subquestion, False),
    "finish_research": (finish.finish_research, False),
}


def canonical_args(args: dict) -> str:
    return json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def args_hash(args: dict) -> str:
    return hashlib.sha256(canonical_args(args).encode("utf-8")).hexdigest()


def tool_signature(name: str, args: dict) -> str:
    return hashlib.sha256(f"{name}:{args_hash(args)}".encode()).hexdigest()


def execute_tool(
    task, name: str, args: dict, offline: bool = False
) -> tuple[ToolResult, int]:
    """Execute one tool call. Returns (result, latency_ms)."""
    started = time.monotonic()
    entry = HANDLERS.get(name)
    if entry is None:
        return (
            ToolResult(
                ok=False,
                error_code="unknown_tool",
                message=f"未知工具: {name}",
                hint="只能使用已声明的工具。",
            ),
            0,
        )

    handler, reusable = entry
    model = ARG_MODELS[name]
    try:
        validated = model(**args)
    except ValidationError as exc:
        return (
            ToolResult(
                ok=False,
                error_code="invalid_args",
                message=f"工具参数不合法: {exc.errors()}",
                hint="修正参数后重试，不要重复完全相同调用。",
            ),
            int((time.monotonic() - started) * 1000),
        )

    data = validated.model_dump()
    digest = args_hash(data)

    if reusable:
        cached = ToolCallCache.objects.filter(
            task=task, tool_name=name, args_hash=digest
        ).first()
        if cached:
            result = ToolResult.from_dict(cached.result)
            result.reused = True
            result.message = f"命中缓存：{result.message}"
            return result, int((time.monotonic() - started) * 1000)

    ctx = ToolContext(task=task, offline=offline)
    try:
        result = handler(ctx, **data)
    except ToolError as exc:
        result = ToolResult(
            ok=False, error_code=exc.error_code, message=exc.message, hint=exc.hint
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("tool %s crashed", name)
        result = ToolResult(
            ok=False,
            error_code="internal_error",
            message=f"工具执行异常: {exc}",
            hint="换一种方式完成当前步骤。",
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    if reusable and result.ok:
        ToolCallCache.objects.get_or_create(
            task=task,
            tool_name=name,
            args_hash=digest,
            defaults={"result": result.to_dict()},
        )
    return result, latency_ms
