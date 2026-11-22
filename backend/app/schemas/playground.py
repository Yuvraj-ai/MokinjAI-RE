"""Playground session schemas (plan Task 2)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.output_formats import ALL_OUTPUT_FORMATS, DEFAULT_OUTPUT_FORMAT


class ChatSessionCreate(BaseModel):
    agent_id: str


class ChatSessionUpdate(BaseModel):
    title: str | None = None


class ChatSessionResponse(BaseModel):
    id: str
    workspace_id: str
    agent_id: str
    title: str
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionResponse]
    total: int


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    reasoning: str | None
    activity: list[dict[str, Any]] | None
    structured: dict[str, Any] | None
    status: str | None
    usage: dict[str, Any] | None
    cost_usd: float | None
    execution_id: str | None
    # How the reply was generated (and so how to render it). Rows from before
    # the feature have none and read as Markdown.
    output_format: str = DEFAULT_OUTPUT_FORMAT
    created_at: datetime


class ChatSessionDetailResponse(ChatSessionResponse):
    messages: list[ChatMessageResponse]


class PlaygroundChatRequest(BaseModel):
    # The same 32 000-char bound the old agents chat path enforced.
    content: str = Field(min_length=1, max_length=32_000)
    # What the model is asked to generate for this turn. Validated against the
    # agent's current model in the router; omitted means Markdown.
    output_format: str = DEFAULT_OUTPUT_FORMAT

    @field_validator("output_format")
    @classmethod
    def known_output_format(cls, value: str) -> str:
        if value not in ALL_OUTPUT_FORMATS:
            raise ValueError(f"output_format must be one of {', '.join(ALL_OUTPUT_FORMATS)}")
        return value

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("the message cannot be empty")
        return value
