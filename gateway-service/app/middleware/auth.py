import logging

import bcrypt
from fastapi import HTTPException, Request
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.metrics import auth_failures_total
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

# Paths that bypass API key auth
PUBLIC_PATHS = {"/health", "/metrics"}
ADMIN_PREFIX = "/admin"


async def authenticate_request(request: Request) -> Tenant | None:
    """
    Authenticates an incoming request by API key.
    Returns the Tenant if valid, raises HTTPException otherwise.
    Skips auth for public paths and admin paths (admin auth is handled separately).
    """
    path = request.url.path

    if path in PUBLIC_PATHS or path.startswith(ADMIN_PREFIX):
        return None

    api_key = request.headers.get("X-API-Key")
    if not api_key:
        auth_failures_total.labels(reason="missing_api_key").inc()
        logger.warning("Request missing X-API-Key header: %s %s", request.method, path)
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")

    # Extract prefix (first 12 chars)
    prefix = api_key[:12]

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Tenant).where(
                Tenant.api_key_prefix == prefix,
                Tenant.is_active == True,  # noqa: E712
            )
        )
        tenant = result.scalar_one_or_none()

    if tenant is None:
        auth_failures_total.labels(reason="invalid_prefix").inc()
        logger.warning("No active tenant found for prefix %r", prefix)
        raise HTTPException(status_code=401, detail="Invalid API key")

    # bcrypt verify (blocking — run in thread pool via anyio)
    import anyio

    key_bytes = api_key.encode()
    hash_bytes = tenant.api_key_hash.encode()

    def _verify() -> bool:
        return bcrypt.checkpw(key_bytes, hash_bytes)

    valid = await anyio.to_thread.run_sync(_verify)

    if not valid:
        auth_failures_total.labels(reason="invalid_key").inc()
        logger.warning("API key verification failed for tenant %s", tenant.id)
        raise HTTPException(status_code=401, detail="Invalid API key")

    logger.debug("Authenticated tenant %s (%s)", tenant.id, tenant.name)
    return tenant


async def authenticate_admin(request: Request) -> None:
    """Validates X-Admin-Secret header for admin routes."""
    from app.config import settings

    secret = request.headers.get("X-Admin-Secret")
    if not secret or secret != settings.ADMIN_SECRET:
        auth_failures_total.labels(reason="invalid_admin_secret").inc()
        logger.warning("Admin auth failed for %s %s", request.method, request.url.path)
        raise HTTPException(status_code=403, detail="Invalid or missing X-Admin-Secret")
