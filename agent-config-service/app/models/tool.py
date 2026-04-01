import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime, String

from app.database import Base


class Tool(Base):
    __tablename__ = "tools"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="1.0.0", server_default="1.0.0")
    endpoint_url: Mapped[str] = mapped_column(Text, nullable=False)
    http_method: Mapped[str] = mapped_column(String(10), nullable=False, default="POST", server_default="POST")
    input_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    output_schema: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    auth_type: Mapped[str] = mapped_column(String(50), nullable=False, default="none", server_default="none")
    auth_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    # --- Spec additions (backward-compatible nullable columns) ---
    # Tracks the highest-numbered schema version; set by the schema-versioning API.
    active_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    # 'active' | 'deprecated' | 'disabled'
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", server_default="active"
    )
    timeout_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30000, server_default="30000"
    )
    max_response_bytes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=102400, server_default="102400"
    )
    is_cacheable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    cache_ttl_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=300, server_default="300"
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (Index("idx_tools_tenant", "tenant_id"),)


class AgentTool(Base):
    __tablename__ = "agent_tools"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tool_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("tools.id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
