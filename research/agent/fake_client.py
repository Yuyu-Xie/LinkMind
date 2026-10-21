"""Deterministic LLM double used by tests and local demos without an API key."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from research.agent.llm_client import LLMResponse, ToolCall, Usage


def tool_call(name: str, call_id: str | None = None, **arguments) -> ToolCall:
    digest = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
    return ToolCall(
        id=call_id or f"call_{name}_{abs(hash((name, digest)))}",
        name=name,
        arguments=arguments,
        raw_arguments="{}",
    )


def tool_response(*calls: ToolCall, content: str = "") -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=list(calls),
        usage=Usage(prompt_tokens=800, completion_tokens=120),
        model="fake",
        latency_ms=5,
    )


def text_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        usage=Usage(prompt_tokens=500, completion_tokens=200),
        model="fake",
        latency_ms=5,
    )


@dataclass
class FakeLLMClient:
    responses: list = field(default_factory=list)
    handler: Callable | None = None
    calls: list = field(default_factory=list)

    def chat(self, messages, tools=None, **kwargs) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, **kwargs})
        if self.handler is not None:
            response = self.handler(messages, tools)
        elif self.responses:
            response = self.responses.pop(0)
        else:
            raise AssertionError("FakeLLMClient 响应已耗尽")

        if callable(response):
            response = response(messages, tools)
        if isinstance(response, str):
            response = text_response(response)
        return response
