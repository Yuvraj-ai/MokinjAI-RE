"""Token and latency telemetry captured per run.

LangChain standardises `usage_metadata` (cache_read / cache_creation / reasoning
details). It does not report time to first token, so the runtime measures that.
"""

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from sqlalchemy import select

from app.models.chat import ChatMessage
from app.models.execution import Execution
from app.services.agent_runtime import _add_usage, new_usage, stream_turn
from unit_tests.test_playground_chat import (
    FakeGraphV2,
    _install,
    _setup,
    encryption_key,  # noqa: F401  (fixture)
)


class TestAddUsage:
    def test_new_usage_starts_empty_and_unreported(self):
        usage = new_usage()
        assert usage["input_tokens"] == 0
        assert usage["reasoning_tokens"] == 0
        assert usage["cache_creation_tokens"] == 0
        assert usage["cache_reported"] is False
        assert usage["reasoning_reported"] is False

    def test_reads_cache_and_reasoning_details(self):
        usage = new_usage()
        _add_usage(
            usage,
            {
                "input_tokens": 100,
                "output_tokens": 40,
                "total_tokens": 140,
                "input_token_details": {"cache_read": 60, "cache_creation": 10},
                "output_token_details": {"reasoning": 25},
            },
        )
        assert usage["cache_read_tokens"] == 60
        assert usage["cache_creation_tokens"] == 10
        assert usage["reasoning_tokens"] == 25
        assert usage["cache_reported"] is True
        assert usage["reasoning_reported"] is True

    def test_missing_details_stay_unreported_not_zero_reported(self):
        usage = new_usage()
        _add_usage(usage, {"input_tokens": 5, "output_tokens": 1, "total_tokens": 6})
        assert usage["cache_reported"] is False
        assert usage["reasoning_reported"] is False

    def test_an_explicit_zero_counts_as_reported(self):
        usage = new_usage()
        _add_usage(
            usage,
            {
                "input_tokens": 5,
                "output_tokens": 1,
                "total_tokens": 6,
                "input_token_details": {"cache_read": 0},
                "output_token_details": {"reasoning": 0},
            },
        )
        assert usage["cache_reported"] is True
        assert usage["reasoning_reported"] is True

    def test_several_model_calls_accumulate(self):
        usage = new_usage()
        for _ in range(2):
            _add_usage(
                usage,
                {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                    "input_token_details": {"cache_read": 4},
                    "output_token_details": {"reasoning": 1},
                },
            )
        assert usage["input_tokens"] == 20
        assert usage["cache_read_tokens"] == 8
        assert usage["reasoning_tokens"] == 2


class FakeGraphReasoning:
    async def astream_events(self, payload, version):
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_checkpoint_ns": "model:1"},
            "data": {"chunk": AIMessageChunk(content="Hi")},
        }
        yield {
            "event": "on_chat_model_end",
            "metadata": {},
            "data": {
                "output": AIMessage(
                    content="Hi",
                    usage_metadata={
                        "input_tokens": 10,
                        "output_tokens": 5,
                        "total_tokens": 15,
                        "input_token_details": {"cache_read": 2, "cache_creation": 3},
                        "output_token_details": {"reasoning": 4},
                    },
                )
            },
        }
        yield {
            "event": "on_chain_end",
            "name": "LangGraph",
            "parent_ids": [],
            "metadata": {},
            "data": {"output": {"messages": [AIMessage(content="Hi")]}},
        }


class TestRunRecord:
    @pytest.mark.asyncio
    async def test_execution_records_model_snapshot_ttft_and_details(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        _agent, chat_session, execution = await _setup(db_session, test_workspace)
        _install(monkeypatch, session_factory, FakeGraphReasoning())

        _ = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]

        async with session_factory() as check:
            row = await check.get(Execution, execution.id)
            assert row.status == "completed"
            assert row.provider == "openai"
            assert row.model_id == "gpt-4o-mini"
            assert row.ttft_ms is not None and row.ttft_ms >= 0
            assert row.token_usage["reasoning_tokens"] == 4
            assert row.token_usage["cache_creation_tokens"] == 3
            assert row.token_usage["cache_reported"] is True

    @pytest.mark.asyncio
    async def test_failed_run_still_records_model_snapshot(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        _agent, chat_session, execution = await _setup(db_session, test_workspace)

        class Boom:
            async def astream_events(self, payload, version):
                raise RuntimeError("provider exploded")
                yield  # pragma: no cover

        _install(monkeypatch, session_factory, Boom())
        _ = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]
        async with session_factory() as check:
            row = await check.get(Execution, execution.id)
            assert row.status == "failed"
            assert row.provider == "openai"
            assert row.model_id == "gpt-4o-mini"
            assert row.ttft_ms is None

    @pytest.mark.asyncio
    async def test_existing_stream_still_reports_basic_usage(
        self, db_session, session_factory, test_workspace, monkeypatch, encryption_key
    ):
        _agent, chat_session, execution = await _setup(db_session, test_workspace)
        _install(monkeypatch, session_factory, FakeGraphV2())
        _ = [
            event
            async for event in stream_turn(
                test_workspace.id, chat_session.id, "hi", execution.id
            )
        ]
        async with session_factory() as check:
            message = (
                await check.execute(
                    select(ChatMessage).where(ChatMessage.role == "assistant")
                )
            ).scalars().one()
            assert message.usage["cache_reported"] is True
            assert message.usage["reasoning_reported"] is False
