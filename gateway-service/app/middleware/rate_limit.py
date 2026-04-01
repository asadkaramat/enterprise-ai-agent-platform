import logging
import time

import redis.asyncio as aioredis
from fastapi import HTTPException

from app.config import settings
from app.metrics import rate_limit_hits_total
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis connection closed.")


async def check_rate_limit(tenant: Tenant) -> None:
    """
    Sliding-window rate limiter using Redis INCR.
    Key: ratelimit:{tenant_id}:{unix_minute}
    Raises HTTP 429 if limit exceeded.
    """
    redis = await get_redis()
    unix_minute = int(time.time()) // 60
    key = f"ratelimit:{tenant.id}:{unix_minute}"

    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 120)

        if count > tenant.rate_limit_per_minute:
            rate_limit_hits_total.labels(tenant_id=str(tenant.id)).inc()
            logger.warning(
                "Rate limit exceeded for tenant %s: %d/%d",
                tenant.id,
                count,
                tenant.rate_limit_per_minute,
            )
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {tenant.rate_limit_per_minute} requests/minute",
                headers={"Retry-After": "60"},
            )
    except HTTPException:
        raise
    except Exception as exc:
        # Redis failure: fail open (log and continue)
        logger.error("Redis rate limit check failed: %s", exc, exc_info=True)
