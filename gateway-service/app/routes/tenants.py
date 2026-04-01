import logging
import secrets
import uuid

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import authenticate_admin
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/tenants", tags=["admin"])


# ---------- Pydantic schemas ----------


class CreateTenantRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    rate_limit_per_minute: int = Field(60, ge=1, le=10000)


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    api_key_prefix: str
    is_active: bool
    rate_limit_per_minute: int
    created_at: str

    class Config:
        from_attributes = True


class CreateTenantResponse(BaseModel):
    tenant_id: uuid.UUID
    api_key: str
    name: str
    message: str = "Store this API key securely — it will not be shown again."


class RotateKeyResponse(BaseModel):
    tenant_id: uuid.UUID
    api_key: str
    message: str = "Store this API key securely — it will not be shown again."


# ---------- Helpers ----------


def _generate_api_key() -> str:
    return f"tap_{secrets.token_urlsafe(32)}"


def _hash_api_key(raw_key: str) -> str:
    return bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt(rounds=12)).decode()


# ---------- Routes ----------


@router.post("", response_model=CreateTenantResponse, status_code=201)
async def create_tenant(
    body: CreateTenantRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CreateTenantResponse:
    await authenticate_admin(request)

    raw_key = _generate_api_key()
    key_hash = _hash_api_key(raw_key)
    prefix = raw_key[:12]

    tenant = Tenant(
        name=body.name,
        api_key_hash=key_hash,
        api_key_prefix=prefix,
        rate_limit_per_minute=body.rate_limit_per_minute,
    )
    db.add(tenant)
    await db.flush()
    await db.refresh(tenant)

    logger.info("Created tenant %s (%s)", tenant.id, tenant.name)
    return CreateTenantResponse(
        tenant_id=tenant.id,
        api_key=raw_key,
        name=tenant.name,
    )


@router.get("", response_model=list[TenantResponse])
async def list_tenants(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[TenantResponse]:
    await authenticate_admin(request)

    result = await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    tenants = result.scalars().all()

    return [
        TenantResponse(
            id=t.id,
            name=t.name,
            api_key_prefix=t.api_key_prefix,
            is_active=t.is_active,
            rate_limit_per_minute=t.rate_limit_per_minute,
            created_at=t.created_at.isoformat(),
        )
        for t in tenants
    ]


@router.delete("/{tenant_id}", status_code=204)
async def deactivate_tenant(
    tenant_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    await authenticate_admin(request)

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()

    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.is_active = False
    logger.info("Deactivated tenant %s (%s)", tenant.id, tenant.name)


@router.post("/{tenant_id}/rotate-key", response_model=RotateKeyResponse)
async def rotate_api_key(
    tenant_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RotateKeyResponse:
    await authenticate_admin(request)

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()

    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if not tenant.is_active:
        raise HTTPException(status_code=400, detail="Cannot rotate key for inactive tenant")

    raw_key = _generate_api_key()
    tenant.api_key_hash = _hash_api_key(raw_key)
    tenant.api_key_prefix = raw_key[:12]

    logger.info("Rotated API key for tenant %s (%s)", tenant.id, tenant.name)
    return RotateKeyResponse(tenant_id=tenant.id, api_key=raw_key)
