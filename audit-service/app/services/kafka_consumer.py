"""
Kafka consumer for audit events.

Consumes from topic 'audit.events' using the consumer group 'audit-service'.
Calls the same process_message() as the Redis consumer for unified processing.
Falls back gracefully if Kafka is unavailable at startup.
"""
import asyncio
import json
import logging

from app.config import settings
from app.services.consumer import process_message

logger = logging.getLogger(__name__)

KAFKA_TOPIC = "audit.events"
CONSUMER_GROUP = "audit-service"


async def run_kafka_consumer() -> None:
    """
    Main Kafka consumer loop. Runs indefinitely as an asyncio background task.
    Uses aiokafka AIOKafkaConsumer with manual offset commit disabled
    (enable_auto_commit=True for simplicity in local MVP).
    """
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        logger.error("aiokafka not installed — Kafka consumer disabled")
        return

    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=CONSUMER_GROUP,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        auto_commit_interval_ms=1000,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        session_timeout_ms=30000,
        heartbeat_interval_ms=10000,
    )

    logger.info("Kafka consumer: connecting to %s", settings.KAFKA_BOOTSTRAP_SERVERS)

    try:
        await consumer.start()
        logger.info("Kafka consumer started — listening on topic %s", KAFKA_TOPIC)
    except Exception as exc:
        logger.error("Kafka consumer: failed to start — %s", exc)
        return

    try:
        async for msg in consumer:
            try:
                fields = msg.value
                if not isinstance(fields, dict):
                    continue
                # Use Kafka offset as message ID for logging
                message_id = f"kafka-{msg.partition}-{msg.offset}"
                await process_message(message_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Kafka consumer: error processing message: %s", exc, exc_info=True)
    except asyncio.CancelledError:
        logger.info("Kafka consumer: cancelled — shutting down")
    except Exception as exc:
        logger.error("Kafka consumer: fatal error — %s", exc, exc_info=True)
    finally:
        try:
            await consumer.stop()
            logger.info("Kafka consumer stopped")
        except Exception:
            pass
