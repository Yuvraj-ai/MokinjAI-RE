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
