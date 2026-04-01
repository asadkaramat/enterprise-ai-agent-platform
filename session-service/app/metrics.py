from prometheus_client import Counter, Histogram

sessions_created_total = Counter(
    "sessions_created_total",
    "Total number of sessions created",
    ["tenant_id", "agent_id"],
)

session_steps_total = Counter(
    "session_steps_total",
    "Total number of agent steps executed",
    ["tenant_id", "agent_id"],
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total LLM tokens consumed",
    ["tenant_id", "agent_id", "model"],
)

tool_calls_total = Counter(
    "tool_calls_total",
    "Total number of tool calls made",
    ["tenant_id", "agent_id", "tool_name"],
)

budget_exceeded_total = Counter(
    "budget_exceeded_total",
    "Total number of sessions that exceeded budget",
    ["tenant_id", "agent_id", "reason"],
)

session_duration_seconds = Histogram(
    "session_duration_seconds",
    "Session duration in seconds",
    ["tenant_id", "agent_id"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)

llm_latency_seconds = Histogram(
    "llm_latency_seconds",
    "LLM call latency in seconds",
    ["tenant_id", "model"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
)
