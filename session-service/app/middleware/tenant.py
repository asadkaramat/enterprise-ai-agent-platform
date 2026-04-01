"""
Tenant extraction middleware and dependency.

Reads X-Tenant-ID from request headers and validates it as a UUID.
Raises HTTP 400 if the header is missing or malformed.
"""
import uuid
import logging
from typing import Annotated

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)


async def get_tenant_id(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
) -> uuid.UUID:
    """
    FastAPI dependency that extracts and validates the X-Tenant-ID header.

    Usage in a route:
        @router.get("/something")
        async def my_route(tenant_id: uuid.UUID = Depends(get_tenant_id)):
            ...

    Raises:
        HTTPException 400 if X-Tenant-ID is missing or not a valid UUID.
    """
    if not x_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID header is required",
        )

    try:
        return uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"X-Tenant-ID '{x_tenant_id}' is not a valid UUID",
        )
