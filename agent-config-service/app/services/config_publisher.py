"""
Config snapshot publisher — decouples orchestration from control plane.

Writes a full config snapshot to a well-known Redis key so the session-service
can read it directly without calling the internal HTTP endpoint.

Key: config:snapshot:{tenant_id}:{agent_id}
TTL: 600 seconds (10 minutes)

Session-service checks this key first; on miss it falls back to HTTP.
Mutations (agent/tool/policy/egress changes) invalidate the key immediately
so the next request gets a fresh snapshot.
"""
import json
import logging

logger = logging.getLogger(__name__)

_TTL_SNAPSHOT = 600  # 10 minutes


def _key(tenant_id: str, agent_id: str) -> str:
    return f"config:snapshot:{tenant_id}:{agent_id}"


async def publish(redis_client, tenant_id: str, agent_id: str, config_data: dict) -> None:
    """Write a full config snapshot to Redis. No-op if redis_client is None."""
    if redis_client is None:
        return
    try:
        await redis_client.set(_key(tenant_id, agent_id), json.dumps(config_data), ex=_TTL_SNAPSHOT)
        logger.debug("config_publisher: published snapshot for agent %s tenant %s", agent_id, tenant_id)
    except Exception as exc:
        logger.debug("config_publisher.publish: %s", exc)


async def invalidate(redis_client, tenant_id: str, agent_id: str) -> None:
    """Delete the config snapshot for an agent. No-op if redis_client is None."""
    if redis_client is None:
        return
    try:
        await redis_client.delete(_key(tenant_id, agent_id))
        logger.debug("config_publisher: invalidated snapshot for agent %s tenant %s", agent_id, tenant_id)
    except Exception as exc:
        logger.debug("config_publisher.invalidate: %s", exc)
