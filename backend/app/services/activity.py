"""Aggregations behind the Activity dashboard and the Activity Logs page.

Everything is computed from `executions`: one row per run, whether it came from
the public API, the Playground or the legacy workflow canvas. Token detail lives
in `token_usage` (JSONB). The model that served a run is the snapshot stored on
the row; rows from before snapshots existed fall back to the agent's current
LLM profile.

Honest-data rules:
- cache and reasoning figures are only reported when at least one run in range
  said it measured them (`cache_reported` / `reasoning_reported`), so a provider
  that sends no detail never shows up as "0% cache hits";
- the previous period is None when it holds no runs, rather than a fake 0.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Integer, Select, and_, case, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.api_key import ApiKey
from app.models.chat import ChatMessage, ChatSession
from app.models.execution import Execution
from app.models.llm_profile import LlmProfile
from app.utils.errors import BadRequestException

SOURCES = ("api", "playground", "workflow")
BUCKETS = ("hour", "day", "week", "month")
RANKS = ("requests", "tokens", "cost")
DEFAULT_RANGE = timedelta(days=30)

MAX_MODELS = 8
MAX_AGENT_SERIES = 6


@dataclass
class ActivityFilters:
    start: datetime
    end: datetime
    tz: str = "UTC"
    api_key_id: str | None = None
    agent_id: str | None = None
    source: str | None = None
    model: str | None = None  # "provider/model_id"
    status: str | None = None


def resolve_filters(
    *,
    start: datetime | None,
    end: datetime | None,
    tz: str = "UTC",
    api_key_id: str | None = None,
    agent_id: str | None = None,
    source: str | None = None,
    model: str | None = None,
    status: str | None = None,
) -> ActivityFilters:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise BadRequestException(f"Unknown timezone: {tz}")
    if source is not None and source not in SOURCES:
        raise BadRequestException(f"source must be one of {', '.join(SOURCES)}")
    end = _aware(end) if end else datetime.now(timezone.utc)
    start = _aware(start) if start else end - DEFAULT_RANGE
    if start >= end:
        raise BadRequestException("The start of the range must be before its end.")
    return ActivityFilters(
        start=start,
        end=end,
        tz=tz,
        api_key_id=api_key_id or None,
        agent_id=agent_id or None,
        source=source or None,
        model=model or None,
        status=status or None,
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# --- SQL building blocks ---------------------------------------------------

SOURCE_EXPR = case(
    (Execution.trigger_type == "api", "api"),
    (Execution.trigger_type == "chat", "playground"),
    else_="workflow",
)
PROVIDER_EXPR = func.coalesce(Execution.provider, LlmProfile.provider)
MODEL_ID_EXPR = func.coalesce(Execution.model_id, LlmProfile.model_id)
MODEL_KEY_EXPR = PROVIDER_EXPR + literal("/") + MODEL_ID_EXPR


def _tok(name: str):
    return func.coalesce(cast(Execution.token_usage[name].astext, Integer), 0)


def _flag(name: str):
    return Execution.token_usage[name].astext == "true"


def _joined(statement: Select) -> Select:
    """Executions with their agent and that agent's current LLM profile."""
    return statement.select_from(Execution).outerjoin(
        Agent, Execution.agent_id == Agent.id
    ).outerjoin(LlmProfile, Agent.llm_profile_id == LlmProfile.id)


def _where(statement: Select, workspace_id: str, f: ActivityFilters, *, start=None, end=None) -> Select:
    statement = statement.where(
        Execution.workspace_id == workspace_id,
        Execution.created_at >= (start or f.start),
        Execution.created_at < (end or f.end),
    )
    if f.api_key_id:
        statement = statement.where(Execution.api_key_id == f.api_key_id)
    if f.agent_id:
        statement = statement.where(Execution.agent_id == f.agent_id)
    if f.source:
        statement = statement.where(SOURCE_EXPR == f.source)
    if f.model:
        statement = statement.where(MODEL_KEY_EXPR == f.model)
    if f.status:
        statement = statement.where(Execution.status == f.status)
    return statement


