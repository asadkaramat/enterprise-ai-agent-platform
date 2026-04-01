"""
Tool schema helpers and tool execution utilities for the agent.
"""
import json
import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


def build_openai_tool_schema(tool: dict) -> dict:
    """Convert a raw tool definition into OpenAI function tool schema format."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


def build_tool_configs(tools: list) -> dict:
    """Build tool_name -> config dict from tool definitions."""
    configs: Dict[str, dict] = {}
    for tool in tools:
        configs[tool["name"]] = {
            "endpoint_url": tool.get("endpoint_url", ""),
            "http_method": tool.get("http_method", "POST"),
            "auth_type": tool.get("auth_type", "none"),
            "auth_config": tool.get("auth_config", {}),
        }
    return configs


async def call_tool_endpoint(
    tool_name: str,
    tool_config: dict,
    arguments: Dict[str, Any],
    timeout: float = 30.0,
) -> str:
    """
    Call a tool's HTTP endpoint with the provided arguments.
    Returns the result as a string, or an error string on failure.
    """
    endpoint_url = tool_config.get("endpoint_url", "")
    http_method = tool_config.get("http_method", "POST").upper()
    auth_type = tool_config.get("auth_type", "none")
    auth_config = tool_config.get("auth_config", {})

    if not endpoint_url:
        return f"Error: no endpoint configured for tool '{tool_name}'"

    headers: Dict[str, str] = {"Content-Type": "application/json"}

    # Apply auth if configured
    if auth_type == "bearer":
        token = auth_config.get("token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    elif auth_type == "api_key":
        header_name = auth_config.get("header_name", "X-API-Key")
        api_key = auth_config.get("api_key", "")
        if api_key:
            headers[header_name] = api_key

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if http_method == "POST":
                response = await client.post(endpoint_url, json=arguments, headers=headers)
            elif http_method == "GET":
                response = await client.get(endpoint_url, params=arguments, headers=headers)
            elif http_method == "PUT":
                response = await client.put(endpoint_url, json=arguments, headers=headers)
            elif http_method == "PATCH":
                response = await client.patch(endpoint_url, json=arguments, headers=headers)
            elif http_method == "DELETE":
                response = await client.delete(endpoint_url, params=arguments, headers=headers)
            else:
                return f"Error: unsupported HTTP method '{http_method}'"

            response.raise_for_status()

            # Try to return JSON, fall back to raw text
            try:
                result = response.json()
                return json.dumps(result)
            except Exception:
                return response.text

    except httpx.TimeoutException:
        logger.warning("Tool call to %s timed out after %ss", endpoint_url, timeout)
        return f"Error: tool call timed out after {timeout}s"
    except httpx.HTTPStatusError as exc:
        logger.warning("Tool call to %s returned HTTP %s", endpoint_url, exc.response.status_code)
        return f"Error: tool endpoint returned HTTP {exc.response.status_code}: {exc.response.text[:500]}"
    except httpx.RequestError as exc:
        logger.error("Tool call to %s failed: %s", endpoint_url, exc)
        return f"Error: could not connect to tool endpoint: {exc}"
    except Exception as exc:
        logger.exception("Unexpected error calling tool %s", tool_name)
        return f"Error: unexpected error calling tool: {exc}"
