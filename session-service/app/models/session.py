import uuid
from datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class Session(Base):
    __tablename__ = "sessions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    agent_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    status = Column(String(50), default="active", nullable=False)
    step_count = Column(Integer, default=0, nullable=False)
    token_count = Column(Integer, default=0, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
