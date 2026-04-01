"""
LangGraph node implementations for the AI agent.

Each node is an async function that takes an AgentState and returns
a dict of state updates to be merged into the current state.
"""
import json
import logging
import re
import time
from typing import Optional

from app.agent.state import AgentState
from app.agent.tools import call_tool_endpoint
from app.config import settings
from app.services.config_client import ConfigClient
from app.services.llm import get_llm_client
from app.services.memory_client import MemoryClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singletons created lazily so tests can override them
# ---------------------------------------------------------------------------
_config_client: Optional[ConfigClient] = None
_memory_client: Optional[MemoryClient] = None


def _get_config_client() -> ConfigClient:
    global _config_client
    if _config_client is None:
        _config_client = ConfigClient()
    return _config_client


def _get_memory_client() -> MemoryClient:
    global _memory_client
    if _memory_client is None:
        _memory_client = MemoryClient()
    return _memory_client


# ---------------------------------------------------------------------------
# Node: load_config
# ---------------------------------------------------------------------------
async def load_config_node(state: AgentState) -> dict:
    """
    Load agent configuration from agent-config-service.
    Populates system_prompt, model, budgets, tools, and tool_configs.
    """
    agent_id = state.get("agent_id", "")
    tenant_id = state.get("tenant_id", "")

    # If config was already loaded (multi-turn continuation), skip the remote call
    if state.get("system_prompt") and state.get("model"):
        logger.debug("load_config_node: config already present, skipping fetch")
        return {"system_prompt": state.get("system_prompt", ""), "model": state.get("model", "llama3.2")}

    try:
        config = await _get_config_client().get_agent_full(agent_id, tenant_id)
    except Exception as exc:
        logger.exception("load_config_node: unexpected error fetching config for agent %s", agent_id)
        return {
            "error": f"Failed to load agent config: {exc}",
            "final_response": "Error: could not load agent configuration.",
        }

    if config is None:
        logger.warning("load_config_node: agent %s not found", agent_id)
        return {
            "error": "Agent not found",
            "final_response": "Error: agent configuration not found.",
        }

    # The config-service returns {"agent": {...}, "tools": [...]}
    agent_data = config.get("agent", config)  # fall back to flat config for backwards compat
    raw_tools: list = config.get("tools", [])

    # Build OpenAI tool schemas and tool_configs map
    available_tools = []
    tool_configs: dict = {}

    for tool in raw_tools:
        available_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
        )
        tool_configs[tool["name"]] = {
            "endpoint_url": tool.get("endpoint_url", ""),
            "http_method": tool.get("http_method", "POST"),
            "auth_type": tool.get("auth_type", "none"),
            "auth_config": tool.get("auth_config", {}),
        }

    return {
        "system_prompt": agent_data.get("system_prompt", "You are a helpful AI assistant."),
        "model": agent_data.get("model", "llama3.2"),
        "max_steps": agent_data.get("max_steps", 10),
        "token_budget": agent_data.get("token_budget", 4096),
        "session_timeout_seconds": agent_data.get("session_timeout_seconds", 300),
        "memory_enabled": agent_data.get("memory_enabled", False),
        "available_tools": available_tools,
        "tool_configs": tool_configs,
    }


# ---------------------------------------------------------------------------
# Node: retrieve_memory
# ---------------------------------------------------------------------------
async def retrieve_memory_node(state: AgentState) -> dict:
    """
    Retrieve relevant memories from the memory service and prepend as context.
    Only runs when memory is enabled and there are messages to query against.
    """
    messages = list(state.get("messages", []))

    if not state.get("memory_enabled", False):
        return {"messages": messages}

    if not messages:
        return {"messages": messages}

    # Use the last user message as the retrieval query
    query: Optional[str] = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            query = msg.get("content", "")
            break

    if not query:
        return {"messages": messages}

    tenant_id = state.get("tenant_id", "")
    session_id = state.get("session_id", "")

    try:
        memories = await _get_memory_client().retrieve(
            tenant_id=tenant_id,
            session_id=session_id,
            query=query,
            top_k=5,
        )
    except Exception as exc:
        logger.warning("retrieve_memory_node: memory retrieval failed: %s", exc)
        return {"messages": messages}

    if not memories:
        return {"messages": messages}

    # Build context string from memories
    context_parts = []
    for mem in memories:
        content = mem.get("content", "")
        if content:
            context_parts.append(content)

    if not context_parts:
        return {"messages": messages}

    context_text = "\n".join(context_parts)
    memory_message = {
        "role": "system",
        "content": f"Relevant context from memory:\n{context_text}",
    }

    # Prepend before the first non-system message
    updated_messages = [memory_message] + list(messages)
    return {"messages": updated_messages}


