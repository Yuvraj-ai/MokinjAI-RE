"""The bounded FIFO wait for sandbox capacity (budget.SlotRequest)."""

import asyncio

import pytest

from app.services.sandbox import budget
from app.services.sandbox.budget import SandboxBusy, SlotRequest


@pytest.fixture(autouse=True)
def clean_budget():
    budget.reset()
    yield
    budget.reset()


async def _drain(request, positions):
    async for position in request.wait():
        positions.append(position)


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_free_capacity_reserves_without_waiting():
    positions: list[int] = []
    async with SlotRequest("ws", 1024) as request:
        await _drain(request, positions)
        assert positions == []
        assert budget.used_mb("ws") == 1024
    assert budget.used_mb("ws") == 0


async def test_waiter_starts_when_memory_frees_in_fifo_order():
    assert budget.reserve("ws", 4096)
    first, second = SlotRequest("ws", 2048), SlotRequest("ws", 2048)
    first_positions: list[int] = []
    second_positions: list[int] = []
    first_task = asyncio.create_task(_drain(first, first_positions))
    await _settle()
    second_task = asyncio.create_task(_drain(second, second_positions))
    await _settle()
    assert first_positions == [1]
    assert second_positions == [2]

    budget.release("ws", 2048)  # room for exactly one
    await asyncio.wait_for(first_task, 1)
    await _settle()
    assert not second_task.done()
    assert second_positions == [2, 1]
    assert budget.used_mb("ws") == 4096

    first.release()
    await asyncio.wait_for(second_task, 1)
    second.release()
    budget.release("ws", 2048)
    assert budget.used_mb("ws") == 0


async def test_queue_full_raises_busy_with_reason_queue_full():
    assert budget.reserve("ws", 4096)
    waiting = SlotRequest("ws", 512, max_waiters=1, max_wait_s=30)
    task = asyncio.create_task(_drain(waiting, []))
    await _settle()
    with pytest.raises(SandboxBusy) as caught:
        await _drain(SlotRequest("ws", 512, max_waiters=1), [])
    assert caught.value.reason == "queue_full"
    assert caught.value.retry_after_s >= 5
    assert budget.waiting("ws") == 1
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_deadline_raises_busy_with_reason_timeout():
    assert budget.reserve("ws", 4096)
    request = SlotRequest("ws", 512, max_wait_s=0.05)
    with pytest.raises(SandboxBusy) as caught:
        await _drain(request, [])
    assert caught.value.reason == "timeout"
    assert caught.value.retry_after_s == 5  # the floor
    assert budget.waiting("ws") == 0
    assert budget.used_mb("ws") == 4096


async def test_cancelled_waiter_leaves_queue_and_never_reserves():
    assert budget.reserve("ws", 4096)
    cancelled = SlotRequest("ws", 2048, max_wait_s=30)
    behind = SlotRequest("ws", 2048, max_wait_s=30)
    cancelled_task = asyncio.create_task(_drain(cancelled, []))
    await _settle()
    behind_positions: list[int] = []
    behind_task = asyncio.create_task(_drain(behind, behind_positions))
    await _settle()
    assert budget.waiting("ws") == 2

    cancelled_task.cancel()
    await asyncio.gather(cancelled_task, return_exceptions=True)
    await _settle()
    assert budget.waiting("ws") == 1
    assert behind_positions == [2, 1]

    budget.release("ws", 4096)
    await asyncio.wait_for(behind_task, 1)
    # Only the waiter behind it holds memory; the cancelled one never reserved.
    assert budget.used_mb("ws") == 2048
    assert cancelled.holds_memory is False
    behind.release()
    assert budget.used_mb("ws") == 0


async def test_closing_the_generator_while_queued_leaves_the_queue():
    assert budget.reserve("ws", 4096)
    request = SlotRequest("ws", 512, max_wait_s=30)
    generator = request.wait()
    assert await generator.__anext__() == 1
    await generator.aclose()
    assert budget.waiting("ws") == 0
    budget.release("ws", 4096)
    assert budget.used_mb("ws") == 0


# --- stream_turn and the public API -------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.models.chat import ChatMessage  # noqa: E402
from app.models.execution import Execution  # noqa: E402
from app.services import agent_runtime  # noqa: E402
from app.services.sandbox import SandboxConfig  # noqa: E402
from unit_tests.test_playground_chat import (  # noqa: E402
    FakeGraphV2,
    _install,
    _setup,
    encryption_key,  # noqa: F401  (fixture)
)


def _plan_with(request):
    def plan(workspace_id, validated):
        return SandboxConfig.from_settings(), request

    return plan


async def _collect(stream, events):
    async for event in stream:
        events.append(event)


async def _until_queued(events):
    for _ in range(300):
        if any(e["event"] == "queued" for e in events):
            return
        await asyncio.sleep(0.01)


