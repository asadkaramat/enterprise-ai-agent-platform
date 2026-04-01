from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/agentplatform"
    REDIS_URL: str = "redis://redis:6379"
    OLLAMA_BASE_URL: str = "http://ollama:11434/v1"
    AGENT_CONFIG_SERVICE_URL: str = "http://agent-config-service:8001"
    MEMORY_SERVICE_URL: str = "http://memory-service:8003"
    INTERNAL_SECRET: str = "changeme-internal-secret"
    FALLBACK_MODEL: str = "llama3.2"  # Used by LLMRouter when the primary model fails
    MAX_LLM_REQUESTS_PER_MINUTE: int = 100  # Per-tenant LLM rate limit (requests/min)
    MAX_TOOL_CALLS_PER_MINUTE: int = 200   # Per-tenant per-tool rate limit (calls/min)
    MAX_TOOL_RESPONSE_BYTES: int = 102_400  # 100 KB cap per tool response
    MAX_OUTPUT_CHARS: int = 8192  # DLP output size limit
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
