from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/agentplatform"
    REDIS_URL: str = "redis://redis:6379"
    OLLAMA_BASE_URL: str = "http://ollama:11434/v1"
    AGENT_CONFIG_SERVICE_URL: str = "http://agent-config-service:8001"
    MEMORY_SERVICE_URL: str = "http://memory-service:8003"
    INTERNAL_SECRET: str = "changeme-internal-secret"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