async def test_stream_turn_emits_queued_then_runs(
    db_session, session_factory, test_workspace, monkeypatch, encryption_key
):
    _agent, chat_session, execution = await _setup(db_session, test_workspace)
    _install(monkeypatch, session_factory, FakeGraphV2())
    assert budget.reserve(test_workspace.id, 4096)
    request = SlotRequest(test_workspace.id, 2048, max_wait_s=10)
    monkeypatch.setattr(agent_runtime, "_plan_slot", _plan_with(request))

    events: list[dict] = []
    task = asyncio.create_task(
        _collect(
            agent_runtime.stream_turn(test_workspace.id, chat_session.id, "hi", execution.id),
            events,
        )
    )
    await _until_queued(events)
    assert [e["event"] for e in events] == ["message", "queued"]
    assert events[1]["data"] == {"position": 1}

    budget.release(test_workspace.id, 4096)
    await asyncio.wait_for(task, 10)

    kinds = [e["event"] for e in events]
    assert kinds[:2] == ["message", "queued"]
    assert kinds[-1] == "done"
    assert kinds.count("queued") == 1
    assert budget.used_mb(test_workspace.id) == 0  # released at teardown


async def test_stream_turn_without_files_never_queues(
    db_session, session_factory, test_workspace, monkeypatch, encryption_key
):
    _agent, chat_session, execution = await _setup(db_session, test_workspace)
    _install(monkeypatch, session_factory, FakeGraphV2())
    events = [
        e
        async for e in agent_runtime.stream_turn(
            test_workspace.id, chat_session.id, "hi", execution.id
        )
    ]
    assert "queued" not in [e["event"] for e in events]
    assert events[-1]["event"] == "done"


