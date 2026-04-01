"""
LangGraph node implementations for the AI agent.

Each node is an async function that takes an AgentState and returns
a dict of state updates to be merged into the current state.
"""
import fnmatch
import hashlib
import json
import logging
import re
import time
from typing import Optional
from urllib.parse import urlparse

from app.agent.state import AgentState
from app.agent.tools import call_tool_endpoint
from app.config import settings
from app.services.config_client import ConfigClient
from app.services.llm import get_llm_router
from app.services.memory_client import MemoryClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Context Assembler — priority-ordered prompt construction with token trimming
# ---------------------------------------------------------------------------
# Token budget safety margin: 8% reserved so the assembled prompt never
# lands right on the model's hard context limit.
_SAFETY_MARGIN = 0.08
# Number of most-recent non-system messages always kept at highest priority.
_RECENT_WINDOW = 10  # ~5 turns of user/assistant pairs


def _estimate_tokens(text: str) -> int:
    """
    Rough token estimate: 1 token ≈ 4 characters.
    Good enough for budget enforcement without a full tokeniser dependency.
    """
    return max(1, len(str(text)) // 4)


def _msg_tokens(msg: dict) -> int:
    """Estimate token cost of a single message dict (content + per-message overhead)."""
    content = msg.get("content") or ""
    if isinstance(content, list):
        content = " ".join(str(c) for c in content)
    tool_calls_str = ""
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        tool_calls_str += fn.get("name", "") + fn.get("arguments", "")
    return _estimate_tokens(content + tool_calls_str) + 4  # 4-token per-message overhead


def _assemble_prompt_with_budget(
    system_prompt: str,
    messages: list,
    token_budget: int,
) -> list:
    """
    Build the full message list with priority-ordered trimming.

    Priority (highest = trimmed last):
      1. system_prompt        — never trimmed
      2. recent conversation  — last RECENT_WINDOW non-system messages
      3. memory messages      — system-role messages injected by retrieve_memory_node
      4. older conversation   — everything beyond the recent window

    When the total prompt exceeds (token_budget * (1 - SAFETY_MARGIN)), the
    lowest-priority groups are dropped first, message by message, until it fits.
    """
    hard_limit = int(token_budget * (1 - _SAFETY_MARGIN))

    # Separate memory context (system role) from the conversation
    memory_msgs = [m for m in messages if m.get("role") == "system"]
    conv_msgs = [m for m in messages if m.get("role") != "system"]

    recent_msgs = conv_msgs[-_RECENT_WINDOW:]
    older_msgs = conv_msgs[:-_RECENT_WINDOW] if len(conv_msgs) > _RECENT_WINDOW else []

    # System prompt is always first and never trimmed
    result = [{"role": "system", "content": system_prompt}]
    budget = hard_limit - _estimate_tokens(system_prompt) - 4

    # --- Priority 1: recent conversation ---
    recent_tokens = sum(_msg_tokens(m) for m in recent_msgs)
    if recent_tokens > budget:
        # Even recent history is too large — keep the newest messages that fit
        kept: list = []
        remaining = budget
        for msg in reversed(recent_msgs):
            t = _msg_tokens(msg)
            if t <= remaining:
                kept.insert(0, msg)
                remaining -= t
            else:
                break
        logger.debug(
            "_assemble_prompt: recent msgs trimmed %d -> %d (token budget %d)",
            len(recent_msgs), len(kept), token_budget,
        )
        return result + kept

    budget -= recent_tokens

    # --- Priority 2: memory system messages ---
    kept_memory: list = []
    for msg in memory_msgs:
        t = _msg_tokens(msg)
        if t <= budget:
            kept_memory.append(msg)
            budget -= t

    # --- Priority 3: older conversation ---
    kept_older: list = []
    for msg in older_msgs:
        t = _msg_tokens(msg)
        if t <= budget:
            kept_older.append(msg)
            budget -= t

    if len(kept_older) < len(older_msgs):
        logger.debug(
            "_assemble_prompt: older msgs trimmed %d -> %d to fit token budget",
            len(older_msgs), len(kept_older),
        )

    return result + kept_older + kept_memory + recent_msgs


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
            "tool_id": tool.get("tool_id", ""),
            "endpoint_url": tool.get("endpoint_url", ""),
            "http_method": tool.get("http_method", "POST"),
            "auth_type": tool.get("auth_type", "none"),
            "auth_config": tool.get("auth_config", {}),
            "parameter_constraints": tool.get("parameter_constraints", {}),
            "max_calls_per_turn": tool.get("max_calls_per_turn"),
            "is_cacheable": tool.get("is_cacheable", False),
            "cache_ttl_seconds": tool.get("cache_ttl_seconds", 300),
        }

    egress_allowlist: list = config.get("egress_allowlist", [])

    # Compute prompt prefix cache key (tenant-scoped, system_prompt + tool schema hash)
    prefix_material = str(agent_data.get("tenant_id", "")) + agent_data.get("system_prompt", "") + ",".join(sorted(t["name"] for t in raw_tools))
    prompt_cache_key = hashlib.sha256(prefix_material.encode()).hexdigest()

    # Prompt prefix cache: mark as seen in Redis (signal for future prompt caching)
    redis_client_lc = state.get("_redis")
    if redis_client_lc is not None:
        try:
            pc_key = f"{tenant_id}:prompt_cache:{prompt_cache_key}"
            await redis_client_lc.set(pc_key, "1", ex=3600, nx=True)
        except Exception:
            pass

    guardrail_policies: list = config.get("guardrail_policies", [])

    return {
        "system_prompt": agent_data.get("system_prompt", "You are a helpful AI assistant."),
        "model": agent_data.get("model", "llama3.2"),
        "max_steps": agent_data.get("max_steps", 10),
        "token_budget": agent_data.get("token_budget", 4096),
        "session_timeout_seconds": agent_data.get("session_timeout_seconds", 300),
        "memory_enabled": agent_data.get("memory_enabled", False),
        "available_tools": available_tools,
        "tool_configs": tool_configs,
        "tool_call_counts": {},
        "egress_allowlist": egress_allowlist,
        "prompt_cache_key": prompt_cache_key,
        "guardrail_policies": guardrail_policies,
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
    Call the LLM via the router (retry + fallback + circuit breaking).

    Responsibilities:
      1. Context assembly — builds the prompt with priority-ordered token
         trimming so the prompt never exceeds the model's context window.
      2. Per-tenant LLM rate limiting — enforces requests/min via Redis.
      3. Malformed response handling — if the LLM returns neither content
         nor tool calls, appends a correction prompt and retries once.
    """
    system_prompt = state.get("system_prompt", "You are a helpful AI assistant.")
    model = state.get("model", "llama3")
    messages = list(state.get("messages", []))
    available_tools = state.get("available_tools", [])
    token_count = state.get("token_count", 0)
    tenant_id = state.get("tenant_id", "")
    token_budget = state.get("token_budget", 4096)

    # --- 1. Context Assembly ---
    full_messages = _assemble_prompt_with_budget(system_prompt, messages, token_budget)

    # --- 2. Per-tenant LLM rate limiting ---
    redis_client = state.get("_redis")
    if redis_client is not None:
        rate_key = f"ratelimit:llm:{tenant_id}:minute"
        try:
            count = await redis_client.incr(rate_key)
            if count == 1:
                await redis_client.expire(rate_key, 60)
            if count > settings.MAX_LLM_REQUESTS_PER_MINUTE:
                logger.warning(
                    "call_llm_node: tenant %s exceeded LLM rate limit (%d rpm)",
                    tenant_id, count,
                )
                return {
                    "error": "tenant_rate_limit_exceeded",
                    "final_response": (
                        "Your request was rate-limited. Please wait a moment and try again."
                    ),
                }
        except Exception as exc:
            logger.debug("call_llm_node: rate limit check failed (non-fatal): %s", exc)

    router = get_llm_router()

    try:
        response = await router.complete(
            model=model,
            messages=full_messages,
            tools=available_tools if available_tools else None,
        )

        # Track token usage
        usage = getattr(response, "usage", None)
        if usage and hasattr(usage, "total_tokens") and usage.total_tokens:
            new_tokens = usage.total_tokens
        else:
            # Rough estimate when provider omits usage
            all_text = " ".join(
                m.get("content", "") for m in full_messages if isinstance(m.get("content"), str)
            )
            new_tokens = len(all_text.split()) + 50

        token_count += new_tokens

        choice = response.choices[0]

        # --- 3. Malformed response handling ---
        # A malformed response has neither text content nor tool calls.
        # Retry once with a correction prompt before surfacing an error.
        if not choice.message.content and not choice.message.tool_calls:
            logger.warning(
                "call_llm_node: empty response from model '%s', retrying with correction", model
            )
            correction_messages = full_messages + [
                {"role": "assistant", "content": ""},
                {
                    "role": "user",
                    "content": (
                        "Your previous response was empty. "
                        "Please provide a complete text response or use one of the available tools."
                    ),
                },
            ]
            try:
                retry_resp = await router.complete(
                    model=model,
                    messages=correction_messages,
                    tools=available_tools if available_tools else None,
                )
                choice = retry_resp.choices[0]
                retry_usage = getattr(retry_resp, "usage", None)
                if retry_usage and retry_usage.total_tokens:
                    token_count += retry_usage.total_tokens
            except Exception:
                pass  # fall through — handled below if still empty

        if not choice.message.content and not choice.message.tool_calls:
            logger.error("call_llm_node: LLM produced empty response after correction retry")
            return {
                "error": "malformed_llm_response",
                "final_response": (
                    "I was unable to generate a response. Please try rephrasing your request."
                ),
                "token_count": token_count,
            }

        # Build the assistant message dict
        assistant_msg: dict = {"role": "assistant"}
        assistant_msg["content"] = choice.message.content or None

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

        # Publish LLM usage event to audit stream (EP_F13 cost attribution)
        redis_for_audit = state.get("_redis")
        if redis_for_audit is not None:
            try:
                await redis_for_audit.xadd(
                    "audit:events",
                    {
                        "event_type": "llm_usage",
                        "tenant_id": tenant_id,
                        "session_id": state.get("session_id", ""),
                        "agent_id": state.get("agent_id", ""),
                        "model": model,
                        "prompt_tokens": str(new_tokens),
                        "completion_tokens": "0",
                        "timestamp": str(time.time()),
                    },
                )
            except Exception:
                pass  # non-fatal

        return {
            "messages": messages,
            "token_count": token_count,
        }

    except Exception as exc:
        logger.exception("call_llm_node: LLM call failed for model %s", model)
        return {
            "error": f"LLM error: {exc}",
            "final_response": "I'm sorry, I encountered an error processing your request. Please try again later.",
        }


# ---------------------------------------------------------------------------
# Node: execute_tool
# ---------------------------------------------------------------------------
async def execute_tool_node(state: AgentState) -> dict:
    """
    Execute all tool calls from the last assistant message.
    Appends tool result messages and increments step_count.

    Pre-flight checks (fail-fast before calling the remote endpoint):
      - max_calls_per_turn: deny if the tool has already been called the
        allowed number of times this turn.
      - parameter_constraints: deny if any argument violates enum/max/min/
        allowed_prefixes/pattern constraints from the tool binding.
    """
    messages = list(state.get("messages", []))
    tool_configs = state.get("tool_configs", {})
    step_count = state.get("step_count", 0)
    tool_call_counts: dict = dict(state.get("tool_call_counts") or {})
    egress_allowlist: list = state.get("egress_allowlist") or []
    tenant_id: str = state.get("tenant_id", "")
    redis_client = state.get("_redis")

    if not messages:
        return {"step_count": step_count + 1, "tool_call_counts": tool_call_counts}

    last_msg = messages[-1]
    if last_msg.get("role") != "assistant":
        return {"step_count": step_count + 1, "tool_call_counts": tool_call_counts}

    tool_calls = last_msg.get("tool_calls", [])
    if not tool_calls:
        return {"step_count": step_count + 1, "tool_call_counts": tool_call_counts}

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
            # ── Tool result cache check ────────────────────────────────────
            is_cacheable = tool_config.get("is_cacheable", False)
            cache_ttl = tool_config.get("cache_ttl_seconds", 300)
            tool_cache_key = None
            if is_cacheable and redis_client is not None:
                param_hash = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()
                tool_cache_key = f"{tenant_id}:tool_result:{tool_name}:{param_hash}"
                try:
                    cached_result = await redis_client.get(tool_cache_key)
                    if cached_result is not None:
                        cached_str = cached_result.decode() if isinstance(cached_result, bytes) else cached_result
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": cached_str,
                        })
                        continue
                except Exception as exc:
                    logger.debug("execute_tool_node: tool cache get failed: %s", exc)

            # ── Pre-flight 1: max_calls_per_turn ──────────────────────────
            max_calls = tool_config.get("max_calls_per_turn")
            current_calls = tool_call_counts.get(tool_name, 0)
            if max_calls is not None and current_calls >= max_calls:
                result_content = (
                    f"Error: tool '{tool_name}' has reached its call limit "
                    f"of {max_calls} call(s) per turn."
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result_content,
                })
                continue

            # ── Pre-flight 2: parameter_constraints ───────────────────────
            constraints = tool_config.get("parameter_constraints") or {}
            constraint_denial = _check_parameter_constraints(tool_name, arguments, constraints)
            if constraint_denial is not None:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": constraint_denial,
                })
                continue

            # ── Pre-flight 3: per-tenant tool-call rate limiting ──────────
            tool_id = tool_config.get("tool_id", "")
            if redis_client is not None and tool_id:
                rate_key = f"{tenant_id}:ratelimit:tool:{tool_id}:minute"
                try:
                    count = await redis_client.incr(rate_key)
                    if count == 1:
                        await redis_client.expire(rate_key, 60)
                    if count > settings.MAX_TOOL_CALLS_PER_MINUTE:
                        result_content = (
                            f"Error: tool '{tool_name}' has exceeded its rate limit "
                            f"of {settings.MAX_TOOL_CALLS_PER_MINUTE} calls/minute for this tenant."
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": result_content,
                        })
                        continue
                except Exception as exc:
                    logger.debug("execute_tool_node: tool rate limit check failed (non-fatal): %s", exc)

            # ── Pre-flight 4: egress allowlist validation ─────────────────
            endpoint_url = tool_config.get("endpoint_url", "")
            if egress_allowlist and endpoint_url:
                if not _url_allowed_by_egress(endpoint_url, egress_allowlist):
                    result_content = (
                        f"Error: tool '{tool_name}' endpoint '{endpoint_url}' "
                        f"is blocked by the tenant egress allowlist."
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": result_content,
                    })
                    continue

            # ── Call the tool endpoint ────────────────────────────────────
            result_content = await call_tool_endpoint(
                tool_name=tool_name,
                tool_config=tool_config,
                arguments=arguments,
                timeout=30.0,
            )
            tool_call_counts[tool_name] = current_calls + 1

            # Store result in cache if tool is cacheable
            if is_cacheable and tool_cache_key is not None and redis_client is not None:
                try:
                    await redis_client.set(tool_cache_key, result_content, ex=cache_ttl)
                except Exception as exc:
                    logger.debug("execute_tool_node: tool cache set failed: %s", exc)

        # Enforce response size limit — large tool responses waste the token budget
        # and can push the prompt over the model's context window.
        max_bytes = settings.MAX_TOOL_RESPONSE_BYTES
        encoded = result_content.encode("utf-8", errors="replace")
        if len(encoded) > max_bytes:
            result_content = encoded[:max_bytes].decode("utf-8", errors="replace")
            result_content += "\n[Response truncated — exceeded 100 KB limit]"
            logger.debug(
                "execute_tool_node: tool=%s response truncated to %d bytes",
                tool_name, max_bytes,
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
    return {"messages": messages, "step_count": step_count, "tool_call_counts": tool_call_counts}


# ---------------------------------------------------------------------------
# Egress allowlist checker
# ---------------------------------------------------------------------------


def _url_allowed_by_egress(url: str, allowlist: list) -> bool:
    """
    Return True if url is permitted by at least one egress allowlist entry.
    Empty allowlist = default-open (all URLs allowed).
    """
    if not allowlist:
        return True
    try:
        parsed = urlparse(url)
        url_scheme = parsed.scheme
        url_port = parsed.port
        if url_port is None:
            url_port = 443 if url_scheme == "https" else 80
        hostname = parsed.hostname or ""
        for entry in allowlist:
            protocol = entry.get("protocol", "*")
            if protocol not in ("*", url_scheme):
                continue
            port = entry.get("port", 0)
            if port not in (0, url_port):
                continue
            if fnmatch.fnmatch(hostname, entry.get("endpoint_pattern", "")):
                return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Parameter constraint checker (local pre-flight, mirrors policy_engine logic)
# ---------------------------------------------------------------------------


def _check_parameter_constraints(
    tool_name: str,
    arguments: dict,
    constraints: dict,
) -> str | None:
    """
    Check tool arguments against parameter constraints from the tool binding.
    Returns an error string if a constraint is violated, else None.
    """
    for param, rules in constraints.items():
        if not isinstance(rules, dict):
            continue
        value = arguments.get(param)
        if value is None:
            continue  # absent parameters are not constrained here

        if "enum" in rules and value not in rules["enum"]:
            return (
                f"Error: parameter '{param}' value '{value}' is not in the "
                f"allowed set {rules['enum']} for tool '{tool_name}'."
            )

        if "max" in rules:
            try:
                if float(value) > float(rules["max"]):
                    return (
                        f"Error: parameter '{param}' value {value} exceeds "
                        f"maximum {rules['max']} for tool '{tool_name}'."
                    )
            except (TypeError, ValueError):
                pass

        if "min" in rules:
            try:
                if float(value) < float(rules["min"]):
                    return (
                        f"Error: parameter '{param}' value {value} is below "
                        f"minimum {rules['min']} for tool '{tool_name}'."
                    )
            except (TypeError, ValueError):
                pass

        if "allowed_prefixes" in rules:
            str_val = str(value).upper()
            prefixes = [str(p).upper() for p in rules["allowed_prefixes"]]
            if not any(str_val.startswith(p) for p in prefixes):
                return (
                    f"Error: parameter '{param}' must start with one of "
                    f"{rules['allowed_prefixes']} for tool '{tool_name}'."
                )

        if "pattern" in rules:
            try:
                if not re.match(rules["pattern"], str(value)):
                    return (
                        f"Error: parameter '{param}' value '{value}' does not match "
                        f"the required pattern for tool '{tool_name}'."
                    )
            except re.error:
                pass  # malformed pattern — don't block

    return None


# ---------------------------------------------------------------------------
# Node: check_budget
# ---------------------------------------------------------------------------

def _detect_tool_loop(messages: list, window: int = 3) -> bool:
    """
    Return True if the last `window` tool calls are identical (same name + args).
    Identical repeated calls with no progress indicate a degenerate loop.
    """
    tool_calls = [
        (tc["function"]["name"], tc["function"]["arguments"])
        for msg in messages
        if msg.get("role") == "assistant"
        for tc in msg.get("tool_calls") or []
    ]
    if len(tool_calls) >= window and len(set(tool_calls[-window:])) == 1:
        return True
    return False


def _detect_tool_oscillation(messages: list) -> bool:
    """
    Return True if the last 4 tool calls form an A→B→A→B oscillation pattern.
    This happens when the agent alternates between two tool calls indefinitely,
    neither making progress nor converging on a final answer.
    """
    tool_calls = [
        (tc["function"]["name"], tc["function"]["arguments"])
        for msg in messages
        if msg.get("role") == "assistant"
        for tc in msg.get("tool_calls") or []
    ]
    if len(tool_calls) >= 4:
        a, b, c, d = tool_calls[-4], tool_calls[-3], tool_calls[-2], tool_calls[-1]
        # A→B→A→B: positions 0 and 2 are equal, positions 1 and 3 are equal,
        # and the two patterns are distinct (A ≠ B)
        if a == c and b == d and a != b:
            return True
    return False


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
    messages = state.get("messages", [])

    # --- Degenerate pattern detection (checked first — fastest to catch runaway agents) ---
    if _detect_tool_loop(messages):
        logger.info("check_budget_node: degenerate tool loop detected (same call x3)")
        return {
            "budget_exceeded": True,
            "budget_reason": "degenerate_loop_detected",
            "final_response": (
                "I appear to be stuck repeating the same tool call. "
                "Here is what I have completed so far."
            ),
        }

    if _detect_tool_oscillation(messages):
        logger.info("check_budget_node: A→B→A→B oscillation detected")
        return {
            "budget_exceeded": True,
            "budget_reason": "oscillation_detected",
            "final_response": (
                "I appear to be oscillating between two approaches without making progress. "
                "Here is what I have completed so far."
            ),
        }

    # --- Early warning at 80% of each limit (emits log, does NOT stop the turn) ---
    if step_count >= int(max_steps * 0.8):
        logger.warning(
            "check_budget_node: step budget 80%% consumed (steps=%d/%d)",
            step_count, max_steps,
        )
    if token_count >= int(token_budget * 0.8):
        logger.warning(
            "check_budget_node: token budget 80%% consumed (tokens=%d/%d)",
            token_count, token_budget,
        )

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
_PHONE_PATTERN = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# Content Safety patterns — checked against LLM output before delivery
_CS_VIOLENCE_PATTERNS = [
    re.compile(r"\bhow\s+to\s+(kill|murder|assassinate|poison|strangle)\s+a\s+(person|human|someone)\b", re.IGNORECASE),
    re.compile(r"\b(step[- ]by[- ]step|detailed)\s+.{0,40}(build|make|construct)\s+(a\s+)?(bomb|explosive|weapon|ied)\b", re.IGNORECASE),
    re.compile(r"\binstructions?\s+(for|to)\s+(carry\s+out|commit|execute)\s+(a\s+)?(attack|massacre|shooting|stabbing)\b", re.IGNORECASE),
]
_CS_SELF_HARM_PATTERNS = [
    re.compile(r"\b(how\s+to|best\s+way\s+to|methods?\s+(of|for))\s+(commit\s+suicide|kill\s+yourself|end\s+your\s+life)\b", re.IGNORECASE),
    re.compile(r"\b(most\s+effective|painless|guaranteed)\s+(suicide|self[- ]harm)\s+(methods?|ways?|techniques?)\b", re.IGNORECASE),
]
_CS_HATE_SPEECH_PATTERNS = [
    re.compile(r"\b(all|every)\s+\w+\s+(should\s+(be\s+)?(killed|exterminated|eliminated|eradicated)|deserve\s+to\s+die)\b", re.IGNORECASE),
    re.compile(r"\b(genocide|ethnic\s+cleansing)\s+(of|against)\s+\w+\s+(is\s+)?(good|justified|necessary|right)\b", re.IGNORECASE),
]
_CS_PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above|your)\s+instructions?", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(operating\s+in\s+)?(dan|jailbreak|unrestricted|developer|god)\s+mode", re.IGNORECASE),
    re.compile(r"(system|assistant):\s*(ignore|disregard|forget)\s+.{0,60}(instructions?|guidelines?|rules?)", re.IGNORECASE),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\s+(a\s+)?(different|unrestricted|evil|uncensored)\s+(ai|llm|assistant|model|bot)", re.IGNORECASE),
]

# Map pattern lists to category labels
_CONTENT_SAFETY_CHECKS: list[tuple[str, list]] = [
    ("violence", _CS_VIOLENCE_PATTERNS),
    ("self_harm", _CS_SELF_HARM_PATTERNS),
    ("hate_speech", _CS_HATE_SPEECH_PATTERNS),
    ("prompt_injection", _CS_PROMPT_INJECTION_PATTERNS),
]


def _check_content_safety(text: str) -> tuple[bool, str]:
    """
    Check LLM output for harmful content categories.

    Returns (is_safe, category) where category is empty string when safe.
    Checked categories: violence · self_harm · hate_speech · prompt_injection
    """
    for category, patterns in _CONTENT_SAFETY_CHECKS:
        for pattern in patterns:
            if pattern.search(text):
                return False, category
    return True, ""


def _redact_pii(text: str) -> str:
    """Apply PII redaction patterns to the text."""
    text = _SSN_PATTERN.sub("[REDACTED-SSN]", text)
    text = _CREDIT_CARD_PATTERN.sub("[REDACTED-CC]", text)
    text = _EMAIL_PATTERN.sub("[REDACTED-EMAIL]", text)
    text = _PHONE_PATTERN.sub("[REDACTED-PHONE]", text)
    text = _IP_PATTERN.sub("[REDACTED-IP]", text)
    return text


_SAFE_FALLBACK = (
    "I'm unable to generate a response that meets safety requirements for this request."
)


async def apply_guardrails_node(state: AgentState) -> dict:
    """
    Apply safety guardrails to the assistant's last response.

    Guardrail pipeline (fail-closed — any exception blocks the response):
      0. Content Safety: block harmful categories (violence, self-harm,
         hate speech, prompt injection) before any further processing.
      1. PII redaction (SSN, credit card, email, phone, IP address).
      2. If significant PII was detected, request one LLM regeneration so the
         agent can produce a response that doesn't need heavy redaction.
         If regeneration also contains PII it is redacted and delivered.
      3. DLP size limit: truncate at MAX_OUTPUT_CHARS.
      4. Tenant DLP policies: keyword blocklist → BLOCK,
         regex patterns → REDACT, per-policy max_output_chars.
    """
    try:
        messages = list(state.get("messages", []))

        # Find the last assistant message
        last_assistant_idx: Optional[int] = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "assistant":
                last_assistant_idx = i
                break

        if last_assistant_idx is None:
            return {"final_response": state.get("error") or "No response generated."}

        last_msg = messages[last_assistant_idx]
        content = last_msg.get("content") or ""
        if not isinstance(content, str):
            content = ""

        # --- Layer 0: Content Safety ---
        is_safe, safety_category = _check_content_safety(content)
        if not is_safe:
            logger.warning(
                "apply_guardrails_node: content safety block — category: %s", safety_category
            )
            return {
                "final_response": "Response blocked by content safety filter.",
                "messages": messages,
                "error": f"content_safety_block:{safety_category}",
            }

        cleaned_content = _redact_pii(content)
        pii_detected = cleaned_content != content

        # --- Guardrail regeneration (spec: violation → regenerate once, then block) ---
        if pii_detected:
            logger.info("apply_guardrails_node: PII detected, requesting regeneration")
            system_prompt = state.get("system_prompt", "You are a helpful AI assistant.")
            model = state.get("model", "llama3")
            available_tools = state.get("available_tools", [])

            regen_messages = list(messages) + [
                {
                    "role": "user",
                    "content": (
                        "Your previous response contained sensitive personal information. "
                        "Please rephrase your answer without including any social security "
                        "numbers, credit card numbers, or other personal identifiers."
                    ),
                }
            ]
            full_regen = [{"role": "system", "content": system_prompt}] + regen_messages
            try:
                regen_resp = await get_llm_router().complete(
                    model=model,
                    messages=full_regen,
                    tools=available_tools if available_tools else None,
                )
                regen_content = regen_resp.choices[0].message.content or ""
                cleaned_content = _redact_pii(regen_content)  # still redact any residual PII
                logger.info("apply_guardrails_node: regeneration succeeded")
            except Exception as exc:
                logger.warning(
                    "apply_guardrails_node: regeneration failed, using redacted original: %s", exc
                )
                # cleaned_content already holds the redacted original — use it

        # --- DLP Layer 3: Output size limit ---
        max_chars = settings.MAX_OUTPUT_CHARS
        if len(cleaned_content) > max_chars:
            cleaned_content = cleaned_content[:max_chars] + "\n[Output truncated — exceeded maximum response length]"
            logger.info("apply_guardrails_node: output truncated to %d chars (DLP size limit)", max_chars)

        # --- DLP Layer 4: Tenant policy keyword blocklist + redact patterns ---
        guardrail_policies: list = state.get("guardrail_policies") or []
        for policy in guardrail_policies:
            try:
                body = json.loads(policy.get("policy_body", "{}"))
            except (json.JSONDecodeError, TypeError):
                continue
            if body.get("type") != "output_dlp":
                continue

            # Keyword blocklist → BLOCK
            for kw in body.get("keyword_blocklist", []):
                if kw.lower() in cleaned_content.lower():
                    logger.info(
                        "apply_guardrails_node: DLP keyword block matched '%s'", kw
                    )
                    return {
                        "final_response": "Response blocked by content policy.",
                        "messages": messages,
                        "error": "dlp_keyword_block",
                    }

            # Redact patterns → REDACT in-place
            for rule in body.get("redact_patterns", []):
                pat = rule.get("pattern", "")
                label = rule.get("name", "DLP")
                if pat:
                    try:
                        cleaned_content = re.sub(pat, f"[{label}_REDACTED]", cleaned_content)
                    except re.error:
                        pass  # malformed pattern — skip

            # Per-policy max_output_chars (overrides global if smaller)
            policy_max = body.get("max_output_chars")
            if policy_max and isinstance(policy_max, int) and len(cleaned_content) > policy_max:
                cleaned_content = cleaned_content[:policy_max] + "\n[Output truncated by policy]"

        # Persist the final (possibly regenerated, possibly redacted) content
        updated_msg = dict(last_msg)
        updated_msg["content"] = cleaned_content
        messages[last_assistant_idx] = updated_msg

        return {
            "final_response": cleaned_content,
            "messages": messages,
        }

    except Exception:
        logger.exception("apply_guardrails_node: guardrail filter failed — blocking response")
        return {
            "final_response": "Response could not be delivered due to a safety check failure.",
            "error": "guardrail_filter_failed",
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
