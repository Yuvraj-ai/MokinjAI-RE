"""Activity dashboard and Activity Logs (read-only, viewer role).

Aggregates and per-run records over `executions`. The dashboard and the logs
page share one filter set so a link from an API key lands on either with the
key already applied.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.rbac import require_workspace_role
from app.models.workspace import WorkspaceMember
from app.services import activity
from app.utils.errors import NotFoundException

router = APIRouter()


def _filters(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    tz: str = "UTC",
    api_key_id: str | None = None,
    agent_id: str | None = None,
    source: str | None = None,
    model: str | None = None,
    status: str | None = None,
) -> activity.ActivityFilters:
    return activity.resolve_filters(
        start=from_,
        end=to,
        tz=tz,
        api_key_id=api_key_id,
        agent_id=agent_id,
        source=source,
        model=model,
        status=status,
    )


@router.get("/summary")
async def activity_summary(
    workspace_id: str,
    filters: activity.ActivityFilters = Depends(_filters),
    bucket: str | None = None,
    rank: str = "requests",
    top: int = Query(5, ge=1, le=20),
    _member: WorkspaceMember = Depends(require_workspace_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    return await activity.build_summary(
        db, workspace_id, filters, bucket=bucket, rank=rank, top=top
    )


@router.get("/logs")
async def activity_logs(
    workspace_id: str,
    filters: activity.ActivityFilters = Depends(_filters),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    _member: WorkspaceMember = Depends(require_workspace_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    return await activity.list_logs(db, workspace_id, filters, page=page, limit=limit)


@router.get("/logs/{execution_id}")
async def activity_log_detail(
    workspace_id: str,
    execution_id: str,
    _member: WorkspaceMember = Depends(require_workspace_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    detail = await activity.get_log(db, workspace_id, execution_id)
    if detail is None:
        raise NotFoundException("Log entry")
    return detail


@router.get("/sessions")
async def activity_sessions(
    workspace_id: str,
    filters: activity.ActivityFilters = Depends(_filters),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    _member: WorkspaceMember = Depends(require_workspace_role("viewer")),
    db: AsyncSession = Depends(get_db),
):
    return await activity.list_sessions(db, workspace_id, filters, page=page, limit=limit)
