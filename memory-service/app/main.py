import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.config import settings
from app.routes.memory import router as memory_router
from app.services.long_term import LongTermMemory
from app.services.short_term import ShortTermMemory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ------------------------------------------------------------------ startup
    logger.info("Starting memory-service — connecting to Redis at %s", settings.REDIS_URL)
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    # Verify Redis is reachable
    await redis_client.ping()
    logger.info("Redis connection established.")

    logger.info(
        "Loading embedding model '%s' and connecting to Qdrant at %s",
        settings.EMBEDDING_MODEL,
        settings.QDRANT_URL,
    )
    long_term = LongTermMemory()
    short_term = ShortTermMemory(redis=redis_client)

    app.state.redis = redis_client
    app.state.long_term = long_term
    app.state.short_term = short_term

    logger.info("memory-service startup complete.")
    yield

    # ----------------------------------------------------------------- shutdown
    logger.info("Shutting down memory-service — closing Redis connection.")
    await redis_client.aclose()
    logger.info("Redis connection closed.")


app = FastAPI(
    title="Memory Service",
    description=(
        "Two-layer memory for enterprise AI agents: "
        "short-term (Redis, session-scoped, 24 h TTL) and "
        "long-term (Qdrant vector store, tenant-scoped, semantic search)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(memory_router)


@app.get("/health", tags=["ops"])
async def health():
    """Liveness / readiness probe."""
    redis_ok = False
    qdrant_ok = False

    try:
        await app.state.redis.ping()
        redis_ok = True
    except Exception as exc:
        logger.warning("Health check — Redis ping failed: %s", exc)

    try:
        # A lightweight Qdrant check: list collections (synchronous, run in executor)
        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, app.state.long_term.client.get_collections)
        qdrant_ok = True
    except Exception as exc:
        logger.warning("Health check — Qdrant unreachable: %s", exc)

    status = "ok" if (redis_ok and qdrant_ok) else "degraded"
    return {
        "status": status,
        "redis": "ok" if redis_ok else "unavailable",
        "qdrant": "ok" if qdrant_ok else "unavailable",
    }


@app.get("/metrics", tags=["ops"])
async def metrics():
    """Prometheus metrics endpoint."""
    data = generate_latest()
    return PlainTextResponse(content=data, media_type=CONTENT_TYPE_LATEST)
