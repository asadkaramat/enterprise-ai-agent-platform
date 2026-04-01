"""
HTTP client for the memory-service.

Handles short-term (conversation) and long-term (vector) memory operations.
"""
import logging
from typing import List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class MemoryClient:
    """Async client for the memory-service API."""

    def __init__(self) -> None:
        self._base_url = settings.MEMORY_SERVICE_URL
        self._timeout = httpx.Timeout(10.0, connect=5.0)

    def _headers(self, tenant_id: str) -> dict:
        return {
            "X-Tenant-ID": str(tenant_id),
            "Content-Type": "application/json",
        }

    async def retrieve(
        self,
        tenant_id: str,
        session_id: str,
        query: str,
        top_k: int = 5,
    ) -> List[dict]:
        """
        Retrieve relevant memories for a query.

        Returns a list of memory dicts (with at minimum a 'content' key),
        or an empty list on any error.
        """
        url = f"{self._base_url}/memory/retrieve"
        payload = {
            "session_id": session_id,
            "query": query,
            "top_k": top_k,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=self._headers(tenant_id),
                )
                response.raise_for_status()
                data = response.json()

                # Support both {"memories": [...]} and direct list responses
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return data.get("memories", data.get("results", []))
                return []

        except httpx.TimeoutException:
            logger.warning("retrieve: request timed out for session %s", session_id)
            return []
        except httpx.HTTPStatusError as exc:
            logger.warning("retrieve: HTTP %s for session %s", exc.response.status_code, session_id)
            return []
        except httpx.RequestError as exc:
            logger.error("retrieve: connection error for session %s: %s", session_id, exc)
            return []
        except Exception:
            logger.exception("retrieve: unexpected error for session %s", session_id)
            return []

    async def append_message(
        self,
        tenant_id: str,
        session_id: str,
        role: str,
        content: str,
    ) -> bool:
        """
        Append a message to the session's short-term memory.

        Returns True on success, False on any error.
        """
        url = f"{self._base_url}/memory/short/append"
        payload = {
            "session_id": session_id,
            "role": role,
            "content": content,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=self._headers(tenant_id),
                )
                response.raise_for_status()
                return True

        except httpx.TimeoutException:
            logger.warning("append_message: request timed out for session %s", session_id)
            return False
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "append_message: HTTP %s for session %s",
                exc.response.status_code,
                session_id,
            )
            return False
        except httpx.RequestError as exc:
            logger.error("append_message: connection error for session %s: %s", session_id, exc)
            return False
        except Exception:
            logger.exception("append_message: unexpected error for session %s", session_id)
            return False

    async def store_long_term(
        self,
        tenant_id: str,
        session_id: str,
        agent_id: str,
        content: str,
    ) -> bool:
        """
        Store content in long-term vector memory.

        Returns True on success, False on any error.
        """
        url = f"{self._base_url}/memory/long/store"
        payload = {
            "session_id": session_id,
            "agent_id": agent_id,
            "content": content,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers=self._headers(tenant_id),
                )
                response.raise_for_status()
                return True

        except httpx.TimeoutException:
            logger.warning("store_long_term: request timed out for session %s", session_id)
            return False
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "store_long_term: HTTP %s for session %s",
                exc.response.status_code,
                session_id,
            )
            return False
        except httpx.RequestError as exc:
            logger.error("store_long_term: connection error for session %s: %s", session_id, exc)
            return False
        except Exception:
            logger.exception("store_long_term: unexpected error for session %s", session_id)
            return False
