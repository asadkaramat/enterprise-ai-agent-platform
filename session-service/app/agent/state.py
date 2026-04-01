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

    # Control
    budget_exceeded: bool
    budget_reason: str

    # Routing
    route_to_agent_id: Optional[str]
    route_message: Optional[str]

    # Final
    final_response: Optional[str]
    error: Optional[str]
