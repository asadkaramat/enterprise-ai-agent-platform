"""
Policy CRUD + evaluation endpoint.

GET    /policies             — list policies (filterable by scope)
POST   /policies             — create a policy
GET    /policies/{id}        — get policy details
PUT    /policies/{id}        — update policy body / enable-disable
DELETE /policies/{id}        — soft-disable (never hard-delete)

POST   /internal/policy/evaluate — evaluate a tool call authorization (internal use)
"""
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.tenant import get_tenant_id
from app.models.policy import Policy
from app.services import policy_engine

router = APIRouter(prefix="/policies", tags=["policies"])
internal_router = APIRouter(tags=["internal"], include_in_schema=False)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class PolicyCreate(BaseModel):
    name: str
    scope: str  # 'tenant' | 'agent' | 'tool'
    scope_ref_id: uuid.UUID | None = None
    policy_lang: str = "inline"  # 'inline' | 'rego' | 'cedar'
    policy_body: str


class PolicyUpdate(BaseModel):
    policy_body: str | None = None
    enabled: bool | None = None


class PolicyResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    scope: str
    scope_ref_id: uuid.UUID | None
    policy_lang: str
    policy_body: str
    version: int
    enabled: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(cls, p: Policy) -> "PolicyResponse":
        return cls(
            id=p.id,
            tenant_id=p.tenant_id,
            name=p.name,
            scope=p.scope,
            scope_ref_id=p.scope_ref_id,
            policy_lang=p.policy_lang,
            policy_body=p.policy_body,
            version=p.version,
            enabled=p.enabled,
            created_at=p.created_at.isoformat() if isinstance(p.created_at, datetime) else str(p.created_at),
            updated_at=p.updated_at.isoformat() if isinstance(p.updated_at, datetime) else str(p.updated_at),
        )


class PolicyEvaluateRequest(BaseModel):
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    tool_id: uuid.UUID
    parameters: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_SCOPES = {"tenant", "agent", "tool"}
_VALID_LANGS = {"inline", "rego", "cedar"}


def _validate_scope(scope: str, scope_ref_id: uuid.UUID | None) -> None:
    if scope not in _VALID_SCOPES:
        raise HTTPException(
            status_code=400,
            detail=f"scope must be one of {sorted(_VALID_SCOPES)}",
        )
    if scope != "tenant" and scope_ref_id is None:
        raise HTTPException(
            status_code=400,
            detail="scope_ref_id is required for agent/tool scope policies",
        )


# ---------------------------------------------------------------------------
# CRUD routes
# ---------------------------------------------------------------------------


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PolicyResponse)
async def create_policy(
    body: PolicyCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    _validate_scope(body.scope, body.scope_ref_id)
    if body.policy_lang not in _VALID_LANGS:
        raise HTTPException(
            status_code=400,
            detail=f"policy_lang must be one of {sorted(_VALID_LANGS)}",
        )

    policy = Policy(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=body.name,
        scope=body.scope,
        scope_ref_id=body.scope_ref_id,
        policy_lang=body.policy_lang,
        policy_body=body.policy_body,
    )
    db.add(policy)
    await db.flush()
    await db.refresh(policy)
    return PolicyResponse.from_orm(policy)


@router.get("", response_model=list[PolicyResponse])
async def list_policies(
    scope: str | None = Query(default=None),
    scope_ref_id: uuid.UUID | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[PolicyResponse]:
    conditions = [Policy.tenant_id == tenant_id]
    if scope is not None:
        conditions.append(Policy.scope == scope)
    if scope_ref_id is not None:
        conditions.append(Policy.scope_ref_id == scope_ref_id)
    if enabled is not None:
        conditions.append(Policy.enabled.is_(enabled))

    result = await db.execute(
        select(Policy).where(and_(*conditions)).order_by(Policy.created_at.desc())
    )
    return [PolicyResponse.from_orm(p) for p in result.scalars().all()]


@router.get("/{policy_id}", response_model=PolicyResponse)
async def get_policy(
    policy_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    result = await db.execute(
        select(Policy).where(
            and_(Policy.id == policy_id, Policy.tenant_id == tenant_id)
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return PolicyResponse.from_orm(policy)


@router.put("/{policy_id}", response_model=PolicyResponse)
async def update_policy(
    policy_id: uuid.UUID,
    body: PolicyUpdate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> PolicyResponse:
    result = await db.execute(
        select(Policy).where(
            and_(Policy.id == policy_id, Policy.tenant_id == tenant_id)
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found.")

    if body.policy_body is not None:
        policy.policy_body = body.policy_body
        policy.version += 1
    if body.enabled is not None:
        policy.enabled = body.enabled
    policy.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(policy)
    return PolicyResponse.from_orm(policy)


@router.delete("/{policy_id}", status_code=status.HTTP_200_OK)
async def delete_policy(
    policy_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Soft-disable — policies are never hard-deleted (audit trail)."""
    result = await db.execute(
        select(Policy).where(
            and_(Policy.id == policy_id, Policy.tenant_id == tenant_id)
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found.")

    policy.enabled = False
    policy.updated_at = datetime.utcnow()
    await db.flush()
    return {"policy_id": str(policy_id), "enabled": False}


# ---------------------------------------------------------------------------
# Internal evaluation endpoint (called by Orchestration Plane)
# ---------------------------------------------------------------------------


@internal_router.post("/internal/policy/evaluate")
async def evaluate_policy(
    body: PolicyEvaluateRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Evaluate whether a tool call is authorized.
    Returns {"decision": "ALLOW"|"DENY", "reason": str, "policy_id": str|None}.
    """
    return await policy_engine.evaluate(
        tenant_id=body.tenant_id,
        agent_id=body.agent_id,
        agent_version_id=body.agent_version_id,
        tool_id=body.tool_id,
        parameters=body.parameters,
        db=db,
    )
