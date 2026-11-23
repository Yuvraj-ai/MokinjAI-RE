"""Final-review fixes: busy refusal cleanup, connector timeout not retried, card redaction."""

import asyncio

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from sqlalchemy import select

from app.models.chat import ChatMessage, ChatSession
from app.services import agent_resilience as ar
from app.services import agent_runtime, connector_runtime
from app.services.agent_runtime import stream_turn
from app.services.sandbox import budget
from app.services.sandbox.budget import SlotRequest
from unit_tests.fakes import ScriptedChatModel, tool_call_message
from unit_tests.test_playground_chat import (  # noqa: F401
    FakeGraphV2,
    _install,
    _setup,
    encryption_key,
)
from unit_tests.test_sandbox_queue import _plan_with, clean_budget  # noqa: F401


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(ar, "TOOL_RETRY_INITIAL_DELAY_S", 0.0)
    monkeypatch.setattr(ar, "TOOL_RETRY_MAX_DELAY_S", 0.0)


# --- Fix 2 -------------------------------------------------------------------


def test_tool_timeout_error_is_not_transient_and_not_a_timeout_error():
    exc = ar.ToolTimeoutError("`x` did not finish within 60s")
    assert not isinstance(exc, TimeoutError)
    assert ar.is_transient(exc) is False


async def test_connector_tool_over_the_ceiling_is_attempted_once(monkeypatch):
    monkeypatch.setattr(connector_runtime, "TOOL_TIMEOUT_S", 0.05)
    calls = []

    async def slow() -> str:
        calls.append(1)
        await asyncio.sleep(5)
        return "never"

    inner = StructuredTool.from_function(coroutine=slow, name="slowmcp", description="d")
    bounded = connector_runtime.with_timeout(inner)
    agent = create_agent(
        ScriptedChatModel(script=[tool_call_message("slowmcp", "1"), AIMessage(content="done")]),
        [bounded],
        middleware=ar.tool_middleware(),
    )
    out = await agent.ainvoke({"messages": [("user", "go")]})
    msgs = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(calls) == 1
    assert msgs[0].status == "error"
    assert "slowmcp" in msgs[0].content and "0.05" in msgs[0].content
    assert out["messages"][-1].content == "done"


# --- Fix 1 -------------------------------------------------------------------


async def _busy_turn(session_factory, workspace, monkeypatch, chat_session, execution, **kw):
    _install(monkeypatch, session_factory, FakeGraphV2())
    request = SlotRequest(workspace.id, 2048, max_wait_s=0.05)
    monkeypatch.setattr(agent_runtime, "_plan_slot", _plan_with(request))
    return [
        e
        async for e in stream_turn(workspace.id, chat_session.id, "hi", execution.id, **kw)
    ]


async def test_busy_refusal_leaves_no_user_message_so_a_retry_stores_one(
    db_session, session_factory, test_workspace, monkeypatch, encryption_key
):
    _agent, chat_session, execution = await _setup(db_session, test_workspace)
    assert budget.reserve(test_workspace.id, 4096)
    events = await _busy_turn(session_factory, test_workspace, monkeypatch, chat_session, execution)
    assert events[-1]["data"]["code"] == "sandbox_busy"
    async with session_factory() as check:
        rows = (
            (
                await check.execute(
                    select(ChatMessage).where(ChatMessage.session_id == chat_session.id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == []

    budget.release(test_workspace.id, 4096)
    monkeypatch.undo()
    _install(monkeypatch, session_factory, FakeGraphV2())
    retry = [
        e async for e in stream_turn(test_workspace.id, chat_session.id, "hi", execution.id)
    ]
    assert retry[-1]["event"] == "done"
    async with session_factory() as check:
        users = (
            (
                await check.execute(
                    select(ChatMessage).where(
                        ChatMessage.session_id == chat_session.id, ChatMessage.role == "user"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(users) == 1


async def test_busy_first_turn_on_a_new_session_leaves_no_chat_session(
    db_session, session_factory, test_workspace, monkeypatch, encryption_key
):
    _agent, chat_session, execution = await _setup(db_session, test_workspace)
    session_id = chat_session.id
    assert budget.reserve(test_workspace.id, 4096)
    await _busy_turn(
        session_factory,
        test_workspace,
        monkeypatch,
        chat_session,
        execution,
        session_created_by_turn=True,
    )
    async with session_factory() as check:
        assert await check.get(ChatSession, session_id) is None


# --- Fix 3 -------------------------------------------------------------------


async def test_tool_error_card_redacts_url_credentials(
    db_session, session_factory, test_workspace, monkeypatch, encryption_key
):
    _agent, chat_session, execution = await _setup(db_session, test_workspace)

    class Graph:
        async def astream_events(self, payload, version):
            yield {
                "event": "on_tool_start",
                "run_id": "r1",
                "name": "t",
                "metadata": {},
                "data": {"input": {}},
            }
            yield {
                "event": "on_tool_error",
                "run_id": "r1",
                "name": "t",
                "metadata": {},
                "data": {"error": "failed https://user:secret@host/x"},
            }
            yield {
                "event": "on_chain_end",
                "name": "LangGraph",
                "parent_ids": [],
                "metadata": {},
                "data": {"output": {"messages": [AIMessage(content="sorry")]}},
            }

    _install(monkeypatch, session_factory, Graph())
    events = [
        e async for e in stream_turn(test_workspace.id, chat_session.id, "hi", execution.id)
    ]
    activities = [e["data"] for e in events if e["event"] == "activity"]
    assert "secret" not in str(activities)
    assert "***" in activities[-1]["error"]
