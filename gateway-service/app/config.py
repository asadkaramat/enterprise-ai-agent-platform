from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/agentplatform"
    REDIS_URL: str = "redis://redis:6379"
    ADMIN_SECRET: str = "changeme-admin-secret"
    AGENT_CONFIG_SERVICE_URL: str = "http://agent-config-service:8001"
    SESSION_SERVICE_URL: str = "http://session-service:8002"
    MEMORY_SERVICE_URL: str = "http://memory-service:8003"
    AUDIT_SERVICE_URL: str = "http://audit-service:8004"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
