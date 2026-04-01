import asyncio
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import settings
from app.database import create_tables, dispose_engine, run_column_migrations
from app.routes.audit import router as audit_router
from app.services.consumer import run_consumer
from app.services.kafka_consumer import run_kafka_consumer
from app.services.blob_archiver import run_archiver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------
    logger.info("audit-service starting up on port 8004")

    # Ensure PostgreSQL schema is ready
    await run_column_migrations()
    await create_tables()

    # Create Redis client and store on app.state so routes can reach it
    redis_client: aioredis.Redis = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        auto_close_connection_pool=False,
    )
    app.state.redis = redis_client

    # Start the stream consumer as an asyncio background task (NOT a thread)
    consumer_task: asyncio.Task = asyncio.create_task(
        run_consumer(redis_client),
        name="audit-stream-consumer",
    )
    app.state.consumer_task = consumer_task
    logger.info("Redis Stream consumer task started")

    # Start Kafka consumer as a background task (primary audit event source)
    kafka_task: asyncio.Task = asyncio.create_task(
        run_kafka_consumer(),
        name="kafka-audit-consumer",
    )
    app.state.kafka_task = kafka_task
    logger.info("Kafka consumer task started")

    # Start MinIO blob archiver as a background task
    archiver_task: asyncio.Task = asyncio.create_task(
        run_archiver(),
        name="blob-archiver",
    )
    app.state.archiver_task = archiver_task
    logger.info("Blob archiver task started")

    yield

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    logger.info("audit-service shutting down")

    # Cancel the consumer and wait for it to finish cleanly
    consumer_task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(consumer_task), timeout=10.0)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass

    # Cancel Kafka consumer
    if hasattr(app.state, "kafka_task"):
        app.state.kafka_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(app.state.kafka_task), timeout=10.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # Cancel blob archiver
    if hasattr(app.state, "archiver_task"):
        app.state.archiver_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(app.state.archiver_task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # Close Redis connection pool
    await redis_client.aclose()
    logger.info("Redis connection closed")

    # Dispose SQLAlchemy engine
    await dispose_engine()
    logger.info("audit-service shutdown complete")


app = FastAPI(
    title="Audit Service",
    description="Consumes audit events from Redis Streams and exposes query / cost-metering APIs.",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(audit_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["ops"])
async def health():
    return {"status": "ok", "service": "audit"}


# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
@app.get("/metrics", tags=["ops"], include_in_schema=False)
async def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
