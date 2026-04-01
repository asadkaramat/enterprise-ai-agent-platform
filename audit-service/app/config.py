from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/agentplatform"
    REDIS_URL: str = "redis://redis:6379"
    TOKEN_COST_PER_UNIT: float = 0.00001

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
