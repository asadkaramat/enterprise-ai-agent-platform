"""
Agent version management.

PUT  /agents/{agent_id}/versions          — create a new immutable version
GET  /agents/{agent_id}/versions          — list all versions
GET  /agents/{agent_id}/versions/{vid}    — get a specific version snapshot
PATCH /agents/{agent_id}/active-version   — promote (or rollback to) a version
"""
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.tenant import get_tenant_id
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.tool import Tool
from app.models.tool_binding import ToolBinding
from app.models.tool_schema_version import ToolSchemaVersion
from app.services import config_cache, config_publisher

router = APIRouter(prefix="/agents", tags=["agent-versions"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ToolBindingInput(BaseModel):
    tool_id: uuid.UUID
    tool_schema_version: int = 1
    parameter_constraints: dict[str, Any] = {}
    max_calls_per_turn: int | None = None


class VersionCreate(BaseModel):
    system_prompt: str
    model_id: str = "llama3.2"
    fallback_model_id: str | None = None
    memory_enabled: bool = False
    memory_retrieval_window_days: int = 30
    max_steps_per_turn: int = 20
    token_budget: int = 100000
    session_timeout_ms: int = 300000
    rollout_percentage: int = Field(default=100, ge=0, le=100)
    guardrail_config: dict[str, Any] = {}
    tool_bindings: list[ToolBindingInput] = []


class VersionPromote(BaseModel):
    version_id: uuid.UUID


class VersionSummary(BaseModel):
    version_id: uuid.UUID
    version_number: int
    model_id: str
    rollout_percentage: int
    created_at: str


class VersionDetail(VersionSummary):
    system_prompt: str
    fallback_model_id: str | None
    memory_enabled: bool
    memory_retrieval_window_days: int
    max_steps_per_turn: int
    token_budget: int
    session_timeout_ms: int
    guardrail_config: dict[str, Any]
    tool_bindings: list[dict[str, Any]]

    @classmethod
    def from_orm(cls, v: AgentVersion, bindings: list[ToolBinding]) -> "VersionDetail":
        return cls(
            version_id=v.id,
            version_number=v.version_number,
            model_id=v.model_id,
            rollout_percentage=v.rollout_percentage,
            created_at=v.created_at.isoformat() if isinstance(v.created_at, datetime) else str(v.created_at),
            system_prompt=v.system_prompt,
            fallback_model_id=v.fallback_model_id,
            memory_enabled=v.memory_enabled,
            memory_retrieval_window_days=v.memory_retrieval_window_days,
            max_steps_per_turn=v.max_steps_per_turn,
            token_budget=v.token_budget,
            session_timeout_ms=v.session_timeout_ms,
            guardrail_config=v.guardrail_config,
            tool_bindings=[
                {
                    "tool_id": str(b.tool_id),
                    "tool_schema_version": b.tool_schema_version,
                    "parameter_constraints": b.parameter_constraints,
                    "max_calls_per_turn": b.max_calls_per_turn,
                    "enabled": b.enabled,
                }
                for b in bindings
            ],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_agent_or_404(
    agent_id: uuid.UUID, tenant_id: uuid.UUID, db: AsyncSession
) -> Agent:
    result = await db.execute(
        select(Agent).where(and_(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return agent


async def _next_version_number(agent_id: uuid.UUID, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(AgentVersion.version_number), 0)).where(
            AgentVersion.agent_id == agent_id
        )
    )
    return result.scalar_one() + 1


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.put("/{agent_id}/versions", status_code=status.HTTP_201_CREATED)
async def create_version(
    agent_id: uuid.UUID,
    body: VersionCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> VersionDetail:
    """Create a new immutable config version (does NOT promote automatically)."""
    agent = await _get_agent_or_404(agent_id, tenant_id, db)

    # Validate tool bindings exist in this tenant
    for tb_input in body.tool_bindings:
        tool_result = await db.execute(
            select(Tool).where(and_(Tool.id == tb_input.tool_id, Tool.is_active.is_(True)))
        )
        tool = tool_result.scalar_one_or_none()
        if tool is None:
            raise HTTPException(
                status_code=400,
                detail=f"Tool '{tb_input.tool_id}' not found or inactive.",
            )
        if tool.tenant_id is not None and tool.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail=f"Tool '{tb_input.tool_id}' belongs to a different tenant.",
            )
        # Verify schema version exists
        schema_result = await db.execute(
            select(ToolSchemaVersion).where(
                and_(
                    ToolSchemaVersion.tool_id == tb_input.tool_id,
                    ToolSchemaVersion.schema_version == tb_input.tool_schema_version,
                )
            )
        )
        if schema_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=400,
                detail=f"Schema version {tb_input.tool_schema_version} not found for tool '{tb_input.tool_id}'.",
            )

    version_number = await _next_version_number(agent_id, db)
    version = AgentVersion(
        id=uuid.uuid4(),
        agent_id=agent_id,
        tenant_id=tenant_id,
        version_number=version_number,
        system_prompt=body.system_prompt,
        model_id=body.model_id,
        fallback_model_id=body.fallback_model_id,
        memory_enabled=body.memory_enabled,
        memory_retrieval_window_days=body.memory_retrieval_window_days,
        max_steps_per_turn=body.max_steps_per_turn,
        token_budget=body.token_budget,
        session_timeout_ms=body.session_timeout_ms,
        rollout_percentage=body.rollout_percentage,
        guardrail_config=body.guardrail_config,
    )
    db.add(version)
    await db.flush()

    bindings: list[ToolBinding] = []
    for tb_input in body.tool_bindings:
        binding = ToolBinding(
            id=uuid.uuid4(),
            version_id=version.id,
            tool_id=tb_input.tool_id,
            tool_schema_version=tb_input.tool_schema_version,
            tenant_id=tenant_id,
            parameter_constraints=tb_input.parameter_constraints,
            max_calls_per_turn=tb_input.max_calls_per_turn,
            enabled=True,
        )
        db.add(binding)
        bindings.append(binding)

    await db.flush()
    return VersionDetail.from_orm(version, bindings)


@router.get("/{agent_id}/versions")
async def list_versions(
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[VersionSummary]:
    """List all versions for an agent, newest first."""
    await _get_agent_or_404(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number.desc())
    )
    versions = result.scalars().all()

    return [
        VersionSummary(
            version_id=v.id,
            version_number=v.version_number,
            model_id=v.model_id,
            rollout_percentage=v.rollout_percentage,
            created_at=v.created_at.isoformat() if isinstance(v.created_at, datetime) else str(v.created_at),
        )
        for v in versions
    ]


@router.get("/{agent_id}/versions/{version_id}")
async def get_version(
    agent_id: uuid.UUID,
    version_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> VersionDetail:
    """Get the full snapshot for a specific version."""
    await _get_agent_or_404(agent_id, tenant_id, db)

    v_result = await db.execute(
        select(AgentVersion).where(
            and_(AgentVersion.id == version_id, AgentVersion.agent_id == agent_id)
        )
    )
    version = v_result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")

    b_result = await db.execute(
        select(ToolBinding).where(ToolBinding.version_id == version_id)
    )
    bindings = b_result.scalars().all()

    return VersionDetail.from_orm(version, list(bindings))


@router.patch("/{agent_id}/active-version")
async def promote_version(
    agent_id: uuid.UUID,
    body: VersionPromote,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Promote (or roll back to) a version.

    Active sessions are unaffected — they are pinned to their version at
    creation time. New sessions pick up the new version within cache TTL (~30 s).
    """
    agent = await _get_agent_or_404(agent_id, tenant_id, db)

    # Verify version belongs to this agent and tenant
    v_result = await db.execute(
        select(AgentVersion).where(
            and_(
                AgentVersion.id == body.version_id,
                AgentVersion.agent_id == agent_id,
                AgentVersion.tenant_id == tenant_id,
            )
        )
    )
    version = v_result.scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")

    previous_version_id = agent.active_version_id
    agent.active_version_id = body.version_id
    agent.updated_at = datetime.utcnow()
    await db.flush()

    # Invalidate Redis cache so new sessions pick up the new version immediately
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is not None:
        await config_cache.invalidate_active_version(
            redis_client, str(tenant_id), str(agent_id)
        )
        # Prime the new cache entry right away
        await config_cache.set_active_version(
            redis_client, str(tenant_id), str(agent_id), str(body.version_id)
        )
        # Invalidate the session-service snapshot so it picks up the new version
        await config_publisher.invalidate(redis_client, str(tenant_id), str(agent_id))

    return {
        "agent_id": str(agent_id),
        "active_version_id": str(body.version_id),
        "previous_version_id": str(previous_version_id) if previous_version_id else None,
    }
