import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.metrics import tools_registered_total
from app.middleware.tenant import get_tenant_id
from app.models.tool import Tool

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
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ToolResponse:
    tool = await _get_tool_or_404(tool_id, tenant_id, db)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tool, field, value)

    await db.flush()
    await db.refresh(tool)
    return ToolResponse.from_orm(tool)


@router.delete("/{tool_id}", status_code=204)
async def delete_tool(
    tool_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    tool = await _get_tool_or_404(tool_id, tenant_id, db)
    tool.is_active = False
    await db.flush()
