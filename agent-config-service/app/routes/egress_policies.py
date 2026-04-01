"""
Egress allowlist management.

GET    /egress-allowlist           — list active entries for tenant
POST   /egress-allowlist           — add an allowed endpoint
DELETE /egress-allowlist/{id}      — remove an entry
GET    /egress-allowlist/validate  — check if a URL is allowed (used by session-service)
"""
import fnmatch
import uuid
from datetime import datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.tenant import get_tenant_id
from app.models.egress_allowlist import EgressAllowlist

router = APIRouter(prefix="/egress-allowlist", tags=["egress-allowlist"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class EgressEntryCreate(BaseModel):
    endpoint_pattern: str
    port: int = 443
    protocol: str = "https"
    description: str | None = None


class EgressEntryResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    endpoint_pattern: str
    port: int
    protocol: str
    description: str | None
    is_active: bool
    created_at: str


def _serialize(e: EgressAllowlist) -> EgressEntryResponse:
    return EgressEntryResponse(
        id=e.id,
        tenant_id=e.tenant_id,
        endpoint_pattern=e.endpoint_pattern,
        port=e.port,
        protocol=e.protocol,
        description=e.description,
        is_active=e.is_active,
        created_at=e.created_at.isoformat() if isinstance(e.created_at, datetime) else str(e.created_at),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _url_matches_entry(url: str, entry: EgressAllowlist) -> bool:
    """Return True if `url` is permitted by this allowlist entry."""
    try:
        parsed = urlparse(url)
        # Protocol check
        if entry.protocol not in ("*", parsed.scheme):
            return False
        # Port check (default 443 for https, 80 for http)
        url_port = parsed.port
        if url_port is None:
            url_port = 443 if parsed.scheme == "https" else 80
        if entry.port not in (0, url_port):
            return False
        # Hostname wildcard match
        hostname = parsed.hostname or ""
        return fnmatch.fnmatch(hostname, entry.endpoint_pattern)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[EgressEntryResponse])
async def list_entries(
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[EgressEntryResponse]:
    result = await db.execute(
        select(EgressAllowlist)
        .where(and_(EgressAllowlist.tenant_id == tenant_id, EgressAllowlist.is_active.is_(True)))
        .order_by(EgressAllowlist.created_at)
    )
    return [_serialize(e) for e in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=EgressEntryResponse)
async def add_entry(
    body: EgressEntryCreate,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> EgressEntryResponse:
    if body.protocol not in ("http", "https", "grpc"):
        raise HTTPException(status_code=400, detail="protocol must be http, https, or grpc")
    entry = EgressAllowlist(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        endpoint_pattern=body.endpoint_pattern,
        port=body.port,
        protocol=body.protocol,
        description=body.description,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return _serialize(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_200_OK)
async def remove_entry(
    entry_id: uuid.UUID,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(
        select(EgressAllowlist).where(
            and_(EgressAllowlist.id == entry_id, EgressAllowlist.tenant_id == tenant_id)
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Egress entry not found.")
    entry.is_active = False
    await db.flush()
    return {"entry_id": str(entry_id), "is_active": False}


@router.get("/validate")
async def validate_url(
    url: str = Query(..., description="Full URL to validate against the tenant's egress allowlist"),
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Returns {"allowed": true/false, "reason": str}.
    If the tenant has NO allowlist entries, all URLs are allowed (default-open).
    """
    result = await db.execute(
        select(EgressAllowlist)
        .where(and_(EgressAllowlist.tenant_id == tenant_id, EgressAllowlist.is_active.is_(True)))
    )
    entries = result.scalars().all()

    # No entries → default-open (allow all)
    if not entries:
        return {"allowed": True, "reason": "no egress restrictions configured"}

    for entry in entries:
        if _url_matches_entry(url, entry):
            return {
                "allowed": True,
                "reason": f"matched pattern '{entry.endpoint_pattern}' (port {entry.port})",
            }

    return {"allowed": False, "reason": f"'{url}' does not match any entry in the egress allowlist"}


# ---------------------------------------------------------------------------
# Internal bulk-fetch endpoint (used by session-service's load_config_node)
# ---------------------------------------------------------------------------

internal_router = APIRouter(tags=["internal"], include_in_schema=False)


@internal_router.get("/internal/egress-allowlist/{tenant_id}")
async def get_tenant_egress_allowlist(
    tenant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return active egress entries for a tenant — called by session-service."""
    result = await db.execute(
        select(EgressAllowlist)
        .where(and_(EgressAllowlist.tenant_id == tenant_id, EgressAllowlist.is_active.is_(True)))
    )
    return [
        {
            "endpoint_pattern": e.endpoint_pattern,
            "port": e.port,
            "protocol": e.protocol,
        }
        for e in result.scalars().all()
    ]
