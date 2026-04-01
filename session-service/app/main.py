"""
Session-service application entry point.

Responsibilities:
  - FastAPI lifespan: DB table creation, Redis connection management
  - Router registration (sessions)
  - /health and /metrics endpoints
"""
import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import settings
from app.database import create_tables, engine
from app.routes.sessions import router as sessions_router
from app.services.audit import set_kafka_producer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- Startup ----
    logger.info("session-service: starting up")

    # Ensure DB tables exist
    try:
        await create_tables()
        logger.info("session-service: database tables verified")
    except Exception as exc:
        logger.error("session-service: DB initialisation failed: %s", exc)
        # Allow startup to continue; individual requests will fail gracefully

    # Connect to Redis
    redis_client = None
    try:
        redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        await redis_client.ping()
        app.state.redis = redis_client
        logger.info("session-service: Redis connected at %s", settings.REDIS_URL)
        from app.agent.nodes import _get_config_client
        _get_config_client().set_redis(redis_client)
    except Exception as exc:
        logger.error("session-service: Redis connection failed: %s", exc)
        app.state.redis = None
        # Redis unavailable — ConfigClient will skip cache, use HTTP only
        from app.agent.nodes import _get_config_client
        _get_config_client().set_redis(None)

    # Connect Kafka producer
    kafka_producer = None
    try:
        from aiokafka import AIOKafkaProducer
        import json as _json
        kafka_producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: _json.dumps(v).encode("utf-8"),
            request_timeout_ms=10000,
            retry_backoff_ms=500,
        )
        await kafka_producer.start()
        set_kafka_producer(kafka_producer)
        logger.info("session-service: Kafka producer connected to %s", settings.KAFKA_BOOTSTRAP_SERVERS)
    except Exception as exc:
        logger.error("session-service: Kafka producer failed to start — %s. Audit events will use Redis fallback.", exc)
        set_kafka_producer(None)

    yield

    # ---- Shutdown ----
    logger.info("session-service: shutting down")

    if kafka_producer is not None:
        try:
            await kafka_producer.stop()
            logger.info("session-service: Kafka producer stopped")
        except Exception:
            pass

    if redis_client is not None:
        await redis_client.aclose()
        logger.info("session-service: Redis connection closed")

    await engine.dispose()
    logger.info("session-service: database engine disposed")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Session Service",
    description="Core AI agent runtime with LangGraph, multi-turn sessions, and budget enforcement",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(sessions_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health(request: Request) -> dict:
    redis_ok = False
    db_ok = False

    # Check Redis
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is not None:
        try:
            await redis_client.ping()
            redis_ok = True
        except Exception:
            redis_ok = False

    # Check DB (lightweight connection test)
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    overall = "healthy" if (redis_ok and db_ok) else "degraded"

    return {
        "status": overall,
        "service": "session-service",
        "dependencies": {
            "database": "ok" if db_ok else "unavailable",
            "redis": "ok" if redis_ok else "unavailable",
        },
    }


# ---------------------------------------------------------------------------
# Prometheus metrics scrape endpoint
# ---------------------------------------------------------------------------

@app.get("/metrics", tags=["ops"])
async def metrics() -> PlainTextResponse:
    data = generate_latest()
    return PlainTextResponse(content=data, media_type=CONTENT_TYPE_LATEST)