def _metric_columns() -> list:
    def total(expr, cond=None):
        agg = func.sum(expr)
        if cond is not None:
            agg = agg.filter(cond)
        return func.coalesce(agg, 0)

    return [
        func.count().label("requests"),
        func.count().filter(Execution.status == "completed").label("completed"),
        func.count().filter(Execution.status == "failed").label("failed"),
        func.count().filter(Execution.status == "cancelled").label("cancelled"),
        total(_tok("input_tokens")).label("input_tokens"),
        total(_tok("output_tokens")).label("output_tokens"),
        total(_tok("total_tokens")).label("total_tokens"),
        total(_tok("cache_read_tokens")).label("cache_read_tokens"),
        total(_tok("cache_creation_tokens")).label("cache_creation_tokens"),
        total(_tok("reasoning_tokens")).label("reasoning_tokens"),
        # Input tokens of only those runs that reported cache detail: the
        # denominator of the hit rate.
        total(_tok("input_tokens"), _flag("cache_reported")).label("input_tokens_cache_reported"),
        func.count().filter(_flag("cache_reported")).label("cache_reported_runs"),
        func.count().filter(_flag("reasoning_reported")).label("reasoning_reported_runs"),
        func.coalesce(func.sum(Execution.cost_usd), 0).label("cost_usd"),
        func.coalesce(func.sum(Execution.execution_time_ms), 0).label("latency_sum"),
        func.count(Execution.execution_time_ms).label("latency_n"),
        func.coalesce(func.sum(Execution.ttft_ms), 0).label("ttft_sum"),
        func.count(Execution.ttft_ms).label("ttft_n"),
    ]


def _metrics(row: Any) -> dict[str, Any]:
    """One aggregate row -> the numbers the UI shows."""
    finished = int(row.completed) + int(row.failed)
    cache_reported = int(row.cache_reported_runs) > 0
    denominator = int(row.input_tokens_cache_reported)
    return {
        "requests": int(row.requests),
        "completed": int(row.completed),
        "failed": int(row.failed),
        "cancelled": int(row.cancelled),
        "success_rate": (int(row.completed) / finished) if finished else None,
        "input_tokens": int(row.input_tokens),
        "output_tokens": int(row.output_tokens),
        "total_tokens": int(row.total_tokens),
        "cost_usd": float(row.cost_usd or 0),
        "avg_latency_ms": (float(row.latency_sum) / int(row.latency_n)) if row.latency_n else None,
        "avg_ttft_ms": (float(row.ttft_sum) / int(row.ttft_n)) if row.ttft_n else None,
        "cache": {
            "reported": cache_reported,
            "read_tokens": int(row.cache_read_tokens) if cache_reported else None,
            "creation_tokens": int(row.cache_creation_tokens) if cache_reported else None,
            # Input tokens of the runs that reported cache detail: the base the
            # cached share is measured against (uncached = this - read_tokens).
            "input_tokens": denominator if cache_reported else None,
            "hit_rate": (
                int(row.cache_read_tokens) / denominator
                if cache_reported and denominator
                else None
            ),
        },
        "reasoning": {
            "reported": int(row.reasoning_reported_runs) > 0,
            "tokens": int(row.reasoning_tokens) if int(row.reasoning_reported_runs) > 0 else None,
        },
    }


# --- time buckets ------------------------------------------------------------

def pick_bucket(start: datetime, end: datetime) -> str:
    span = end - start
    if span <= timedelta(hours=48):
        return "hour"
    if span <= timedelta(days=92):
        return "day"
    if span <= timedelta(days=400):
        return "week"
    return "month"


def _truncate(value: datetime, bucket: str) -> datetime:
    if bucket == "hour":
        return value.replace(minute=0, second=0, microsecond=0)
    value = value.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "day":
        return value
    if bucket == "week":
        return value - timedelta(days=value.weekday())
    return value.replace(day=1)


def _next(value: datetime, bucket: str) -> datetime:
    if bucket == "hour":
        return value + timedelta(hours=1)
    if bucket == "day":
        return value + timedelta(days=1)
    if bucket == "week":
        return value + timedelta(weeks=1)
    year, month = (value.year + 1, 1) if value.month == 12 else (value.year, value.month + 1)
    return value.replace(year=year, month=month)


def bucket_starts(f: ActivityFilters, bucket: str) -> list[datetime]:
    zone = ZoneInfo(f.tz)
    cursor = _truncate(f.start.astimezone(zone).replace(tzinfo=None), bucket)
    last = f.end.astimezone(zone).replace(tzinfo=None)
    starts = []
    while cursor < last:
        starts.append(cursor)
        cursor = _next(cursor, bucket)
    return starts


def _bucket_expr(f: ActivityFilters, bucket: str):
    return func.date_trunc(bucket, func.timezone(f.tz, Execution.created_at))


def _empty_metrics() -> dict[str, Any]:
    class Zero:
        def __getattr__(self, name: str):
            return 0

    return _metrics(Zero())


# --- summary ------------------------------------------------------------------

