from fastapi import HTTPException, Request


async def get_tenant_id(request: Request) -> str:
    """
    Dependency that extracts the X-Tenant-ID header from the incoming request.
    Raises HTTP 400 if the header is absent or empty.
    """
    tenant_id = request.headers.get("X-Tenant-ID", "").strip()
    if not tenant_id:
        raise HTTPException(
            status_code=400,
            detail="Missing required header: X-Tenant-ID",
        )
    return tenant_id
