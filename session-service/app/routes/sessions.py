"""
Session management routes.

Handles:
  POST /sessions            - Create a new session and run the first turn
  POST /sessions/{id}/messages - Continue an existing session
  GET  /sessions            - List sessions for a tenant
  GET  /sessions/{id}       - Get session details + conversation history
  DELETE /sessions/{id}     - Terminate a session
"""
import json
import logging
import time
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import agent_graph
from app.agent.state import AgentState
from app.database import get_db
from app.metrics import (
    budget_exceeded_total,
    llm_tokens_total,
    session_steps_total,
    sessions_created_total,
)
from app.middleware.tenant import get_tenant_id
from app.models.session import Session
from app.services.audit import publish_event
from app.services.config_client import ConfigClient
from app.services.memory_client import MemoryClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])

_config_client = ConfigClient()
_memory_client = MemoryClient()

# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    agent_id: str
    message: str


class ContinueSessionRequest(BaseModel):
    message: str


class SessionResponse(BaseModel):
    session_id: str
    agent_id: str
    tenant_id: str
    status: str
    step_count: int
    token_count: int
    response: Optional[str]
    created_at: datetime


class SessionListItem(BaseModel):
    session_id: str
    agent_id: str
    status: str
    step_count: int
    token_count: int
    created_at: datetime


class SessionDetail(BaseModel):
    session_id: str
    agent_id: str
    tenant_id: str
    status: str
    step_count: int
    token_count: int
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime]
    error_message: Optional[str]
    messages: List[dict]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATE_TTL = 60 * 60 * 24  # 24 hours
_TURN_LOCK_TTL_MS = 30_000  # 30 s — released early on success; TTL is a safety net


async def _acquire_turn_lock(redis_client, tenant_id: str, session_id: str) -> bool:
    """Acquire a per-session distributed lock. Returns True on success."""
    key = f"turn:lock:{tenant_id}:{session_id}"
    result = await redis_client.set(key, "1", nx=True, px=_TURN_LOCK_TTL_MS)
    return result is not None


async def _release_turn_lock(redis_client, tenant_id: str, session_id: str) -> None:
    key = f"turn:lock:{tenant_id}:{session_id}"
    await redis_client.delete(key)


async def _save_state_to_redis(redis_client, tenant_id: str, session_id: str, state: dict) -> None:
    """
    Serialise the agent state to Redis with a 24-hour TTL.
    Key is scoped by tenant_id to prevent cross-tenant state collisions.
    Increments the state version counter on every write for audit and
    optimistic-concurrency purposes.
    """
    key = f"{tenant_id}:session:{session_id}:state"
    try:
        state["version"] = state.get("version", 0) + 1
        serialised = json.dumps(state, default=str)
        await redis_client.set(key, serialised, ex=_STATE_TTL)
    except Exception as exc:
        logger.warning("_save_state_to_redis: failed for session %s: %s", session_id, exc)


async def _load_state_from_redis(redis_client, tenant_id: str, session_id: str) -> Optional[dict]:
    """Load and deserialise the agent state from Redis (tenant-scoped key)."""
    key = f"{tenant_id}:session:{session_id}:state"
    try:
        raw = await redis_client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning("_load_state_from_redis: failed for session %s: %s", session_id, exc)
        return None


def _build_initial_state(
    session_id: str,
    tenant_id: str,
    agent_id: str,
    user_message: str,
    redis_client,
) -> AgentState:
    """Build a fresh AgentState for the first turn of a session."""
    return AgentState(
        session_id=session_id,
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        # Config will be populated by load_config_node
        system_prompt="",
        model="",
        max_steps=10,
        token_budget=4096,
        session_timeout_seconds=300,
        memory_enabled=False,
        available_tools=[],
        tool_configs={},
        # Runtime
        messages=[{"role": "user", "content": user_message}],
        step_count=0,
        token_count=0,
        start_time=time.time(),
        # Caching / DLP
        prompt_cache_key=None,
        guardrail_policies=[],
        # Control
        budget_exceeded=False,
        budget_reason="",
        # Routing
        route_to_agent_id=None,
        route_message=None,
        # Final
        final_response=None,
        error=None,
        egress_allowlist=[],
        # Internal — not persisted in DB, injected at runtime
        _redis=redis_client,  # type: ignore[typeddict-item]
    )


