"""Per-key agent access: which agents an API key may call.

Rules under test:
- creating a key requires an explicit choice (all agents / selected agents)
- access can be changed at any time, including after the key has been used
- the public API enforces it on new conversations, continued conversations and
  the agent list
- keys created through the service default to "all agents" (existing keys)
"""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.config import get_settings
from app.models.agent import Agent
from app.models.chat import ChatSession
from app.models.execution import Execution
from app.services.api_keys import create_key
from unit_tests.test_playground_chat import FakeGraphV2, make_profile

BASE = "/api/workspaces/{ws}/api-keys"


@pytest.fixture
def encryption_key():
    settings = get_settings()
    previous = getattr(settings, "LLM_ENCRYPTION_KEY", "")
    settings.LLM_ENCRYPTION_KEY = Fernet.generate_key().decode()
    yield settings.LLM_ENCRYPTION_KEY
    settings.LLM_ENCRYPTION_KEY = previous


def auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


async def _agents(db_session, workspace_id, names=("Alpha", "Beta", "Gamma")):
    profile = make_profile(workspace_id)
    db_session.add(profile)
    await db_session.flush()
    agents = []
    for name in names:
        agent = Agent(
            workspace_id=workspace_id,
            name=name,
            llm_profile_id=profile.id,
            system_prompt="Be brief.",
            params={},
        )
        db_session.add(agent)
        agents.append(agent)
    await db_session.commit()
    for agent in agents:
        await db_session.refresh(agent)
    return agents


async def _create(client, ws_id, headers, agent_access, name="Key"):
    return await client.post(
        BASE.format(ws=ws_id),
        json={"name": name, "agent_access": agent_access},
        headers=headers,
    )


def _install(monkeypatch, session_factory):
    monkeypatch.setattr("app.services.agent_runtime.async_session", session_factory)
    monkeypatch.setattr(
        "app.services.agent_runtime.build_graph", lambda *a, **k: FakeGraphV2()
    )


