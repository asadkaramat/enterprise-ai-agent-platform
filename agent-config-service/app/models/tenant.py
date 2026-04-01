"""
Tenant, Role, and ApiKey models for the RBAC layer.

Tenants: one per enterprise customer. Every other table is scoped to a tenant.
Roles: define what a user is allowed to do via a permissions array.
ApiKeys: hashed bearer tokens bound to a role. Plaintext shown once at creation.
"""
import uuid

from sqlalchemy import Boolean, Index, Integer, Text, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime, String

from app.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", server_default="active"
    )
    # Soft quota enforced at session creation time by the session-service.
    max_concurrent_sessions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Role(Base):
    """
    RBAC role.  permissions is a JSON array of permission strings, e.g.:
    ["agents:read", "agents:write", "tools:read", "sessions:write"]
    A wildcard ["*"] grants all permissions.
    """
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    permissions: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_role_tenant_name"),
        Index("idx_roles_tenant", "tenant_id"),
    )


class ApiKey(Base):
    """
    Hashed API keys for programmatic access.

    The plaintext key is shown exactly once at creation and never stored.
    key_hash = SHA-256(plaintext_key).
    key_prefix stores the first 8 characters for identification in logs/UI.
    """
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    # Optional fine-grained override; defaults to full role permissions.
    scopes: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=lambda: ["*"], server_default='["*"]'
    )
    expires_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_used_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="active", server_default="active"
    )
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_api_keys_hash", "key_hash"),
        Index("idx_api_keys_tenant", "tenant_id"),
    )
