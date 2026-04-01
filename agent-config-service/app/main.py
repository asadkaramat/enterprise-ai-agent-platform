import hashlib
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal, create_tables, dispose_engine, get_db, run_column_migrations, run_rls_migrations
from app.metrics import agent_config_requests_total
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.tool import AgentTool, Tool
from app.models.egress_allowlist import EgressAllowlist
from app.models.tool_binding import ToolBinding
from app.models.tool_schema_version import ToolSchemaVersion
from app.routes.agents import router as agents_router
from app.routes.egress_policies import internal_router as egress_internal_router
from app.routes.egress_policies import router as egress_router
from app.routes.policies import internal_router as policy_internal_router
from app.routes.policies import router as policies_router
from app.routes.tenants import router as tenants_router
from app.routes.tools import router as tools_router
from app.routes.versions import router as versions_router
from app.services import config_cache, config_publisher

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Startup migration helpers
# ---------------------------------------------------------------------------


def _schema_checksum(schema_def: dict) -> str:
    canonical = json.dumps(schema_def, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _run_startup_migration() -> None:
    """
    Idempotent startup migration:
    1. For every active Tool with no ToolSchemaVersion v1, seed v1 from Tool.input_schema.
    2. For every active Agent with no active_version_id, create AgentVersion v1 from the
       agent's current fields and create ToolBindings from its AgentTool entries.
    """
    async with AsyncSessionLocal() as db:
        try:
            # ── Seed ToolSchemaVersion v1 for tools that have none ──────────
            tools_result = await db.execute(
                select(Tool).where(Tool.is_active.is_(True))
            )
            tools = tools_result.scalars().all()

            seeded_schemas = 0
            for tool in tools:
                exists = await db.execute(
                    select(ToolSchemaVersion).where(
                        and_(
                            ToolSchemaVersion.tool_id == tool.id,
                            ToolSchemaVersion.schema_version == 1,
                        )
                    )
                )
                if exists.scalar_one_or_none() is None:
                    db.add(ToolSchemaVersion(
                        tool_id=tool.id,
                        schema_version=1,
                        schema_def=tool.input_schema or {},
                        checksum=_schema_checksum(tool.input_schema or {}),
                    ))
                    seeded_schemas += 1

            await db.flush()

            # ── Create AgentVersion v1 for agents that have none ─────────────
            agents_result = await db.execute(
                select(Agent).where(
                    and_(Agent.is_active.is_(True), Agent.active_version_id.is_(None))
                )
            )
            agents = agents_result.scalars().all()

            seeded_versions = 0
            for agent in agents:
                version = AgentVersion(
                    id=uuid.uuid4(),
                    agent_id=agent.id,
                    tenant_id=agent.tenant_id,
                    version_number=1,
                    system_prompt=agent.system_prompt,
                    model_id=agent.model,
                    memory_enabled=agent.memory_enabled,
                    max_steps_per_turn=agent.max_steps,
                    token_budget=agent.token_budget,
                    session_timeout_ms=agent.session_timeout_seconds * 1000,
                )
                db.add(version)
                await db.flush()

                # Bind every authorized tool from AgentTool
                at_result = await db.execute(
                    select(AgentTool).where(
                        and_(AgentTool.agent_id == agent.id, AgentTool.is_authorized.is_(True))
                    )
                )
                for at in at_result.scalars().all():
                    db.add(ToolBinding(
                        id=uuid.uuid4(),
                        version_id=version.id,
                        tool_id=at.tool_id,
                        tool_schema_version=1,
                        tenant_id=agent.tenant_id,
                    ))

                agent.active_version_id = version.id
                seeded_versions += 1

            await db.commit()
            if seeded_schemas or seeded_versions:
                logger.info(
                    "startup_migration: seeded %d tool schemas, %d agent versions",
                    seeded_schemas,
                    seeded_versions,
                )
        except Exception:
            await db.rollback()
            logger.exception("startup_migration: failed — continuing without migration")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("agent-config-service starting up …")
    await run_column_migrations()
    await create_tables()
    await run_rls_migrations()

    # Redis — optional; degrade gracefully when unavailable
    redis_client = None
    try:
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=False)
        await redis_client.ping()
        app.state.redis = redis_client
        logger.info("Redis connected: %s", settings.REDIS_URL)
    except Exception as exc:
        logger.warning("Redis unavailable — config caching disabled: %s", exc)
        app.state.redis = None

    await _run_startup_migration()

    yield

    if redis_client is not None:
        await redis_client.aclose()
    logger.info("agent-config-service shutting down …")
    await dispose_engine()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Agent Config Service",
    description="CRUD for agent configurations and tool registry. Enforces tenant isolation via X-Tenant-ID header.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins (internal service; gateway enforces auth)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Prometheus instrumentation middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start = time.perf_counter()
    response: Response = await call_next(request)
    duration = time.perf_counter() - start  # noqa: F841 — kept for future histogram use

    agent_config_requests_total.labels(
        method=request.method,
        path=request.url.path,
        status=str(response.status_code),
    ).inc()

    return response


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(agents_router)
app.include_router(tools_router)
app.include_router(versions_router)
app.include_router(policies_router)
app.include_router(policy_internal_router)
app.include_router(tenants_router)
app.include_router(egress_router)
app.include_router(egress_internal_router)


