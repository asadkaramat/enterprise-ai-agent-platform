import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.metrics import tools_registered_total
from app.middleware.tenant import get_tenant_id
from app.models.agent import Agent
from app.models.tool import AgentTool, Tool
from app.models.tool_schema_version import ToolSchemaVersion
from app.services import config_publisher

router = APIRouter(prefix="/tools", tags=["tools"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ToolCreate(BaseModel):
    name: str
    description: str
    version: str = "1.0.0"
    endpoint_url: str
    http_method: str = "POST"
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}
    auth_type: str = "none"
    auth_config: dict[str, Any] = {}
    is_cacheable: bool = False
    cache_ttl_seconds: int = 300


class ToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    version: str | None = None
    endpoint_url: str | None = None
    http_method: str | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    auth_type: str | None = None
    auth_config: dict[str, Any] | None = None
    is_active: bool | None = None
    is_cacheable: bool | None = None
    cache_ttl_seconds: int | None = None


class ToolResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    description: str
    version: str
    endpoint_url: str
    http_method: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    auth_type: str
    auth_config: dict[str, Any]
    is_active: bool
    is_cacheable: bool
    cache_ttl_seconds: int
    created_at: str

    @classmethod
    def from_orm(cls, tool: Tool) -> "ToolResponse":
        return cls(
            id=tool.id,
            tenant_id=tool.tenant_id,
            name=tool.name,
            description=tool.description,
            version=tool.version,
            endpoint_url=tool.endpoint_url,
            http_method=tool.http_method,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            auth_type=tool.auth_type,
            auth_config=tool.auth_config,
            is_active=tool.is_active,
            is_cacheable=tool.is_cacheable,
            cache_ttl_seconds=tool.cache_ttl_seconds,
            created_at=tool.created_at.isoformat() if isinstance(tool.created_at, datetime) else str(tool.created_at),
        )


class ToolListResponse(BaseModel):
    items: list[ToolResponse]
    total: int


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _get_tool_or_404(
    tool_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> Tool:
    result = await db.execute(
        select(Tool).where(and_(Tool.id == tool_id, Tool.tenant_id == tenant_id))
    )
    tool = result.scalar_one_or_none()
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool '{tool_id}' not found.")
    return tool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("", status_code=201, response_model=ToolResponse)
async def create_tool(
    body: ToolCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ToolResponse:
    tool = Tool(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=body.name,
        description=body.description,
        version=body.version,
        endpoint_url=body.endpoint_url,
        http_method=body.http_method,
        input_schema=body.input_schema,
        output_schema=body.output_schema,
        auth_type=body.auth_type,
        auth_config=body.auth_config,
        is_cacheable=body.is_cacheable,
        cache_ttl_seconds=body.cache_ttl_seconds,
    )
    db.add(tool)
    await db.flush()
    await db.refresh(tool)
    tools_registered_total.inc()
    return ToolResponse.from_orm(tool)


@router.get("", response_model=ToolListResponse)
async def list_tools(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ToolListResponse:
    base_where = and_(Tool.tenant_id == tenant_id, Tool.is_active.is_(True))

    count_result = await db.execute(select(func.count()).select_from(Tool).where(base_where))
    total: int = count_result.scalar_one()

    result = await db.execute(
        select(Tool).where(base_where).order_by(Tool.created_at.desc()).offset(skip).limit(limit)
    )
    tools = result.scalars().all()

    return ToolListResponse(
        items=[ToolResponse.from_orm(t) for t in tools],
        total=total,
    )


@router.get("/{tool_id}", response_model=ToolResponse)
async def get_tool(
    tool_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ToolResponse:
    tool = await _get_tool_or_404(tool_id, tenant_id, db)
    return ToolResponse.from_orm(tool)


@router.put("/{tool_id}", response_model=ToolResponse)
async def update_tool(
    tool_id: uuid.UUID,
    body: ToolUpdate,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ToolResponse:
    tool = await _get_tool_or_404(tool_id, tenant_id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tool, field, value)

    await db.flush()
    await db.refresh(tool)

    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        # Find all agents using this tool and invalidate their snapshots
        agent_tools_result = await db.execute(
            select(AgentTool).where(AgentTool.tool_id == tool_id)
        )
        for at in agent_tools_result.scalars().all():
            agent_result = await db.execute(select(Agent).where(Agent.id == at.agent_id))
            agent = agent_result.scalar_one_or_none()
            if agent:
                await config_publisher.invalidate(redis, str(agent.tenant_id), str(agent.id))

    return ToolResponse.from_orm(tool)


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(
    tool_id: uuid.UUID,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    tool = await _get_tool_or_404(tool_id, tenant_id, db)
    tool.is_active = False
    await db.flush()

    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        # Find all agents using this tool and invalidate their snapshots
        agent_tools_result = await db.execute(
            select(AgentTool).where(AgentTool.tool_id == tool_id)
        )
        for at in agent_tools_result.scalars().all():
            agent_result = await db.execute(select(Agent).where(Agent.id == at.agent_id))
            agent = agent_result.scalar_one_or_none()
            if agent:
                await config_publisher.invalidate(redis, str(agent.tenant_id), str(agent.id))


# ---------------------------------------------------------------------------
# Schema versioning sub-routes
# ---------------------------------------------------------------------------


class SchemaVersionCreate(BaseModel):
    schema_def: dict[str, Any]
    schema_version: int | None = None  # auto-increments if not provided


class SchemaVersionResponse(BaseModel):
    tool_id: uuid.UUID
    schema_version: int
    schema_def: dict[str, Any]
    checksum: str
    created_at: str


def _schema_checksum(schema_def: dict) -> str:
    canonical = json.dumps(schema_def, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@router.put("/{tool_id}/schemas", status_code=201, response_model=SchemaVersionResponse)
async def publish_schema_version(
    tool_id: uuid.UUID,
    body: SchemaVersionCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SchemaVersionResponse:
    """Publish a new immutable schema version for a tool."""
    tool = await _get_tool_or_404(tool_id, tenant_id, db)

    # Determine next schema version
    if body.schema_version is not None:
        next_ver = body.schema_version
    else:
        max_result = await db.execute(
            select(func.coalesce(func.max(ToolSchemaVersion.schema_version), 0)).where(
                ToolSchemaVersion.tool_id == tool_id
            )
        )
        next_ver = max_result.scalar_one() + 1

    # Idempotent — if this version already exists return existing
    existing = await db.execute(
        select(ToolSchemaVersion).where(
            and_(
                ToolSchemaVersion.tool_id == tool_id,
                ToolSchemaVersion.schema_version == next_ver,
            )
        )
    )
    existing_row = existing.scalar_one_or_none()
    if existing_row is not None:
        return SchemaVersionResponse(
            tool_id=existing_row.tool_id,
            schema_version=existing_row.schema_version,
            schema_def=existing_row.schema_def,
            checksum=existing_row.checksum,
            created_at=existing_row.created_at.isoformat() if isinstance(existing_row.created_at, datetime) else str(existing_row.created_at),
        )

    checksum = _schema_checksum(body.schema_def)
    schema_ver = ToolSchemaVersion(
        tool_id=tool_id,
        schema_version=next_ver,
        schema_def=body.schema_def,
        checksum=checksum,
    )
    db.add(schema_ver)

    # Advance tool's active_schema_version pointer
    if next_ver > tool.active_schema_version:
        tool.active_schema_version = next_ver

    await db.flush()
    await db.refresh(schema_ver)

    return SchemaVersionResponse(
        tool_id=schema_ver.tool_id,
        schema_version=schema_ver.schema_version,
        schema_def=schema_ver.schema_def,
        checksum=schema_ver.checksum,
        created_at=schema_ver.created_at.isoformat() if isinstance(schema_ver.created_at, datetime) else str(schema_ver.created_at),
    )


@router.get("/{tool_id}/schemas", response_model=list[SchemaVersionResponse])
async def list_schema_versions(
    tool_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[SchemaVersionResponse]:
    """List all schema versions for a tool, newest first."""
    await _get_tool_or_404(tool_id, tenant_id, db)

    result = await db.execute(
        select(ToolSchemaVersion)
        .where(ToolSchemaVersion.tool_id == tool_id)
        .order_by(ToolSchemaVersion.schema_version.desc())
    )
    versions = result.scalars().all()

    return [
        SchemaVersionResponse(
            tool_id=v.tool_id,
            schema_version=v.schema_version,
            schema_def=v.schema_def,
            checksum=v.checksum,
            created_at=v.created_at.isoformat() if isinstance(v.created_at, datetime) else str(v.created_at),
        )
        for v in versions
    ]