async def build_summary(
    db: AsyncSession,
    workspace_id: str,
    f: ActivityFilters,
    *,
    bucket: str | None = None,
    rank: str = "requests",
    top: int = 5,
) -> dict[str, Any]:
    if bucket is not None and bucket not in BUCKETS:
        raise BadRequestException(f"bucket must be one of {', '.join(BUCKETS)}")
    if rank not in RANKS:
        raise BadRequestException(f"rank must be one of {', '.join(RANKS)}")
    bucket = bucket or pick_bucket(f.start, f.end)
    starts = bucket_starts(f, bucket)
    keys = [value.isoformat() for value in starts]

    # Totals for the range, and the same-length range just before it.
    totals_row = (
        await db.execute(_where(_joined(select(*_metric_columns())), workspace_id, f))
    ).one()
    span = f.end - f.start
    previous_row = (
        await db.execute(
            _where(
                _joined(select(*_metric_columns())),
                workspace_id,
                f,
                start=f.start - span,
                end=f.start,
            )
        )
    ).one()
    totals = _metrics(totals_row)
    previous = _metrics(previous_row) if int(previous_row.requests) > 0 else None

    # Time series, zero-filled.
    bucket_col = _bucket_expr(f, bucket).label("bucket")
    series_rows = (
        await db.execute(
            _where(_joined(select(bucket_col, *_metric_columns())), workspace_id, f)
            .group_by(bucket_col)
        )
    ).all()
    by_bucket = {row.bucket.isoformat(): _metrics(row) for row in series_rows}
    series = [
        {"bucket": key, **by_bucket.get(key, _empty_metrics())} for key in keys
    ]

    # Per model.
    model_rows = (
        await db.execute(
            _where(
                _joined(
                    select(
                        MODEL_KEY_EXPR.label("model_key"),
                        PROVIDER_EXPR.label("provider"),
                        MODEL_ID_EXPR.label("model_id"),
                        *_metric_columns(),
                    )
                ),
                workspace_id,
                f,
            )
            .where(MODEL_ID_EXPR.is_not(None))
            .group_by(MODEL_KEY_EXPR, PROVIDER_EXPR, MODEL_ID_EXPR)
            .order_by(func.count().desc())
            .limit(MAX_MODELS)
        )
    ).all()
    model_keys = [row.model_key for row in model_rows]
    model_series_rows = []
    if model_keys:
        model_series_rows = (
            await db.execute(
                _where(
                    _joined(
                        select(
                            bucket_col,
                            MODEL_KEY_EXPR.label("model_key"),
                            *_metric_columns(),
                        )
                    ),
                    workspace_id,
                    f,
                )
                .where(MODEL_KEY_EXPR.in_(model_keys))
                .group_by(bucket_col, MODEL_KEY_EXPR)
            )
        ).all()
    model_buckets: dict[str, dict[str, dict]] = {}
    for row in model_series_rows:
        model_buckets.setdefault(row.model_key, {})[row.bucket.isoformat()] = _metrics(row)
    by_model = [
        {
            "key": row.model_key,
            "provider": row.provider,
            "model_id": row.model_id,
            "totals": _metrics(row),
            "series": [
                {"bucket": key, **model_buckets.get(row.model_key, {}).get(key, _empty_metrics())}
                for key in keys
            ],
        }
        for row in model_rows
    ]

    # Per agent: ranking table and a stacked series.
    rank_order = {
        "requests": func.count().desc(),
        "tokens": func.coalesce(func.sum(_tok("total_tokens")), 0).desc(),
        "cost": func.coalesce(func.sum(Execution.cost_usd), 0).desc(),
    }[rank]
    agent_rows = (
        await db.execute(
            _where(
                _joined(
                    select(
                        Agent.id.label("agent_id"),
                        Agent.name.label("agent_name"),
                        LlmProfile.provider.label("current_provider"),
                        LlmProfile.model_id.label("current_model_id"),
                        *_metric_columns(),
                    )
                ),
                workspace_id,
                f,
            )
            .where(Execution.agent_id.is_not(None))
            .group_by(Agent.id, Agent.name, LlmProfile.provider, LlmProfile.model_id)
            .order_by(rank_order, Agent.name)
            .limit(max(1, min(top, 20)))
        )
    ).all()
    top_agents = [
        {
            "agent_id": row.agent_id,
            "name": row.agent_name,
            "model": (
                f"{row.current_provider}/{row.current_model_id}"
                if row.current_model_id
                else None
            ),
            **_metrics(row),
        }
        for row in agent_rows
    ]

    series_agent_ids = [row.agent_id for row in agent_rows][:MAX_AGENT_SERIES]
    agent_series_rows = []
    if series_agent_ids:
        agent_series_rows = (
            await db.execute(
                _where(
                    _joined(select(bucket_col, Execution.agent_id, *_metric_columns())),
                    workspace_id,
                    f,
                )
                .where(Execution.agent_id.in_(series_agent_ids))
                .group_by(bucket_col, Execution.agent_id)
            )
        ).all()
    agent_buckets: dict[str, dict[str, dict]] = {}
    for row in agent_series_rows:
        agent_buckets.setdefault(row.agent_id, {})[row.bucket.isoformat()] = _metrics(row)
    names = {row.agent_id: row.agent_name for row in agent_rows}
    agent_series = [
        {
            "agent_id": agent_id,
            "name": names[agent_id],
            "series": [
                {"bucket": key, **agent_buckets.get(agent_id, {}).get(key, _empty_metrics())}
                for key in keys
            ],
        }
        for agent_id in series_agent_ids
    ]

    # Top API keys.
    key_rows = (
        await db.execute(
            _where(
                _joined(
                    select(
                        ApiKey.id.label("key_id"),
                        ApiKey.name.label("key_name"),
                        ApiKey.prefix.label("key_prefix"),
                        *_metric_columns(),
                    ).join(ApiKey, Execution.api_key_id == ApiKey.id)
                ),
                workspace_id,
                f,
            )
            .group_by(ApiKey.id, ApiKey.name, ApiKey.prefix)
            .order_by(rank_order, ApiKey.name)
            .limit(5)
        )
    ).all()
    top_keys = [
        {
            "api_key_id": row.key_id,
            "name": row.key_name,
            "prefix": row.key_prefix,
            **_metrics(row),
        }
        for row in key_rows
    ]

    # Has this workspace ever run anything? Drives the first-run empty state,
    # independent of the selected range and filters.
    ever = (
        await db.execute(
            select(func.count()).select_from(Execution).where(Execution.workspace_id == workspace_id).limit(1)
        )
    ).scalar_one()
    agent_count = (
        await db.execute(select(func.count()).select_from(Agent).where(Agent.workspace_id == workspace_id))
    ).scalar_one()

    return {
        "range": {
            "from": f.start.isoformat(),
            "to": f.end.isoformat(),
            "tz": f.tz,
            "bucket": bucket,
        },
        "workspace_has_activity": bool(ever),
        "agent_count": int(agent_count),
        "totals": totals,
        "previous": previous,
        "series": series,
        "by_model": by_model,
        "top_agents": top_agents,
        "agent_series": agent_series,
        "top_keys": top_keys,
    }


