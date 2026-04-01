from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@postgres:5432/agentplatform"
    REDIS_URL: str = "redis://redis:6379"
    TOKEN_COST_PER_UNIT: float = 0.00001
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    MINIO_ENDPOINT: str = "http://minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin123"
    MINIO_BUCKET: str = "audit-logs"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
