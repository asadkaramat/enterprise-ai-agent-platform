from prometheus_client import Counter, Histogram

requests_total = Counter(
    "gateway_requests_total",
    "Total number of requests processed by the gateway",
    ["tenant_id", "method", "path", "status"],
)

auth_failures_total = Counter(
    "gateway_auth_failures_total",
    "Total number of authentication failures",
    ["reason"],
)

rate_limit_hits_total = Counter(
    "gateway_rate_limit_hits_total",
    "Total number of rate limit hits",
    ["tenant_id"],
)

request_duration_seconds = Histogram(
    "gateway_request_duration_seconds",
    "Request duration in seconds",
    ["method", "path"],
)