# --- logs -----------------------------------------------------------------------

def _log_columns() -> list:
    return [
        Execution.id,
        Execution.created_at,
        Execution.status,
        Execution.trigger_type,
        SOURCE_EXPR.label("source"),
        Execution.agent_id,
        Agent.name.label("agent_name"),
        Execution.api_key_id,
        ApiKey.name.label("api_key_name"),
        ApiKey.prefix.label("api_key_prefix"),
        PROVIDER_EXPR.label("provider"),
        MODEL_ID_EXPR.label("model_id"),
        (Execution.provider.is_(None) & MODEL_ID_EXPR.is_not(None)).label("model_is_current"),
        Execution.token_usage,
        Execution.cost_usd,
        Execution.execution_time_ms,
        Execution.ttft_ms,
        Execution.error_message,
    ]


def _log_row(row: Any) -> dict[str, Any]:
    usage = row.token_usage or {}
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat(),
        "status": row.status,
        "source": row.source,
        "agent_id": row.agent_id,
        "agent_name": row.agent_name,
        "api_key_id": row.api_key_id,
        "api_key_name": row.api_key_name,
        "api_key_prefix": row.api_key_prefix,
        "provider": row.provider,
        "model_id": row.model_id,
        # True when the model shown is the agent's current one because the run
        # predates model snapshots.
        "model_is_current": bool(row.model_is_current),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cached_tokens": usage.get("cache_read_tokens") if usage.get("cache_reported") else None,
        "reasoning_tokens": usage.get("reasoning_tokens") if usage.get("reasoning_reported") else None,
        "cost_usd": float(row.cost_usd) if row.cost_usd is not None else None,
        "latency_ms": row.execution_time_ms,
        "ttft_ms": row.ttft_ms,
        "error": row.error_message,
    }


def _logs_base(statement: Select) -> Select:
    return (
        statement.select_from(Execution)
        .outerjoin(Agent, Execution.agent_id == Agent.id)
        .outerjoin(LlmProfile, Agent.llm_profile_id == LlmProfile.id)
        .outerjoin(ApiKey, Execution.api_key_id == ApiKey.id)
    )


