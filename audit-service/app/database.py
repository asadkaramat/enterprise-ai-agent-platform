import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency that yields an AsyncSession."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def run_column_migrations() -> None:
    """Idempotent column-level migrations for existing tables."""
    _migrations = [
        "ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS prev_hash TEXT",
        "ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS event_id VARCHAR(36)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_events_event_id ON audit_events (event_id) WHERE event_id IS NOT NULL",
    ]
    async with engine.begin() as conn:
        for stmt in _migrations:
            await conn.execute(text(stmt))
    logger.info("Audit column migrations applied.")


async def create_tables() -> None:
    """Create all tables on startup (idempotent)."""
    from app.models import audit  # noqa: F401 — ensure model is registered

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created / verified")


async def dispose_engine() -> None:
    """Dispose the engine connection pool on shutdown."""
    await engine.dispose()
    logger.info("Database engine disposed")
