"""
Tenant management + RBAC: tenants, roles, and API keys.

POST /tenants                      — create a tenant (platform admin)
GET  /tenants/{id}                 — get tenant metadata
PATCH /tenants/{id}                — update quota/status

GET  /roles                        — list roles for current tenant
POST /roles                        — create a custom role
GET  /roles/{id}                   — get role details

POST /api-keys                     — create an API key (plaintext returned once)
DELETE /api-keys/{id}              — revoke an API key
GET  /api-keys                     — list API keys for tenant (prefixes only)
"""
import hashlib
import secrets
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.tenant import get_tenant_id
from app.models.tenant import ApiKey, Role, Tenant

router = APIRouter(tags=["tenants"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TenantCreate(BaseModel):
    name: str
    slug: str
    max_concurrent_sessions: int = 100


class TenantUpdate(BaseModel):
    max_concurrent_sessions: int | None = None
    status: str | None = None


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    max_concurrent_sessions: int
    created_at: str


class RoleCreate(BaseModel):
    name: str
    permissions: list[str] = []


class RoleResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    permissions: list[str]
    created_at: str

    @classmethod
    def from_orm(cls, r: Role) -> "RoleResponse":
        return cls(
            id=r.id,
            tenant_id=r.tenant_id,
            name=r.name,
            permissions=r.permissions or [],
            created_at=r.created_at.isoformat() if isinstance(r.created_at, datetime) else str(r.created_at),
        )


class ApiKeyCreate(BaseModel):
    role_id: uuid.UUID
    scopes: list[str] = ["*"]
    expires_at: datetime | None = None


class ApiKeyResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    role_id: uuid.UUID
    key_prefix: str
    scopes: list[str]
    expires_at: str | None
    status: str
    created_at: str


class ApiKeyCreateResponse(ApiKeyResponse):
    """Returned only on creation — includes plaintext_key shown once."""
    plaintext_key: str


# ---------------------------------------------------------------------------
# Tenant routes
# ---------------------------------------------------------------------------


@router.post("/tenants", status_code=status.HTTP_201_CREATED, response_model=TenantResponse)
async def create_tenant(
    body: TenantCreate,
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Platform-admin operation — no tenant header required."""
    existing = await db.execute(select(Tenant).where(Tenant.slug == body.slug))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' already taken.")

    tenant = Tenant(
        id=uuid.uuid4(),
        name=body.name,
        slug=body.slug,
        max_concurrent_sessions=body.max_concurrent_sessions,
    )
    db.add(tenant)
    await db.flush()

    # Provision default roles
    for role_name, perms in [
        ("tenant_admin", ["*"]),
        ("agent_developer", ["agents:read", "agents:write", "tools:read", "tools:write",
                              "sessions:read", "sessions:write"]),
        ("agent_operator", ["agents:read", "agents:deploy", "sessions:read",
                             "audit:read", "usage:read"]),
        ("auditor", ["audit:read", "audit:export", "usage:read"]),
        ("viewer", ["agents:read", "tools:read", "sessions:read"]),
    ]:
        db.add(Role(
            id=uuid.uuid4(),
            tenant_id=tenant.id,
            name=role_name,
            permissions=perms,
        ))

    await db.flush()

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        max_concurrent_sessions=tenant.max_concurrent_sessions,
        created_at=tenant.created_at.isoformat() if isinstance(tenant.created_at, datetime) else str(tenant.created_at),
    )


@router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")
    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        max_concurrent_sessions=tenant.max_concurrent_sessions,
        created_at=tenant.created_at.isoformat() if isinstance(tenant.created_at, datetime) else str(tenant.created_at),
    )


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: uuid.UUID,
    body: TenantUpdate,
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    if body.max_concurrent_sessions is not None:
        tenant.max_concurrent_sessions = body.max_concurrent_sessions
    if body.status is not None:
        tenant.status = body.status
    tenant.updated_at = datetime.utcnow()
    await db.flush()

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        max_concurrent_sessions=tenant.max_concurrent_sessions,
        created_at=tenant.created_at.isoformat() if isinstance(tenant.created_at, datetime) else str(tenant.created_at),
    )


# ---------------------------------------------------------------------------
# Role routes
# ---------------------------------------------------------------------------


@router.post("/roles", status_code=status.HTTP_201_CREATED, response_model=RoleResponse)
async def create_role(
    body: RoleCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    role = Role(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=body.name,
        permissions=body.permissions,
    )
    db.add(role)
    await db.flush()
    await db.refresh(role)
    return RoleResponse.from_orm(role)


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[RoleResponse]:
    result = await db.execute(
        select(Role).where(Role.tenant_id == tenant_id).order_by(Role.name)
    )
    return [RoleResponse.from_orm(r) for r in result.scalars().all()]


@router.get("/roles/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> RoleResponse:
    result = await db.execute(
        select(Role).where(and_(Role.id == role_id, Role.tenant_id == tenant_id))
    )
    role = result.scalar_one_or_none()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found.")
    return RoleResponse.from_orm(role)


# ---------------------------------------------------------------------------
# API key routes
# ---------------------------------------------------------------------------


def _hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


@router.post("/api-keys", status_code=status.HTTP_201_CREATED, response_model=ApiKeyCreateResponse)
async def create_api_key(
    body: ApiKeyCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreateResponse:
    """
    Generate an API key. The plaintext is returned ONCE — it is never stored.
    Format: {tenant_slug}_{random_32_chars}
    """
    # Verify role belongs to tenant
    role_result = await db.execute(
        select(Role).where(and_(Role.id == body.role_id, Role.tenant_id == tenant_id))
    )
    if role_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Role not found.")

    plaintext = secrets.token_urlsafe(32)
    key_hash = _hash_key(plaintext)
    key_prefix = plaintext[:8]

    api_key = ApiKey(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        role_id=body.role_id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        scopes=body.scopes,
        expires_at=body.expires_at,
    )
    db.add(api_key)
    await db.flush()

    return ApiKeyCreateResponse(
        id=api_key.id,
        tenant_id=tenant_id,
        role_id=body.role_id,
        key_prefix=key_prefix,
        scopes=body.scopes,
        expires_at=body.expires_at.isoformat() if body.expires_at else None,
        status="active",
        created_at=api_key.created_at.isoformat() if isinstance(api_key.created_at, datetime) else str(api_key.created_at),
        plaintext_key=plaintext,
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKeyResponse]:
    result = await db.execute(
        select(ApiKey)
        .where(and_(ApiKey.tenant_id == tenant_id, ApiKey.status == "active"))
        .order_by(ApiKey.created_at.desc())
    )
    return [
        ApiKeyResponse(
            id=k.id,
            tenant_id=k.tenant_id,
            role_id=k.role_id,
            key_prefix=k.key_prefix,
            scopes=k.scopes or ["*"],
            expires_at=k.expires_at.isoformat() if k.expires_at else None,
            status=k.status,
            created_at=k.created_at.isoformat() if isinstance(k.created_at, datetime) else str(k.created_at),
        )
        for k in result.scalars().all()
    ]


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_200_OK)
async def revoke_api_key(
    key_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(ApiKey).where(and_(ApiKey.id == key_id, ApiKey.tenant_id == tenant_id))
    )
    key = result.scalar_one_or_none()
    if key is None:
        raise HTTPException(status_code=404, detail="API key not found.")

    key.status = "revoked"
    await db.flush()
    return {"key_id": str(key_id), "status": "revoked"}
