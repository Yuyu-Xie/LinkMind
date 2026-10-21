from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from django.conf import settings
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

logger = logging.getLogger("research")


class LLMError(Exception):
    pass


class LLMAuthError(LLMError):
    pass


class RetryableLLMError(LLMError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    raw_arguments: str = ""
    parse_error: str = ""


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    latency_ms: int = 0


def _repair_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("响应中没有 JSON 对象")
    return json.loads(text[start : end + 1])


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self.api_key = api_key if api_key is not None else settings.DEEPSEEK_API_KEY
        self.base_url = base_url or settings.DEEPSEEK_BASE_URL
        self.model = model or settings.DEEPSEEK_MODEL
        self.timeout = timeout or settings.DEEPSEEK_TIMEOUT
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _get_client(self) -> OpenAI:
        if not self.api_key:
            raise LLMAuthError("未配置 DEEPSEEK_API_KEY，请写入 .env")
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0,
            )
        return self._client

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: dict | None = None,
        timeout: float | None = None,
    ) -> LLMResponse:
        client = self._get_client()
        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if response_format:
            kwargs["response_format"] = response_format
        if timeout:
            kwargs["timeout"] = timeout

        last_error: Exception | None = None
        for attempt in range(3):
            started = time.monotonic()
            try:
                response = client.chat.completions.create(**kwargs)
                latency_ms = int((time.monotonic() - started) * 1000)
                return self._parse_response(response, latency_ms)
            except AuthenticationError as exc:
                raise LLMAuthError(f"DeepSeek 鉴权失败: {exc}") from exc
            except BadRequestError as exc:
                raise LLMError(f"DeepSeek 请求非法: {exc}") from exc
            except (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError) as exc:
                last_error = exc
                logger.warning("LLM 调用失败（第 %s 次）: %s", attempt + 1, exc)
                if attempt < 2:
                    time.sleep(2**attempt)
            except APIStatusError as exc:
                if exc.status_code >= 500:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(2**attempt)
                        continue
                raise LLMError(f"DeepSeek 返回 {exc.status_code}: {exc}") from exc

        raise RetryableLLMError(f"LLM 调用重试耗尽: {last_error}")

    def _parse_response(self, response, latency_ms: int) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message
        usage = Usage()
        raw_usage = getattr(response, "usage", None)
        if raw_usage:
            usage.prompt_tokens = getattr(raw_usage, "prompt_tokens", 0) or 0
            usage.completion_tokens = getattr(raw_usage, "completion_tokens", 0) or 0
            usage.cached_tokens = getattr(raw_usage, "prompt_cache_hit_tokens", 0) or 0
            details = getattr(raw_usage, "prompt_tokens_details", None)
            if details and not usage.cached_tokens:
                usage.cached_tokens = getattr(details, "cached_tokens", 0) or 0

        tool_calls: list[ToolCall] = []
        for item in getattr(message, "tool_calls", None) or []:
            raw_arguments = item.function.arguments or "{}"
            parse_error = ""
            try:
                arguments = _repair_json(raw_arguments)
            except (ValueError, json.JSONDecodeError) as exc:
                arguments = {}
                parse_error = str(exc)
            tool_calls.append(
                ToolCall(
                    id=item.id,
                    name=item.function.name,
                    arguments=arguments,
                    raw_arguments=raw_arguments,
                    parse_error=parse_error,
                )
            )

        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            usage=usage,
            model=getattr(response, "model", self.model),
            latency_ms=latency_ms,
        )


def get_llm_client() -> LLMClient:
    return LLMClient()
