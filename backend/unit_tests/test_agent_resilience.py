import logging

import pytest
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool

from app.logging import logger as app_logger
from app.services import agent_resilience as ar
from unit_tests.fakes import ScriptedChatModel, tool_call_message

BLOCKED = "This tool is not available right now. Continue without it or tell the user."


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(ar, "TOOL_RETRY_INITIAL_DELAY_S", 0.0)
    monkeypatch.setattr(ar, "TOOL_RETRY_MAX_DELAY_S", 0.0)


class _Status(Exception):
    def __init__(self, code):
        super().__init__(f"status {code}")
        self.status_code = code


class _Resp:
    def __init__(self, code):
        self.status_code = code


class _ViaResponse(Exception):
    def __init__(self, code):
        super().__init__("http")
        self.response = _Resp(code)


def make_tool(name, behaviour, calls):
    @tool(name)
    def fn() -> str:
        """Test tool."""
        calls.append(1)
        return behaviour(len(calls))

    return fn


async def run(tools, script):
    agent = create_agent(
        ScriptedChatModel(script=list(script)), tools, middleware=ar.tool_middleware()
    )
    out = await agent.ainvoke({"messages": [("user", "go")]})
    return [m for m in out["messages"] if isinstance(m, ToolMessage)], out


def raiser(exc):
    def _b(n):
        raise exc

    return _b


async def test_transient_error_is_retried_twice_then_reported():
    calls = []
    t = make_tool("flaky", raiser(ConnectionError("down")), calls)
    msgs, out = await run(
        [t], [tool_call_message("flaky", "1"), AIMessage(content="done")]
    )
    assert len(calls) == 3
    assert out["messages"][-1].content == "done"
    assert msgs[0].status == "error"
    assert "flaky" in msgs[0].content


async def test_non_transient_error_is_reported_without_retry():
    calls = []
    t = make_tool("bad", raiser(ValueError("nope")), calls)
    msgs, out = await run([t], [tool_call_message("bad", "1"), AIMessage(content="done")])
    assert len(calls) == 1
    assert msgs[0].status == "error"
    assert out["messages"][-1].content == "done"


async def test_success_after_one_transient_failure_returns_the_result():
    calls = []

    def b(n):
        if n == 1:
            raise TimeoutError("slow")
        return "fine"

    t = make_tool("sometimes", b, calls)
    msgs, _ = await run([t], [tool_call_message("sometimes", "1"), AIMessage(content="ok")])
    assert len(calls) == 2
    assert msgs[0].status != "error"
    assert msgs[0].content == "fine"


def test_http_429_and_503_are_transient_but_400_is_not():
    assert ar.is_transient(_Status(429))
    assert ar.is_transient(_Status(503))
    assert ar.is_transient(_ViaResponse(502))
    assert not ar.is_transient(_Status(400))
    assert not ar.is_transient(_ViaResponse(404))
    assert ar.is_transient(TimeoutError())
    assert ar.is_transient(ConnectionError())
    assert not ar.is_transient(ValueError())


async def test_failure_is_logged_once_as_warning_without_traceback(caplog):
    calls = []
    t = make_tool("flaky", raiser(ConnectionError("down")), calls)
    app_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=app_logger.name):
            await run([t], [tool_call_message("flaky", "1"), AIMessage(content="d")])
    finally:
        app_logger.removeHandler(caplog.handler)
    records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(records) == 1
    assert not records[0].exc_info
    assert "flaky" in records[0].getMessage()
    assert "ConnectionError" in records[0].getMessage()


async def test_error_message_hides_connection_strings():
    t = make_tool("db", raiser(ValueError("cannot reach postgresql://u:p@h/db")), [])
    msgs, _ = await run([t], [tool_call_message("db", "1"), AIMessage(content="d")])
    assert "p@h" not in msgs[0].content
    assert "***@" in msgs[0].content


async def test_subagent_failure_comes_back_as_tool_error():
    t = make_tool("sub_agent", raiser(RuntimeError("boom")), [])
    msgs, out = await run([t], [tool_call_message("sub_agent", "1"), AIMessage(content="d")])
    assert msgs[0].status == "error"
    assert out["messages"][-1].content == "d"


async def test_third_failure_blocks_the_tool_for_the_rest_of_the_run():
    calls = []
    t = make_tool("bad", raiser(ValueError("x")), calls)
    script = [tool_call_message("bad", str(i)) for i in range(5)] + [AIMessage(content="d")]
    msgs, out = await run([t], script)
    assert len(calls) == 3
    assert [m.content for m in msgs[3:]] == [BLOCKED, BLOCKED]
    assert all(m.status == "error" for m in msgs[3:])
    assert out["messages"][-1].content == "d"


async def test_successful_calls_are_never_limited():
    calls = []
    t = make_tool("good", lambda n: "ok", calls)
    script = [tool_call_message("good", str(i)) for i in range(6)] + [AIMessage(content="d")]
    msgs, _ = await run([t], script)
    assert len(calls) == 6
    assert all(m.content == "ok" for m in msgs)


async def test_failure_limit_is_per_tool():
    a_calls, b_calls = [], []
    a = make_tool("a", raiser(ValueError("x")), a_calls)
    b = make_tool("b", lambda n: "b-ok", b_calls)
    script = [tool_call_message("a", str(i)) for i in range(3)]
    script += [tool_call_message("b", "9"), AIMessage(content="d")]
    msgs, _ = await run([a, b], script)
    assert len(a_calls) == 3
    assert len(b_calls) == 1
    assert msgs[-1].content == "b-ok"


async def test_failure_counts_reset_for_a_new_graph():
    calls = []
    t = make_tool("bad", raiser(ValueError("x")), calls)
    script = [tool_call_message("bad", str(i)) for i in range(3)] + [AIMessage(content="d")]
    await run([t], script)
    assert len(calls) == 3
    msgs, _ = await run(
        [t], [tool_call_message("bad", "n"), AIMessage(content="d")]
    )
    assert len(calls) == 4
    assert msgs[0].content != BLOCKED
