import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.middleware.tenant import get_tenant_id
from app.metrics import (
    memory_append_total,
    memory_retrieve_total,
    memory_store_long_total,
)
from app.models.memory import (
    AppendMessageRequest,
    MemoryItem,
    MessageItem,
    RetrieveRequest,
    RetrieveResponse,
    SessionEndRequest,
    StoreMemoryRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/memory", tags=["memory"])

TenantID = Annotated[str, Depends(get_tenant_id)]


# ---------------------------------------------------------------------------
# Short-term memory routes
# ---------------------------------------------------------------------------


@router.post("/short/append", status_code=204)
async def append_message(
    body: AppendMessageRequest,
    request: Request,
    tenant_id: TenantID,
):
    """Append a message to the short-term (Redis) memory for a session."""
    short_term = request.app.state.short_term
    await short_term.append_message(
        tenant_id=tenant_id,
        session_id=body.session_id,
        role=body.role,
        content=body.content,
    )
    memory_append_total.labels(tenant_id=tenant_id).inc()
    return None


@router.get("/short/{session_id}", response_model=list[MessageItem])
async def get_history(
    session_id: str,
    request: Request,
    tenant_id: TenantID,
):
    """Return the full message history for a session from Redis."""
    short_term = request.app.state.short_term
    history = await short_term.get_history(
        tenant_id=tenant_id, session_id=session_id
    )
    return history


@router.get("/short/{session_id}/context", response_model=list[MessageItem])
async def get_context_window(
    session_id: str,
    request: Request,
    tenant_id: TenantID,
    max_messages: int = Query(default=20, ge=1, le=50),
):
    """Return the most recent N messages from a session's Redis history."""
    short_term = request.app.state.short_term
    window = await short_term.get_context_window(
        tenant_id=tenant_id,
        session_id=session_id,
        max_messages=max_messages,
    )
    return window


@router.delete("/short/{session_id}", status_code=204)
async def clear_session(
    session_id: str,
    request: Request,
    tenant_id: TenantID,
):
    """Delete the short-term memory for a session from Redis."""
    short_term = request.app.state.short_term
    await short_term.clear_session(tenant_id=tenant_id, session_id=session_id)
    return None


# ---------------------------------------------------------------------------
# Long-term memory routes
# ---------------------------------------------------------------------------


@router.post("/long/store", status_code=204)
async def store_memory(
    body: StoreMemoryRequest,
    request: Request,
    tenant_id: TenantID,
):
    """Embed and store a memory entry in the Qdrant vector store."""
    long_term = request.app.state.long_term
    await long_term.store_memory(
        tenant_id=tenant_id,
        session_id=body.session_id,
        agent_id=body.agent_id,
        content=body.content,
        metadata=body.metadata or {},
    )
    memory_store_long_total.labels(tenant_id=tenant_id).inc()
    return None


@router.delete("/long/{session_id}", status_code=204)
async def delete_long_term_session(
    session_id: str,
    request: Request,
    tenant_id: TenantID,
):
    """Remove all long-term memories for a session from Qdrant."""
    long_term = request.app.state.long_term
    await long_term.delete_session_memories(
        tenant_id=tenant_id, session_id=session_id
    )
    return None


# ---------------------------------------------------------------------------
# Combined routes
# ---------------------------------------------------------------------------


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_memories(
    body: RetrieveRequest,
    request: Request,
    tenant_id: TenantID,
):
    """Semantic search across long-term memories for the tenant."""
    long_term = request.app.state.long_term
    results = await long_term.retrieve_similar(
        tenant_id=tenant_id,
        query=body.query,
        top_k=body.top_k or 5,
    )
    memory_retrieve_total.labels(tenant_id=tenant_id).inc()
    memories = [
        MemoryItem(
            content=r["content"],
            score=r["score"],
            session_id=r["session_id"],
            timestamp=r["timestamp"],
        )
        for r in results
    ]
    return RetrieveResponse(memories=memories)


@router.post("/session/end")
async def end_session(
    body: SessionEndRequest,
    request: Request,
    tenant_id: TenantID,
):
    """
    Consolidate a session into long-term memory:
      1. Fetch the last 10 messages from short-term Redis.
      2. Store every assistant message into Qdrant.
      3. Clear the short-term session from Redis.
    Returns {"stored": <count>, "cleared": true}.
    """
    short_term = request.app.state.short_term
    long_term = request.app.state.long_term

    # Step 1 – fetch last 10 messages
    recent = await short_term.get_context_window(
        tenant_id=tenant_id,
        session_id=body.session_id,
        max_messages=10,
    )

    # Step 2 – persist assistant messages to long-term memory
    stored = 0
    for msg in recent:
        if msg.get("role") == "assistant":
            await long_term.store_memory(
                tenant_id=tenant_id,
                session_id=body.session_id,
                agent_id=body.agent_id,
                content=msg["content"],
                metadata={"source": "session_end"},
            )
            memory_store_long_total.labels(tenant_id=tenant_id).inc()
            stored += 1

    # Step 3 – clear short-term session
    await short_term.clear_session(
        tenant_id=tenant_id, session_id=body.session_id
    )

    logger.info(
        "Session end: tenant=%s session=%s stored=%d",
        tenant_id,
        body.session_id,
        stored,
    )
    return {"stored": stored, "cleared": True}