async def list_logs(
    db: AsyncSession,
    workspace_id: str,
    f: ActivityFilters,
    *,
    page: int,
    limit: int,
) -> dict[str, Any]:
    total = (
        await db.execute(_where(_logs_base(select(func.count())), workspace_id, f))
    ).scalar_one()
    rows = (
        await db.execute(
            _where(_logs_base(select(*_log_columns())), workspace_id, f)
            .order_by(Execution.created_at.desc(), Execution.id)
            .offset((page - 1) * limit)
            .limit(limit)
        )
    ).all()
    return {"total": int(total), "page": page, "limit": limit, "rows": [_log_row(row) for row in rows]}


async def get_log(db: AsyncSession, workspace_id: str, execution_id: str) -> dict[str, Any] | None:
    row = (
        await db.execute(
            _logs_base(select(*_log_columns())).where(
                Execution.id == execution_id, Execution.workspace_id == workspace_id
            )
        )
    ).one_or_none()
    if row is None:
        return None
    detail = _log_row(row)

    execution = await db.get(Execution, execution_id)
    messages = (
        (
            await db.execute(
                select(ChatMessage)
                .where(ChatMessage.execution_id == execution_id)
                .order_by(ChatMessage.seq)
            )
        )
        .scalars()
        .all()
    )
    user = next((m for m in messages if m.role == "user"), None)
    assistant = next((m for m in messages if m.role == "assistant"), None)
    detail["conversation_id"] = (user or assistant).session_id if (user or assistant) else None
    detail["input"] = user.content if user else (execution.input_data if execution else None)
    detail["output"] = assistant.content if assistant else (execution.output_data if execution else None)
    detail["reasoning"] = assistant.reasoning if assistant else None
    detail["activity"] = assistant.activity if assistant else None
    detail["usage"] = execution.token_usage if execution else None
    detail["trace"] = execution.execution_trace if execution else None
    return detail


# --- sessions ---------------------------------------------------------------------

async def list_sessions(
    db: AsyncSession,
    workspace_id: str,
    f: ActivityFilters,
    *,
    page: int,
    limit: int,
) -> dict[str, Any]:
    def base(statement: Select) -> Select:
        return (
            statement.select_from(ChatSession)
            .join(ChatMessage, and_(ChatMessage.session_id == ChatSession.id, ChatMessage.role == "assistant"))
            .join(Execution, Execution.id == ChatMessage.execution_id)
            .outerjoin(Agent, Agent.id == ChatSession.agent_id)
            .outerjoin(LlmProfile, Agent.llm_profile_id == LlmProfile.id)
            .outerjoin(ApiKey, ApiKey.id == ChatSession.api_key_id)
        )

    group = (ChatSession.id, ChatSession.title, ChatSession.agent_id, Agent.name,
             ChatSession.api_key_id, ApiKey.name, ApiKey.prefix)
    filtered = _where(base(select(ChatSession.id)), workspace_id, f).group_by(ChatSession.id)
    total = (
        await db.execute(select(func.count()).select_from(filtered.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            _where(
                base(
                    select(
                        ChatSession.id,
                        ChatSession.title,
                        ChatSession.agent_id,
                        Agent.name.label("agent_name"),
                        ChatSession.api_key_id,
                        ApiKey.name.label("api_key_name"),
                        ApiKey.prefix.label("api_key_prefix"),
                        func.min(Execution.created_at).label("started_at"),
                        func.max(Execution.created_at).label("last_activity_at"),
                        func.count(func.distinct(Execution.id)).label("requests"),
                        func.coalesce(func.sum(Execution.cost_usd), 0).label("cost_usd"),
                        func.coalesce(func.sum(_tok("total_tokens")), 0).label("total_tokens"),
                        func.max(MODEL_KEY_EXPR).label("model"),
                    )
                ),
                workspace_id,
                f,
            )
            .group_by(*group)
            .order_by(func.max(Execution.created_at).desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
    ).all()
    return {
        "total": int(total),
        "page": page,
        "limit": limit,
        "rows": [
            {
                "id": row.id,
                "title": row.title,
                "agent_id": row.agent_id,
                "agent_name": row.agent_name,
                "api_key_id": row.api_key_id,
                "api_key_name": row.api_key_name,
                "api_key_prefix": row.api_key_prefix,
                "source": "api" if row.api_key_id else "playground",
                "started_at": row.started_at.isoformat(),
                "last_activity_at": row.last_activity_at.isoformat(),
                "requests": int(row.requests),
                "total_tokens": int(row.total_tokens),
                "cost_usd": float(row.cost_usd or 0),
                "model": row.model,
            }
            for row in rows
        ],
    }
