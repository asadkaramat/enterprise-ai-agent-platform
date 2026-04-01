from prometheus_client import Counter, Histogram

memory_append_total = Counter(
    "memory_append_total",
    "Total number of short-term memory append operations",
    ["tenant_id"],
)

memory_retrieve_total = Counter(
    "memory_retrieve_total",
    "Total number of long-term memory retrieve operations",
    ["tenant_id"],
)

memory_store_long_total = Counter(
    "memory_store_long_total",
    "Total number of long-term memory store operations",
    ["tenant_id"],
)

embedding_duration_seconds = Histogram(
    "embedding_duration_seconds",
    "Time spent computing embeddings",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)
