from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/agentplatform"
    INTERNAL_SECRET: str = "changeme-internal-secret"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
