from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    REDIS_URL: str = "redis://redis:6379"
    QDRANT_URL: str = "http://qdrant:6333"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    SHORT_TERM_TTL_HOURS: int = 24
    SHORT_TERM_MAX_MESSAGES: int = 50

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