# ---------------------------------------------------------------------------
# Node: call_llm
# ---------------------------------------------------------------------------
async def call_llm_node(state: AgentState) -> dict:
    """
    Call the Ollama LLM via the OpenAI-compatible API.
    Builds the full message list, sends the request, and appends the assistant reply.
    """
    system_prompt = state.get("system_prompt", "You are a helpful AI assistant.")
    model = state.get("model", "llama3")
    messages = list(state.get("messages", []))
    available_tools = state.get("available_tools", [])
    token_count = state.get("token_count", 0)

    # Build the full conversation: system + history
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    client = get_llm_client()

    try:
        kwargs: dict = {
            "model": model,
            "messages": full_messages,
        }
        if available_tools:
            kwargs["tools"] = available_tools
            kwargs["tool_choice"] = "auto"

        response = await client.chat.completions.create(**kwargs)

        # Track token usage
        usage = getattr(response, "usage", None)
        if usage and hasattr(usage, "total_tokens") and usage.total_tokens:
            new_tokens = usage.total_tokens
        else:
            # Rough estimation when usage is not available
            all_text = " ".join(
                m.get("content", "") for m in full_messages if isinstance(m.get("content"), str)
            )
            new_tokens = len(all_text.split()) + 50  # approximate

        token_count += new_tokens

        # Convert the response choice into a dict for our state
        choice = response.choices[0]
        assistant_msg: dict = {"role": "assistant"}

        if choice.message.content:
            assistant_msg["content"] = choice.message.content
        else:
            assistant_msg["content"] = None

        # Preserve tool calls in serialisable form
        if choice.message.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ]

        messages.append(assistant_msg)

        return {
            "messages": messages,
            "token_count": token_count,
        }

    except Exception as exc:
        logger.exception("call_llm_node: LLM call failed for model %s", model)
        error_msg = f"LLM error: {exc}"
        return {
            "error": error_msg,
            "final_response": f"I'm sorry, I encountered an error processing your request. Please try again later.",
        }


# ---------------------------------------------------------------------------
# Node: execute_tool
# ---------------------------------------------------------------------------
async def execute_tool_node(state: AgentState) -> dict:
    """
    Execute all tool calls from the last assistant message.
    Appends tool result messages and increments step_count.
    """
    messages = list(state.get("messages", []))
    tool_configs = state.get("tool_configs", {})
    step_count = state.get("step_count", 0)

    if not messages:
        return {"step_count": step_count + 1}

    last_msg = messages[-1]
    if last_msg.get("role") != "assistant":
        return {"step_count": step_count + 1}

    tool_calls = last_msg.get("tool_calls", [])
    if not tool_calls:
        return {"step_count": step_count + 1}

    for tool_call in tool_calls:
        tool_call_id = tool_call.get("id", "")
        function_info = tool_call.get("function", {})
        tool_name = function_info.get("name", "")
        arguments_str = function_info.get("arguments", "{}")

        # Parse arguments
        try:
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
        except json.JSONDecodeError:
            arguments = {}

        # Look up tool config
        tool_config = tool_configs.get(tool_name)
        if tool_config is None:
            result_content = f"Error: tool '{tool_name}' is not configured"
        else:
            result_content = await call_tool_endpoint(
                tool_name=tool_name,
                tool_config=tool_config,
                arguments=arguments,
                timeout=30.0,
            )

        tool_result_msg = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": result_content,
        }
        messages.append(tool_result_msg)

        logger.debug(
            "execute_tool_node: tool=%s, call_id=%s, result_len=%d",
            tool_name,
            tool_call_id,
            len(result_content),
        )

    step_count += 1
    return {"messages": messages, "step_count": step_count}


