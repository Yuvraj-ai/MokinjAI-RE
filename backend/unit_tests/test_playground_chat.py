"""stream_turn runtime behaviour (plan Task 3): v2 events, caps, persistence.

Runtime-level, mirroring test_agent_runtime.py::TestChatStream — monkeypatch
`async_session` and `build_graph`, then assert on the event sequence and the
persisted chat_messages rows.
"""

import asyncio
import json

import pytest
from cryptography.fernet import Fernet
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from sqlalchemy import select

from app.config import get_settings
from app.crypto import encrypt_api_key
from app.models.agent import Agent
from app.models.chat import ChatMessage, ChatSession
from app.models.execution import Execution
from app.models.llm_profile import LlmProfile
from app.services.agent_runtime import _tool_kind, stream_turn


@pytest.fixture
def encryption_key():
    settings = get_settings()
    previous = getattr(settings, "LLM_ENCRYPTION_KEY", "")
    settings.LLM_ENCRYPTION_KEY = Fernet.generate_key().decode()
    yield settings.LLM_ENCRYPTION_KEY
    settings.LLM_ENCRYPTION_KEY = previous


def make_profile(workspace_id: str) -> LlmProfile:
    return LlmProfile(
        workspace_id=workspace_id,
        name="Primary",
        provider="openai",
        model_id="gpt-4o-mini",
        encrypted_api_key=encrypt_api_key("sk-test"),
        context_window=128000,
        compaction_at_tokens=102400,
        input_price_per_million=2.0,
        output_price_per_million=10.0,
        cache_price_per_million=0.5,
        status="verified",
    )


class FakeGraphV2:
    """Reasoning delta, one tool round-trip, then streamed text."""

    def __init__(self):
        self.payloads: list[dict] = []

    async def astream_events(self, payload, version):
        self.payloads.append(payload)
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_checkpoint_ns": "model:1"},
            "data": {
                "chunk": AIMessageChunk(
                    content="", additional_kwargs={"reasoning_content": "thinking hard"}
                )
            },
        }
        yield {
            "event": "on_tool_start",
            "run_id": "run-1",
            "name": "query_data_source",
            "metadata": {},
            "data": {"input": {"connection_id": "c1", "sql": "SELECT 1"}},
        }
        yield {
            "event": "on_tool_end",
            "run_id": "run-1",
            "name": "query_data_source",
            "metadata": {},
            "data": {"output": "2 rows"},
        }
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_checkpoint_ns": "model:1"},
            "data": {"chunk": AIMessageChunk(content="Hel")},
        }
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_checkpoint_ns": "model:1"},
            "data": {"chunk": AIMessageChunk(content="lo")},
        }
        yield {
            "event": "on_chat_model_end",
            "metadata": {},
            "data": {
                "output": AIMessage(
                    content="Hello",
                    usage_metadata={
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "total_tokens": 12,
                        "input_token_details": {"cache_read": 4},
                    },
                )
            },
        }
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "parent_ids": [],
            "metadata": {},
            "data": {"output": {"messages": [AIMessage(content="Hello")]}},
        }


