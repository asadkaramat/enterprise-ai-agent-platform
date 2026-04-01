from prometheus_client import Counter, Gauge

audit_events_consumed_total = Counter(
    "audit_events_consumed_total",
    "Events consumed from Redis Stream",
    ["event_type"],
)

audit_events_failed_total = Counter(
    "audit_events_failed_total",
    "Events that failed processing",
)

consumer_lag_gauge = Gauge(
    "audit_consumer_lag",
    "Estimated consumer lag (pending messages)",
)
