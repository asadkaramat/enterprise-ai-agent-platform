import uuid

from fastapi import Header, HTTPException, Request


def get_tenant_id(x_tenant_id: str | None = Header(default=None)) -> uuid.UUID:
    """
    FastAPI dependency that extracts and validates the X-Tenant-ID header.
    Raises HTTP 400 if the header is missing or not a valid UUID.
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
            detail=f"Invalid X-Tenant-ID header value '{x_tenant_id}': must be a valid UUID.",
        )


def get_tenant_id_from_request(request: Request) -> uuid.UUID:
    """
    Utility that extracts and validates X-Tenant-ID directly from a Request object.
    Useful in middleware or non-dependency contexts.
    """
    raw = request.headers.get("x-tenant-id") or request.headers.get("X-Tenant-ID")
    if not raw:
        raise HTTPException(
            status_code=400,
            detail="Missing required header: X-Tenant-ID",
        )
    try:
        return uuid.UUID(raw)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid X-Tenant-ID header value '{raw}': must be a valid UUID.",
        )
