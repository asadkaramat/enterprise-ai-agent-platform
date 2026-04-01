import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.tenant import get_tenant_id
from app.models.audit import AuditEvent
from app.services import metering

router = APIRouter(prefix="/audit", tags=["audit"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DT_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)


def _parse_datetime(value: str, param_name: str) -> datetime:
    """
    Try several ISO-8601 formats.
    Raises HTTP 400 with a descriptive message on failure.
    """
    for fmt in _DT_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            # Make timezone-aware (UTC) if naive
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    raise HTTPException(
        status_code=400,
        detail=(
            f"Invalid datetime format for '{param_name}': {value!r}. "
            "Expected ISO-8601, e.g. '2024-01-15T00:00:00Z'."
        ),
    )


def _serialize_event(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "tenant_id": str(event.tenant_id),
        "session_id": str(event.session_id) if event.session_id else None,
        "agent_id": str(event.agent_id) if event.agent_id else None,
        "event_type": event.event_type,
        "event_data": event.event_data,
        "created_at": event.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Event listing
# ---------------------------------------------------------------------------

@router.get("/events")
async def list_events(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    event_type: str | None = Query(default=None),
    session_id: str | None = Query(default=None),
    from_ts: str | None = Query(default=None),
    to_ts: str | None = Query(default=None),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    List audit events for the authenticated tenant.
    All filters are optional; default time window is the last 7 days.
    """
    now = datetime.now(tz=timezone.utc)
    parsed_from = _parse_datetime(from_ts, "from_ts") if from_ts else now - timedelta(days=7)
    parsed_to = _parse_datetime(to_ts, "to_ts") if to_ts else now

    filters = [
        AuditEvent.tenant_id == tenant_id,
        AuditEvent.created_at >= parsed_from,
        AuditEvent.created_at <= parsed_to,
    ]

    if event_type:
        filters.append(AuditEvent.event_type == event_type)

    if session_id:
        try:
            sid = uuid.UUID(session_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid session_id UUID: {session_id!r}")
        filters.append(AuditEvent.session_id == sid)

    # Total count (no pagination)
    count_result = await db.execute(select(func.count()).where(*filters))
    total: int = count_result.scalar() or 0

    # Paginated rows, newest first
    rows_result = await db.execute(
        select(AuditEvent)
        .where(*filters)
        .order_by(AuditEvent.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    events = rows_result.scalars().all()

    return {
        "events": [_serialize_event(e) for e in events],
        "total": total,
    }


# ---------------------------------------------------------------------------
# Single event
# ---------------------------------------------------------------------------

@router.get("/events/{event_id}")
async def get_event(
    event_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single audit event. Returns 404 if not found or owned by a different tenant."""
    result = await db.execute(
        select(AuditEvent).where(
            AuditEvent.id == event_id,
            AuditEvent.tenant_id == tenant_id,
        )
    )
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=404, detail="Audit event not found")
    return _serialize_event(event)


# ---------------------------------------------------------------------------
# Session timeline
# ---------------------------------------------------------------------------

@router.get("/sessions/{session_id}/timeline")
async def get_session_timeline(
    session_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Return all events for a session in chronological order.
    Verifies the session belongs to the requesting tenant.
    """
    result = await db.execute(
        select(AuditEvent)
        .where(AuditEvent.session_id == session_id)
        .order_by(AuditEvent.created_at.asc())
    )
    events = result.scalars().all()

    if not events:
        raise HTTPException(status_code=404, detail="Session not found")

    # Tenant ownership check: every event must belong to the requesting tenant
    if events[0].tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "session_id": str(session_id),
        "event_count": len(events),
        "events": [_serialize_event(e) for e in events],
    }


# ---------------------------------------------------------------------------
# Usage / metering endpoints
# ---------------------------------------------------------------------------

def _default_usage_window(hours: int = 24) -> tuple[datetime, datetime]:
    now = datetime.now(tz=timezone.utc)
    return now - timedelta(hours=hours), now


@router.get("/usage/summary")
async def usage_summary(
    from_ts: str | None = Query(default=None),
    to_ts: str | None = Query(default=None),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate usage metrics for the tenant.
    Default window: last 24 hours.
    """
    default_from, default_to = _default_usage_window(24)
    parsed_from = _parse_datetime(from_ts, "from_ts") if from_ts else default_from
    parsed_to = _parse_datetime(to_ts, "to_ts") if to_ts else default_to

    summary = await metering.get_usage_summary(db, tenant_id, parsed_from, parsed_to)
    return {
        "tenant_id": str(tenant_id),
        "from_ts": parsed_from.isoformat(),
        "to_ts": parsed_to.isoformat(),
        **summary,
    }


@router.get("/usage/by-agent")
async def usage_by_agent(
    from_ts: str | None = Query(default=None),
    to_ts: str | None = Query(default=None),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Per-agent session count, token consumption, and estimated cost.
    Default window: last 24 hours.
    """
    default_from, default_to = _default_usage_window(24)
    parsed_from = _parse_datetime(from_ts, "from_ts") if from_ts else default_from
    parsed_to = _parse_datetime(to_ts, "to_ts") if to_ts else default_to

    data = await metering.get_usage_by_agent(db, tenant_id, parsed_from, parsed_to)
    return {
        "tenant_id": str(tenant_id),
        "from_ts": parsed_from.isoformat(),
        "to_ts": parsed_to.isoformat(),
        "agents": data,
    }


@router.get("/usage/tool-adoption")
async def usage_tool_adoption(
    from_ts: str | None = Query(default=None),
    to_ts: str | None = Query(default=None),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Ranked tool usage (by call count) within the time window.
    Default window: last 24 hours.
    """
    default_from, default_to = _default_usage_window(24)
    parsed_from = _parse_datetime(from_ts, "from_ts") if from_ts else default_from
    parsed_to = _parse_datetime(to_ts, "to_ts") if to_ts else default_to

    data = await metering.get_tool_adoption(db, tenant_id, parsed_from, parsed_to)
    return {
        "tenant_id": str(tenant_id),
        "from_ts": parsed_from.isoformat(),
        "to_ts": parsed_to.isoformat(),
        "tools": data,
    }
