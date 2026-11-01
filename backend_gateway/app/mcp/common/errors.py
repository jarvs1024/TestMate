"""Safe public errors for MCP tool execution."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException


@dataclass(frozen=True, slots=True)
class SafeError:
    """An audit-safe code and a caller-safe message."""

    code: str
    message: str


class McpRuntimeError(Exception):
    """An expected runtime failure whose message is safe to return."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def safe_error(exc: Exception) -> SafeError:
    """Discard exception details that may contain SQL, secrets, or arguments."""
    if isinstance(exc, McpRuntimeError):
        return SafeError(exc.code, exc.message)
    if isinstance(exc, HTTPException):
        return SafeError(
            f"http_{exc.status_code}",
            f"Tool request failed (HTTP {exc.status_code}).",
        )
    return SafeError(type(exc).__name__, "Tool execution failed.")