async def _run_graph(state: dict, redis_client) -> dict:
    """
    Invoke the compiled LangGraph agent_graph.

    Injects the Redis client into the state so nodes like route_to_agent_node
    can publish stream events without importing the global.
    """
    state["_redis"] = redis_client
    try:
        final_state = await agent_graph.ainvoke(state)
    except Exception as exc:
        logger.exception("_run_graph: unhandled exception during graph execution")
        state["error"] = f"Graph execution error: {exc}"
        state["final_response"] = "An internal error occurred. Please try again."
        return state
    # Inject redis back (it won't survive JSON serialisation but is fine)
    final_state["_redis"] = redis_client
    return final_state


async def _update_session_from_result(
    db: AsyncSession,
    session: Session,
    final_state: dict,
) -> None:
    """Persist step/token counts and final status to the DB session row."""
    session.step_count = final_state.get("step_count", session.step_count)
    session.token_count = final_state.get("token_count", session.token_count)
    session.updated_at = datetime.utcnow()

    if final_state.get("error") and not final_state.get("final_response", "").startswith("Task routed"):
        session.status = "error"
        session.error_message = final_state["error"]
        session.completed_at = datetime.utcnow()
    elif final_state.get("budget_exceeded"):
        session.status = "budget_exceeded"
        session.completed_at = datetime.utcnow()
    else:
        session.status = "completed"
        session.completed_at = datetime.utcnow()

    db.add(session)
    await db.flush()


# ---------------------------------------------------------------------------
# POST /sessions  — create session and run first turn
# ---------------------------------------------------------------------------