# ---------------------------------------------------------------------------
# Built-in endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok", "service": "agent-config"}


@app.get("/metrics", tags=["ops"], include_in_schema=False)
async def metrics() -> Response:
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Internal helpers for the full-config endpoint
# ---------------------------------------------------------------------------


async def _build_versioned_config(
    agent: Agent,
    version: AgentVersion,
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Build the full agent config dict from an AgentVersion + its ToolBindings.
    Field names are mapped for backward-compat with the session-service.
    """
    # Load tool bindings for this version
    bindings_result = await db.execute(
        select(ToolBinding).where(
            and_(ToolBinding.version_id == version.id, ToolBinding.enabled.is_(True))
        )
    )
    bindings = bindings_result.scalars().all()

    # Load tool details + pinned schema versions in one pass
    tools_out: list[dict[str, Any]] = []
    for binding in bindings:
        tool_result = await db.execute(
            select(Tool).where(and_(Tool.id == binding.tool_id, Tool.is_active.is_(True)))
        )
        tool = tool_result.scalar_one_or_none()
        if tool is None:
            continue

        # Pinned schema definition
        sv_result = await db.execute(
            select(ToolSchemaVersion).where(
                and_(
                    ToolSchemaVersion.tool_id == binding.tool_id,
                    ToolSchemaVersion.schema_version == binding.tool_schema_version,
                )
            )
        )
        sv = sv_result.scalar_one_or_none()
        input_schema = sv.schema_def if sv is not None else tool.input_schema

        tools_out.append({
            "tool_id": str(tool.id),
            "name": tool.name,
            "description": tool.description,
            "endpoint_url": tool.endpoint_url,
            "http_method": tool.http_method,
            "input_schema": input_schema,
            "output_schema": tool.output_schema,
            "auth_type": tool.auth_type,
            "auth_config": tool.auth_config,
            "is_authorized": True,
            "parameter_constraints": binding.parameter_constraints or {},
            "max_calls_per_turn": binding.max_calls_per_turn,
            "timeout_ms": tool.timeout_ms,
            "max_response_bytes": tool.max_response_bytes,
            "is_cacheable": tool.is_cacheable,
            "cache_ttl_seconds": tool.cache_ttl_seconds,
        })

    agent_out = {
        # Legacy field names for session-service compat
        "id": str(agent.id),
        "tenant_id": str(agent.tenant_id),
        "name": agent.name,
        "description": agent.description,
        "system_prompt": version.system_prompt,
        "model": version.model_id,
        "max_steps": version.max_steps_per_turn,
        "token_budget": version.token_budget,
        "session_timeout_seconds": version.session_timeout_ms // 1000,
        "memory_enabled": version.memory_enabled,
        "is_active": agent.is_active,
        # Version metadata
        "active_version_id": str(version.id),
        "version_number": version.version_number,
        "fallback_model_id": version.fallback_model_id,
        "guardrail_config": version.guardrail_config,
        "rollout_percentage": version.rollout_percentage,
    }

    # Load egress allowlist for this tenant
    egress_result = await db.execute(
        select(EgressAllowlist).where(
            and_(EgressAllowlist.tenant_id == agent.tenant_id, EgressAllowlist.is_active.is_(True))
        )
    )
    egress_entries = [
        {"endpoint_pattern": e.endpoint_pattern, "port": e.port, "protocol": e.protocol}
        for e in egress_result.scalars().all()
    ]

    # Load output DLP policies for this tenant (tenant-scope and agent-scope)
    from app.models.policy import Policy
    policies_result = await db.execute(
        select(Policy).where(
            and_(
                Policy.tenant_id == agent.tenant_id,
                Policy.enabled.is_(True),
                Policy.policy_lang == "inline",
            )
        )
    )
    guardrail_policies = [
        {"scope": p.scope, "policy_body": p.policy_body}
        for p in policies_result.scalars().all()
    ]

    return {"agent": agent_out, "tools": tools_out, "egress_allowlist": egress_entries, "guardrail_policies": guardrail_policies}


async def _build_legacy_config(agent: Agent, db: AsyncSession) -> dict[str, Any]:
    """
    Legacy path for agents that have no active_version_id yet.
    Reads directly from the agents + agent_tools tables.
    """
    tools_result = await db.execute(
        select(Tool, AgentTool.is_authorized)
        .join(AgentTool, AgentTool.tool_id == Tool.id)
        .where(
            and_(
                AgentTool.agent_id == agent.id,
                Tool.is_active.is_(True),
            )
        )
    )
    tools_rows = tools_result.all()

    tools_out = [
        {
            "tool_id": str(tool.id),
            "name": tool.name,
            "description": tool.description,
            "endpoint_url": tool.endpoint_url,
            "http_method": tool.http_method,
            "input_schema": tool.input_schema,
            "output_schema": tool.output_schema,
            "auth_type": tool.auth_type,
            "auth_config": tool.auth_config,
            "is_authorized": is_authorized,
            "parameter_constraints": {},
            "max_calls_per_turn": None,
            "timeout_ms": tool.timeout_ms,
            "max_response_bytes": tool.max_response_bytes,
            "is_cacheable": tool.is_cacheable,
            "cache_ttl_seconds": tool.cache_ttl_seconds,
        }
        for tool, is_authorized in tools_rows
    ]

    agent_out = {
        "id": str(agent.id),
        "tenant_id": str(agent.tenant_id),
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "model": agent.model,
        "max_steps": agent.max_steps,
        "token_budget": agent.token_budget,
        "session_timeout_seconds": agent.session_timeout_seconds,
        "memory_enabled": agent.memory_enabled,
        "is_active": agent.is_active,
        "active_version_id": None,
    }

    # Load egress allowlist for this tenant (same as versioned path)
    egress_result = await db.execute(
        select(EgressAllowlist).where(
            and_(EgressAllowlist.tenant_id == agent.tenant_id, EgressAllowlist.is_active.is_(True))
        )
    )
    egress_entries = [
        {"endpoint_pattern": e.endpoint_pattern, "port": e.port, "protocol": e.protocol}
        for e in egress_result.scalars().all()
    ]

    # Load output DLP policies for this tenant (tenant-scope and agent-scope)
    from app.models.policy import Policy
    policies_result = await db.execute(
        select(Policy).where(
            and_(
                Policy.tenant_id == agent.tenant_id,
                Policy.enabled.is_(True),
                Policy.policy_lang == "inline",
            )
        )
    )
    guardrail_policies = [
        {"scope": p.scope, "policy_body": p.policy_body}
        for p in policies_result.scalars().all()
    ]

    return {"agent": agent_out, "tools": tools_out, "egress_allowlist": egress_entries, "guardrail_policies": guardrail_policies}


# ---------------------------------------------------------------------------
# Internal route — called by session-service; not in public schema
# ---------------------------------------------------------------------------


@app.get(
    "/internal/agents/{agent_id}/full",
    tags=["internal"],
    include_in_schema=False,
)
async def get_agent_full(
    agent_id: uuid.UUID,
    request: Request,
    x_internal_secret: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return the full agent config plus all bound tools with schemas.
    Reads from AgentVersion + ToolBindings when available; falls back to
    the legacy agents/agent_tools tables for agents without a version.

    Secured by X-Internal-Secret header.
    """
    if x_internal_secret != settings.INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden: invalid or missing X-Internal-Secret.")

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")

    redis_client = getattr(request.app.state, "redis", None)
    tenant_id_str = str(agent.tenant_id)
    agent_id_str = str(agent_id)

    # ── Versioned path ─────────────────────────────────────────────────────
    if agent.active_version_id is not None:
        # Check Redis cache for the version snapshot
        cached_version_id = await config_cache.get_active_version(
            redis_client, tenant_id_str, agent_id_str
        )
        if cached_version_id is None:
            cached_version_id = str(agent.active_version_id)
            await config_cache.set_active_version(
                redis_client, tenant_id_str, agent_id_str, cached_version_id
            )

        cached_snapshot = await config_cache.get_version_snapshot(
            redis_client, tenant_id_str, cached_version_id
        )
        if cached_snapshot is not None:
            await config_publisher.publish(redis_client, tenant_id_str, agent_id_str, cached_snapshot)
            return cached_snapshot

        # Cache miss — build from DB
        v_result = await db.execute(
            select(AgentVersion).where(AgentVersion.id == agent.active_version_id)
        )
        version = v_result.scalar_one_or_none()
        if version is None:
            # Version row missing (shouldn't happen) — fall through to legacy
            pass
        else:
            config_data = await _build_versioned_config(agent, version, db)
            await config_cache.set_version_snapshot(
                redis_client, tenant_id_str, cached_version_id, config_data
            )
            await config_publisher.publish(redis_client, tenant_id_str, agent_id_str, config_data)
            return config_data

    # ── Legacy path (no active version) ────────────────────────────────────
    legacy_config = await _build_legacy_config(agent, db)
    await config_publisher.publish(redis_client, tenant_id_str, agent_id_str, legacy_config)
    return legacy_config
