"""Activity dashboard + Activity Logs endpoints."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.agent import Agent
from app.models.chat import ChatMessage, ChatSession
from app.models.execution import Execution
from app.models.llm_profile import LlmProfile
from app.services.api_keys import create_key
from unit_tests.test_playground_chat import make_profile

BASE = "/api/workspaces/{ws}/activity"
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def params(**extra) -> dict:
    base = {"from": iso(NOW - timedelta(days=7)), "to": iso(NOW)}
    base.update(extra)
    return base


async def _agent(db_session, workspace_id, name="Alpha", provider="openai", model="gpt-4o-mini"):
    profile = make_profile(workspace_id)
    profile.name = f"profile-{name}"
    profile.provider = provider
    profile.model_id = model
    db_session.add(profile)
    await db_session.flush()
    agent = Agent(
        workspace_id=workspace_id,
        name=name,
        llm_profile_id=profile.id,
        system_prompt="x",
        params={},
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


def _run(
    workspace_id,
    agent,
    *,
    at,
    status="completed",
    trigger="api",
    key=None,
    inp=100,
    out=20,
    cost="0.01",
    latency=1000,
    ttft=200,
    provider="openai",
    model="gpt-4o-mini",
    cache=None,
    reasoning=None,
):
    usage = {
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": inp + out,
        "cache_read_tokens": cache or 0,
        "cache_creation_tokens": 0,
        "reasoning_tokens": reasoning or 0,
        "cache_reported": cache is not None,
        "reasoning_reported": reasoning is not None,
    }
    return Execution(
        workspace_id=workspace_id,
        agent_id=agent.id if agent else None,
        api_key_id=key.id if key else None,
        status=status,
        trigger_type=trigger,
        token_usage=usage,
        cost_usd=Decimal(cost),
        execution_time_ms=latency,
        ttft_ms=ttft,
        provider=provider,
        model_id=model,
        created_at=at,
    )


class TestSummary:
    @pytest.mark.asyncio
    async def test_totals_for_the_range(
        self, client, auth_headers, test_workspace, db_session
    ):
        agent = await _agent(db_session, test_workspace.id)
        day = NOW - timedelta(days=1)
        db_session.add_all(
            [
                _run(test_workspace.id, agent, at=day, inp=100, out=20, cost="0.01"),
                _run(test_workspace.id, agent, at=day, inp=300, out=40, cost="0.03", latency=3000),
                _run(test_workspace.id, agent, at=day, status="failed", inp=0, out=0, cost="0", latency=500),
            ]
        )
        await db_session.commit()

        response = await client.get(
            BASE.format(ws=test_workspace.id) + "/summary", params=params(), headers=auth_headers
        )
        assert response.status_code == 200, response.text
        totals = response.json()["totals"]
        assert totals["requests"] == 3
        assert totals["completed"] == 2 and totals["failed"] == 1
        assert totals["success_rate"] == pytest.approx(2 / 3)
        assert totals["input_tokens"] == 400
        assert totals["output_tokens"] == 60
        assert totals["total_tokens"] == 460
        assert totals["cost_usd"] == pytest.approx(0.04)
        assert totals["avg_latency_ms"] == pytest.approx((1000 + 3000 + 500) / 3)
        assert totals["avg_ttft_ms"] == pytest.approx(200)

    @pytest.mark.asyncio
    async def test_empty_workspace_has_no_activity_and_no_previous(
        self, client, auth_headers, test_workspace
    ):
        response = await client.get(
            BASE.format(ws=test_workspace.id) + "/summary", params=params(), headers=auth_headers
        )
        body = response.json()
        assert body["workspace_has_activity"] is False
        assert body["totals"]["requests"] == 0
        assert body["totals"]["success_rate"] is None
        assert body["previous"] is None
        assert body["top_agents"] == [] and body["by_model"] == [] and body["top_keys"] == []
        assert len(body["series"]) == 8  # partial first and last days count

    @pytest.mark.asyncio
    async def test_previous_period_is_the_range_just_before(
        self, client, auth_headers, test_workspace, db_session
    ):
        agent = await _agent(db_session, test_workspace.id)
        db_session.add_all(
            [
                _run(test_workspace.id, agent, at=NOW - timedelta(days=1)),
                _run(test_workspace.id, agent, at=NOW - timedelta(days=2)),
                _run(test_workspace.id, agent, at=NOW - timedelta(days=9)),
            ]
        )
        await db_session.commit()
        body = (
            await client.get(
                BASE.format(ws=test_workspace.id) + "/summary", params=params(), headers=auth_headers
            )
        ).json()
        assert body["totals"]["requests"] == 2
        assert body["previous"]["requests"] == 1

    @pytest.mark.asyncio
    async def test_series_is_zero_filled_and_bucketed(
        self, client, auth_headers, test_workspace, db_session
    ):
        agent = await _agent(db_session, test_workspace.id)
        db_session.add(_run(test_workspace.id, agent, at=datetime(2026, 6, 13, 10, 0, tzinfo=timezone.utc)))
        await db_session.commit()
        body = (
            await client.get(
                BASE.format(ws=test_workspace.id) + "/summary", params=params(), headers=auth_headers
            )
        ).json()
        assert body["range"]["bucket"] == "day"
        series = {row["bucket"]: row["requests"] for row in body["series"]}
        assert series["2026-06-13T00:00:00"] == 1
        assert sum(series.values()) == 1
        assert len(series) == 8

    @pytest.mark.asyncio
    async def test_short_range_uses_hourly_buckets(
        self, client, auth_headers, test_workspace
    ):
        body = (
            await client.get(
                BASE.format(ws=test_workspace.id) + "/summary",
                params={"from": iso(NOW - timedelta(hours=6)), "to": iso(NOW)},
                headers=auth_headers,
            )
        ).json()
        assert body["range"]["bucket"] == "hour"
        assert len(body["series"]) == 6

    @pytest.mark.asyncio
    async def test_cache_is_only_reported_when_a_provider_measured_it(
        self, client, auth_headers, test_workspace, db_session
    ):
        agent = await _agent(db_session, test_workspace.id)
        at = NOW - timedelta(days=1)
        db_session.add_all(
            [
                _run(test_workspace.id, agent, at=at, inp=100, cache=None),
                _run(test_workspace.id, agent, at=at, inp=100, cache=None),
            ]
        )
        await db_session.commit()
        url = BASE.format(ws=test_workspace.id) + "/summary"
        body = (await client.get(url, params=params(), headers=auth_headers)).json()
        assert body["totals"]["cache"] == {
            "reported": False, "read_tokens": None, "creation_tokens": None,
            "input_tokens": None, "hit_rate": None,
        }
        assert body["totals"]["reasoning"]["reported"] is False

        db_session.add_all(
            [
                _run(test_workspace.id, agent, at=at, inp=200, cache=150, reasoning=30),
                _run(test_workspace.id, agent, at=at, inp=200, cache=50, reasoning=10),
            ]
        )
        await db_session.commit()
        body = (await client.get(url, params=params(), headers=auth_headers)).json()
        cache = body["totals"]["cache"]
        assert cache["reported"] is True
        assert cache["read_tokens"] == 200
        # Unreporting runs stay out of the denominator: 200 / (200 + 200).
        assert cache["hit_rate"] == pytest.approx(0.5)
        assert body["totals"]["reasoning"] == {"reported": True, "tokens": 40}

    @pytest.mark.asyncio
    async def test_filters_by_key_agent_source_and_model(
        self, client, auth_headers, test_workspace, test_user, db_session
    ):
        alpha = await _agent(db_session, test_workspace.id, "Alpha")
        beta = await _agent(db_session, test_workspace.id, "Beta", "anthropic", "claude-x")
        key, _ = await create_key(
            db_session, workspace_id=test_workspace.id, user_id=test_user.id, name="K1"
        )
        at = NOW - timedelta(days=1)
        db_session.add_all(
            [
                _run(test_workspace.id, alpha, at=at, key=key),
                _run(test_workspace.id, alpha, at=at, trigger="chat"),
                _run(test_workspace.id, beta, at=at, key=key, provider="anthropic", model="claude-x"),
            ]
        )
        await db_session.commit()
        url = BASE.format(ws=test_workspace.id) + "/summary"

        async def requests(**extra):
            body = (await client.get(url, params=params(**extra), headers=auth_headers)).json()
            return body["totals"]["requests"]

        assert await requests() == 3
        assert await requests(api_key_id=key.id) == 2
        assert await requests(agent_id=alpha.id) == 2
        assert await requests(source="api") == 2
        assert await requests(source="playground") == 1
        assert await requests(model="anthropic/claude-x") == 1
        assert await requests(api_key_id=key.id, agent_id=alpha.id) == 1

    @pytest.mark.asyncio
    async def test_model_uses_the_snapshot_not_the_current_profile(
        self, client, auth_headers, test_workspace, db_session
    ):
        agent = await _agent(db_session, test_workspace.id, "Alpha", "openai", "gpt-new")
        at = NOW - timedelta(days=1)
        db_session.add_all(
            [
                _run(test_workspace.id, agent, at=at, provider="openai", model="gpt-old"),
                # A run from before snapshots existed: falls back to the profile.
                Execution(
                    workspace_id=test_workspace.id, agent_id=agent.id, status="completed",
                    trigger_type="api", created_at=at,
                ),
            ]
        )
        await db_session.commit()
        body = (
            await client.get(
                BASE.format(ws=test_workspace.id) + "/summary", params=params(), headers=auth_headers
            )
        ).json()
        keys = {row["key"]: row["totals"]["requests"] for row in body["by_model"]}
        assert keys == {"openai/gpt-old": 1, "openai/gpt-new": 1}

    @pytest.mark.asyncio
    async def test_top_agents_rank_by_requests_tokens_or_cost(
        self, client, auth_headers, test_workspace, db_session
    ):
        busy = await _agent(db_session, test_workspace.id, "Busy")
        heavy = await _agent(db_session, test_workspace.id, "Heavy")
        at = NOW - timedelta(days=1)
        db_session.add_all(
            [_run(test_workspace.id, busy, at=at, inp=10, out=1, cost="0.001") for _ in range(3)]
            + [_run(test_workspace.id, heavy, at=at, inp=5000, out=500, cost="0.5")]
        )
        await db_session.commit()
        url = BASE.format(ws=test_workspace.id) + "/summary"

        async def order(rank):
            body = (await client.get(url, params=params(rank=rank), headers=auth_headers)).json()
            return [a["name"] for a in body["top_agents"]]

        assert await order("requests") == ["Busy", "Heavy"]
        assert await order("tokens") == ["Heavy", "Busy"]
        assert await order("cost") == ["Heavy", "Busy"]
        body = (await client.get(url, params=params(), headers=auth_headers)).json()
        assert body["top_agents"][0]["model"] == "openai/gpt-4o-mini"
        assert {s["name"] for s in body["agent_series"]} == {"Busy", "Heavy"}

    @pytest.mark.asyncio
    async def test_top_keys_lists_only_keyed_runs(
        self, client, auth_headers, test_workspace, test_user, db_session
    ):
        agent = await _agent(db_session, test_workspace.id)
        key, _ = await create_key(
            db_session, workspace_id=test_workspace.id, user_id=test_user.id, name="Prod"
        )
        at = NOW - timedelta(days=1)
        db_session.add_all(
            [_run(test_workspace.id, agent, at=at, key=key), _run(test_workspace.id, agent, at=at, trigger="chat")]
        )
        await db_session.commit()
        body = (
            await client.get(
                BASE.format(ws=test_workspace.id) + "/summary", params=params(), headers=auth_headers
            )
        ).json()
        assert [k["name"] for k in body["top_keys"]] == ["Prod"]
        assert body["top_keys"][0]["requests"] == 1
        assert body["workspace_has_activity"] is True

    @pytest.mark.asyncio
    async def test_bad_inputs_are_400(self, client, auth_headers, test_workspace):
        url = BASE.format(ws=test_workspace.id) + "/summary"
        assert (await client.get(url, params=params(tz="Not/AZone"), headers=auth_headers)).status_code == 400
        assert (await client.get(url, params=params(source="bogus"), headers=auth_headers)).status_code == 400
        assert (await client.get(url, params=params(rank="bogus"), headers=auth_headers)).status_code == 400
        swapped = {"from": iso(NOW), "to": iso(NOW - timedelta(days=1))}
        assert (await client.get(url, params=swapped, headers=auth_headers)).status_code == 400

    @pytest.mark.asyncio
    async def test_other_workspaces_data_never_leaks(
        self, client, auth_headers, test_workspace, test_user, db_session
    ):
        from app.models.workspace import Workspace

        other = Workspace(name="Other", owner_id=test_user.id)
        db_session.add(other)
        await db_session.flush()
        agent = await _agent(db_session, other.id, "Foreign")
        db_session.add(_run(other.id, agent, at=NOW - timedelta(days=1)))
        await db_session.commit()
        body = (
            await client.get(
                BASE.format(ws=test_workspace.id) + "/summary", params=params(), headers=auth_headers
            )
        ).json()
        assert body["totals"]["requests"] == 0
        assert body["workspace_has_activity"] is False


class TestAccess:
    @pytest.mark.asyncio
    async def test_non_members_are_refused(
        self, client, auth_headers, admin_user, db_session
    ):
        # A workspace the signed-in user does not belong to.
        from app.models.workspace import Workspace

        foreign = Workspace(name="Foreign", owner_id=admin_user.id)
        db_session.add(foreign)
        await db_session.commit()
        response = await client.get(
            BASE.format(ws=foreign.id) + "/summary", params=params(), headers=auth_headers
        )
        assert response.status_code in (403, 404)

    @pytest.mark.asyncio
    async def test_unauthenticated_is_401(self, client, test_workspace):
        response = await client.get(
            BASE.format(ws=test_workspace.id) + "/summary", params=params()
        )
        assert response.status_code in (401, 403)

    @pytest.mark.asyncio
    async def test_a_viewer_can_read(self, client, test_workspace, viewer_headers):
        response = await client.get(
            BASE.format(ws=test_workspace.id) + "/summary", params=params(), headers=viewer_headers
        )
        assert response.status_code == 200


class TestLogs:
    @pytest.mark.asyncio
    async def test_rows_carry_agent_key_model_tokens_and_timing(
        self, client, auth_headers, test_workspace, test_user, db_session
    ):
        agent = await _agent(db_session, test_workspace.id)
        key, _ = await create_key(
            db_session, workspace_id=test_workspace.id, user_id=test_user.id, name="Prod"
        )
        db_session.add(
            _run(
                test_workspace.id, agent, at=NOW - timedelta(hours=3), key=key,
                inp=120, out=30, cost="0.02", latency=1500, ttft=250, cache=80, reasoning=5,
            )
        )
        await db_session.commit()
        body = (
            await client.get(
                BASE.format(ws=test_workspace.id) + "/logs", params=params(), headers=auth_headers
            )
        ).json()
        assert body["total"] == 1
        row = body["rows"][0]
        assert row["agent_name"] == "Alpha"
        assert row["api_key_name"] == "Prod" and row["api_key_prefix"].startswith("mk_")
        assert row["source"] == "api" and row["status"] == "completed"
        assert row["provider"] == "openai" and row["model_id"] == "gpt-4o-mini"
        assert row["model_is_current"] is False
        assert (row["input_tokens"], row["output_tokens"]) == (120, 30)
        assert row["cached_tokens"] == 80 and row["reasoning_tokens"] == 5
        assert row["cost_usd"] == pytest.approx(0.02)
        assert row["latency_ms"] == 1500 and row["ttft_ms"] == 250

    @pytest.mark.asyncio
    async def test_cached_tokens_are_null_when_not_reported(
        self, client, auth_headers, test_workspace, db_session
    ):
        agent = await _agent(db_session, test_workspace.id)
        db_session.add(_run(test_workspace.id, agent, at=NOW - timedelta(hours=3), cache=None))
        await db_session.commit()
        row = (
            await client.get(
                BASE.format(ws=test_workspace.id) + "/logs", params=params(), headers=auth_headers
            )
        ).json()["rows"][0]
        assert row["cached_tokens"] is None and row["reasoning_tokens"] is None

    @pytest.mark.asyncio
    async def test_pagination_newest_first_and_filters(
        self, client, auth_headers, test_workspace, test_user, db_session
    ):
        agent = await _agent(db_session, test_workspace.id)
        key, _ = await create_key(
            db_session, workspace_id=test_workspace.id, user_id=test_user.id, name="Prod"
        )
        db_session.add_all(
            [_run(test_workspace.id, agent, at=NOW - timedelta(hours=i + 1), key=key) for i in range(5)]
            + [_run(test_workspace.id, agent, at=NOW - timedelta(hours=1), status="failed")]
        )
        await db_session.commit()
        url = BASE.format(ws=test_workspace.id) + "/logs"

        first = (await client.get(url, params=params(limit=2), headers=auth_headers)).json()
        assert first["total"] == 6 and len(first["rows"]) == 2
        stamps = [row["created_at"] for row in first["rows"]]
        assert stamps == sorted(stamps, reverse=True)
        third = (await client.get(url, params=params(limit=2, page=3), headers=auth_headers)).json()
        assert len(third["rows"]) == 2
        failed = (await client.get(url, params=params(status="failed"), headers=auth_headers)).json()
        assert failed["total"] == 1
        keyed = (await client.get(url, params=params(api_key_id=key.id), headers=auth_headers)).json()
        assert keyed["total"] == 5

    @pytest.mark.asyncio
    async def test_detail_includes_the_conversation(
        self, client, auth_headers, test_workspace, db_session
    ):
        agent = await _agent(db_session, test_workspace.id)
        execution = _run(test_workspace.id, agent, at=NOW - timedelta(hours=2), trigger="chat")
        db_session.add(execution)
        await db_session.flush()
        chat = ChatSession(workspace_id=test_workspace.id, agent_id=agent.id)
        db_session.add(chat)
        await db_session.flush()
        db_session.add_all(
            [
                ChatMessage(session_id=chat.id, role="user", seq=1, content="What is 2+2?", execution_id=execution.id),
                ChatMessage(session_id=chat.id, role="assistant", seq=2, content="Four.", status="completed", execution_id=execution.id),
            ]
        )
        await db_session.commit()
        detail = (
            await client.get(
                BASE.format(ws=test_workspace.id) + f"/logs/{execution.id}", headers=auth_headers
            )
        ).json()
        assert detail["input"] == "What is 2+2?" and detail["output"] == "Four."
        assert detail["conversation_id"] == chat.id
        assert detail["agent_name"] == "Alpha"

    @pytest.mark.asyncio
    async def test_detail_of_another_workspace_is_404(
        self, client, auth_headers, test_workspace
    ):
        response = await client.get(
            BASE.format(ws=test_workspace.id) + "/logs/does-not-exist", headers=auth_headers
        )
        assert response.status_code == 404


class TestSessions:
    @pytest.mark.asyncio
    async def test_sessions_group_their_requests(
        self, client, auth_headers, test_workspace, db_session
    ):
        agent = await _agent(db_session, test_workspace.id)
        chat = ChatSession(workspace_id=test_workspace.id, agent_id=agent.id, title="Hello")
        db_session.add(chat)
        await db_session.flush()
        for i in range(2):
            execution = _run(test_workspace.id, agent, at=NOW - timedelta(hours=3 - i), trigger="chat", cost="0.02")
            db_session.add(execution)
            await db_session.flush()
            db_session.add_all(
                [
                    ChatMessage(session_id=chat.id, role="user", seq=i * 2 + 1, content="q", execution_id=execution.id),
                    ChatMessage(session_id=chat.id, role="assistant", seq=i * 2 + 2, content="a", execution_id=execution.id),
                ]
            )
        await db_session.commit()
        body = (
            await client.get(
                BASE.format(ws=test_workspace.id) + "/sessions", params=params(), headers=auth_headers
            )
        ).json()
        assert body["total"] == 1
        row = body["rows"][0]
        assert row["title"] == "Hello" and row["requests"] == 2
        assert row["cost_usd"] == pytest.approx(0.04)
        assert row["agent_name"] == "Alpha"
