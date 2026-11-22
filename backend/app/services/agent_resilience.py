"""Fail-safe settings and tool middleware for agent runs.

A tool that raises must not crash the run. Transient errors are retried, every
other failure goes back to the model as an error `ToolMessage`, and a tool that
keeps failing is switched off for the rest of the run. All values here are global,
not per agent.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
from langchain.agents.middleware import ToolErrorMiddleware, ToolRetryMiddleware
from langchain.agents.middleware.types import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage

from app.logging import logger

TOOL_MAX_RETRIES = 2
TOOL_RETRY_INITIAL_DELAY_S = 1.0
TOOL_RETRY_BACKOFF = 2.0
TOOL_RETRY_MAX_DELAY_S = 4.0
TOOL_FAILURE_LIMIT_PER_RUN = 3
TOOL_BLOCKED_MESSAGE = (
    "This tool is not available right now. Continue without it or tell the user."
)

# Sandbox queue limits (used by the sandbox session, per workspace).
SANDBOX_QUEUE_MAX_WAIT_S = 120
SANDBOX_QUEUE_MAX_WAITERS = 20

_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
_MAX_MESSAGE_CHARS = 300
_URL_CREDENTIALS = re.compile(r"://[^@/\s]+@")


def _status_code(exc: BaseException) -> int | None:
    code = getattr(exc, "status_code", None)
    if code is None:
        code = getattr(getattr(exc, "response", None), "status_code", None)
    return code if isinstance(code, int) else None


def is_transient(exc: BaseException) -> bool:
    """True for errors worth retrying: timeouts, connection and transport faults, 429/5xx."""
    if isinstance(
        exc, (TimeoutError, asyncio.TimeoutError, ConnectionError, httpx.TransportError)
    ):
        return True
    return _status_code(exc) in _TRANSIENT_STATUS


def _short_message(exc: BaseException) -> str:
    text = _URL_CREDENTIALS.sub("://***@", " ".join(str(exc).split()))
    if len(text) > _MAX_MESSAGE_CHARS:
        text = text[: _MAX_MESSAGE_CHARS - 3] + "..."
    return text


def tool_error_message(exc: Exception, request: ToolCallRequest) -> str:
    """Log one warning (no traceback) and return the text the model will see."""
    name = request.tool.name if request.tool else request.tool_call["name"]
    message = _short_message(exc)
    kind = type(exc).__name__
    logger.warning("Tool %s failed: %s: %s", name, kind, message)
    return (
        f"`{name}` failed ({kind}): {message}. "
        "It is not available right now; continue without it or tell the user."
    )


class ToolFailureLimitMiddleware(AgentMiddleware):
    """Stop running a tool once it has failed `TOOL_FAILURE_LIMIT_PER_RUN` times.

    Only calls whose final result is an error `ToolMessage` count, so place this
    outside `ToolErrorMiddleware`. Counts live on the instance; build a new one
    for every graph so they reset each run.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tools = []
        self._failures: dict[str, int] = {}

    @staticmethod
    def _name(request: ToolCallRequest) -> str:
        return request.tool.name if request.tool else request.tool_call["name"]

    def _blocked(self, request: ToolCallRequest) -> ToolMessage | None:
        name = self._name(request)
        if self._failures.get(name, 0) < TOOL_FAILURE_LIMIT_PER_RUN:
            return None
        return ToolMessage(
            content=TOOL_BLOCKED_MESSAGE,
            tool_call_id=request.tool_call["id"],
            name=name,
            status="error",
        )

    def _record(self, request: ToolCallRequest, result: Any) -> None:
        if isinstance(result, ToolMessage) and result.status == "error":
            name = self._name(request)
            self._failures[name] = self._failures.get(name, 0) + 1

    def wrap_tool_call(self, request, handler):
        blocked = self._blocked(request)
        if blocked is not None:
            return blocked
        result = handler(request)
        self._record(request, result)
        return result

    async def awrap_tool_call(self, request, handler):
        blocked = self._blocked(request)
        if blocked is not None:
            return blocked
        result = await handler(request)
        self._record(request, result)
        return result


def tool_middleware() -> list[AgentMiddleware]:
    """A fresh stack, outermost first: failure limit, error to model, retry."""
    return [
        ToolFailureLimitMiddleware(),
        ToolErrorMiddleware(on_error=tool_error_message),
        ToolRetryMiddleware(
            max_retries=TOOL_MAX_RETRIES,
            retry_on=is_transient,
            on_failure="error",
            backoff_factor=TOOL_RETRY_BACKOFF,
            initial_delay=TOOL_RETRY_INITIAL_DELAY_S,
            max_delay=TOOL_RETRY_MAX_DELAY_S,
            jitter=True,
        ),
    ]
