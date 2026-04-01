import uuid
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit import AuditEvent


async def get_usage_summary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> dict:
    """
    Aggregate usage metrics for a tenant over a time window.
    All queries are SELECT-only — audit_events is append-only.
    """

    def _base(*extra):
        return (
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.created_at >= from_ts,
            AuditEvent.created_at <= to_ts,
            *extra,
        )

    # Total sessions started
    total_sessions: int = (
        await db.execute(
            select(func.count()).where(*_base(AuditEvent.event_type == "session_start"))
        )
    ).scalar() or 0

    # Sessions that completed
    completed_sessions: int = (
        await db.execute(
            select(func.count()).where(*_base(AuditEvent.event_type == "session_complete"))
        )
    ).scalar() or 0

    # Total tokens from completed-session records (JSONB field)
    total_tokens: int = (
        await db.execute(
            select(
                func.sum(text("(event_data->>'token_count')::integer"))
            ).where(*_base(AuditEvent.event_type == "session_complete"))
        )
    ).scalar() or 0

    # Total steps from completed-session records
    total_steps: int = (
        await db.execute(
            select(
                func.sum(text("(event_data->>'step_count')::integer"))
            ).where(*_base(AuditEvent.event_type == "session_complete"))
        )
    ).scalar() or 0

    # Tool call events
    tool_calls: int = (
        await db.execute(
            select(func.count()).where(*_base(AuditEvent.event_type == "tool_call"))
        )
    ).scalar() or 0

    # Budget-exceeded events
    budget_exceeded: int = (
        await db.execute(
            select(func.count()).where(*_base(AuditEvent.event_type == "budget_exceeded"))
        )
    ).scalar() or 0

    estimated_cost = float(total_tokens) * settings.TOKEN_COST_PER_UNIT

    return {
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "total_steps": int(total_steps),
        "total_tokens": int(total_tokens),
        "tool_calls": tool_calls,
        "budget_exceeded_count": budget_exceeded,
        "estimated_cost_usd": round(estimated_cost, 6),
    }


async def get_usage_by_agent(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> list[dict]:
    """Per-agent session count and token consumption for the time window."""
    result = await db.execute(
        select(
            AuditEvent.agent_id,
            func.count().label("session_count"),
            func.sum(text("(event_data->>'token_count')::integer")).label("total_tokens"),
        ).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.created_at >= from_ts,
            AuditEvent.created_at <= to_ts,
            AuditEvent.event_type == "session_complete",
            AuditEvent.agent_id.isnot(None),
        ).group_by(AuditEvent.agent_id)
    )
    rows = result.all()
    return [
        {
            "agent_id": str(r.agent_id),
            "session_count": r.session_count,
            "total_tokens": int(r.total_tokens or 0),
            "estimated_cost_usd": round(int(r.total_tokens or 0) * settings.TOKEN_COST_PER_UNIT, 6),
        }
        for r in rows
    ]


async def get_tool_adoption(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    from_ts: datetime,
    to_ts: datetime,
) -> list[dict]:
    """Ranked list of tools by call frequency within the time window."""
    result = await db.execute(
        select(
            text("event_data->>'tool_name' as tool_name"),
            func.count().label("call_count"),
        ).where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.created_at >= from_ts,
            AuditEvent.created_at <= to_ts,
            AuditEvent.event_type == "tool_call",
        )
        .group_by(text("event_data->>'tool_name'"))
        .order_by(func.count().desc())
    )
    rows = result.all()
    return [{"tool_name": r.tool_name, "call_count": r.call_count} for r in rows]
