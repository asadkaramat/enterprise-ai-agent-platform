import uuid

from sqlalchemy import Boolean, Index, Integer, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime, String

from app.database import Base


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False, default="llama3.2", server_default="llama3.2")
    max_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=10, server_default="10")
    token_budget: Mapped[int] = mapped_column(Integer, nullable=False, default=8000, server_default="8000")
    session_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300, server_default="300")
    memory_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (Index("idx_agents_tenant", "tenant_id"),)
