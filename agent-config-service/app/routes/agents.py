import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.metrics import agents_created_total
from app.middleware.tenant import get_tenant_id
from app.services import config_publisher
from app.models.agent import Agent
from app.models.tool import AgentTool, Tool

router = APIRouter(prefix="/agents", tags=["agents"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class AgentCreate(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str
    model: str = "llama3.2"
    max_steps: int = 10
    token_budget: int = 8000
    session_timeout_seconds: int = 300
    memory_enabled: bool = True


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    model: str | None = None
    max_steps: int | None = None
    token_budget: int | None = None
    session_timeout_seconds: int | None = None
    memory_enabled: bool | None = None
    is_active: bool | None = None


class AgentResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str | None
    system_prompt: str
    model: str
    max_steps: int
    token_budget: int
    session_timeout_seconds: int
    memory_enabled: bool
    is_active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(cls, agent: Agent) -> "AgentResponse":
        return cls(
            id=agent.id,
            tenant_id=agent.tenant_id,
            name=agent.name,
            description=agent.description,
            system_prompt=agent.system_prompt,
            model=agent.model,
            max_steps=agent.max_steps,
            token_budget=agent.token_budget,
            session_timeout_seconds=agent.session_timeout_seconds,
            memory_enabled=agent.memory_enabled,
            is_active=agent.is_active,
            created_at=agent.created_at.isoformat() if isinstance(agent.created_at, datetime) else str(agent.created_at),
            updated_at=agent.updated_at.isoformat() if isinstance(agent.updated_at, datetime) else str(agent.updated_at),
        )


class AgentListResponse(BaseModel):
    items: list[AgentResponse]
    total: int


class ToolWithSchema(BaseModel):
    tool_id: uuid.UUID
    name: str
    endpoint_url: str
    http_method: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    auth_type: str
    auth_config: dict[str, Any]
    is_authorized: bool


class AgentFullResponse(BaseModel):
    agent: AgentResponse
    tools: list[ToolWithSchema]


class ToolBindingResponse(BaseModel):
    tool_id: uuid.UUID
    name: str
    description: str
    version: str
    is_authorized: bool


class AuthorizeBody(BaseModel):
    is_authorized: bool


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _get_agent_or_404(
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> Agent:
    result = await db.execute(
        select(Agent).where(
            and_(Agent.id == agent_id, Agent.tenant_id == tenant_id)
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")
    return agent


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=AgentResponse)
async def create_agent(
    body: AgentCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    agent = Agent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        model=body.model,
        max_steps=body.max_steps,
        token_budget=body.token_budget,
        session_timeout_seconds=body.session_timeout_seconds,
        memory_enabled=body.memory_enabled,
    )
    db.add(agent)
    await db.flush()
    await db.refresh(agent)
    agents_created_total.inc()
    return AgentResponse.from_orm(agent)


@router.get("", response_model=AgentListResponse)
async def list_agents(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> AgentListResponse:
    base_where = and_(Agent.tenant_id == tenant_id, Agent.is_active.is_(True))

    count_result = await db.execute(select(func.count()).select_from(Agent).where(base_where))
    total: int = count_result.scalar_one()

    result = await db.execute(
        select(Agent).where(base_where).order_by(Agent.created_at.desc()).offset(skip).limit(limit)
    )
    agents = result.scalars().all()

    return AgentListResponse(
        items=[AgentResponse.from_orm(a) for a in agents],
        total=total,
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    agent = await _get_agent_or_404(agent_id, tenant_id, db)
    return AgentResponse.from_orm(agent)


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID,
    body: AgentUpdate,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    agent = await _get_agent_or_404(agent_id, tenant_id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(agent, field, value)

    agent.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(agent)
    redis = getattr(request.app.state, "redis", None)
    await config_publisher.invalidate(redis, str(tenant_id), str(agent_id))
    return AgentResponse.from_orm(agent)


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    agent = await _get_agent_or_404(agent_id, tenant_id, db)
    agent.is_active = False
    agent.updated_at = datetime.utcnow()
    await db.flush()
    redis = getattr(request.app.state, "redis", None)
    await config_publisher.invalidate(redis, str(tenant_id), str(agent_id))


# ---------------------------------------------------------------------------
# Tool binding sub-routes
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/tools", response_model=list[ToolBindingResponse])
async def list_agent_tools(
    agent_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ToolBindingResponse]:
    # Verify agent belongs to tenant
    await _get_agent_or_404(agent_id, tenant_id, db)

    result = await db.execute(
        select(Tool, AgentTool.is_authorized)
        .join(AgentTool, AgentTool.tool_id == Tool.id)
        .where(
            and_(
                AgentTool.agent_id == agent_id,
                Tool.tenant_id == tenant_id,
            )
        )
    )
    rows = result.all()

    return [
        ToolBindingResponse(
            tool_id=tool.id,
            name=tool.name,
            description=tool.description,
            version=tool.version,
            is_authorized=is_authorized,
        )
        for tool, is_authorized in rows
    ]


@router.post("/{agent_id}/tools/{tool_id}", status_code=201)
async def bind_tool_to_agent(
    agent_id: uuid.UUID,
    tool_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Verify agent belongs to tenant
    await _get_agent_or_404(agent_id, tenant_id, db)

    # Verify tool belongs to tenant
    tool_result = await db.execute(
        select(Tool).where(and_(Tool.id == tool_id, Tool.tenant_id == tenant_id))
    )
    if tool_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found.")

    # Check if binding already exists
    existing = await db.execute(
        select(AgentTool).where(
            and_(AgentTool.agent_id == agent_id, AgentTool.tool_id == tool_id)
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Tool is already bound to this agent.")

    binding = AgentTool(agent_id=agent_id, tool_id=tool_id, is_authorized=True)
    db.add(binding)
    await db.flush()

    return {"agent_id": str(agent_id), "tool_id": str(tool_id), "is_authorized": True}


@router.delete("/{agent_id}/tools/{tool_id}", status_code=204)
async def unbind_tool_from_agent(
    agent_id: uuid.UUID,
    tool_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Verify agent belongs to tenant
    await _get_agent_or_404(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentTool).where(
            and_(AgentTool.agent_id == agent_id, AgentTool.tool_id == tool_id)
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise HTTPException(status_code=404, detail="Tool binding not found.")

    await db.delete(binding)
    await db.flush()


@router.put("/{agent_id}/tools/{tool_id}/authorize")
async def authorize_tool(
    agent_id: uuid.UUID,
    tool_id: uuid.UUID,
    body: AuthorizeBody,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Verify agent belongs to tenant
    await _get_agent_or_404(agent_id, tenant_id, db)

    result = await db.execute(
        select(AgentTool).where(
            and_(AgentTool.agent_id == agent_id, AgentTool.tool_id == tool_id)
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise HTTPException(status_code=404, detail="Tool binding not found.")

    binding.is_authorized = body.is_authorized
    await db.flush()

    return {
        "agent_id": str(agent_id),
        "tool_id": str(tool_id),
        "is_authorized": binding.is_authorized,
    }


