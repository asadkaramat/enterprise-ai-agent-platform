"""
Audit event publisher — dual-publish to Kafka (primary) and Redis Streams (fallback).

Kafka topic: audit.events
Redis fallback: audit:events stream (for when Kafka is unavailable)

Each event carries a unique event_id UUID so the audit-service consumer
can deduplicate events received via both transports.
"""
import logging
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# Module-level Kafka producer singleton — set at startup via set_kafka_producer()
_kafka_producer: Any = None

KAFKA_TOPIC = "audit.events"


def set_kafka_producer(producer: Any) -> None:
    """Called once at startup after the Kafka producer is connected."""
    global _kafka_producer
    _kafka_producer = producer


async def publish_event(redis_client: Any, event_type: str, **kwargs: Any) -> None:
    """
    Publish a structured audit event.

    Resolution order:
      1. Kafka topic 'audit.events' (primary — durable, replayable)
      2. Redis Stream 'audit:events' (fallback — when Kafka unavailable)

    Each event carries a unique event_id so the audit-service consumer
    can deduplicate across both transports.

    Args:
        redis_client: An async Redis client (redis.asyncio.Redis).
        event_type:   A short identifier for the event, e.g. 'session_start'.
        **kwargs:     Arbitrary key/value pairs included in the event payload.
    """
    # Build the event payload
    event_id = str(uuid.uuid4())
    data: dict[str, str] = {
        "event_id": event_id,
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
    }
    for key, value in kwargs.items():
        data[key] = str(value) if value is not None else ""

    # --- Primary: Kafka ---
    if _kafka_producer is not None:
        try:
            await _kafka_producer.send_and_wait(KAFKA_TOPIC, data)
            logger.debug("publish_event: published '%s' to Kafka (event_id=%s)", event_type, event_id)
            return
        except Exception as exc:
            logger.error(
                "publish_event: Kafka publish failed for '%s', falling back to Redis: %s",
                event_type,
                exc,
            )

    # --- Fallback: Redis Stream ---
    if redis_client is None:
        logger.warning("publish_event: no Kafka or Redis client — event '%s' not published", event_type)
        return

    try:
        await redis_client.xadd("audit:events", data)
        logger.debug("publish_event: published '%s' to Redis fallback (event_id=%s)", event_type, event_id)
    except Exception as exc:
        logger.error(
            "publish_event: Redis fallback also failed for '%s': %s",
            event_type,
            exc,
        )
