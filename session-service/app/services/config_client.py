"""
HTTP client for the agent-config-service.

Fetches full agent configurations including system prompt, model settings,
tool definitions, and runtime limits.
"""
import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class ConfigClient:
    """Async client for the agent-config-service internal API."""

    def __init__(self) -> None:
        self._base_url = settings.AGENT_CONFIG_SERVICE_URL
        self._secret = settings.INTERNAL_SECRET
        self._timeout = httpx.Timeout(10.0, connect=5.0)

    async def get_agent_full(self, agent_id: str, tenant_id: str) -> Optional[dict]:
        """
        Fetch the full agent configuration from agent-config-service.

        Returns the parsed JSON dict on success, or None if the agent is not
        found or the request fails.

        The returned dict is expected to contain at minimum:
            system_prompt, model, max_steps, token_budget,
            session_timeout_seconds, memory_enabled, tools (list)

        Each tool in 'tools' should have:
            name, description, input_schema,
            endpoint_url, http_method, auth_type, auth_config
        """
        url = f"{self._base_url}/internal/agents/{agent_id}/full"
        headers = {
            "X-Internal-Secret": self._secret,
            "X-Tenant-ID": str(tenant_id),
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=headers)

                if response.status_code == 404:
                    logger.info("get_agent_full: agent %s not found", agent_id)
                    return None

                response.raise_for_status()
                data: dict = response.json()

        except httpx.TimeoutException:
            logger.warning("get_agent_full: request timed out for agent %s", agent_id)
            return None
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "get_agent_full: HTTP %s for agent %s",
                exc.response.status_code,
                agent_id,
            )
            return None
        except httpx.RequestError as exc:
            logger.error("get_agent_full: connection error for agent %s: %s", agent_id, exc)
            return None
        except Exception as exc:
            logger.exception("get_agent_full: unexpected error for agent %s", agent_id)
            return None

        return data

    async def agent_exists(self, agent_id: str, tenant_id: str) -> bool:
        """
        Lightweight check to verify an agent exists before creating a session.
        Falls back to True on network error to avoid blocking session creation.
        """
        config = await self.get_agent_full(agent_id, tenant_id)
        return config is not None
