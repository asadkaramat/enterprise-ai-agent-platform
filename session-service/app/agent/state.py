from typing import TypedDict, List, Optional


class AgentState(TypedDict):
    # Identity
    session_id: str
    tenant_id: str
    agent_id: str

    # Config (loaded from agent-config-service)
    system_prompt: str
    model: str
    max_steps: int
    token_budget: int
    session_timeout_seconds: int
    memory_enabled: bool
    available_tools: List[dict]   # OpenAI tool schemas [{type:"function", function:{name,description,parameters}}]
    tool_configs: dict            # tool_name -> {endpoint_url, http_method, auth_type, auth_config}

    # Runtime
    messages: List[dict]          # OpenAI message format
    step_count: int
    token_count: int
    start_time: float
    tool_call_counts: dict        # tool_name -> call count this turn (for max_calls_per_turn)
    egress_allowlist: List[dict]  # [{endpoint_pattern, port, protocol}] for tenant egress enforcement

    # Caching / DLP
    prompt_cache_key: Optional[str]   # Hash for Redis prompt prefix cache
    guardrail_policies: List[dict]    # Output DLP policies from Control Plane

    # Control
    budget_exceeded: bool
    budget_reason: str

    # Routing
    route_to_agent_id: Optional[str]
    route_message: Optional[str]

    # Final
    final_response: Optional[str]
    error: Optional[str]
