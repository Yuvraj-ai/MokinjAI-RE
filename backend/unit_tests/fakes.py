"""Reusable test doubles for agent runs."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    """Non-streaming chat model that replays a fixed list of AIMessages.

    `GenericFakeChatModel` drops tool calls when streaming and rejects empty
    content, so tool-call messages should carry non-empty content.
    """

    script: list[Any]

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        message: AIMessage = self.script.pop(0)
        return ChatResult(generations=[ChatGeneration(message=message)])


def tool_call_message(name: str, call_id: str, args: dict | None = None) -> AIMessage:
    return AIMessage(
        content="calling",
        tool_calls=[{"name": name, "args": args or {}, "id": call_id}],
    )
