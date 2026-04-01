"""
Declarative authorization policies evaluated by the policy engine.

Scopes:
  tenant — applies to ALL agents and tools in the tenant.
  agent  — applies to a specific agent (scope_ref_id = agent_id).
  tool   — applies to a specific tool (scope_ref_id = tool_id).

Policy languages:
  inline — JSON-defined rule set, evaluated in-process (zero extra dependencies).
  rego   — OPA Rego (compiled to WASM); stubbed until OPA is integrated.
  cedar  — AWS Cedar; stubbed until Cedar is integrated.

For the current MVP, only 'inline' policies are actively evaluated.
Rego/Cedar policies are stored and validated for syntax but abstain from
decisions (neither ALLOW nor DENY) until the respective engine is wired in.
"""
import uuid

from sqlalchemy import Boolean, Index, Integer, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime, String

from app.database import Base


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    # 'tenant' | 'agent' | 'tool'
    scope: Mapped[str] = mapped_column(String(50), nullable=False)
    # NULL for tenant-scope policies; agent_id or tool_id for narrower scopes.
    scope_ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    # 'inline' | 'rego' | 'cedar'
    policy_lang: Mapped[str] = mapped_column(
        String(50), nullable=False, default="inline", server_default="inline"
    )
    policy_body: Mapped[str] = mapped_column(Text, nullable=False)

    # Monotonically incremented on each UPDATE.
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_policies_tenant_scope", "tenant_id", "scope", "scope_ref_id"),
    )
