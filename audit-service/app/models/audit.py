import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditEvent(Base):
    """
    Append-only audit event record.
    NEVER issue UPDATE or DELETE on this table.
    """

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=False,  # covered by composite index below
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    event_data: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # Hash chain: SHA-256(prev_hash + canonical_event_json).
    # NULL for the first event in a tenant's chain.
    prev_hash: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Deduplication key: populated from upstream event_id (Kafka / Redis dual-publish).
    event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=False)

    __table_args__ = (
        # Primary access pattern: tenant-scoped time-range queries (DESC on created_at)
        Index(
            "ix_audit_events_tenant_created",
            "tenant_id",
            text("created_at DESC"),
        ),
        # Session timeline lookups
        Index("ix_audit_events_session_id", "session_id"),
        # Event type filtering
        Index("ix_audit_events_event_type", "event_type"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditEvent id={self.id} tenant={self.tenant_id} "
            f"type={self.event_type} at={self.created_at}>"
        )
