from prometheus_client import Counter

agent_config_requests_total = Counter(
    "agent_config_requests_total",
    "Total HTTP requests handled by agent-config-service",
    ["method", "path", "status"],
)

agents_created_total = Counter(
    "agents_created_total",
    "Total number of agent configurations created",
)

tools_registered_total = Counter(
    "tools_registered_total",
    "Total number of tools registered",
)
