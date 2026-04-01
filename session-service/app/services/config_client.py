"""
HTTP client for the agent-config-service — with Redis cache-aside and circuit breaker.

Resolution order for get_agent_full():
  1. Redis snapshot key: config:snapshot:{tenant_id}:{agent_id}  (TTL 600s)
     Published by agent-config-service after every config build.
     Invalidated by agent-config-service on agent/tool mutations.
  2. HTTP call to /internal/agents/{agent_id}/full  (circuit-breaker protected)

This means session-service is fully independent of agent-config-service at
runtime once a snapshot is warm. The HTTP path only fires on:
  - Cold start (first session for an agent)
  - After a config mutation forces invalidation
  - After the 10-minute TTL expires

Circuit breaker: 3 consecutive HTTP failures → open (60s cooldown) → half-open probe.
"""
import json
import logging
import time
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Redis key for published config snapshots (written by agent-config-service)
_SNAPSHOT_TTL = 600  # seconds — must match config_publisher._TTL_SNAPSHOT


def _snapshot_key(tenant_id: str, agent_id: str) -> str:
    return f"config:snapshot:{tenant_id}:{agent_id}"


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class _CircuitBreaker:
    """Simple per-instance circuit breaker for the HTTP config fetch path."""

    FAILURE_THRESHOLD = 3
    COOLDOWN_SECONDS = 60.0

    def __init__(self) -> None:
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at >= self.COOLDOWN_SECONDS:
            # Half-open: allow one probe
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.FAILURE_THRESHOLD:
            self._opened_at = time.monotonic()
            logger.warning(
                "config_client: circuit breaker OPEN after %d failures — "
                "HTTP fallback disabled for %ds",
                self._failures,
                self.COOLDOWN_SECONDS,
            )


# ---------------------------------------------------------------------------
# ConfigClient
# ---------------------------------------------------------------------------

class ConfigClient:
    """Async client for agent config — Redis-first, HTTP fallback."""

    def __init__(self) -> None:
        self._base_url = settings.AGENT_CONFIG_SERVICE_URL
        self._secret = settings.INTERNAL_SECRET
        self._timeout = httpx.Timeout(10.0, connect=5.0)
        self._breaker = _CircuitBreaker()
        self._redis: Any = None

    def set_redis(self, redis_client: Any) -> None:
        """Called once at startup after the Redis connection is established."""
        self._redis = redis_client

    # ---- Redis cache helpers -----------------------------------------------

    async def _read_snapshot(self, tenant_id: str, agent_id: str) -> Optional[dict]:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(_snapshot_key(tenant_id, agent_id))
            if raw is None:
                return None
            data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            logger.debug("config_client: snapshot cache HIT for agent %s", agent_id)
            return data
        except Exception as exc:
            logger.debug("config_client._read_snapshot: %s", exc)
            return None

    async def _write_snapshot(self, tenant_id: str, agent_id: str, data: dict) -> None:
        """Back-fill the snapshot after a successful HTTP fetch (warm for next caller)."""
        if self._redis is None:
            return
        try:
            await self._redis.set(
                _snapshot_key(tenant_id, agent_id),
                json.dumps(data),
                ex=_SNAPSHOT_TTL,
            )
        except Exception as exc:
            logger.debug("config_client._write_snapshot: %s", exc)

    # ---- HTTP fallback -------------------------------------------------------

    async def _fetch_via_http(self, agent_id: str, tenant_id: str) -> Optional[dict]:
        """Call the internal HTTP endpoint. Returns None on any failure."""
        if self._breaker.is_open:
            logger.warning(
                "config_client: circuit breaker is OPEN — skipping HTTP fetch for agent %s",
                agent_id,
            )
            return None

        url = f"{self._base_url}/internal/agents/{agent_id}/full"
        headers = {
            "X-Internal-Secret": self._secret,
            "X-Tenant-ID": str(tenant_id),
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=headers)

                if response.status_code == 404:
                    logger.info("config_client: agent %s not found (404)", agent_id)
                    # 404 is a definitive answer — don't count as circuit-breaker failure
                    return None

                response.raise_for_status()
                data: dict = response.json()
                self._breaker.record_success()
                return data

        except httpx.TimeoutException:
            logger.warning("config_client: HTTP timeout for agent %s", agent_id)
            self._breaker.record_failure()
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "config_client: HTTP %s for agent %s",
                exc.response.status_code,
                agent_id,
            )
            self._breaker.record_failure()
            return None
        except httpx.RequestError as exc:
            logger.error("config_client: connection error for agent %s: %s", agent_id, exc)
            self._breaker.record_failure()
            return None
        except Exception:
            logger.exception("config_client: unexpected error for agent %s", agent_id)
            self._breaker.record_failure()
            return None

    # ---- Public API ---------------------------------------------------------

    async def get_agent_full(self, agent_id: str, tenant_id: str) -> Optional[dict]:
        """
        Fetch the full agent configuration.

        Resolution order:
          1. Redis snapshot (config:snapshot:{tenant_id}:{agent_id})
          2. HTTP call to agent-config-service (circuit-breaker protected)

        Returns the parsed config dict, or None if not found / unavailable.
        """
        # 1. Try Redis snapshot first
        snapshot = await self._read_snapshot(tenant_id, agent_id)
        if snapshot is not None:
            return snapshot

        # 2. HTTP fallback
        data = await self._fetch_via_http(agent_id, tenant_id)
        if data is not None:
            # Back-fill snapshot for next caller
            await self._write_snapshot(tenant_id, agent_id, data)

        return data

    async def agent_exists(self, agent_id: str, tenant_id: str) -> bool:
        """
        Lightweight check to verify an agent exists before creating a session.
        Falls back to True on network error to avoid blocking session creation.
        """
        config = await self.get_agent_full(agent_id, tenant_id)
        # config is None only on definitive 404 or complete unavailability
        # On unavailability, fail-open (True) so session DB row can be created
        if config is None and not self._breaker.is_open:
            # Definitive miss (404) — agent doesn't exist
            return False
        if config is None:
            # Circuit open or network error — fail-open
            logger.warning(
                "config_client: agent_exists fail-open for agent %s (circuit open or error)",
                agent_id,
            )
            return True
        return True
