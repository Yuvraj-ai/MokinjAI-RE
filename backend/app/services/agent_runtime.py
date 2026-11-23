"""Build one agent from its saved configuration and stream a chat run.

This is the only place that turns a validated agent into LangChain objects. It
uses `create_agent` rather than a hand-written loop, `create_agent`'s built-in
tool-dict support for provider-native search, and the existing sandbox/connector
services for execution.

One run is one `Execution` row with `trigger_type="chat"`; the chat history is
sent by the client each turn (no conversation tables).
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, AsyncIterator

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from sqlalchemy import select

from app.crypto import decrypt_api_key
from app.services.agent_resilience import short_message, tool_middleware
from app.database import async_session
from app.logging import logger
from app.models.agent import Agent
from app.models.chat import ChatMessage, ChatSession
from app.models.execution import Execution
from app.models.knowledge import Document
from app.models.llm_profile import LlmProfile
from app.models.resource_usage import bump_usage
from app.models.search_credential import SearchCredential
from app.services.agent_composition import (
    CompositionError,
    ValidatedAgent,
    saved_input,
    validate_agent,
)
from app.services.agent_dependencies import DEFAULT_MAX_SUBAGENT_DEPTH
from app.services.agent_tools import (
    describe_data_source_tool,
    query_data_source_tool,
    query_document_data_source_tool,
    read_skill_tool,
    sandbox_python_tool,
    subagent_tool,
    user_tool,
)
from app.services.connector_runtime import load_connector_tools
from app.services.output_formats import (
    DEFAULT_OUTPUT_FORMAT,
    OPENUI,
    UnsupportedOutputFormat,
    openui_prompt,
    require_supported,
)
from app.services.sandbox import InMemoryToolSource, SandboxConfig, SandboxSession
from app.services.sandbox.budget import release, reserve
from app.services.storage import StorageError, get_storage
from app.services.tool_schema import extract_schema, extraction_error
from app.services.web_search import build_web_search_tool, native_web_search_spec
from app.tools.registry import list_builtin_tools


class AgentRuntimeError(Exception):
    """A saved agent cannot be run as configured."""


# Playground activity caps (spec §4): one serialized args/result per event,
# reasoning text, and the number of events kept for a single turn.
ACTIVITY_VALUE_CAP = 8_000
REASONING_CAP = 32_000
ACTIVITY_EVENT_CAP = 200

_TRUNCATION_MARKER = "...[truncated]"


def _tool_kind(name: str) -> str:
    """Card family for a tool name (spec §6). Connector and user tools are
    indistinguishable by name alone and both land on the generic `tool` card;
    attribution by build-time data is a future refinement."""
    lowered = (name or "").lower()
    if lowered in ("query_data_source", "describe_data_source"):
        return "sql"
    if lowered == "execute_python":
        return "code"
    if lowered == "read_skill":
        return "skill"
    if "tavily" in lowered or "exa" in lowered or lowered == "web_search":
        return "web"
    if lowered.startswith("ask_"):
        return "subagent"
    return "tool"


def _reasoning_delta(chunk: Any) -> str:
    """Thinking text carried by a stream chunk, across provider shapes.

    Anthropic emits content blocks with type `thinking`; OpenAI-compatible
    endpoints (DeepSeek-style) put `reasoning_content` in additional_kwargs.
    Providers that emit neither simply never populate the thinking card.
    """
    parts: list[str] = []
    content = getattr(chunk, "content", None)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in ("thinking", "reasoning"):
                text = block.get("thinking") or block.get("text") or block.get("reasoning")
                if text:
                    parts.append(str(text))
    kwargs = getattr(chunk, "additional_kwargs", None)
    if isinstance(kwargs, dict):
        value = kwargs.get("reasoning_content") or kwargs.get("reasoning")
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            text = value.get("text") or value.get("content")
            if text:
                parts.append(str(text))
    return "".join(parts)


def _cap(value: Any, limit: int = ACTIVITY_VALUE_CAP) -> Any:
    """Bound a persisted/streamed value: past the limit, keep a truncated
    prefix — parsed back when it still parses, as text otherwise.

    Always returns plain JSON types: the result is stored in a JSONB column
    whose serializer has no `default`, so a live LangChain object (ToolMessage)
    must never leak through unchanged."""
    try:
        serialized = json.dumps(value, default=str)
    except (TypeError, ValueError):
        return _cap(str(value), limit)
    if len(serialized) <= limit:
        return json.loads(serialized)
    truncated = serialized[:limit] + _TRUNCATION_MARKER
    try:
        return json.loads(truncated)
    except json.JSONDecodeError:
        return truncated


_PROVIDER_TARGET = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "google_genai",
    "custom": "openai",
}
_MAX_TOKENS_KEY = {
    "openai": "max_tokens",
    "custom": "max_tokens",
    "anthropic": "max_tokens",
    "gemini": "max_output_tokens",
}
_STOP_KEY = {
    "openai": "stop",
    "custom": "stop",
    "anthropic": "stop_sequences",
    "gemini": "stop",
}


def build_chat_model(profile: LlmProfile, params: dict[str, Any], *, streaming: bool = True):
    provider = profile.provider
    target = _PROVIDER_TARGET.get(provider)
    if target is None:
        raise AgentRuntimeError(f"unsupported provider {provider!r}")

    kwargs: dict[str, Any] = {
        "api_key": decrypt_api_key(profile.encrypted_api_key),
        "streaming": streaming,
    }
    if provider == "custom":
        if not profile.base_url:
            raise AgentRuntimeError("the custom profile has no base URL")
        kwargs["base_url"] = profile.base_url

    if "temperature" in params:
        kwargs["temperature"] = params["temperature"]
    if "max_tokens" in params:
        kwargs[_MAX_TOKENS_KEY[provider]] = params["max_tokens"]
    if "top_p" in params:
        kwargs["top_p"] = params["top_p"]
    if "seed" in params:
        kwargs["seed"] = params["seed"]
    if "stop" in params and params["stop"]:
        kwargs[_STOP_KEY[provider]] = params["stop"]
    if "reasoning" in params:
        kwargs["reasoning_effort"] = params["reasoning"]

    return init_chat_model(f"{target}:{profile.model_id}", **kwargs)


async def build_tools(
    db,
    workspace_id: str,
    validated: ValidatedAgent,
    session: SandboxSession,
    *,
    depth: int,
    filenames: list[str] | None = None,
    unavailable: list[str] | None = None,
) -> list[BaseTool | dict[str, Any]]:
    """The run's tools. A component that fails to build is skipped and logged, and
    named in `unavailable` so the model can be told; it never fails the turn."""
    if unavailable is None:
        unavailable = []
    tools: list[BaseTool | dict[str, Any]] = []
    workspace_tools = {row.name.lower(): row for row in validated.workspace_tools}
    builtins = {entry.key.lower(): entry for entry in list_builtin_tools()}

    for name in validated.effective_tools:
        row = workspace_tools.get(name.lower())
        if row is not None:
            extracted = extract_schema(row.code)
            if extracted.schema is None:
                logger.warning(
                    f"Tool {row.name!r} skipped for this run: {extraction_error(row.name, extracted)}"
                )
                unavailable.append(f"Tool {row.name} (code no longer parses)")
                continue
            tools.append(user_tool(extracted.schema, session))
            continue
        entry = builtins.get(name.lower())
        if entry is not None:
            tools.append(
                StructuredTool.from_function(
                    func=entry.function,
                    name=entry.key,
                    description=entry.description,
                )
            )

    sql_attachments = [
        item for item in validated.data_sources if item.connection.kind in ("postgres", "mysql")
    ]
    document_attachments = [
        item for item in validated.data_sources if item.connection.kind == "mongodb"
    ]
    if sql_attachments:
        tools.append(
            query_data_source_tool(
                [(item.connection, item.tables) for item in sql_attachments],
                validated.agent_id,
            )
        )
    if document_attachments:
        tools.append(
            query_document_data_source_tool(
                [(item.connection, item.tables) for item in document_attachments],
                validated.agent_id,
            )
        )
    if validated.data_sources:
        tools.append(
            describe_data_source_tool(
                [(item.connection, item.tables) for item in sql_attachments],
                [(item.connection, item.tables) for item in document_attachments],
            )
        )
    if validated.selected_skills:
        tools.append(read_skill_tool(validated.resolved_skills))

    connector_tools, failed_connectors = await load_connector_tools(validated.connectors)
    tools.extend(connector_tools)
    unavailable.extend(f"Connector {name} (unreachable)" for name in failed_connectors)

    if depth + 1 < DEFAULT_MAX_SUBAGENT_DEPTH:
        for child in validated.subagents:
            tools.append(
                subagent_tool(
                    agent_id=child.id,
                    name=child.name,
                    description=child.description,
                    run=_subagent_runner(workspace_id, child.id, depth + 1),
                )
            )

    if validated.web_search:
        method = validated.web_search["method"]
        if method in ("tavily", "exa"):
            credential = (
                await db.execute(
                    select(SearchCredential).where(
                        SearchCredential.workspace_id == workspace_id,
                        SearchCredential.provider == method,
                    )
                )
            ).scalar_one_or_none()
            if credential is None:
                logger.warning(
                    f"Web search skipped for this run: no {method} API key is stored "
                    "for this workspace"
                )
                unavailable.append(f"Web search: no {method} API key")
            else:
                try:
                    tools.append(
                        build_web_search_tool(
                            method, decrypt_api_key(credential.encrypted_api_key)
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        f"Web search skipped for this run: {type(exc).__name__}: "
                        f"{short_message(exc)}"
                    )
                    unavailable.append(f"Web search: {method} unavailable")
        elif method == "native":
            spec = native_web_search_spec(validated.profile.provider)
            if spec is not None:
                tools.append(spec)

    # Files reach the model as data it can read with code, not as pre-extracted text.
    # The subprocess fallback cannot honour the mount contract, so it gets no tool.
    if validated.attached_documents and session.uses_docker:
        tools.append(sandbox_python_tool(session, filenames or []))

    unique: list[BaseTool | dict[str, Any]] = []
    seen: set[str] = set()
    for tool in tools:
        if isinstance(tool, dict):
            # Provider-native specs (e.g. {"type": "web_search"}) have no common name.
            unique.append(tool)
            continue
        name = tool.name
        if name in seen:
            logger.warning(f"Skipping duplicate tool name {name!r} for agent run")
            continue
        seen.add(name)
        unique.append(tool)
    return unique


def build_graph(
    validated: ValidatedAgent,
    agent: Agent,
    tools: list[BaseTool | dict[str, Any]],
    *,
    streaming: bool,
    output_format: str | None = None,
    unavailable: list[str] | None = None,
):
    model = build_chat_model(validated.profile, validated.params, streaming=streaming)
    return create_agent(
        model,
        tools,
        system_prompt=_system_prompt(agent.system_prompt, validated, output_format, unavailable),
        response_format=(
            ToolStrategy(validated.structured_schema)
            if validated.structured_schema is not None
            else None
        ),
        name=_graph_name(agent),
        middleware=tool_middleware(),
    )


def _system_prompt(
    prompt: str,
    validated: ValidatedAgent,
    output_format: str | None = None,
    unavailable: list[str] | None = None,
) -> str:
    sections: list[str] = []
    menu = validated.resolved_skills.menu
    if menu:
        lines = "\n".join(entry.line() for entry in menu)
        sections.append(
            "The following skills are available. When a task matches one, call "
            f"read_skill with its name and follow the returned instructions.\n{lines}"
        )
    if validated.data_sources:
        sql_items = [
            item for item in validated.data_sources
            if item.connection.kind in ("postgres", "mysql")
        ]
        document_items = [
            item for item in validated.data_sources if item.connection.kind == "mongodb"
        ]
        if sql_items:
            lines = "\n".join(
                f"- {item.connection.name} ({item.connection.kind}; connection_id: "
                f"{item.connection.id}); queryable tables: {', '.join(item.tables)}"
                for item in sql_items
            )
            sections.append(
                "External SQL data sources are attached. To read from them, call "
                "query_data_source with the connection_id and a single read-only "
                "SELECT limited to the listed tables; call describe_data_source to "
                f"discover columns.\n{lines}"
            )
        if document_items:
            lines = "\n".join(
                f"- {item.connection.name} (mongodb; connection_id: {item.connection.id}); "
                f"queryable collections: {', '.join(item.tables)}"
                for item in document_items
            )
            sections.append(
                "External MongoDB data sources are attached. To read from them, call "
                "query_document_data_source with the connection_id, a collection from "
                "the list, and a JSON filter object (find() semantics, read-only); call "
                f"describe_data_source to discover fields.\n{lines}"
            )
    if unavailable:
        sections.append(
            f"These are unavailable for this run: {'; '.join(unavailable)}. "
            "Do not call them; tell the user if the task needs them."
        )
    if output_format == OPENUI:
        # Last, so the format rules sit closest to the conversation.
        sections.append(openui_prompt())
    if not sections:
        return prompt
    return prompt + "\n\n" + "\n\n".join(sections)


def _graph_name(agent: Agent) -> str:
    safe = "".join(character if character.isalnum() else "_" for character in agent.name)
    return safe[:40] or "agent"


ATTACHMENT_NAME_MAX = 120


def _attachment_name(raw: str | None, fallback: str, used: set[str]) -> str:
    """A name safe for `/app/data`: no separators, no leading dots, bounded, unique.

    The cap keeps a hostile 255-character name from making the mount listing unreadable;
    the dedupe keeps two files with the same name from overwriting each other, which
    would silently hand the model one file when the agent attached two.
    """
    name = Path((raw or "").replace("\\", "/")).name
    name = re.sub(r"[^A-Za-z0-9._ -]", "", name).lstrip(". ").strip()[:ATTACHMENT_NAME_MAX]
    name = name or fallback
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate = name
    index = 2
    while candidate in used:
        room = ATTACHMENT_NAME_MAX - len(suffix) - len(f" ({index})")
        candidate = f"{stem[:room]} ({index}){suffix}"
        index += 1
    return candidate


async def _stage_files(documents: list[Document]) -> tuple[Path | None, list[str]]:
    """Download the run's files into a directory the sandbox mounts read-only.

    A missing object is logged and skipped rather than killing the run: the rest of the
    files are still worth reading, and the model can say one name was not there.
    """
    if not documents:
        return None, []
    staging = Path(tempfile.mkdtemp(prefix="mokinjay-files-"))
    storage = get_storage()
    used: set[str] = set()
    names: list[str] = []
    for row in documents:
        if not row.file_url:
            continue
        try:
            data = await storage.download_file(row.file_url)
        except StorageError:
            logger.exception(f"Could not stage file {row.id}; it will be absent from /app/data")
            continue
        name = _attachment_name(row.filename, row.id, used)
        used.add(name)
        names.append(name)
        (staging / name).write_bytes(data)
    return staging, names


def _open_session(
    workspace_id: str, validated: ValidatedAgent, data_dir: str | None
) -> tuple[SandboxSession, int]:
    """The run's sandbox, plus the megabytes reserved for it (0 when there is nothing
    to reserve). Callers must `release` the returned amount in their teardown.

    A run with no attached files keeps the configured size: there is nothing to read,
    so the tool-only tier is right and the budget is not touched.
    """
    config = SandboxConfig.from_settings()
    reserved_mb = 0
    if validated.attached_documents:
        largest = max((row.file_size or 0) for row in validated.attached_documents)
        config = config.tiered(largest)
        if not reserve(workspace_id, config.memory_mb):
            raise AgentRuntimeError(
                "This workspace has too many sandbox runs in flight; try again when one finishes."
            )
        reserved_mb = config.memory_mb
    session = SandboxSession(
        config=config,
        data_dir=data_dir,
        tools=InMemoryToolSource({row.name: row.code for row in validated.workspace_tools}),
    )
    return session, reserved_mb


def _subagent_runner(workspace_id: str, child_id: str, depth: int):
    async def run(task: str) -> str:
        session: SandboxSession | None = None
        staging: Path | None = None
        reserved_mb = 0
        try:
            async with async_session() as db:
                child = await db.get(Agent, child_id)
                if child is None or child.workspace_id != workspace_id:
                    return "That subagent no longer exists."
                data = await saved_input(db, child)
                validated = await validate_agent(db, workspace_id, data, agent_id=child.id)
                staging, filenames = await _stage_files(validated.attached_documents)
                session, reserved_mb = _open_session(
                    workspace_id, validated, str(staging) if staging else None
                )
                unavailable: list[str] = []
                tools = await build_tools(
                    db,
                    workspace_id,
                    validated,
                    session,
                    depth=depth,
                    filenames=filenames,
                    unavailable=unavailable,
                )
                graph = build_graph(
                    validated, child, tools, streaming=False, unavailable=unavailable
                )
            result = await graph.ainvoke({"messages": [HumanMessage(content=task)]})
            return _message_text(result.get("messages", [])[-1]) or "(the subagent returned no answer)"
        finally:
            try:
                if session is not None:
                    await asyncio.to_thread(session.close)
            finally:
                try:
                    if reserved_mb:
                        release(workspace_id, reserved_mb)
                finally:
                    if staging is not None:
                        shutil.rmtree(staging, ignore_errors=True)

    return run


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in ("text", "output_text"):
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""


def new_usage() -> dict[str, Any]:
    """An empty usage record.

    `cache_reported` / `reasoning_reported` stay False until a provider actually
    sends the detail block, so a real 0 can be told from "not reported"."""
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read_tokens": 0,
        "cache_creation_tokens": 0,
        "reasoning_tokens": 0,
        "cache_reported": False,
        "reasoning_reported": False,
    }


def _add_usage(total: dict[str, Any], metadata: Any) -> None:
    """Fold one model call's LangChain `usage_metadata` into the run total.

    LangChain standardises `input_token_details` (cache_read, cache_creation)
    and `output_token_details` (reasoning); each provider adapter fills what the
    provider returns."""
    if not isinstance(metadata, dict):
        return
    total["input_tokens"] += int(metadata.get("input_tokens") or 0)
    total["output_tokens"] += int(metadata.get("output_tokens") or 0)
    total["total_tokens"] += int(metadata.get("total_tokens") or 0)
    input_details = metadata.get("input_token_details")
    if isinstance(input_details, dict) and input_details:
        total["cache_read_tokens"] += int(input_details.get("cache_read") or 0)
        total["cache_creation_tokens"] += int(input_details.get("cache_creation") or 0)
        total["cache_reported"] = True
    output_details = metadata.get("output_token_details")
    if isinstance(output_details, dict) and output_details:
        total["reasoning_tokens"] += int(output_details.get("reasoning") or 0)
        total["reasoning_reported"] = True


def _cost(profile: LlmProfile, usage: dict[str, Any]) -> float:
    cached = min(usage["cache_read_tokens"], usage["input_tokens"])
    uncached = usage["input_tokens"] - cached
    return (
        uncached * profile.input_price_per_million
        + cached * profile.cache_price_per_million
        + usage["output_tokens"] * profile.output_price_per_million
    ) / 1_000_000


async def _mark_execution(
    execution_id: str,
    status: str,
    *,
    output: dict | None = None,
    usage: dict | None = None,
    cost: float | None = None,
    error: str | None = None,
    started: float | None = None,
    model: tuple[str, str] | None = None,
    ttft_ms: int | None = None,
) -> None:
    async with async_session() as db:
        execution = await db.get(Execution, execution_id)
        if execution is None:
            return
        execution.status = status
        if model is not None:
            execution.provider, execution.model_id = model
        if ttft_ms is not None:
            execution.ttft_ms = ttft_ms
        if output is not None:
            execution.output_data = output
        if usage is not None:
            execution.token_usage = usage
        if cost is not None:
            execution.cost_usd = Decimal(str(round(cost, 6)))
        if error is not None:
            execution.error_message = error[:2000]
        if started is not None:
            execution.execution_time_ms = int((time.monotonic() - started) * 1000)
        if status != "running":
            execution.completed_at = datetime.now(timezone.utc)
        await db.commit()


async def _bump_run_usage(db, workspace_id: str, validated: ValidatedAgent) -> None:
    await bump_usage(db, workspace_id, "llm_profile", validated.profile.id)
    if validated.structured_output is not None:
        await bump_usage(db, workspace_id, "structured_output", validated.structured_output.id)
    for row in validated.selected_skills:
        await bump_usage(db, workspace_id, "skill", row.id)
    for row in validated.connectors:
        await bump_usage(db, workspace_id, "connector", row.id)
    effective = {name.lower() for name in validated.effective_tools}
    for row in validated.workspace_tools:
        if row.name.lower() in effective:
            await bump_usage(db, workspace_id, "tool", row.id)
    for row in validated.subagents:
        await bump_usage(db, workspace_id, "agent", row.id)


async def _write_assistant_message(
    assistant_message_id: str,
    *,
    content: str,
    reasoning: str,
    activity: list[dict],
    structured: Any,
    status: str,
    usage: dict[str, Any],
    cost: float | None,
) -> None:
    async with async_session() as db:
        row = await db.get(ChatMessage, assistant_message_id)
        if row is None:
            return
        row.content = content
        row.reasoning = reasoning or None
        row.activity = activity or None
        row.structured = structured
        row.status = status
        row.usage = usage
        row.cost_usd = Decimal(str(round(cost, 8))) if cost is not None else None
        await db.commit()


async def _delete_assistant_message(assistant_message_id: str) -> None:
    async with async_session() as db:
        row = await db.get(ChatMessage, assistant_message_id)
        if row is not None:
            await db.delete(row)
            await db.commit()


async def _flush_activity(assistant_message_id: str, activity: list[dict]) -> None:
    """Persist the activity seen so far, without touching status/content.

    A turn that hangs mid-tool-call (an unreachable MCP server, a stuck
    sandbox) used to lose everything the user had already watched stream,
    because activity was only written when the turn finished. Flushing as
    events arrive keeps the replay truthful even for a turn that never
    completes. Throttled by the caller."""
    if assistant_message_id is None:
        return
    async with async_session() as db:
        row = await db.get(ChatMessage, assistant_message_id)
        if row is not None:
            row.activity = list(activity) or None
            await db.commit()


async def stream_turn(
    workspace_id: str,
    session_id: str,
    content: str,
    execution_id: str,
    output_format: str = DEFAULT_OUTPUT_FORMAT,
    *,
    emit_content_reset: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    """Run one playground turn (spec §6-7): persist both messages, stream the
    v2 protocol, and keep the assistant row's activity log identical to what
    was streamed so a replay renders exactly as the live turn did.

    The client sends only `content`; history is loaded from chat_messages.
    Live config (P4): the agent is re-resolved from its saved row every turn.
    """
    started = time.monotonic()
    sandbox: Any | None = None
    staging: Path | None = None
    reserved_mb = 0

    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    activity: list[dict[str, Any]] = []
    # One entry per in-flight tool call. ToolRetryMiddleware re-runs a failing
    # tool inside the same call; each attempt streams its own run_id but all
    # share langgraph_checkpoint_ns (the tool_call_id only appears on the
    # end/error events, not the start). Keying by the ns keeps one card.
    tool_calls: dict[str, dict[str, Any]] = {}
    # A failed attempt is held back: it is only the call's real end if no
    # retry start for the same call follows.
    pending_errors: dict[str, dict[str, Any]] = {}
    usage = new_usage()
    model_snapshot: tuple[str, str] | None = None
    ttft_ms: int | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None

    def _remember(event: dict[str, Any]) -> None:
        if len(activity) < ACTIVITY_EVENT_CAP:
            activity.append(event)

    def _tool_key(event: dict[str, Any]) -> str:
        ns = str((event.get("metadata") or {}).get("langgraph_checkpoint_ns", ""))
        return ns or str(event.get("run_id") or event.get("name", ""))

    def _finish_tool(key: str, entry: dict[str, Any]) -> dict[str, Any]:
        call = tool_calls.pop(key, None)
        if call is None:
            # End without a seen start: keep the event's own run_id.
            call = {"id": entry["id"], "started": None, "attempts": 1}
        entry["id"] = call["id"]
        entry["duration_ms"] = (
            int((time.monotonic() - call["started"]) * 1000) if call["started"] else None
        )
        if call["attempts"] > 1:
            entry["attempts"] = call["attempts"]
        _remember(entry)
        return entry

    def _release_pending(only: str | None = None) -> list[dict[str, Any]]:
        if only is None:
            keys = list(pending_errors)
        else:
            keys = [only] if only in pending_errors else []
        return [_finish_tool(key, pending_errors.pop(key)) for key in keys]

    try:
        async with async_session() as db:
            chat_session = await db.get(ChatSession, session_id)
            if chat_session is None or chat_session.workspace_id != workspace_id:
                raise AgentRuntimeError("The chat session no longer exists.")
            agent = (
                await db.execute(
                    select(Agent).where(
                        Agent.id == chat_session.agent_id,
                        Agent.workspace_id == workspace_id,
                    )
                )
            ).scalar_one_or_none()
            if agent is None:
                raise AgentRuntimeError("The agent no longer exists.")

            history_rows = (
                (
                    await db.execute(
                        select(ChatMessage)
                        .where(ChatMessage.session_id == session_id)
                        .order_by(ChatMessage.seq)
                    )
                )
                .scalars()
                .all()
            )

            # Both rows exist before any failure can happen: the message event
            # carries real ids, and an error turn deletes the empty assistant
            # row rather than leaving a phantom bubble.
            user_row = ChatMessage(session_id=session_id, role="user", content=content)
            assistant_row = ChatMessage(
                session_id=session_id,
                role="assistant",
                content="",
                execution_id=execution_id,
                output_format=output_format,
            )
            db.add_all([user_row, assistant_row])
            if chat_session.title == "New session":
                first_line = content.split("\n", 1)[0].strip()
                chat_session.title = first_line[:60] or "New session"
            # Every turn must bump the session or the list (ordered by
            # updated_at) freezes at the first turn: on later turns no other
            # session attribute changes, so onupdate alone never fires.
            chat_session.updated_at = datetime.now(timezone.utc)
            await db.commit()
            await db.refresh(user_row)
            await db.refresh(assistant_row)
            user_message_id = user_row.id
            assistant_message_id = assistant_row.id

            validated = await validate_agent(
                db, workspace_id, await saved_input(db, agent), agent_id=agent.id
            )
            # Re-checked against the profile this turn actually resolved, in case
            # it changed after the router's check.
            require_supported(
                output_format,
                validated.profile.context_window if validated.profile else None,
            )
            staging, filenames = await _stage_files(validated.attached_documents)
            sandbox, reserved_mb = _open_session(
                workspace_id, validated, str(staging) if staging else None
            )
            unavailable: list[str] = []
            tools = await build_tools(
                db,
                workspace_id,
                validated,
                sandbox,
                depth=0,
                filenames=filenames,
                unavailable=unavailable,
            )
            graph = build_graph(
                validated,
                agent,
                tools,
                streaming=True,
                output_format=output_format,
                unavailable=unavailable,
            )
            model_snapshot = (validated.profile.provider, validated.profile.model_id)
            await _bump_run_usage(db, workspace_id, validated)
            await db.commit()

        yield {
            "event": "message",
            "data": {
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
            },
        }

        if filenames:
            staged_event: dict[str, Any] = {"type": "files_staged", "names": list(filenames)}
            _remember(staged_event)
            await _flush_activity(assistant_message_id, activity)
            yield {"event": "activity", "data": staged_event}

        if unavailable:
            unavailable_event: dict[str, Any] = {"type": "unavailable", "names": list(unavailable)}
            _remember(unavailable_event)
            await _flush_activity(assistant_message_id, activity)
            yield {"event": "activity", "data": unavailable_event}

        history = [
            HumanMessage(content=row.content)
            if row.role == "user"
            else AIMessage(content=row.content)
            for row in history_rows
        ]
        history.append(HumanMessage(content=content))

        streamed = False
        final_text = ""
        structured: Any = None
        last_flush = 0.0

        model_started = time.monotonic()
        async for event in graph.astream_events({"messages": history}, version="v2"):
            kind = event["event"]
            metadata = event.get("metadata") or {}
            nested = "|" in str(metadata.get("langgraph_checkpoint_ns", ""))

            if pending_errors and not nested:
                # Parallel calls each run in their own tools:<id> namespace and
                # a sibling's events must not end this call's retry window.
                # Release a held error only when proof arrives that its call is
                # over: its own tools node ended, or the model node took over.
                ns = str(metadata.get("langgraph_checkpoint_ns", ""))
                if kind == "on_chain_end" and event.get("name") == "tools":
                    to_release = _release_pending(ns)
                elif kind.startswith("on_chat_model") or ns.startswith("model:"):
                    to_release = _release_pending()
                else:
                    to_release = []
                for released in to_release:
                    await _flush_activity(assistant_message_id, activity)
                    yield {"event": "activity", "data": released}

            if kind == "on_chat_model_stream" and not nested:
                chunk = event["data"].get("chunk")
                reasoning = _reasoning_delta(chunk)
                if ttft_ms is None and (reasoning or _message_text(chunk)):
                    ttft_ms = int((time.monotonic() - model_started) * 1000)
                if reasoning:
                    reasoning_parts.append(reasoning)
                    yield {"event": "reasoning", "data": {"delta": reasoning}}
                delta = _message_text(chunk)
                if delta:
                    streamed = True
                    content_parts.append(delta)
                    yield {"event": "token", "data": {"delta": delta}}

            elif kind == "on_chat_model_end":
                output = event["data"].get("output")
                if isinstance(output, AIMessage):
                    _add_usage(usage, output.usage_metadata)

            elif kind == "on_tool_start" and not nested:
                if emit_content_reset and content_parts:
                    # Text streamed before a tool call is narration, not the
                    # reply: only the final model step is persisted. Telling
                    # the client to drop it keeps the live bubble identical to
                    # the saved one (an OpenUI program must not start with prose).
                    content_parts.clear()
                    yield {"event": "content_reset", "data": {}}
                run_id = str(event.get("run_id") or event.get("name", ""))
                key = _tool_key(event)
                if key in tool_calls:
                    # A retry of a call that already has a card.
                    tool_calls[key]["attempts"] += 1
                    pending_errors.pop(key, None)
                    continue
                tool_calls[key] = {
                    "id": run_id,
                    "started": time.monotonic(),
                    "attempts": 1,
                }
                name = event.get("name", "")
                entry = {
                    "type": "tool_start",
                    "id": run_id,
                    "name": name,
                    "kind": _tool_kind(name),
                    "args": _cap(event["data"].get("input") or {}),
                }
                _remember(entry)
                if time.monotonic() - last_flush > 1.0:
                    last_flush = time.monotonic()
                    await _flush_activity(assistant_message_id, activity)
                yield {"event": "activity", "data": entry}

            elif kind == "on_tool_end" and not nested:
                name = event.get("name", "")
                key = _tool_key(event)
                pending_errors.pop(key, None)
                entry = _finish_tool(
                    key,
                    {
                        "type": "tool_end",
                        "id": str(event.get("run_id") or name),
                        "name": name,
                        "kind": _tool_kind(name),
                        "result": _cap(event["data"].get("output")),
                    },
                )
                await _flush_activity(assistant_message_id, activity)
                yield {"event": "activity", "data": entry}

            elif kind == "on_tool_error" and not nested:
                # LangGraph emits this instead of on_tool_end when the tool
                # raises; without it the card would say "Calling…" forever.
                # Held back until we know no retry follows (see above).
                name = event.get("name", "")
                key = _tool_key(event)
                pending_errors[key] = {
                    "type": "tool_end",
                    "id": str(event.get("run_id") or name),
                    "name": name,
                    "kind": _tool_kind(name),
                    "error": _cap(str(event["data"].get("error") or "the tool failed")),
                }

            elif (
                kind == "on_chain_end"
                and event.get("name") == "LangGraph"
                and not event.get("parent_ids")
            ):
                output = event["data"].get("output") or {}
                if isinstance(output, dict):
                    final_messages = output.get("messages") or []
                    if final_messages:
                        final_text = _message_text(final_messages[-1])
                    structured = output.get("structured_response")

        for released in _release_pending():
            yield {"event": "activity", "data": released}

        text = final_text or "".join(content_parts)
        if not streamed and text:
            yield {"event": "token", "data": {"delta": text}}

        cost = _cost(validated.profile, usage)
        await _write_assistant_message(
            assistant_message_id,
            content=text,
            reasoning="".join(reasoning_parts)[:REASONING_CAP],
            activity=list(activity),
            structured=(
                structured.model_dump() if hasattr(structured, "model_dump") else structured
            ),
            status="completed",
            usage=usage,
            cost=cost,
        )
        await _mark_execution(
            execution_id,
            "completed",
            usage=usage,
            cost=cost,
            started=started,
            model=model_snapshot,
            ttft_ms=ttft_ms,
        )
        yield {
            "event": "done",
            "data": {"usage": usage, "cost_usd": round(cost, 6), "status": "completed"},
        }

    except (asyncio.CancelledError, GeneratorExit):
        # Stop button (P8): whatever streamed so far stays, marked stopped.
        # A disconnect before the rows were even created must still cancel the
        # execution — otherwise the row is stuck at "running" forever.
        _release_pending()
        if assistant_message_id is not None:
            partial = "".join(content_parts)
            await _write_assistant_message(
                assistant_message_id,
                content=partial,
                reasoning="".join(reasoning_parts)[:REASONING_CAP],
                activity=list(activity),
                structured=None,
                status="stopped",
                usage=usage,
                cost=None,
            )
        await _mark_execution(
            execution_id, "cancelled", started=started, model=model_snapshot, ttft_ms=ttft_ms
        )
        raise

    except CompositionError as exc:
        detail = "; ".join(f"{error.field}: {error.message}" for error in exc.errors)
        await _mark_execution(
            execution_id,
            "failed",
            error=detail,
            started=started,
            model=model_snapshot,
            ttft_ms=ttft_ms,
        )
        if assistant_message_id is not None and not content_parts and not reasoning_parts and not activity:
            await _delete_assistant_message(assistant_message_id)
        yield {"event": "error", "data": {"detail": detail}}

    except UnsupportedOutputFormat as exc:
        detail = str(exc)
        await _mark_execution(
            execution_id,
            "failed",
            error=detail,
            started=started,
            model=model_snapshot,
            ttft_ms=ttft_ms,
        )
        if assistant_message_id is not None:
            await _delete_assistant_message(assistant_message_id)
        yield {"event": "error", "data": {"detail": detail}}

    except Exception as exc:
        logger.exception(f"Playground turn {execution_id} failed")
        _release_pending()
        detail = str(exc).strip().replace("\n", " ") or exc.__class__.__name__
        await _mark_execution(
            execution_id,
            "failed",
            error=detail,
            started=started,
            model=model_snapshot,
            ttft_ms=ttft_ms,
        )
        if assistant_message_id is not None and not content_parts and not reasoning_parts and not activity:
            await _delete_assistant_message(assistant_message_id)
        else:
            await _write_assistant_message(
                assistant_message_id,
                content="".join(content_parts),
                reasoning="".join(reasoning_parts)[:REASONING_CAP],
                activity=list(activity),
                structured=None,
                status="failed",
                usage=usage,
                cost=None,
            )
        yield {"event": "error", "data": {"detail": detail}}

    finally:
        try:
            if sandbox is not None:
                await asyncio.to_thread(sandbox.close)
        finally:
            try:
                if reserved_mb:
                    release(workspace_id, reserved_mb)
            finally:
                if staging is not None:
                    shutil.rmtree(staging, ignore_errors=True)
