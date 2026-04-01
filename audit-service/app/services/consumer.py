import asyncio
import json
import logging
import uuid

import redis.asyncio as aioredis

from app.config import settings
from app.database import AsyncSessionLocal
from app.metrics import audit_events_consumed_total, audit_events_failed_total, consumer_lag_gauge
from app.models.audit import AuditEvent

logger = logging.getLogger(__name__)

STREAM_KEY = "audit:events"
CONSUMER_GROUP = "audit-service"
CONSUMER_NAME = "audit-service-1"


async def ensure_consumer_group(redis: aioredis.Redis) -> None:
    """Create the consumer group if it does not already exist."""
    try:
        await redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
        logger.info("Created consumer group %s", CONSUMER_GROUP)
    except Exception as exc:
        if "BUSYGROUP" in str(exc):
            logger.info("Consumer group %s already exists", CONSUMER_GROUP)
        else:
            logger.error("Failed to create consumer group: %s", exc)
            raise


async def process_message(message_id: str, fields: dict) -> None:
    """Parse a Redis Stream message and write one row to audit_events (append only)."""
    try:
        event_type = fields.get("event_type", "unknown")
        tenant_id_str = fields.get("tenant_id", "")
        session_id_str = fields.get("session_id")
        agent_id_str = fields.get("agent_id")

        # All remaining fields become event_data
        reserved = {"event_type", "tenant_id", "session_id", "agent_id", "timestamp"}
        event_data: dict = {}
        for key, value in fields.items():
            if key in reserved:
                continue
            # Attempt JSON decode for nested structures
            try:
                event_data[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                event_data[key] = value  # keep as plain string

        # Parse tenant_id — required; drop message if invalid
        try:
            tenant_id = uuid.UUID(tenant_id_str)
        except (ValueError, AttributeError):
            logger.warning(
                "Invalid or missing tenant_id in message %s: %r — dropping",
                message_id,
                tenant_id_str,
            )
            return

        # Parse optional UUIDs
        session_id: uuid.UUID | None = None
        if session_id_str:
            try:
                session_id = uuid.UUID(session_id_str)
            except ValueError:
                logger.debug("Unparseable session_id %r in message %s", session_id_str, message_id)

        agent_id: uuid.UUID | None = None
        if agent_id_str:
            try:
                agent_id = uuid.UUID(agent_id_str)
            except ValueError:
                logger.debug("Unparseable agent_id %r in message %s", agent_id_str, message_id)

        # INSERT only — no UPDATE/DELETE ever
        async with AsyncSessionLocal() as db:
            event = AuditEvent(
                tenant_id=tenant_id,
                session_id=session_id,
                agent_id=agent_id,
                event_type=event_type,
                event_data=event_data,
            )
            db.add(event)
            await db.commit()

        audit_events_consumed_total.labels(event_type=event_type).inc()
        logger.debug("Processed audit event %s: type=%s tenant=%s", message_id, event_type, tenant_id)

    except Exception as exc:
        audit_events_failed_total.inc()
        logger.error(
            "Failed to process message %s: %s",
            message_id,
            exc,
            exc_info=True,
        )


async def _update_lag_metric(redis: aioredis.Redis) -> None:
    """Update the consumer_lag_gauge from XPENDING info."""
    try:
        info = await redis.xpending(STREAM_KEY, CONSUMER_GROUP)
        pending_count = info.get("pending", 0) if isinstance(info, dict) else (info[0] if info else 0)
        consumer_lag_gauge.set(pending_count)
    except Exception:
        pass  # metric update is best-effort


async def run_consumer(redis: aioredis.Redis) -> None:
    """
    Main consumer loop. Runs indefinitely as an asyncio background task.
    Reads from Redis Stream using consumer groups (XREADGROUP).
    ACKs every message after processing to prevent poison-message loops.
    """
    await ensure_consumer_group(redis)
    logger.info("Audit consumer started — listening on stream %s", STREAM_KEY)

    lag_tick = 0

    while True:
        try:
            results = await redis.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_KEY: ">"},
                count=10,
                block=5000,  # wait up to 5 s when the stream is empty
            )

            if not results:
                lag_tick += 1
                if lag_tick % 12 == 0:  # ~every minute
                    await _update_lag_metric(redis)
                continue

            for _stream_name, messages in results:
                for message_id, fields in messages:
                    await process_message(message_id, fields)
                    # ACK unconditionally: bad messages must not stall the consumer
                    await redis.xack(STREAM_KEY, CONSUMER_GROUP, message_id)

            await _update_lag_metric(redis)

        except asyncio.CancelledError:
            logger.info("Audit consumer cancelled — shutting down gracefully")
            break
        except Exception as exc:
            logger.error("Consumer loop error: %s", exc, exc_info=True)
            await asyncio.sleep(5)  # back off before retrying
