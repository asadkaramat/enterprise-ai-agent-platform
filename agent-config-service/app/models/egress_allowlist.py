"""
Tenant egress allowlist — defines which external endpoints a tenant's tool
sandboxes are permitted to reach.

When a tenant has one or more active entries, the Session Manager validates
every tool endpoint URL against this list before dispatching the call.
An empty allowlist (no rows) means "allow all endpoints" (default-open),
preserving backward compatibility for tenants that have not configured
explicit restrictions.
"""
import uuid

from sqlalchemy import Boolean, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime

from app.database import Base


class EgressAllowlist(Base):
    __tablename__ = "egress_allowlist"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    # Hostname or wildcard pattern, e.g. "api.example.com" or "*.acme-internal.com"
    endpoint_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=443, server_default="443")
    # "http" | "https" | "grpc"
    protocol: Mapped[str] = mapped_column(String(20), nullable=False, default="https", server_default="https")
    description: Mapped[str] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("idx_egress_allowlist_tenant", "tenant_id"),)