@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    request: Request,
    body: CreateSessionRequest,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    redis_client = request.app.state.redis

    # Validate agent_id is a UUID
    try:
        agent_uuid = uuid.UUID(body.agent_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"agent_id '{body.agent_id}' is not a valid UUID",
        )

    # Soft-validate agent existence — fail gracefully on network error
    agent_exists = await _config_client.agent_exists(str(agent_uuid), str(tenant_id))
    if not agent_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{body.agent_id}' not found or not accessible for this tenant",
        )

    # Create DB session row
    session = Session(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        agent_id=agent_uuid,
        status="active",
        step_count=0,
        token_count=0,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(session)
    await db.flush()
    session_id = str(session.id)

    # Build initial state and save before running
    initial_state = _build_initial_state(
        session_id=session_id,
        tenant_id=tenant_id,
        agent_id=agent_uuid,
        user_message=body.message,
        redis_client=redis_client,
    )
    await _save_state_to_redis(redis_client, str(tenant_id), session_id, dict(initial_state))

    # Publish session_start audit event
    await publish_event(
        redis_client,
        "session_start",
        session_id=session_id,
        tenant_id=str(tenant_id),
        agent_id=str(agent_uuid),
    )

    # Run the agent graph
    final_state = await _run_graph(dict(initial_state), redis_client)

    # Update DB
    await _update_session_from_result(db, session, final_state)

    # Save final state to Redis (drop non-serialisable _redis key)
    state_to_save = {k: v for k, v in final_state.items() if k != "_redis"}
    await _save_state_to_redis(redis_client, str(tenant_id), session_id, state_to_save)

    # Update activity sorted set — enables efficient listing by last-active time
    # without a full DB scan.  Score = Unix timestamp.
    try:
        await redis_client.zadd(
            f"{tenant_id}:sessions:by_activity",
            {session_id: time.time()},
        )
    except Exception as exc:
        logger.debug("create_session: activity index update failed (non-fatal): %s", exc)

    # Publish session_complete audit event
    await publish_event(
        redis_client,
        "session_complete",
        session_id=session_id,
        tenant_id=str(tenant_id),
        agent_id=str(agent_uuid),
        status=session.status,
        step_count=session.step_count,
        token_count=session.token_count,
    )

    # Update Prometheus metrics
    sessions_created_total.labels(
        tenant_id=str(tenant_id), agent_id=str(agent_uuid)
    ).inc()
    session_steps_total.labels(
        tenant_id=str(tenant_id), agent_id=str(agent_uuid)
    ).inc(final_state.get("step_count", 0))
    llm_tokens_total.labels(
        tenant_id=str(tenant_id),
        agent_id=str(agent_uuid),
        model=final_state.get("model", "unknown"),
    ).inc(final_state.get("token_count", 0))

    if final_state.get("budget_exceeded"):
        budget_exceeded_total.labels(
            tenant_id=str(tenant_id),
            agent_id=str(agent_uuid),
            reason=final_state.get("budget_reason", "unknown"),
        ).inc()

    # Persist messages to memory service if enabled
    if final_state.get("memory_enabled"):
        try:
            await _memory_client.append_message(
                str(tenant_id), session_id, "user", body.message
            )
            assistant_reply = final_state.get("final_response") or ""
            if assistant_reply:
                await _memory_client.append_message(
                    str(tenant_id), session_id, "assistant", assistant_reply
                )
        except Exception as exc:
            logger.warning("create_session: memory append failed: %s", exc)

    return SessionResponse(
        session_id=session_id,
        agent_id=str(agent_uuid),
        tenant_id=str(tenant_id),
        status=session.status,
        step_count=session.step_count,
        token_count=session.token_count,
        response=final_state.get("final_response"),
        created_at=session.created_at,
    )


# ---------------------------------------------------------------------------
# POST /sessions/{session_id}/messages  — continue an existing session
# ---------------------------------------------------------------------------

@router.post("/{session_id}/messages", response_model=SessionResponse)
async def continue_session(
    session_id: str,
    request: Request,
    body: ContinueSessionRequest,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SessionResponse:
    redis_client = request.app.state.redis

    # Validate session_id format
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session_id format",
        )

    # Load session from DB
    result = await db.execute(select(Session).where(Session.id == session_uuid))
    session: Optional[Session] = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if str(session.tenant_id) != str(tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if session.status not in ("active", "completed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Session is not continuable (status='{session.status}')",
        )

    # Load persisted state from Redis
    persisted_state = await _load_state_from_redis(redis_client, str(tenant_id), session_id)
    if persisted_state is None:
        # State expired or was never saved — rebuild from DB and restart
        logger.warning("continue_session: no Redis state for %s, rebuilding", session_id)
        persisted_state = _build_initial_state(
            session_id=session_id,
            tenant_id=tenant_id,
            agent_id=session.agent_id,
            user_message=body.message,
            redis_client=redis_client,
        )
        persisted_state = dict(persisted_state)
    else:
        # Append the new user message to the existing conversation
        messages = persisted_state.get("messages", [])
        messages.append({"role": "user", "content": body.message})
        persisted_state["messages"] = messages

        # Reset per-turn start_time; keep cumulative step/token counts
        persisted_state["start_time"] = time.time()
        # Re-open the session
        persisted_state["budget_exceeded"] = False
        persisted_state["budget_reason"] = ""
        persisted_state["final_response"] = None
        persisted_state["error"] = None
        persisted_state["route_to_agent_id"] = None
        persisted_state["route_message"] = None

    # Acquire per-session turn lock to prevent concurrent turns corrupting state
    lock_acquired = await _acquire_turn_lock(redis_client, str(tenant_id), session_id)
    if not lock_acquired:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Another turn is already in progress for this session. Please wait.",
        )

    # Mark session active again
    session.status = "active"
    session.updated_at = datetime.utcnow()
    db.add(session)
    await db.flush()

    # Run graph
    try:
        final_state = await _run_graph(persisted_state, redis_client)
    finally:
        await _release_turn_lock(redis_client, str(tenant_id), session_id)

    # Update DB
    await _update_session_from_result(db, session, final_state)

    # Save state
    state_to_save = {k: v for k, v in final_state.items() if k != "_redis"}
    await _save_state_to_redis(redis_client, str(tenant_id), session_id, state_to_save)

    # Update activity sorted set
    try:
        await redis_client.zadd(
            f"{tenant_id}:sessions:by_activity",
            {session_id: time.time()},
        )
    except Exception as exc:
        logger.debug("continue_session: activity index update failed (non-fatal): %s", exc)

    # Audit
    await publish_event(
        redis_client,
        "session_turn",
        session_id=session_id,
        tenant_id=str(tenant_id),
        agent_id=str(session.agent_id),
        step_count=session.step_count,
        token_count=session.token_count,
    )

    # Metrics
    session_steps_total.labels(
        tenant_id=str(tenant_id), agent_id=str(session.agent_id)
    ).inc(final_state.get("step_count", 0) - session.step_count)
    llm_tokens_total.labels(
        tenant_id=str(tenant_id),
        agent_id=str(session.agent_id),
        model=final_state.get("model", "unknown"),
    ).inc(max(0, final_state.get("token_count", 0) - session.token_count))

    if final_state.get("budget_exceeded"):
        budget_exceeded_total.labels(
            tenant_id=str(tenant_id),
            agent_id=str(session.agent_id),
            reason=final_state.get("budget_reason", "unknown"),
        ).inc()

    # Memory
    if final_state.get("memory_enabled"):
        try:
            await _memory_client.append_message(
                str(tenant_id), session_id, "user", body.message
            )
            assistant_reply = final_state.get("final_response") or ""
            if assistant_reply:
                await _memory_client.append_message(
                    str(tenant_id), session_id, "assistant", assistant_reply
                )
        except Exception as exc:
            logger.warning("continue_session: memory append failed: %s", exc)

    return SessionResponse(
        session_id=session_id,
        agent_id=str(session.agent_id),
        tenant_id=str(tenant_id),
        status=session.status,
        step_count=session.step_count,
        token_count=session.token_count,
        response=final_state.get("final_response"),
        created_at=session.created_at,
    )


# ---------------------------------------------------------------------------
# GET /sessions  — list tenant sessions
# ---------------------------------------------------------------------------

@router.get("", response_model=List[SessionListItem])
async def list_sessions(
    request: Request,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
) -> List[SessionListItem]:
    result = await db.execute(
        select(Session)
        .where(Session.tenant_id == tenant_id)
        .order_by(Session.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    sessions = result.scalars().all()

    return [
        SessionListItem(
            session_id=str(s.id),
            agent_id=str(s.agent_id),
            status=s.status,
            step_count=s.step_count,
            token_count=s.token_count,
            created_at=s.created_at,
        )
        for s in sessions
    ]


# ---------------------------------------------------------------------------
# GET /sessions/{session_id}  — session detail with history
# ---------------------------------------------------------------------------

@router.get("/{session_id}", response_model=SessionDetail)
async def get_session(
    session_id: str,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> SessionDetail:
    redis_client = request.app.state.redis

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session_id format"
        )

    result = await db.execute(select(Session).where(Session.id == session_uuid))
    session: Optional[Session] = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if str(session.tenant_id) != str(tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Load conversation history from Redis
    persisted_state = await _load_state_from_redis(redis_client, str(session.tenant_id), session_id)
    messages: List[dict] = []
    if persisted_state:
        raw_messages = persisted_state.get("messages", [])
        # Filter out internal _redis key and strip tool call details for cleanliness
        messages = [
            {k: v for k, v in m.items() if k != "_redis"}
            for m in raw_messages
            if isinstance(m, dict)
        ]

    return SessionDetail(
        session_id=session_id,
        agent_id=str(session.agent_id),
        tenant_id=str(session.tenant_id),
        status=session.status,
        step_count=session.step_count,
        token_count=session.token_count,
        created_at=session.created_at,
        updated_at=session.updated_at,
        completed_at=session.completed_at,
        error_message=session.error_message,
        messages=messages,
    )


# ---------------------------------------------------------------------------
# DELETE /sessions/{session_id}  — terminate a session
# ---------------------------------------------------------------------------

@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    request: Request,
    tenant_id: uuid.UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> None:
    redis_client = request.app.state.redis

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid session_id format"
        )

    result = await db.execute(select(Session).where(Session.id == session_uuid))
    session: Optional[Session] = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if str(session.tenant_id) != str(tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    session.status = "terminated"
    session.updated_at = datetime.utcnow()
    session.completed_at = datetime.utcnow()
    db.add(session)

    # Publish termination event
    await publish_event(
        redis_client,
        "session_terminated",
        session_id=session_id,
        tenant_id=str(tenant_id),
        agent_id=str(session.agent_id),
    )
