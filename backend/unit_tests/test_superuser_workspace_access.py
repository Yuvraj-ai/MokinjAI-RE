"""Superusers bypass workspace RBAC, and the member they get must be usable.

The bypass used to hand handlers an uninitialised `WorkspaceMember`, so any
handler reading `member.user_id` or `member.role` crashed with a 500 for the
default (superuser) admin: creating a Playground session or an API key, and
reading a workspace.
"""

import pytest
from sqlalchemy import func, select

from app.models.agent import Agent
from app.models.workspace import WorkspaceMember


async def _agent(db_session, workspace_id: str) -> Agent:
    agent = Agent(
        workspace_id=workspace_id, name="Helper", llm_profile_id=None,
        system_prompt="", params={},
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


async def _member_count(db_session) -> int:
    return (await db_session.execute(select(func.count()).select_from(WorkspaceMember))).scalar_one()


@pytest.mark.asyncio
async def test_superuser_without_membership_can_create_a_playground_session(
    client, admin_headers, admin_user, test_workspace, db_session
):
    agent = await _agent(db_session, test_workspace.id)
    before = await _member_count(db_session)

    response = await client.post(
        f"/api/workspaces/{test_workspace.id}/playground/sessions",
        json={"agent_id": agent.id},
        headers=admin_headers,
    )

    assert response.status_code == 201, response.text
    assert response.json()["created_by"] == admin_user.id
    # The bypass must not quietly enrol the superuser in the workspace.
    assert await _member_count(db_session) == before


@pytest.mark.asyncio
async def test_superuser_without_membership_can_create_an_api_key(
    client, admin_headers, test_workspace, db_session
):
    response = await client.post(
        f"/api/workspaces/{test_workspace.id}/api-keys",
        json={"name": "ops", "agent_access": {"mode": "all"}},
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_superuser_without_membership_reads_a_workspace_as_owner(
    client, admin_headers, test_workspace
):
    response = await client.get(f"/api/workspaces/{test_workspace.id}", headers=admin_headers)
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "owner"


@pytest.mark.asyncio
async def test_superuser_with_a_membership_gets_their_real_row(
    client, admin_headers, admin_user, test_workspace, db_session
):
    db_session.add(
        WorkspaceMember(workspace_id=test_workspace.id, user_id=admin_user.id, role="viewer")
    )
    await db_session.commit()
    agent = await _agent(db_session, test_workspace.id)

    read = await client.get(f"/api/workspaces/{test_workspace.id}", headers=admin_headers)
    assert read.json()["role"] == "viewer"

    # Still bypasses the role check: a viewer could not create a session.
    created = await client.post(
        f"/api/workspaces/{test_workspace.id}/playground/sessions",
        json={"agent_id": agent.id},
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
