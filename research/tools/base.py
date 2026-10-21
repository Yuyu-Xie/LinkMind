from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolContext:
    task: object
    offline: bool = False


@dataclass
class ToolResult:
    ok: bool
    data: dict = field(default_factory=dict)
    message: str = ""
    hint: str = ""
    error_code: str = ""
    reused: bool = False

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "data": self.data,
            "message": self.message,
            "hint": self.hint,
            "error_code": self.error_code,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> ToolResult:
        return cls(
            ok=payload.get("ok", False),
            data=payload.get("data", {}),
            message=payload.get("message", ""),
            hint=payload.get("hint", ""),
            error_code=payload.get("error_code", ""),
        )


class ToolError(Exception):
    def __init__(self, error_code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.hint = hint