async def _setup(db_session, test_workspace):
    profile = make_profile(test_workspace.id)
    db_session.add(profile)
    await db_session.flush()
    agent = Agent(
        workspace_id=test_workspace.id,
        name="Chatty",
        llm_profile_id=profile.id,
        system_prompt="Be brief.",
        params={},
    )
    db_session.add(agent)
    await db_session.flush()
    chat_session = ChatSession(workspace_id=test_workspace.id, agent_id=agent.id)
    db_session.add(chat_session)
    await db_session.flush()
    execution = Execution(
        workspace_id=test_workspace.id,
        agent_id=agent.id,
        status="running",
        trigger_type="chat",
        input_data={},
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(agent)
    await db_session.refresh(chat_session)
    await db_session.refresh(execution)
    return agent, chat_session, execution


def _install(monkeypatch, session_factory, graph):
    monkeypatch.setattr("app.services.agent_runtime.async_session", session_factory)
    monkeypatch.setattr(
        "app.services.agent_runtime.build_graph", lambda *a, **k: graph
    )


class TestStreamTurn:
    @pytest.mark.asyncio
    async def test_turn_persists_messages_and_emits_v2_events(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        graph = FakeGraphV2()
        _install(monkeypatch, session_factory, graph)

        events = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]

        kinds = [event["event"] for event in events]
        assert kinds[0] == "message"
        assert set(kinds[0:2] + kinds[2:]) >= {"message", "reasoning", "activity", "token", "done"}
        assert kinds[-1] == "done"

        message_event = events[0]["data"]
        assert message_event["assistant_message_id"] != message_event["user_message_id"]

        reasoning = [e for e in events if e["event"] == "reasoning"]
        assert reasoning[0]["data"]["delta"] == "thinking hard"

        activities = [e["data"] for e in events if e["event"] == "activity"]
        assert activities[0]["type"] == "tool_start"
        assert activities[0]["kind"] == "sql"
        assert activities[0]["args"]["sql"] == "SELECT 1"
        assert activities[1]["type"] == "tool_end"
        assert activities[1]["result"] == "2 rows"
        assert activities[1]["id"] == activities[0]["id"]

        tokens = [e["data"]["delta"] for e in events if e["event"] == "token"]
        assert tokens == ["Hel", "lo"]

        done = events[-1]["data"]
        assert done["status"] == "completed"
        assert done["usage"]["input_tokens"] == 10
        assert done["cost_usd"] == pytest.approx(0.000034)

        async with session_factory() as check:
            rows = (
                (
                    await check.execute(
                        select(ChatMessage)
                        .where(ChatMessage.session_id == chat_session.id)
                        .order_by(ChatMessage.seq)
                    )
                )
                .scalars()
                .all()
            )
            assert [row.role for row in rows] == ["user", "assistant"]
            assert rows[0].content == "hi"
            assert rows[1].content == "Hello"
            assert rows[1].reasoning == "thinking hard"
            assert rows[1].status == "completed"
            assert rows[1].activity is not None and len(rows[1].activity) == 2
            assert rows[1].usage["total_tokens"] == 12
            assert rows[1].execution_id == execution.id
            session_row = await check.get(ChatSession, chat_session.id)
            assert session_row.title == "hi"

    def test_tool_kind_mapping(self):
        assert _tool_kind("query_data_source") == "sql"
        assert _tool_kind("describe_data_source") == "sql"
        assert _tool_kind("execute_python") == "code"
        assert _tool_kind("read_skill") == "skill"
        assert _tool_kind("tavily_search") == "web"
        assert _tool_kind("exa_search_results") == "web"
        assert _tool_kind("ask_helper_ab12") == "subagent"
        assert _tool_kind("github_create_issue") == "tool"
        assert _tool_kind("my_custom_tool") == "tool"

    @pytest.mark.asyncio
    async def test_persisted_activity_matches_streamed_events(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        graph = FakeGraphV2()
        _install(monkeypatch, session_factory, graph)

        events = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]
        streamed = [e["data"] for e in events if e["event"] == "activity"]

        async with session_factory() as check:
            row = (
                (
                    await check.execute(
                        select(ChatMessage).where(
                            ChatMessage.session_id == chat_session.id,
                            ChatMessage.role == "assistant",
                        )
                    )
                )
                .scalars()
                .one()
            )
            assert json.loads(json.dumps(row.activity)) == streamed

    @pytest.mark.asyncio
    async def test_second_turn_loads_persisted_history(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        graph = FakeGraphV2()
        _install(monkeypatch, session_factory, graph)

        async for _ in stream_turn(
            test_workspace.id, chat_session.id, "hi", execution.id
        ):
            pass

        async with session_factory() as check:
            stamp_after_first = (await check.get(ChatSession, chat_session.id)).updated_at

        async for _ in stream_turn(
            test_workspace.id, chat_session.id, "again", execution.id
        ):
            pass

        async with session_factory() as check:
            session_row = await check.get(ChatSession, chat_session.id)
            # The session list orders by updated_at; every turn must bump it.
            assert session_row.updated_at > stamp_after_first

        history = graph.payloads[1]["messages"]
        assert [type(m).__name__ for m in history] == [
            "HumanMessage",
            "AIMessage",
            "HumanMessage",
        ]
        assert history[-1].content == "again"
        assert history[1].content == "Hello"

    @pytest.mark.asyncio
    async def test_abort_keeps_partial_text_as_stopped(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        graph = FakeGraphV2()
        _install(monkeypatch, session_factory, graph)

        gen = stream_turn(test_workspace.id, chat_session.id, "hi", execution.id)
        seen_token = False
        async for event in gen:
            if event["event"] == "token":
                seen_token = True
                break
        assert seen_token
        await gen.aclose()

        async with session_factory() as check:
            row = (
                (
                    await check.execute(
                        select(ChatMessage).where(
                            ChatMessage.session_id == chat_session.id,
                            ChatMessage.role == "assistant",
                        )
                    )
                )
                .scalars()
                .one()
            )
            assert row.status == "stopped"
            assert "Hel" in row.content
            run_row = await check.get(Execution, execution.id)
            assert run_row.status == "cancelled"

    @pytest.mark.asyncio
    async def test_error_deletes_empty_assistant_row(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        from app.services.agent_runtime import AgentRuntimeError

        agent, chat_session, execution = await _setup(db_session, test_workspace)

        async def explode(*a, **k):
            raise AgentRuntimeError("no profile")

        monkeypatch.setattr("app.services.agent_runtime.async_session", session_factory)
        monkeypatch.setattr("app.services.agent_runtime.build_graph", explode)

        events = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]
        assert events[-1]["event"] == "error"

        async with session_factory() as check:
            assistant = (
                (
                    await check.execute(
                        select(ChatMessage).where(
                            ChatMessage.session_id == chat_session.id,
                            ChatMessage.role == "assistant",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert assistant == []
            user = (
                (
                    await check.execute(
                        select(ChatMessage).where(
                            ChatMessage.session_id == chat_session.id,
                            ChatMessage.role == "user",
                        )
                    )
                )
                .scalars()
                .one()
            )
            assert user.content == "hi"
            run_row = await check.get(Execution, execution.id)
            assert run_row.status == "failed"

    @pytest.mark.asyncio
    async def test_activity_and_reasoning_are_capped(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)

        class BloatedGraph:
            async def astream_events(self, payload, version):
                yield {
                    "event": "on_tool_start",
                    "run_id": "r1",
                    "name": "read_skill",
                    "metadata": {},
                    "data": {"input": {"name": "big"}},
                }
                yield {
                    "event": "on_tool_end",
                    "run_id": "r1",
                    "name": "read_skill",
                    "metadata": {},
                    "data": {"output": "x" * 1_000_000},
                }
                yield {
                    "event": "on_chat_model_stream",
                    "metadata": {},
                    "data": {
                        "chunk": AIMessageChunk(
                            content="ok",
                            additional_kwargs={"reasoning_content": "y" * 100_000},
                        )
                    },
                }
                yield {
                    "event": "on_chain_end",
                    "name": "LangGraph",
                    "parent_ids": [],
                    "metadata": {},
                    "data": {"output": {"messages": [AIMessage(content="ok")]}},
                }

        _install(monkeypatch, session_factory, BloatedGraph())
        events = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]
        done = events[-1]
        assert done["event"] == "done"

        async with session_factory() as check:
            row = (
                (
                    await check.execute(
                        select(ChatMessage).where(
                            ChatMessage.session_id == chat_session.id,
                            ChatMessage.role == "assistant",
                        )
                    )
                )
                .scalars()
                .one()
            )
            assert len(row.reasoning) <= 32_000 + 32
            for event in row.activity:
                for key in ("args", "result"):
                    if event.get(key) is not None:
                        assert len(json.dumps(event[key])) <= 8_000 + 32

    @pytest.mark.asyncio
    async def test_files_staged_event(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        graph = FakeGraphV2()
        _install(monkeypatch, session_factory, graph)
        async def fake_stage(documents):
            return None, ["a.csv", "b.csv"], []

        monkeypatch.setattr(
            "app.services.agent_runtime._stage_files", fake_stage
        )

        events = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]
        staged = [
            e["data"]
            for e in events
            if e["event"] == "activity" and e["data"]["type"] == "files_staged"
        ]
        assert staged == [{"type": "files_staged", "names": ["a.csv", "b.csv"]}]

    @pytest.mark.asyncio
    async def test_missing_file_reaches_prompt_list_and_event(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        graph = FakeGraphV2()
        seen: dict[str, list[str]] = {}

        def capture_build(validated, agent_row, tools, *, unavailable=None, **_):
            seen["graph"] = list(unavailable or [])
            return graph

        monkeypatch.setattr("app.services.agent_runtime.async_session", session_factory)
        monkeypatch.setattr("app.services.agent_runtime.build_graph", capture_build)

        async def fake_stage(documents):
            return None, [], ["gone.csv"]

        monkeypatch.setattr("app.services.agent_runtime._stage_files", fake_stage)

        events = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]
        expected = "File gone.csv (not found in storage)"
        assert expected in seen["graph"]
        unavailable = [
            e["data"]
            for e in events
            if e["event"] == "activity" and e["data"]["type"] == "unavailable"
        ]
        assert unavailable and expected in unavailable[0]["names"]

    @pytest.mark.asyncio
    async def test_subagent_runner_passes_missing_file_as_unavailable(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        from app.services import agent_runtime

        agent, _chat_session, _execution = await _setup(db_session, test_workspace)
        seen: dict[str, list[str]] = {}

        class _Session:
            def close(self):
                pass

        class _Graph:
            async def ainvoke(self, _input):
                return {"messages": [AIMessage(content="ok")]}

        async def fake_stage(documents):
            return None, [], ["gone.csv"]

        async def fake_build_tools(*_a, unavailable=None, **_k):
            seen["tools"] = list(unavailable or [])
            return []

        def fake_build_graph(*_a, unavailable=None, **_k):
            seen["graph"] = list(unavailable or [])
            return _Graph()

        monkeypatch.setattr(agent_runtime, "async_session", session_factory)
        monkeypatch.setattr(agent_runtime, "_stage_files", fake_stage)
        monkeypatch.setattr(agent_runtime, "_open_session", lambda *a, **k: (_Session(), 0))
        monkeypatch.setattr(agent_runtime, "build_tools", fake_build_tools)
        monkeypatch.setattr(agent_runtime, "build_graph", fake_build_graph)

        result = await agent_runtime._subagent_runner(
            test_workspace.id, agent.id, 1
        )("do it")

        assert result == "ok"
        expected = ["File gone.csv (not found in storage)"]
        assert seen["tools"] == expected
        assert seen["graph"] == expected

    @pytest.mark.asyncio
    async def test_live_config_reread_between_turns(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        graph = FakeGraphV2()
        prompts_seen: list[str] = []

        def capture_build(validated, agent_row, tools, *, streaming, **_):
            prompts_seen.append(agent_row.system_prompt)
            return graph

        monkeypatch.setattr("app.services.agent_runtime.async_session", session_factory)
        monkeypatch.setattr(
            "app.services.agent_runtime.build_graph", capture_build
        )

        async for _ in stream_turn(
            test_workspace.id, chat_session.id, "hi", execution.id
        ):
            pass

        agent.system_prompt = "New instructions."
        db_session.add(agent)
        await db_session.commit()

        async for _ in stream_turn(
            test_workspace.id, chat_session.id, "again", execution.id
        ):
            pass

        assert prompts_seen == ["Be brief.", "New instructions."]

    @pytest.mark.asyncio
    async def test_activity_is_persisted_before_the_turn_completes(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        """A hung turn must not lose what the user already saw: each activity
        event lands in the assistant row as it streams, not only at the end."""
        agent, chat_session, execution = await _setup(db_session, test_workspace)

        class SlowAfterToolGraph:
            async def astream_events(self, payload, version):
                yield {
                    "event": "on_tool_start",
                    "run_id": "r1",
                    "name": "execute_python",
                    "metadata": {},
                    "data": {"input": {"code": "1 + 1"}},
                }
                # Simulate the tool/model hanging after the event streamed.
                await asyncio.sleep(3600)

        _install(monkeypatch, session_factory, SlowAfterToolGraph())

        gen = stream_turn(test_workspace.id, chat_session.id, "hi", execution.id)
        async for event in gen:
            if event["event"] == "activity":
                break

        async with session_factory() as check:
            row = (
                (
                    await check.execute(
                        select(ChatMessage).where(
                            ChatMessage.session_id == chat_session.id,
                            ChatMessage.role == "assistant",
                        )
                    )
                )
                .scalars()
                .one()
            )
            assert row.activity is not None
            assert row.activity[0]["name"] == "execute_python"

        await gen.aclose()

    @pytest.mark.asyncio
    async def test_abort_persists_the_seen_activity(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)

        class ToolThenHangGraph:
            async def astream_events(self, payload, version):
                yield {
                    "event": "on_tool_start",
                    "run_id": "r1",
                    "name": "read_skill",
                    "metadata": {},
                    "data": {"input": {"name": "s"}},
                }
                await asyncio.sleep(3600)

        _install(monkeypatch, session_factory, ToolThenHangGraph())

        gen = stream_turn(test_workspace.id, chat_session.id, "hi", execution.id)
        async for event in gen:
            if event["event"] == "activity":
                break
        await gen.aclose()

        async with session_factory() as check:
            row = (
                (
                    await check.execute(
                        select(ChatMessage).where(
                            ChatMessage.session_id == chat_session.id,
                            ChatMessage.role == "assistant",
                        )
                    )
                )
                .scalars()
                .one()
            )
            assert row.status == "stopped"
            assert row.activity and row.activity[0]["name"] == "read_skill"
            run_row = await check.get(Execution, execution.id)
            assert run_row.status == "cancelled"

    @pytest.mark.asyncio
    async def test_tool_error_becomes_a_completed_card(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        """LangGraph emits on_tool_error instead of on_tool_end when a tool
        raises; without handling it the card stays 'Calling…' forever."""
        agent, chat_session, execution = await _setup(db_session, test_workspace)

        class FailingToolGraph:
            async def astream_events(self, payload, version):
                yield {
                    "event": "on_tool_start",
                    "run_id": "r1",
                    "name": "get_time",
                    "metadata": {},
                    "data": {"input": {"tz": "local"}},
                }
                yield {
                    "event": "on_tool_error",
                    "run_id": "r1",
                    "name": "get_time",
                    "metadata": {},
                    "data": {"error": "tz: Field required"},
                }
                yield {
                    "event": "on_chain_end",
                    "name": "LangGraph",
                    "parent_ids": [],
                    "metadata": {},
                    "data": {"output": {"messages": [AIMessage(content="sorry")]}},
                }

        _install(monkeypatch, session_factory, FailingToolGraph())
        events = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]
        activities = [e["data"] for e in events if e["event"] == "activity"]
        assert [a["type"] for a in activities] == ["tool_start", "tool_end"]
        assert "Field required" in activities[1]["error"]

    @pytest.mark.asyncio
    async def test_event_count_cap(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)

        class ChattyGraph:
            async def astream_events(self, payload, version):
                for index in range(250):
                    yield {
                        "event": "on_tool_start",
                        "run_id": f"r{index}",
                        "name": "read_skill",
                        "metadata": {},
                        "data": {"input": {"name": f"s{index}"}},
                    }
                    yield {
                        "event": "on_tool_end",
                        "run_id": f"r{index}",
                        "name": "read_skill",
                        "metadata": {},
                        "data": {"output": "ok"},
                    }
                yield {
                    "event": "on_chain_end",
                    "name": "LangGraph",
                    "parent_ids": [],
                    "metadata": {},
                    "data": {"output": {"messages": [AIMessage(content="done")]}},
                }

        _install(monkeypatch, session_factory, ChattyGraph())
        events = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]
        assert events[-1]["event"] == "done"

        async with session_factory() as check:
            row = (
                (
                    await check.execute(
                        select(ChatMessage).where(
                            ChatMessage.session_id == chat_session.id,
                            ChatMessage.role == "assistant",
                        )
                    )
                )
                .scalars()
                .one()
            )
            assert len(row.activity) <= 200


class TestChatEndpoint:
    @pytest.mark.asyncio
    async def test_chat_endpoint_streams_and_requires_editor(
        self, client, auth_headers, viewer_headers, test_workspace, db_session
    ):
        agent, chat_session, _ = await _setup(db_session, test_workspace)

        async def fake_stream(workspace_id, session_id, content, execution_id, **_):
            yield {"event": "token", "data": {"delta": "Hi"}}
            yield {"event": "done", "data": {"usage": {}, "cost_usd": 0.0, "status": "completed"}}

        monkeypatch_target = "app.routers.playground.stream_turn"
        import app.routers.playground as playground_router

        original = playground_router.stream_turn
        playground_router.stream_turn = fake_stream
        try:
            url = f"/api/workspaces/{test_workspace.id}/playground/sessions/{chat_session.id}/chat"
            ok = await client.post(url, json={"content": "hello"}, headers=auth_headers)
            assert ok.status_code == 200
            assert ok.headers["content-type"].startswith("text/event-stream")
            assert "event: token" in ok.text
            assert '"delta": "Hi"' in ok.text

            denied = await client.post(
                url, json={"content": "hello"}, headers=viewer_headers
            )
            assert denied.status_code == 403
        finally:
            playground_router.stream_turn = original

    @pytest.mark.asyncio
    async def test_chat_endpoint_scopes_session(
        self, client, auth_headers, test_workspace, test_user, db_session
    ):
        from app.models.workspace import Workspace

        agent, chat_session, _ = await _setup(db_session, test_workspace)
        other_ws = Workspace(name="Elsewhere", owner_id=test_user.id)
        db_session.add(other_ws)
        await db_session.commit()

        base = f"/api/workspaces/{other_ws.id}/playground/sessions"
        missing = await client.post(
            f"{base}/{chat_session.id}/chat", json={"content": "hi"}, headers=auth_headers
        )
        assert missing.status_code == 404

        empty = await client.post(
            f"/api/workspaces/{test_workspace.id}/playground/sessions/{chat_session.id}/chat",
            json={"content": "   "},
            headers=auth_headers,
        )
        assert empty.status_code == 422

        oversized = await client.post(
            f"/api/workspaces/{test_workspace.id}/playground/sessions/{chat_session.id}/chat",
            json={"content": "x" * 32_001},
            headers=auth_headers,
        )
        assert oversized.status_code == 422

    @pytest.mark.asyncio
    async def test_executions_list_hides_chat_runs(
        self, client, auth_headers, test_workspace, db_session
    ):
        from app.models.workflow import Workflow

        workflow = Workflow(
            workspace_id=test_workspace.id,
            name="W",
            created_by=test_workspace.owner_id,
            flow_definition={"nodes": [], "edges": []},
        )
        db_session.add(workflow)
        await db_session.flush()
        db_session.add_all(
            [
                Execution(
                    workspace_id=test_workspace.id,
                    workflow_id=workflow.id,
                    status="completed",
                    trigger_type="manual",
                ),
                Execution(
                    workspace_id=test_workspace.id,
                    agent_id=None,
                    status="completed",
                    trigger_type="chat",
                ),
            ]
        )
        await db_session.commit()

        response = await client.get(
            f"/api/workspaces/{test_workspace.id}/executions", headers=auth_headers
        )
        assert response.status_code == 200
        items = response.json() if isinstance(response.json(), list) else response.json().get("executions", [])
        assert all(item.get("workflow_id") is not None for item in items)
        assert len(items) == 1


class TestOutputFormatTurn:
    @staticmethod
    async def _run(db_session, session_factory, test_workspace, monkeypatch, window, **kwargs):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        profile = await db_session.get(LlmProfile, agent.llm_profile_id)
        profile.context_window = window
        await db_session.commit()
        seen: dict = {}

        def fake_build_graph(*args, **kw):
            seen.update(kw)
            return FakeGraphV2()

        monkeypatch.setattr("app.services.agent_runtime.async_session", session_factory)
        monkeypatch.setattr("app.services.agent_runtime.build_graph", fake_build_graph)
        events = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id, **kwargs
            )
        ]
        async with session_factory() as check:
            rows = (
                (
                    await check.execute(
                        select(ChatMessage)
                        .where(ChatMessage.session_id == chat_session.id)
                        .order_by(ChatMessage.seq)
                    )
                )
                .scalars()
                .all()
            )
        return events, rows, seen

    @pytest.mark.asyncio
    async def test_reply_defaults_to_markdown(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        events, rows, seen = await self._run(
            db_session, session_factory, test_workspace, monkeypatch, 128_000
        )
        assert events[-1]["event"] == "done"
        assert rows[1].output_format == "markdown"
        assert seen["output_format"] == "markdown"

    @pytest.mark.asyncio
    async def test_openui_turn_is_recorded_and_reaches_the_graph(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        events, rows, seen = await self._run(
            db_session, session_factory, test_workspace, monkeypatch, 200_000,
            output_format="openui",
        )
        assert events[-1]["event"] == "done"
        assert rows[1].output_format == "openui"
        assert seen["output_format"] == "openui"

    @pytest.mark.asyncio
    async def test_openui_is_refused_when_the_profile_shrank_mid_flight(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        events, rows, seen = await self._run(
            db_session, session_factory, test_workspace, monkeypatch, 199_999,
            output_format="openui",
        )
        assert [e["event"] for e in events] == ["error"]
        assert "200,000" in events[-1]["data"]["detail"]
        assert seen == {}
        assert [row.role for row in rows] == ["user"]


class NarratingGraph:
    """The model says something, calls a tool, then gives the real answer."""

    async def astream_events(self, payload, version):
        meta = {"langgraph_checkpoint_ns": "model:1"}
        yield {"event": "on_chat_model_stream", "metadata": meta,
               "data": {"chunk": AIMessageChunk(content="Let me check.")}}
        yield {"event": "on_tool_start", "run_id": "r1", "name": "lookup", "metadata": {},
               "data": {"input": {}}}
        yield {"event": "on_tool_end", "run_id": "r1", "name": "lookup", "metadata": {},
               "data": {"output": "42"}}
        yield {"event": "on_chat_model_stream", "metadata": meta,
               "data": {"chunk": AIMessageChunk(content="The answer is 42.")}}
        yield {"event": "on_chain_end", "name": "LangGraph", "parent_ids": [], "metadata": {},
               "data": {"output": {"messages": [AIMessage(content="The answer is 42.")]}}}


class TestContentReset:
    @pytest.mark.asyncio
    async def test_playground_resets_live_text_when_a_tool_starts(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        _install(monkeypatch, session_factory, NarratingGraph())
        events = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id,
                emit_content_reset=True,
            )
        ]
        kinds = [e["event"] for e in events]
        assert kinds.index("content_reset") < kinds.index("activity")
        after = kinds[kinds.index("content_reset"):]
        live = [e["data"]["delta"] for e in events[len(kinds) - len(after):] if e["event"] == "token"]
        assert "".join(live) == "The answer is 42."

    @pytest.mark.asyncio
    async def test_no_reset_event_by_default(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        _install(monkeypatch, session_factory, NarratingGraph())
        events = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]
        assert "content_reset" not in [e["event"] for e in events]


class TestOutputFormatPrompt:
    def _validated(self):
        from types import SimpleNamespace

        return SimpleNamespace(
            resolved_skills=SimpleNamespace(menu=[]), data_sources=[]
        )

    def test_markdown_adds_nothing(self):
        from app.services.agent_runtime import _system_prompt

        assert _system_prompt("Be brief.", self._validated(), "markdown") == "Be brief."
        assert _system_prompt("Be brief.", self._validated()) == "Be brief."

    def test_openui_appends_the_generated_prompt_last(self):
        from app.services.agent_runtime import _system_prompt
        from app.services.output_formats import openui_prompt

        prompt = _system_prompt("Be brief.", self._validated(), "openui")
        assert prompt.startswith("Be brief.\n\n")
        assert prompt.endswith(openui_prompt())
        assert "root = Card(" in openui_prompt()

    def test_subagents_never_get_the_openui_prompt(self, monkeypatch):
        import inspect

        from app.services import agent_runtime

        source = inspect.getsource(agent_runtime._subagent_runner)
        assert "output_format" not in source


def _tool_event(kind, run_id, ns, **data):
    # Real streams (probed): on_tool_start has no tool_call_id; every attempt of
    # one call shares langgraph_checkpoint_ns, and on_tool_error/on_tool_end
    # carry data["tool_call_id"].
    return {
        "event": kind,
        "run_id": run_id,
        "name": "flaky",
        "metadata": {"langgraph_checkpoint_ns": f"tools:{ns}"},
        "data": data,
    }


class RetryGraph:
    def __init__(self, events):
        self._events = events

    async def astream_events(self, payload, version):
        for event in self._events:
            yield event
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "parent_ids": [],
            "metadata": {},
            "data": {"output": {"messages": [AIMessage(content="ok")]}},
        }


class TestToolRetryActivity:
    async def _run(self, db_session, session_factory, test_workspace, monkeypatch, events):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        _install(monkeypatch, session_factory, RetryGraph(events))
        out = [
            e
            async for e in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]
        return [e["data"] for e in out if e["event"] == "activity"]

    @pytest.mark.asyncio
    async def test_retried_call_streams_one_card(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        events = []
        for i in range(3):
            events.append(_tool_event("on_tool_start", f"r{i}", "A", input={"x": 1}))
            events.append(
                _tool_event(
                    "on_tool_error", f"r{i}", "A", input={"x": 1},
                    error="boom", tool_call_id="call_abc",
                )
            )
        events.append({"event": "on_chain_end", "name": "tools", "metadata": {}, "data": {}})
        activity = await self._run(
            db_session, session_factory, test_workspace, monkeypatch, events
        )
        starts = [a for a in activity if a["type"] == "tool_start"]
        ends = [a for a in activity if a["type"] == "tool_end"]
        assert len(starts) == 1 and len(ends) == 1
        assert starts[0]["id"] == ends[0]["id"]
        assert ends[0]["error"] == "boom"
        assert ends[0]["attempts"] == 3

    @pytest.mark.asyncio
    async def test_retry_that_succeeds_is_one_card_with_attempts(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        events = [
            _tool_event("on_tool_start", "r0", "A", input={}),
            _tool_event("on_tool_error", "r0", "A", input={}, error="boom", tool_call_id="c"),
            _tool_event("on_tool_start", "r1", "A", input={}),
            _tool_event("on_tool_end", "r1", "A", output="fine", tool_call_id="c"),
        ]
        activity = await self._run(
            db_session, session_factory, test_workspace, monkeypatch, events
        )
        ends = [a for a in activity if a["type"] == "tool_end"]
        assert [a["type"] for a in activity] == ["tool_start", "tool_end"]
        assert ends[0]["result"] == "fine" and "error" not in ends[0]
        assert ends[0]["attempts"] == 2

    @pytest.mark.asyncio
    async def test_single_attempt_has_no_attempts_field_and_parallel_calls_stay_separate(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        events = [
            _tool_event("on_tool_start", "a", "A", input={}),
            _tool_event("on_tool_start", "b", "B", input={}),
            _tool_event("on_tool_end", "a", "A", output="1"),
            _tool_event("on_tool_end", "b", "B", output="2"),
        ]
        activity = await self._run(
            db_session, session_factory, test_workspace, monkeypatch, events
        )
        assert len([a for a in activity if a["type"] == "tool_start"]) == 2
        ends = [a for a in activity if a["type"] == "tool_end"]
        assert len(ends) == 2 and all("attempts" not in e for e in ends)
        assert {e["id"] for e in ends} == {"a", "b"}

    @pytest.mark.asyncio
    async def test_sibling_chain_event_does_not_release_a_held_error(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        # Probed: parallel calls each have their own tools:<uuid> namespace; a
        # sibling finishing emits its own chain events while A sleeps between
        # retries, and the loop's LangGraph stream events carry no namespace.
        events = [
            _tool_event("on_tool_start", "a0", "A", input={}),
            _tool_event("on_tool_start", "b0", "B", input={}),
            _tool_event("on_tool_error", "a0", "A", input={}, error="boom", tool_call_id="ca"),
            _tool_event("on_tool_end", "b0", "B", output="2", tool_call_id="cb"),
            {"event": "on_chain_stream", "name": "tools",
             "metadata": {"langgraph_checkpoint_ns": "tools:B"}, "data": {}},
            {"event": "on_chain_end", "name": "tools",
             "metadata": {"langgraph_checkpoint_ns": "tools:B"}, "data": {}},
            {"event": "on_chain_stream", "name": "LangGraph",
             "metadata": {}, "parent_ids": [], "data": {}},
            _tool_event("on_tool_start", "a1", "A", input={}),
            _tool_event("on_tool_end", "a1", "A", output="fine", tool_call_id="ca"),
        ]
        activity = await self._run(
            db_session, session_factory, test_workspace, monkeypatch, events
        )
        a_cards = [a for a in activity if a["id"] == "a0"]
        assert [a["type"] for a in a_cards] == ["tool_start", "tool_end"]
        assert a_cards[1]["attempts"] == 2 and a_cards[1]["result"] == "fine"
        assert not [a for a in activity if a["id"] == "a1"]
        assert len([a for a in activity if a["type"] == "tool_end"]) == 2

    @pytest.mark.asyncio
    async def test_own_tools_node_end_releases_the_held_error_at_once(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        events = [
            _tool_event("on_tool_start", "a0", "A", input={}),
            _tool_event("on_tool_error", "a0", "A", input={}, error="boom", tool_call_id="ca"),
            {"event": "on_chain_end", "name": "tools",
             "metadata": {"langgraph_checkpoint_ns": "tools:A"}, "data": {}},
            _tool_event("on_tool_start", "z", "Z", input={}),
        ]
        _install(monkeypatch, session_factory, RetryGraph(events))
        gen = stream_turn(test_workspace.id, chat_session.id, "hi", execution.id)
        seen = []
        async for e in gen:
            if e["event"] == "activity":
                seen.append(e["data"])
                if e["data"]["id"] == "z":
                    break
        await gen.aclose()
        assert [a["type"] for a in seen] == ["tool_start", "tool_end", "tool_start"]
        assert seen[1]["error"] == "boom"

    async def _assistant_row(self, session_factory, chat_session):
        async with session_factory() as check:
            return (
                (
                    await check.execute(
                        select(ChatMessage).where(
                            ChatMessage.session_id == chat_session.id,
                            ChatMessage.role == "assistant",
                        )
                    )
                )
                .scalars()
                .one()
            )

    @pytest.mark.asyncio
    async def test_stop_persists_a_held_failed_end(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)
        events = [
            _tool_event("on_tool_start", "a0", "A", input={}),
            _tool_event("on_tool_error", "a0", "A", input={}, error="boom", tool_call_id="ca"),
            _tool_event("on_tool_start", "b0", "B", input={}),
        ]
        _install(monkeypatch, session_factory, RetryGraph(events))
        gen = stream_turn(test_workspace.id, chat_session.id, "hi", execution.id)
        async for e in gen:
            if e["event"] == "activity" and e["data"]["id"] == "a0" and e["data"]["type"] == "tool_start":
                continue
            if e["event"] == "activity":
                break
        await gen.aclose()
        row = await self._assistant_row(session_factory, chat_session)
        assert row.status == "stopped"
        ends = [a for a in row.activity if a["type"] == "tool_end"]
        assert len(ends) == 1 and ends[0]["id"] == "a0" and ends[0]["error"] == "boom"

    @pytest.mark.asyncio
    async def test_exception_persists_a_held_failed_end(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        agent, chat_session, execution = await _setup(db_session, test_workspace)

        class Boom:
            async def astream_events(self, payload, version):
                yield _tool_event("on_tool_start", "a0", "A", input={})
                yield _tool_event(
                    "on_tool_error", "a0", "A", input={}, error="boom", tool_call_id="ca"
                )
                raise RuntimeError("graph died")

        _install(monkeypatch, session_factory, Boom())
        out = [
            e
            async for e in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]
        assert out[-1]["event"] == "error"
        row = await self._assistant_row(session_factory, chat_session)
        assert row.status == "failed"
        ends = [a for a in row.activity if a["type"] == "tool_end"]
        assert len(ends) == 1 and ends[0]["error"] == "boom"
