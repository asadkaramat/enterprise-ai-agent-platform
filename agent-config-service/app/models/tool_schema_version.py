"""
Immutable tool schema versions.

Agent versions bind to a specific schema_version of a tool, not "latest."
This creates a stable contract: a tool owner can publish breaking schema
changes without affecting existing agent configs.
"""
import uuid

from sqlalchemy import Index, Integer, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime

from app.database import Base


class ToolSchemaVersion(Base):
    __tablename__ = "tool_schema_versions"

    tool_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    schema_version: Mapped[int] = mapped_column(Integer, primary_key=True)

    # The schema definition — immutable after INSERT
    schema_def: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # SHA-256 of canonical JSON for integrity verification
    checksum: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("idx_tool_schema_versions_tool", "tool_id"),)
