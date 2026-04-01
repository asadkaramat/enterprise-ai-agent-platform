import json
import logging
from datetime import datetime

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)


class ShortTermMemory:
    def __init__(self, redis: aioredis.Redis):
        self.redis = redis
        self.ttl = settings.SHORT_TERM_TTL_HOURS * 3600
        self.max_messages = settings.SHORT_TERM_MAX_MESSAGES

    def _key(self, tenant_id: str, session_id: str) -> str:
        return f"memory:short:{tenant_id}:{session_id}"

    async def append_message(
        self, tenant_id: str, session_id: str, role: str, content: str
    ) -> None:
        key = self._key(tenant_id, session_id)
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        }
        existing_raw = await self.redis.get(key)
        messages = json.loads(existing_raw) if existing_raw else []
        messages.append(message)
        if len(messages) > self.max_messages:
            messages = messages[-self.max_messages :]
        await self.redis.set(key, json.dumps(messages), ex=self.ttl)
        logger.debug(
            "Appended message for tenant=%s session=%s role=%s",
            tenant_id,
            session_id,
            role,
        )

    async def get_history(self, tenant_id: str, session_id: str) -> list:
        key = self._key(tenant_id, session_id)
        raw = await self.redis.get(key)
        return json.loads(raw) if raw else []

    async def get_context_window(
        self, tenant_id: str, session_id: str, max_messages: int = 20
    ) -> list:
        history = await self.get_history(tenant_id, session_id)
        return history[-max_messages:]

    async def clear_session(self, tenant_id: str, session_id: str) -> None:
        key = self._key(tenant_id, session_id)
        await self.redis.delete(key)
        logger.info(
            "Cleared short-term memory for tenant=%s session=%s", tenant_id, session_id
        )
