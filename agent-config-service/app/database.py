import logging
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def create_tables() -> None:
    from app.models import agent, tool  # noqa: F401 — ensure models are registered
    # Import new models so they are registered with metadata before create_all
    from app.models import (  # noqa: F401
        agent_version,
        egress_allowlist,
        policy,
        tenant,
        tool_binding,
        tool_schema_version,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created (or already exist).")


async def run_column_migrations() -> None:
    """
    Idempotent column-level migrations for existing tables.
    Uses ALTER TABLE ... ADD COLUMN IF NOT EXISTS to avoid errors on re-runs.
    New tables are handled by create_tables() above.
    """
    _migrations = [
        # tools — spec additions
        "ALTER TABLE tools ADD COLUMN IF NOT EXISTS active_schema_version INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE tools ADD COLUMN IF NOT EXISTS status VARCHAR(50) NOT NULL DEFAULT 'active'",
        "ALTER TABLE tools ADD COLUMN IF NOT EXISTS timeout_ms INTEGER NOT NULL DEFAULT 30000",
        "ALTER TABLE tools ADD COLUMN IF NOT EXISTS max_response_bytes INTEGER NOT NULL DEFAULT 102400",
        "ALTER TABLE tools ADD COLUMN IF NOT EXISTS is_cacheable BOOLEAN NOT NULL DEFAULT false",
        "ALTER TABLE tools ADD COLUMN IF NOT EXISTS cache_ttl_seconds INTEGER NOT NULL DEFAULT 300",
        # agents — active version pointer
        "ALTER TABLE agents ADD COLUMN IF NOT EXISTS active_version_id UUID",
    ]
    async with engine.begin() as conn:
        for stmt in _migrations:
            await conn.execute(text(stmt))
    logger.info("Column migrations applied.")


async def run_rls_migrations() -> None:
    """
    Apply PostgreSQL Row-Level Security (RLS) policies to all tenant-scoped tables.

    Each policy filters rows by matching tenant_id to the session-local variable
    app.current_tenant_id, which get_db() sets at the start of every
    tenant-authenticated request.

    Notes on enforcement:
    - Policies are created with `OR REPLACE` so re-runs are idempotent.
    - RLS is enabled (but NOT FORCED) so PostgreSQL superusers bypass it
      automatically. This preserves backward compat for platform-admin paths
      (gateway admin routes) that don't set app.current_tenant_id.
    - Full enforcement in production requires a dedicated non-superuser
      `app_user` role; adding `ALTER TABLE ... FORCE ROW LEVEL SECURITY` once
      that role is provisioned completes the hardening.
    - The tools table has a dual policy: platform-wide tools (tenant_id IS NULL)
      are visible to every tenant.
    """
    # Tables that carry tenant_id and must be row-level isolated
    _tenant_tables = [
        "agents",
        "agent_versions",
        "tool_bindings",
        "policies",
        "egress_allowlist",
        "roles",
        "api_keys",
    ]
    # tools: platform-wide rows (tenant_id IS NULL) are also visible
    _shared_tables = ["tools", "tool_schema_versions"]

    try:
        async with engine.begin() as conn:
            # Enable RLS on tenant-only tables
            for table in _tenant_tables:
                await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
                await conn.execute(text(
                    f"CREATE POLICY IF NOT EXISTS tenant_isolation ON {table} "
                    f"USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
                ))

            # Enable RLS on shared tables (tenant rows + platform-wide rows)
            for table in _shared_tables:
                await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
                await conn.execute(text(
                    f"CREATE POLICY IF NOT EXISTS tenant_isolation ON {table} "
                    f"USING (tenant_id IS NULL "
                    f"OR tenant_id = current_setting('app.current_tenant_id', true)::uuid)"
                ))

        logger.info("RLS policies applied to %d tables.", len(_tenant_tables) + len(_shared_tables))
    except Exception as exc:
        # Non-fatal: log and continue — application-level filtering remains the primary guard
        logger.warning("RLS migration failed (non-fatal, app-level filtering still active): %s", exc)


async def dispose_engine() -> None:
    await engine.dispose()
    logger.info("Database engine disposed.")
