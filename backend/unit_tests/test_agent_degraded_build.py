import asyncio
import logging
from types import SimpleNamespace

import pytest

from app.logging import logger as app_logger
from app.services import agent_runtime, connector_runtime
from app.services.agent_runtime import _system_prompt, build_tools, stream_turn
from unit_tests.test_connectors import _StubClient
from unit_tests.test_playground_chat import (
    FakeGraphV2,
    _install,
    _setup,
    encryption_key,  # noqa: F401  (fixture)
)


@pytest.fixture
def warnings_log(caplog):
    app_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING)
    yield caplog
    app_logger.removeHandler(caplog.handler)


def _instance(name, ident):
    return SimpleNamespace(id=ident, name=name)


def _validated(**overrides):
    base = dict(
        workspace_tools=[],
        effective_tools=(),
        data_sources=[],
        selected_skills=[],
        resolved_skills=None,
        connectors=[],
        subagents=[],
        web_search=None,
        attached_documents=[],
        profile=SimpleNamespace(provider="openai"),
        agent_id="a1",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _prompt_validated():
    return SimpleNamespace(
        resolved_skills=SimpleNamespace(menu=[]), data_sources=[]
    )


async def test_unreachable_connector_is_skipped_and_others_load(monkeypatch, warnings_log):
    class Client(_StubClient):
        async def get_tools(self, *, server_name=None):
            if server_name == "bad":
                raise ConnectionError("boom https://user:secret@host/x")
            return await super().get_tools(server_name=server_name)

    monkeypatch.setattr(_StubClient, "tools_by_server", {"good": ["read_file"]})
    monkeypatch.setattr(connector_runtime, "MultiServerMCPClient", Client)
    monkeypatch.setattr(connector_runtime, "connections_for", lambda instances: {})

    tools, failed = await connector_runtime.load_connector_tools(
        [_instance("Slack", "bad"), _instance("Files", "good")]
    )

    assert [tool.name for tool in tools] == ["read_file"]
    assert failed == ["Slack"]
    lines = [r.getMessage() for r in warnings_log.records if "Slack" in r.getMessage()]
    assert len(lines) == 1
    assert "ConnectionError" in lines[0]
    assert "secret" not in lines[0]
    assert warnings_log.records[-1].exc_info is None


async def test_slow_connector_times_out_and_is_skipped(monkeypatch):
    class Client(_StubClient):
        async def get_tools(self, *, server_name=None):
            await asyncio.sleep(1)
            return []

    monkeypatch.setattr(connector_runtime, "MultiServerMCPClient", Client)
    monkeypatch.setattr(connector_runtime, "connections_for", lambda instances: {})
    monkeypatch.setattr(connector_runtime, "CONNECTOR_LOAD_TIMEOUT_S", 0.05)

    tools, failed = await connector_runtime.load_connector_tools([_instance("Slow", "s")])

    assert tools == []
    assert failed == ["Slow"]


async def test_missing_search_key_skips_web_search(db_session, test_workspace, warnings_log):
    unavailable: list[str] = []
    validated = _validated(web_search={"method": "tavily"})

    tools = await build_tools(
        db_session, test_workspace.id, validated, None, depth=0, unavailable=unavailable
    )

    assert tools == []
    assert unavailable == ["Web search: no tavily API key"]
    assert any("Web search" in r.getMessage() for r in warnings_log.records)


async def test_unparseable_workspace_tool_is_skipped(db_session, test_workspace, warnings_log):
    unavailable: list[str] = []
    row = SimpleNamespace(name="parse_csv", code="def broken(:")
    validated = _validated(workspace_tools=[row], effective_tools=("parse_csv",))

    tools = await build_tools(
        db_session, test_workspace.id, validated, None, depth=0, unavailable=unavailable
    )

    assert tools == []
    assert unavailable == ["Tool parse_csv (code no longer parses)"]
    assert any("parse_csv" in r.getMessage() for r in warnings_log.records)


async def test_failed_connector_is_named_by_build_tools(
    db_session, test_workspace, monkeypatch
):
    async def fake_load(instances):
        return [], ["Slack"]

    monkeypatch.setattr(agent_runtime, "load_connector_tools", fake_load)
    unavailable: list[str] = []

    await build_tools(
        db_session,
        test_workspace.id,
        _validated(connectors=[object()]),
        None,
        depth=0,
        unavailable=unavailable,
    )

    assert unavailable == ["Connector Slack (unreachable)"]


def test_unavailable_section_is_in_the_system_prompt():
    text = _system_prompt(
        "Base.", _prompt_validated(), unavailable=["Connector Slack (unreachable)"]
    )
    assert "unavailable for this run" in text
    assert "Connector Slack (unreachable)" in text
    assert "Do not call them" in text


def test_unavailable_section_precedes_the_openui_block(monkeypatch):
    monkeypatch.setattr(agent_runtime, "openui_prompt", lambda: "OPENUI-RULES")
    text = _system_prompt(
        "Base.", _prompt_validated(), "openui", unavailable=["Web search: no exa API key"]
    )
    assert text.index("unavailable for this run") < text.index("OPENUI-RULES")


def test_no_section_when_everything_loads():
    assert _system_prompt("Base.", _prompt_validated(), unavailable=[]) == "Base."
    assert _system_prompt("Base.", _prompt_validated()) == "Base."


async def test_stream_turn_emits_unavailable_event_and_completes(
    db_session, session_factory, test_workspace, monkeypatch, encryption_key
):
    agent, chat_session, execution = await _setup(db_session, test_workspace)
    _install(monkeypatch, session_factory, FakeGraphV2())

    async def fake_build_tools(*args, unavailable=None, **kwargs):
        unavailable.append("Connector Slack (unreachable)")
        return []

    monkeypatch.setattr(agent_runtime, "build_tools", fake_build_tools)

    events = [
        event
        async for event in stream_turn(test_workspace.id, chat_session.id, "hi", execution.id)
    ]

    assert events[0]["event"] == "message"
    assert events[1] == {
        "event": "activity",
        "data": {"type": "unavailable", "names": ["Connector Slack (unreachable)"]},
    }
    assert events[-1]["event"] == "done"
