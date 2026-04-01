"""
Redis config cache — wraps the two hot read paths from the Orchestration Plane.

Cache keys (spec Section 9):
  {tenant_id}:config:agent:{agent_id}:active_version  →  version_id  (TTL 30s)
  {tenant_id}:config:version:{version_id}              →  full config JSON  (TTL 300s)
  {tenant_id}:config:tools:{version_id}                →  tool array JSON  (TTL 300s)

All methods degrade gracefully when Redis is unavailable — a miss is returned
so the caller falls through to the database.
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Cache TTLs (seconds)
_TTL_ACTIVE_VERSION = 30
_TTL_VERSION_SNAPSHOT = 300
_TTL_TOOL_SCHEMAS = 300


def _key_active_version(tenant_id: str, agent_id: str) -> str:
    return f"{tenant_id}:config:agent:{agent_id}:active_version"


def _key_version_snapshot(tenant_id: str, version_id: str) -> str:
    return f"{tenant_id}:config:version:{version_id}"


def _key_tool_schemas(tenant_id: str, version_id: str) -> str:
    return f"{tenant_id}:config:tools:{version_id}"


async def get_active_version(
    redis_client: Any, tenant_id: str, agent_id: str
) -> str | None:
    """Return the cached active version_id, or None on miss/error."""
    try:
        val = await redis_client.get(_key_active_version(tenant_id, agent_id))
        return val.decode() if isinstance(val, bytes) else val
    except Exception as exc:
        logger.debug("config_cache.get_active_version: %s", exc)
        return None


async def set_active_version(
    redis_client: Any, tenant_id: str, agent_id: str, version_id: str
) -> None:
    try:
        await redis_client.set(
            _key_active_version(tenant_id, agent_id), version_id, ex=_TTL_ACTIVE_VERSION
        )
    except Exception as exc:
        logger.debug("config_cache.set_active_version: %s", exc)


async def invalidate_active_version(
    redis_client: Any, tenant_id: str, agent_id: str
) -> None:
    """Called on version promotion / rollback to force a fresh DB read."""
    try:
        await redis_client.delete(_key_active_version(tenant_id, agent_id))
    except Exception as exc:
        logger.debug("config_cache.invalidate_active_version: %s", exc)


async def get_version_snapshot(
    redis_client: Any, tenant_id: str, version_id: str
) -> dict | None:
    """Return the cached full agent config dict, or None on miss/error."""
    try:
        raw = await redis_client.get(_key_version_snapshot(tenant_id, version_id))
        if raw is None:
            return None
        return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    except Exception as exc:
        logger.debug("config_cache.get_version_snapshot: %s", exc)
        return None


async def set_version_snapshot(
    redis_client: Any, tenant_id: str, version_id: str, data: dict
) -> None:
    try:
        await redis_client.set(
            _key_version_snapshot(tenant_id, version_id),
            json.dumps(data),
            ex=_TTL_VERSION_SNAPSHOT,
        )
    except Exception as exc:
        logger.debug("config_cache.set_version_snapshot: %s", exc)


async def get_tool_schemas(
    redis_client: Any, tenant_id: str, version_id: str
) -> list | None:
    """Return cached tool schema array, or None on miss/error."""
    try:
        raw = await redis_client.get(_key_tool_schemas(tenant_id, version_id))
        if raw is None:
            return None
        return json.loads(raw.decode() if isinstance(raw, bytes) else raw)
    except Exception as exc:
        logger.debug("config_cache.get_tool_schemas: %s", exc)
        return None


async def set_tool_schemas(
    redis_client: Any, tenant_id: str, version_id: str, data: list
) -> None:
    try:
        await redis_client.set(
            _key_tool_schemas(tenant_id, version_id),
            json.dumps(data),
            ex=_TTL_TOOL_SCHEMAS,
        )
    except Exception as exc:
        logger.debug("config_cache.set_tool_schemas: %s", exc)
