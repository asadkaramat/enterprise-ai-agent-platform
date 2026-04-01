"""
Redis-based audit event publisher.

All agent activity (session creation, completion, budget enforcement, errors)
is published to the 'audit:events' Redis Stream for downstream consumers.
"""
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


async def publish_event(redis_client: Any, event_type: str, **kwargs: Any) -> None:
    """
    Publish a structured audit event to the 'audit:events' Redis Stream.

    All values are coerced to strings because Redis Streams require string
    field values.

    Args:
        redis_client: An async Redis client (redis.asyncio.Redis).
        event_type:   A short identifier for the event, e.g. 'session_start'.
        **kwargs:     Arbitrary key/value pairs to include in the event payload.
    """
    if redis_client is None:
        logger.warning("publish_event: no Redis client, event '%s' not published", event_type)
        return

    data: dict[str, str] = {
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
    }
    for key, value in kwargs.items():
        data[key] = str(value) if value is not None else ""

    try:
        await redis_client.xadd("audit:events", data)
        logger.debug("publish_event: published '%s' to audit:events", event_type)
    except Exception as exc:
        # Audit failure must never crash the main request flow
        logger.error(
            "publish_event: failed to publish '%s' to Redis: %s",
            event_type,
            exc,
        )