async def test_stream_turn_busy_emits_error_with_code(
    db_session, session_factory, test_workspace, monkeypatch, encryption_key
):
    _agent, chat_session, execution = await _setup(db_session, test_workspace)
    _install(monkeypatch, session_factory, FakeGraphV2())
    assert budget.reserve(test_workspace.id, 4096)
    request = SlotRequest(test_workspace.id, 2048, max_wait_s=0.05)
    monkeypatch.setattr(agent_runtime, "_plan_slot", _plan_with(request))

    events = [
        e
        async for e in agent_runtime.stream_turn(
            test_workspace.id, chat_session.id, "hi", execution.id
        )
    ]

    error = events[-1]
    assert error["event"] == "error"
    assert error["data"]["code"] == "sandbox_busy"
    assert error["data"]["retry_after_s"] == 5
    assert error["data"]["detail"] == "The sandbox is busy. Try again in about 5 seconds."
    assert budget.waiting(test_workspace.id) == 0
    async with session_factory() as check:
        row = await check.get(Execution, execution.id)
        assert row.status == "failed"
        assistants = (
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
        assert assistants == []


async def test_stream_turn_stopped_while_queued_never_reserves(
    db_session, session_factory, test_workspace, monkeypatch, encryption_key
):
    _agent, chat_session, execution = await _setup(db_session, test_workspace)
    _install(monkeypatch, session_factory, FakeGraphV2())
    assert budget.reserve(test_workspace.id, 4096)
    request = SlotRequest(test_workspace.id, 2048, max_wait_s=10)
    monkeypatch.setattr(agent_runtime, "_plan_slot", _plan_with(request))

    events: list[dict] = []
    task = asyncio.create_task(
        _collect(
            agent_runtime.stream_turn(test_workspace.id, chat_session.id, "hi", execution.id),
            events,
        )
    )
    await _until_queued(events)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert budget.waiting(test_workspace.id) == 0
    budget.release(test_workspace.id, 4096)
    assert budget.used_mb(test_workspace.id) == 0  # nothing was reserved afterwards
    async with session_factory() as check:
        assert (await check.get(Execution, execution.id)).status == "cancelled"


def test_subagent_open_session_raises_busy_at_once_when_full():
    assert budget.reserve("ws", 4096)
    validated = SimpleNamespace(
        attached_documents=[SimpleNamespace(file_size=1024)], workspace_tools=[]
    )
    with pytest.raises(SandboxBusy) as caught:
        agent_runtime._open_session("ws", validated, None)
    assert caught.value.retry_after_s >= 5
    assert budget.used_mb("ws") == 4096


async def test_public_buffered_busy_returns_429_with_retry_after(
    client, test_workspace, test_user, db_session, session_factory, monkeypatch, encryption_key
):
    from unit_tests.test_public_api import _key_and_agent, auth

    _key, plaintext, agent = await _key_and_agent(db_session, test_workspace, test_user)
    _install(monkeypatch, session_factory, FakeGraphV2())
    assert budget.reserve(test_workspace.id, 4096)
    request = SlotRequest(test_workspace.id, 2048, max_wait_s=0.05)
    monkeypatch.setattr(agent_runtime, "_plan_slot", _plan_with(request))

    response = await client.post(
        "/v1/chat",
        json={"agent_id": agent.id, "message": "hi"},
        headers=auth(plaintext),
    )

    assert response.status_code == 429, response.text
    assert response.headers["Retry-After"] == "5"
    error = response.json()["error"]
    assert error["code"] == "sandbox_busy"
    assert error["message"] == "The sandbox is busy. Try again in about 5 seconds."


async def _until(condition, timeout=1.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached"
        await asyncio.sleep(0.005)


async def test_large_head_blocks_a_smaller_tail_that_would_fit():
    assert budget.reserve("ws", 4096)
    head, tail = SlotRequest("ws", 2048), SlotRequest("ws", 512)
    head_task = asyncio.create_task(_drain(head, []))
    await _until(lambda: budget.waiting("ws") == 1)
    tail_task = asyncio.create_task(_drain(tail, []))
    await _until(lambda: budget.waiting("ws") == 2)

    budget.release("ws", 1536)  # 1536 free: the tail would fit, the head does not
    await _settle()
    assert not tail_task.done()
    assert not tail.holds_memory
    assert budget.waiting("ws") == 2
    assert budget.used_mb("ws") == 2560

    budget.release("ws", 1024)  # now the head fits; it goes first, then the tail
    await asyncio.wait_for(head_task, 1)
    await asyncio.wait_for(tail_task, 1)
    assert head.holds_memory and tail.holds_memory
    head.release()
    tail.release()
    budget.release("ws", 1536)
    assert budget.used_mb("ws") == 0


async def test_grant_then_cancel_before_resuming_returns_memory():
    assert budget.reserve("ws", 4096)
    request = SlotRequest("ws", 2048)
    task = asyncio.create_task(_drain(request, []))
    await _until(lambda: budget.waiting("ws") == 1)
    baseline = budget.used_mb("ws")

    budget.release("ws", 2048)  # grants the head...
    task.cancel()  # ...and cancel in the same instant, before it resumes
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    assert not request.holds_memory
    assert budget.waiting("ws") == 0
    assert budget.used_mb("ws") == baseline - 2048


async def test_subagent_busy_is_a_tool_error_and_is_not_retried(monkeypatch):
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage, ToolMessage

    from app.services import agent_resilience, agent_runtime
    from app.services.agent_tools import subagent_tool
    from unit_tests.fakes import ScriptedChatModel, tool_call_message

    monkeypatch.setattr(agent_resilience, "TOOL_RETRY_INITIAL_DELAY_S", 0.0)
    monkeypatch.setattr(agent_resilience, "TOOL_RETRY_MAX_DELAY_S", 0.0)

    class _Db:
        async def get(self, model, key):
            return SimpleNamespace(id=key, workspace_id="ws")

    class _Scope:
        async def __aenter__(self):
            return _Db()

        async def __aexit__(self, *exc):
            return None

    validated = SimpleNamespace(
        attached_documents=[SimpleNamespace(file_size=1024)], workspace_tools=[]
    )

    async def fake_saved_input(db, child):
        return None

    async def fake_validate(db, workspace_id, data, agent_id=None):
        return validated

    async def fake_stage(documents):
        return None, [], []

    monkeypatch.setattr(agent_runtime, "async_session", lambda: _Scope())
    monkeypatch.setattr(agent_runtime, "saved_input", fake_saved_input)
    monkeypatch.setattr(agent_runtime, "validate_agent", fake_validate)
    monkeypatch.setattr(agent_runtime, "_stage_files", fake_stage)
    attempts: list[int] = []
    real_open = agent_runtime._open_session

    def counting_open(*args, **kwargs):
        attempts.append(1)
        return real_open(*args, **kwargs)

    monkeypatch.setattr(agent_runtime, "_open_session", counting_open)

    assert budget.reserve("ws", 4096)  # the parent already holds everything
    child = subagent_tool(
        agent_id="abcd1234",
        name="helper",
        description=None,
        run=agent_runtime._subagent_runner("ws", "abcd1234", 1),
    )
    parent = create_agent(
        ScriptedChatModel(
            script=[
                tool_call_message(child.name, "1", {"task": "do it"}),
                AIMessage(content="done"),
            ]
        ),
        [child],
        middleware=agent_resilience.tool_middleware(),
    )
    out = await parent.ainvoke({"messages": [("user", "go")]})

    assert out["messages"][-1].content == "done"
    errors = [m for m in out["messages"] if isinstance(m, ToolMessage)]
    assert len(errors) == 1 and errors[0].status == "error"
    assert "busy" in errors[0].content.lower()
    assert len(attempts) == 1
    assert budget.used_mb("ws") == 4096
