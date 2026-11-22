"""Agent list and detail must not issue queries per agent.

Every query is a network round trip to the database; against a hosted
database the list used to cost about 10 sequential queries per agent. The
list now loads each kind of data once for all agents, so its query count
does not grow with the number of agents, and its status badge still comes
from the same checks as the detail view.
"""

import pytest
from sqlalchemy import event

from app.crypto import encrypt_api_key
from app.models.agent import Agent, AgentSkill, AgentTool
from app.models.llm_profile import LlmProfile
from app.models.skill import Skill
from app.models.tool import Tool

TOOL_CODE = '''def shout(text: str) -> str:
    """Shout it.

    Args:
        text: what to shout
    """
    return text.upper()
'''

# A ceiling, not an exact pin: auth, RBAC and the agent reads together.
LIST_QUERY_CEILING = 10
DETAIL_QUERY_CEILING = 10


@pytest.fixture
def query_counter(engine):
    count = {"n": 0}

    def on_execute(*args, **kwargs):
        count["n"] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", on_execute)
    yield count
    event.remove(engine.sync_engine, "before_cursor_execute", on_execute)


async def _make_agents(db_session, workspace_id: str, count: int, *, offset: int = 0) -> list[Agent]:
    verified = LlmProfile(
        workspace_id=workspace_id, name=f"Verified {offset}", provider="openai", model_id="gpt-4o",
        encrypted_api_key=encrypt_api_key("sk"), context_window=128000,
        compaction_at_tokens=100000, input_price_per_million=1, output_price_per_million=1,
        cache_price_per_million=0, status="verified",
    )
    db_session.add(verified)
    skill = Skill(
        workspace_id=workspace_id, name=f"Skill{offset}", description="d",
        content="Use /shout when asked to shout.",
    )
    tool = Tool(workspace_id=workspace_id, name="shout" if offset == 0 else f"shout{offset}", code=TOOL_CODE)
    db_session.add_all([skill, tool])
    await db_session.flush()
    agents = []
    for index in range(count):
        # Every third agent has no model, so the list mixes both statuses.
        agent = Agent(
            workspace_id=workspace_id,
            name=f"Agent {offset + index}",
            llm_profile_id=None if index % 3 == 2 else verified.id,
            system_prompt="x",
            params={},
        )
        db_session.add(agent)
        await db_session.flush()
        db_session.add_all(
            [AgentSkill(agent_id=agent.id, skill_id=skill.id), AgentTool(agent_id=agent.id, tool_id=tool.id)]
        )
        agents.append(agent)
    await db_session.commit()
    return agents


async def _count(client, headers, url, counter) -> tuple[int, dict]:
    counter["n"] = 0
    response = await client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    return counter["n"], response.json()


@pytest.mark.asyncio
async def test_list_query_count_does_not_grow_with_agents(
    client, auth_headers, test_workspace, db_session, query_counter
):
    url = f"/api/workspaces/{test_workspace.id}/agents"
    await _make_agents(db_session, test_workspace.id, 1)
    one, _ = await _count(client, auth_headers, url, query_counter)

    await _make_agents(db_session, test_workspace.id, 11, offset=1)
    many, body = await _count(client, auth_headers, url, query_counter)

    assert body["total"] == 12
    assert many == one, f"list issued {one} queries for 1 agent but {many} for 12"
    assert many <= LIST_QUERY_CEILING


@pytest.mark.asyncio
async def test_detail_query_count_is_bounded(
    client, auth_headers, test_workspace, db_session, query_counter
):
    [agent] = await _make_agents(db_session, test_workspace.id, 1)
    queries, body = await _count(
        client, auth_headers, f"/api/workspaces/{test_workspace.id}/agents/{agent.id}", query_counter
    )
    assert body["resolved"]["tools"], "the skill's /shout tool should resolve"
    assert queries <= DETAIL_QUERY_CEILING


@pytest.mark.asyncio
async def test_list_badges_match_the_detail_view(
    client, auth_headers, test_workspace, db_session
):
    await _make_agents(db_session, test_workspace.id, 6)
    base = f"/api/workspaces/{test_workspace.id}/agents"
    listed = (await client.get(base, headers=auth_headers)).json()["agents"]

    statuses = set()
    for item in listed:
        detail = (await client.get(f"{base}/{item['id']}", headers=auth_headers)).json()
        assert item["status"] == detail["status"], item["name"]
        statuses.add(item["status"])
    assert statuses == {"ready", "needs_attention"}
