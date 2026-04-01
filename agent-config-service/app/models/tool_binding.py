"""
Tool bindings — connects an agent version to a tool at a pinned schema version.

Replaces the functionality of `agent_tools` with:
  - Pinned schema version (not "latest")
  - Parameter-level constraints (evaluated by the policy engine at runtime)
  - Per-turn call budget
"""
import uuid

from sqlalchemy import Boolean, Index, Integer, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ToolBinding(Base):
    __tablename__ = "tool_bindings"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    version_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tool_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    tool_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    # Parameter-level authorization constraints evaluated before each tool call.
    # Format: {"param_name": {"enum": [...], "max": N, "allowed_prefixes": [...]}}
    parameter_constraints: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Maximum number of times this tool may be called in a single turn.
    max_calls_per_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Set to False to temporarily disable without removing the binding.
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    __table_args__ = (
        UniqueConstraint("version_id", "tool_id", name="uq_tool_binding_version_tool"),
        Index("idx_tool_bindings_version", "version_id"),
        Index("idx_tool_bindings_tool", "tool_id"),
    )
