"""
Immutable agent configuration snapshots.

Each version is a complete, self-contained definition of agent behaviour.
Versions are never updated or deleted — rollback is a pointer change on the
agents table (active_version_id), not a mutation of any version row.
"""
import uuid

from sqlalchemy import Boolean, Index, Integer, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime, String

from app.database import Base


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Config snapshot — immutable after INSERT
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(
        String(255), nullable=False, default="llama3.2", server_default="llama3.2"
    )
    fallback_model_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    memory_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    memory_retrieval_window_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    max_steps_per_turn: Mapped[int] = mapped_column(
        Integer, nullable=False, default=20, server_default="20"
    )
    token_budget: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100000, server_default="100000"
    )
    # Stored in milliseconds (spec-consistent); exposed as seconds by the
    # internal endpoint for backward-compatibility with the session-service.
    session_timeout_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300000, server_default="300000"
    )
    rollout_percentage: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    guardrail_config: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("agent_id", "version_number", name="uq_agent_version_number"),
        Index("idx_agent_versions_agent", "agent_id"),
        Index("idx_agent_versions_tenant", "tenant_id"),
    )