# ---------------------------------------------------------------------------
# Node: check_budget
# ---------------------------------------------------------------------------
async def check_budget_node(state: AgentState) -> dict:
    """
    Enforce step, token, and time budgets.
    Sets budget_exceeded=True with a reason if any limit is crossed.
    """
    step_count = state.get("step_count", 0)
    max_steps = state.get("max_steps", 10)
    token_count = state.get("token_count", 0)
    token_budget = state.get("token_budget", 4096)
    start_time = state.get("start_time", time.time())
    session_timeout_seconds = state.get("session_timeout_seconds", 300)

    if step_count >= max_steps:
        logger.info(
            "check_budget_node: max_steps reached (steps=%d, max=%d)", step_count, max_steps
        )
        return {
            "budget_exceeded": True,
            "budget_reason": f"max_steps reached ({step_count}/{max_steps})",
            "final_response": f"I've reached the maximum number of reasoning steps ({max_steps}). Here is what I have so far.",
        }

    if token_count >= token_budget:
        logger.info(
            "check_budget_node: token budget exhausted (tokens=%d, budget=%d)",
            token_count,
            token_budget,
        )
        return {
            "budget_exceeded": True,
            "budget_reason": f"token budget exhausted ({token_count}/{token_budget})",
            "final_response": "I've used the available token budget for this session.",
        }

    elapsed = time.time() - start_time
    if elapsed > session_timeout_seconds:
        logger.info(
            "check_budget_node: session timeout (elapsed=%.1fs, limit=%ds)",
            elapsed,
            session_timeout_seconds,
        )
        return {
            "budget_exceeded": True,
            "budget_reason": f"session timeout ({elapsed:.1f}s > {session_timeout_seconds}s)",
            "final_response": "The session has timed out. Please start a new session to continue.",
        }

    return {"budget_exceeded": False}


# ---------------------------------------------------------------------------
# Node: apply_guardrails
# ---------------------------------------------------------------------------
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD_PATTERN = re.compile(r"\b\d{4}[- ]\d{4}[- ]\d{4}[- ]\d{4}\b")
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")


def _redact_pii(text: str) -> str:
    """Apply PII redaction patterns to the text."""
    text = _SSN_PATTERN.sub("[REDACTED-SSN]", text)
    text = _CREDIT_CARD_PATTERN.sub("[REDACTED-CC]", text)
    return text


async def apply_guardrails_node(state: AgentState) -> dict:
    """
    Apply safety guardrails to the assistant's last response.
    Redacts PII patterns (SSN, credit card numbers).
    Sets final_response to the cleaned content.
    """
    messages = list(state.get("messages", []))

    # Find the last assistant message
    last_assistant_idx: Optional[int] = None
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            last_assistant_idx = i
            break

    if last_assistant_idx is None:
        # No assistant message yet — surface the error or a default
        return {"final_response": state.get("error") or "No response generated."}

    last_msg = messages[last_assistant_idx]
    content = last_msg.get("content") or ""

    if not isinstance(content, str):
        # Content can be None when tool_calls are pending
        content = ""

    cleaned_content = _redact_pii(content)

    # Update the message in place with the cleaned content
    updated_msg = dict(last_msg)
    updated_msg["content"] = cleaned_content
    messages[last_assistant_idx] = updated_msg

    return {
        "final_response": cleaned_content,
        "messages": messages,
    }


# ---------------------------------------------------------------------------
# Node: route_to_agent
# ---------------------------------------------------------------------------
async def route_to_agent_node(state: AgentState) -> dict:
    """
    Publish an agent-routing event to the Redis Stream and set final_response.
    The Redis client is injected via the state key '_redis' at runtime.
    """
    import json as _json
    from datetime import datetime

    redis_client = state.get("_redis")  # type: ignore[assignment]
    target_agent_id = state.get("route_to_agent_id", "")
    route_message = state.get("route_message", "")
    tenant_id = state.get("tenant_id", "")
    session_id = state.get("session_id", "")

    event_data = {
        "tenant_id": tenant_id,
        "source_session_id": session_id,
        "target_agent_id": target_agent_id,
        "message": route_message,
        "timestamp": datetime.utcnow().isoformat(),
    }

    if redis_client is not None:
        try:
            await redis_client.xadd("agent:routing", {k: str(v) for k, v in event_data.items()})
            logger.info(
                "route_to_agent_node: published routing event for session=%s -> agent=%s",
                session_id,
                target_agent_id,
            )
        except Exception as exc:
            logger.warning("route_to_agent_node: failed to publish routing event: %s", exc)
    else:
        logger.warning("route_to_agent_node: no Redis client available, routing event not published")

    final_response = f"Task routed to specialist agent {target_agent_id}"
    return {"final_response": final_response}