class TestManagement:
    @pytest.mark.asyncio
    async def test_agent_access_is_required_on_create(
        self, client, auth_headers, test_workspace
    ):
        response = await client.post(
            BASE.format(ws=test_workspace.id), json={"name": "K"}, headers=auth_headers
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_for_all_agents(self, client, auth_headers, test_workspace):
        response = await _create(
            client, test_workspace.id, auth_headers, {"mode": "all"}
        )
        assert response.status_code == 201, response.text
        assert response.json()["agent_access"] == {"mode": "all", "agent_ids": []}

    @pytest.mark.asyncio
    async def test_create_for_selected_agents(
        self, client, auth_headers, test_workspace, db_session
    ):
        alpha, beta, _gamma = await _agents(db_session, test_workspace.id)
        response = await _create(
            client,
            test_workspace.id,
            auth_headers,
            {"mode": "selected", "agent_ids": [alpha.id, beta.id, alpha.id]},
        )
        assert response.status_code == 201, response.text
        access = response.json()["agent_access"]
        assert access["mode"] == "selected"
        assert sorted(access["agent_ids"]) == sorted([alpha.id, beta.id])

    @pytest.mark.asyncio
    async def test_selected_needs_at_least_one_agent(
        self, client, auth_headers, test_workspace
    ):
        response = await _create(
            client, test_workspace.id, auth_headers, {"mode": "selected", "agent_ids": []}
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_unknown_or_foreign_agent_is_rejected(
        self, client, auth_headers, test_workspace
    ):
        response = await _create(
            client,
            test_workspace.id,
            auth_headers,
            {"mode": "selected", "agent_ids": ["00000000-0000-0000-0000-000000000000"]},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_access_can_be_changed_after_the_key_has_been_used(
        self, client, auth_headers, test_workspace, db_session
    ):
        alpha, beta, _gamma = await _agents(db_session, test_workspace.id)
        created = (
            await _create(
                client, test_workspace.id, auth_headers,
                {"mode": "selected", "agent_ids": [alpha.id]},
            )
        ).json()
        # The key has run a request already.
        db_session.add(
            Execution(
                workspace_id=test_workspace.id,
                agent_id=alpha.id,
                api_key_id=created["id"],
                status="completed",
                trigger_type="api",
            )
        )
        await db_session.commit()

        url = BASE.format(ws=test_workspace.id) + f"/{created['id']}"
        changed = await client.patch(
            url,
            json={"agent_access": {"mode": "selected", "agent_ids": [beta.id]}},
            headers=auth_headers,
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["agent_access"]["agent_ids"] == [beta.id]

        widened = await client.patch(
            url, json={"agent_access": {"mode": "all"}}, headers=auth_headers
        )
        assert widened.json()["agent_access"] == {"mode": "all", "agent_ids": []}

        narrowed = await client.patch(
            url,
            json={"agent_access": {"mode": "selected", "agent_ids": [alpha.id]}},
            headers=auth_headers,
        )
        assert narrowed.json()["agent_access"]["agent_ids"] == [alpha.id]
        fetched = await client.get(url, headers=auth_headers)
        assert fetched.json()["agent_access"]["agent_ids"] == [alpha.id]

    @pytest.mark.asyncio
    async def test_patch_without_agent_access_leaves_it_alone(
        self, client, auth_headers, test_workspace, db_session
    ):
        alpha, *_ = await _agents(db_session, test_workspace.id)
        created = (
            await _create(
                client, test_workspace.id, auth_headers,
                {"mode": "selected", "agent_ids": [alpha.id]},
            )
        ).json()
        url = BASE.format(ws=test_workspace.id) + f"/{created['id']}"
        renamed = await client.patch(url, json={"name": "Renamed"}, headers=auth_headers)
        assert renamed.json()["agent_access"]["agent_ids"] == [alpha.id]

    @pytest.mark.asyncio
    async def test_deleting_an_agent_drops_it_from_the_key(
        self, client, auth_headers, test_workspace, db_session
    ):
        alpha, beta, _ = await _agents(db_session, test_workspace.id)
        created = (
            await _create(
                client, test_workspace.id, auth_headers,
                {"mode": "selected", "agent_ids": [alpha.id, beta.id]},
            )
        ).json()
        await db_session.delete(alpha)
        await db_session.commit()
        fetched = await client.get(
            BASE.format(ws=test_workspace.id) + f"/{created['id']}", headers=auth_headers
        )
        assert fetched.json()["agent_access"]["agent_ids"] == [beta.id]

    @pytest.mark.asyncio
    async def test_access_changes_are_audited(
        self, client, auth_headers, test_workspace, db_session
    ):
        from app.models.api_key import AuditLog

        alpha, *_ = await _agents(db_session, test_workspace.id)
        created = (
            await _create(client, test_workspace.id, auth_headers, {"mode": "all"})
        ).json()
        await client.patch(
            BASE.format(ws=test_workspace.id) + f"/{created['id']}",
            json={"agent_access": {"mode": "selected", "agent_ids": [alpha.id]}},
            headers=auth_headers,
        )
        actions = (
            await db_session.execute(
                select(AuditLog.action).where(AuditLog.resource_id == created["id"])
            )
        ).scalars().all()
        assert "access_updated" in actions

    @pytest.mark.asyncio
    async def test_service_created_keys_default_to_all_agents(
        self, db_session, test_workspace, test_user, client, auth_headers
    ):
        key, _ = await create_key(
            db_session, workspace_id=test_workspace.id, user_id=test_user.id, name="Old"
        )
        await db_session.commit()
        fetched = await client.get(
            BASE.format(ws=test_workspace.id) + f"/{key.id}", headers=auth_headers
        )
        assert fetched.json()["agent_access"] == {"mode": "all", "agent_ids": []}


async def _selected_key(db_session, test_workspace, test_user, client, auth_headers, ids):
    created = (
        await _create(
            client, test_workspace.id, auth_headers,
            {"mode": "selected", "agent_ids": ids},
        )
    ).json()
    return created["id"], created["key"]


class TestPublicEnforcement:
    @pytest.mark.asyncio
    async def test_allowed_agent_runs_and_restricted_agent_is_403(
        self, client, auth_headers, test_workspace, test_user, db_session,
        session_factory, monkeypatch, encryption_key,
    ):
        alpha, beta, _ = await _agents(db_session, test_workspace.id)
        _key_id, plaintext = await _selected_key(
            db_session, test_workspace, test_user, client, auth_headers, [alpha.id]
        )
        _install(monkeypatch, session_factory)

        ok = await client.post(
            "/v1/chat", json={"agent_id": alpha.id, "message": "hi"}, headers=auth(plaintext)
        )
        assert ok.status_code == 200, ok.text

        blocked = await client.post(
            "/v1/chat", json={"agent_id": beta.id, "message": "hi"}, headers=auth(plaintext)
        )
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "agent_not_permitted"
        assert blocked.json()["error"]["type"] == "permission_error"

        # The refused call left no session or execution behind.
        beta_id = beta.id
        db_session.expire_all()
        sessions = (
            await db_session.execute(
                select(func.count()).select_from(ChatSession).where(ChatSession.agent_id == beta_id)
            )
        ).scalar_one()
        runs = (
            await db_session.execute(
                select(func.count()).select_from(Execution).where(Execution.agent_id == beta_id)
            )
        ).scalar_one()
        assert sessions == 0 and runs == 0

    @pytest.mark.asyncio
    async def test_unknown_agent_id_is_also_403_not_404(
        self, client, auth_headers, test_workspace, test_user, db_session
    ):
        alpha, *_ = await _agents(db_session, test_workspace.id)
        _key_id, plaintext = await _selected_key(
            db_session, test_workspace, test_user, client, auth_headers, [alpha.id]
        )
        response = await client.post(
            "/v1/chat",
            json={"agent_id": "00000000-0000-0000-0000-000000000000", "message": "hi"},
            headers=auth(plaintext),
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "agent_not_permitted"

    @pytest.mark.asyncio
    async def test_agent_list_is_filtered_to_the_key(
        self, client, auth_headers, test_workspace, test_user, db_session
    ):
        alpha, beta, gamma = await _agents(db_session, test_workspace.id)
        _key_id, selected = await _selected_key(
            db_session, test_workspace, test_user, client, auth_headers, [alpha.id, gamma.id]
        )
        all_key = (
            await _create(client, test_workspace.id, auth_headers, {"mode": "all"}, name="All")
        ).json()["key"]

        listed = await client.get("/v1/agent", headers=auth(selected))
        assert sorted(a["name"] for a in listed.json()["agents"]) == ["Alpha", "Gamma"]
        everything = await client.get("/v1/agent", headers=auth(all_key))
        assert len(everything.json()["agents"]) == 3

    @pytest.mark.asyncio
    async def test_all_key_sees_later_agents_selected_key_does_not(
        self, client, auth_headers, test_workspace, test_user, db_session
    ):
        alpha, *_ = await _agents(db_session, test_workspace.id, names=("Alpha",))
        _key_id, selected = await _selected_key(
            db_session, test_workspace, test_user, client, auth_headers, [alpha.id]
        )
        all_key = (
            await _create(client, test_workspace.id, auth_headers, {"mode": "all"}, name="All")
        ).json()["key"]
        await _agents(db_session, test_workspace.id, names=("Later",))

        assert [a["name"] for a in (await client.get("/v1/agent", headers=auth(selected))).json()["agents"]] == ["Alpha"]
        assert len((await client.get("/v1/agent", headers=auth(all_key))).json()["agents"]) == 2

    @pytest.mark.asyncio
    async def test_changing_access_takes_effect_on_the_next_call(
        self, client, auth_headers, test_workspace, test_user, db_session,
        session_factory, monkeypatch, encryption_key,
    ):
        alpha, beta, _ = await _agents(db_session, test_workspace.id)
        key_id, plaintext = await _selected_key(
            db_session, test_workspace, test_user, client, auth_headers, [alpha.id]
        )
        _install(monkeypatch, session_factory)
        before = await client.post(
            "/v1/chat", json={"agent_id": beta.id, "message": "hi"}, headers=auth(plaintext)
        )
        assert before.status_code == 403

        await client.patch(
            BASE.format(ws=test_workspace.id) + f"/{key_id}",
            json={"agent_access": {"mode": "selected", "agent_ids": [alpha.id, beta.id]}},
            headers=auth_headers,
        )
        after = await client.post(
            "/v1/chat", json={"agent_id": beta.id, "message": "hi"}, headers=auth(plaintext)
        )
        assert after.status_code == 200, after.text

    @pytest.mark.asyncio
    async def test_existing_conversation_is_blocked_once_access_is_removed(
        self, client, auth_headers, test_workspace, test_user, db_session,
        session_factory, monkeypatch, encryption_key,
    ):
        alpha, beta, _ = await _agents(db_session, test_workspace.id)
        key_id, plaintext = await _selected_key(
            db_session, test_workspace, test_user, client, auth_headers, [alpha.id]
        )
        _install(monkeypatch, session_factory)
        first = await client.post(
            "/v1/chat", json={"agent_id": alpha.id, "message": "hi"}, headers=auth(plaintext)
        )
        conversation = first.json()["conversation_id"]

        await client.patch(
            BASE.format(ws=test_workspace.id) + f"/{key_id}",
            json={"agent_access": {"mode": "selected", "agent_ids": [beta.id]}},
            headers=auth_headers,
        )
        again = await client.post(
            "/v1/chat",
            json={"conversation_id": conversation, "message": "more"},
            headers=auth(plaintext),
        )
        assert again.status_code == 403
        assert again.json()["error"]["code"] == "agent_not_permitted"
