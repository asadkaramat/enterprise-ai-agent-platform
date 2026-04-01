import uuid

from fastapi import Header, HTTPException


async def get_tenant_id(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
) -> uuid.UUID:
    """
    FastAPI dependency.
    Extracts the X-Tenant-ID header and validates it as a UUID.
    Raises HTTP 400 if the header is absent or not a valid UUID.
    """
    if not x_tenant_id:
        raise HTTPException(
            status_code=400,
            detail="Missing required header: X-Tenant-ID",
        )
    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid X-Tenant-ID — must be a valid UUID, got: {x_tenant_id!r}",
        )
