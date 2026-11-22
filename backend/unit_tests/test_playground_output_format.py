"""Playground output format over HTTP: validated server-side per turn.

The frontend disables OpenUI for small models, but the backend must refuse it on
its own, against the agent's current profile.
"""

import pytest
from sqlalchemy import select

from app.crypto import encrypt_api_key
from app.models.agent import Agent
from app.models.chat import ChatSession
from app.models.execution import Execution
from app.models.llm_profile import LlmProfile


async def _make(db_session, workspace_id: str, window: int | None):
    profile_id = None
    if window is not None:
        profile = LlmProfile(
            workspace_id=workspace_id,
            name=f"P{window}",
            provider="custom",
            model_id="m",
            base_url="https://llm.example/v1",
            encrypted_api_key=encrypt_api_key("sk-test"),
            context_window=window,
            compaction_at_tokens=int(window * 0.8),
            input_price_per_million=0,
            output_price_per_million=0,
            cache_price_per_million=0,
            status="verified",
        )
        db_session.add(profile)
        await db_session.flush()
        profile_id = profile.id
    agent = Agent(
        workspace_id=workspace_id,
        name=f"A{window}",
        llm_profile_id=profile_id,
        system_prompt="Be brief.",
        params={},
    )
    db_session.add(agent)
    await db_session.flush()
    chat_session = ChatSession(workspace_id=workspace_id, agent_id=agent.id)
    db_session.add(chat_session)
    await db_session.commit()
    await db_session.refresh(agent)
    await db_session.refresh(chat_session)
    return agent, chat_session


@pytest.fixture
def captured(monkeypatch):
    seen: dict = {}

    async def fake_stream_turn(workspace_id, session_id, content, execution_id, **kwargs):
        seen.update(kwargs)
        yield {"event": "done", "data": {"usage": {}, "cost_usd": 0, "status": "completed"}}

    monkeypatch.setattr("app.routers.playground.stream_turn", fake_stream_turn)
    return seen


def _url(workspace_id: str, session_id: str) -> str:
    return f"/api/workspaces/{workspace_id}/playground/sessions/{session_id}/chat"


@pytest.mark.asyncio
async def test_agent_capabilities_list_the_eligible_formats(
    client, auth_headers, test_workspace, db_session
):
    big, _ = await _make(db_session, test_workspace.id, 256_000)
    small, _ = await _make(db_session, test_workspace.id, 128_000)
    base = f"/api/workspaces/{test_workspace.id}/agents"

    got_big = (await client.get(f"{base}/{big.id}", headers=auth_headers)).json()
    got_small = (await client.get(f"{base}/{small.id}", headers=auth_headers)).json()

    assert got_big["capabilities"]["output_formats"] == ["markdown", "openui"]
    assert got_big["capabilities"]["context_window"] == 256_000
    assert got_small["capabilities"]["output_formats"] == ["markdown"]
    assert got_small["capabilities"]["context_window"] == 128_000


@pytest.mark.asyncio
async def test_default_turn_is_markdown(
    client, auth_headers, test_workspace, db_session, captured
):
    _, chat = await _make(db_session, test_workspace.id, 128_000)
    response = await client.post(
        _url(test_workspace.id, chat.id), json={"content": "hi"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert captured["output_format"] == "markdown"


@pytest.mark.asyncio
async def test_openui_is_accepted_at_exactly_200000(
    client, auth_headers, test_workspace, db_session, captured
):
    _, chat = await _make(db_session, test_workspace.id, 200_000)
    response = await client.post(
        _url(test_workspace.id, chat.id),
        json={"content": "hi", "output_format": "openui"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert captured["output_format"] == "openui"


@pytest.mark.asyncio
async def test_openui_is_refused_at_199999_without_creating_a_run(
    client, auth_headers, test_workspace, db_session, captured
):
    _, chat = await _make(db_session, test_workspace.id, 199_999)
    response = await client.post(
        _url(test_workspace.id, chat.id),
        json={"content": "hi", "output_format": "openui"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "200,000" in response.json()["detail"]
    assert captured == {}
    assert (await db_session.execute(select(Execution))).first() is None


@pytest.mark.asyncio
async def test_openui_is_refused_for_an_agent_without_a_model(
    client, auth_headers, test_workspace, db_session, captured
):
    _, chat = await _make(db_session, test_workspace.id, None)
    response = await client.post(
        _url(test_workspace.id, chat.id),
        json={"content": "hi", "output_format": "openui"},
        headers=auth_headers,
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_unknown_format_is_a_validation_error(
    client, auth_headers, test_workspace, db_session, captured
):
    _, chat = await _make(db_session, test_workspace.id, 1_000_000)
    response = await client.post(
        _url(test_workspace.id, chat.id),
        json={"content": "hi", "output_format": "html"},
        headers=auth_headers,
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_format_is_recorded_on_the_execution(
    client, auth_headers, test_workspace, db_session, captured
):
    _, chat = await _make(db_session, test_workspace.id, 256_000)
    await client.post(
        _url(test_workspace.id, chat.id),
        json={"content": "hi", "output_format": "openui"},
        headers=auth_headers,
    )
    execution = (await db_session.execute(select(Execution))).scalars().one()
    assert execution.input_data["output_format"] == "openui"
