"""
Memory service E2E tests (short-term Redis + long-term Qdrant).

The memory service requires an X-Tenant-ID header on direct calls.
Schemas (from openapi.json):
  AppendMessageRequest: session_id, role, content
  StoreMemoryRequest:   session_id, agent_id, content, metadata?
  RetrieveRequest:      session_id, query, top_k?
  /retrieve response:   {"memories": [...]}
"""
import time
import httpx
import pytest

MEMORY_BASE = "http://localhost:8003"
TEST_AGENT_ID = "00000000-0000-0000-0000-000000000001"  # placeholder for direct tests


def mem_headers(tenant_id: str) -> dict:
    return {"X-Tenant-ID": tenant_id, "Content-Type": "application/json"}


def test_append_short_term_memory(tenant):
    r = httpx.post(
        f"{MEMORY_BASE}/memory/short/append",
        json={
            "session_id": "test-session-mem",
            "role": "user",
            "content": "Hello from E2E",
        },
        headers=mem_headers(tenant["id"]),
        timeout=10,
    )
    assert r.status_code == 204, r.text


def test_retrieve_short_term_memory(tenant):
    session_id = "test-session-retrieve-2"

    # Append a message
    httpx.post(
        f"{MEMORY_BASE}/memory/short/append",
        json={"session_id": session_id, "role": "user", "content": "Short-term E2E content"},
        headers=mem_headers(tenant["id"]),
        timeout=10,
    )

    # Retrieve
    r = httpx.get(
        f"{MEMORY_BASE}/memory/short/{session_id}",
        headers=mem_headers(tenant["id"]),
        timeout=10,
    )
    assert r.status_code == 200, r.text
    messages = r.json()
    assert isinstance(messages, list)
    assert any("Short-term E2E content" in m.get("content", "") for m in messages)


def test_store_long_term_memory(tenant):
    r = httpx.post(
        f"{MEMORY_BASE}/memory/long/store",
        json={
            "session_id": "test-session-long",
            "agent_id": TEST_AGENT_ID,
            "content": "The user prefers dark mode and concise answers.",
            "metadata": {"source": "e2e-test"},
        },
        headers=mem_headers(tenant["id"]),
        timeout=15,
    )
    assert r.status_code == 204, r.text


def test_retrieve_long_term_memory(tenant):
    session_id = "test-session-long-retrieve-2"
    content = "The user is a senior Python engineer who dislikes verbose explanations."

    # Store
    httpx.post(
        f"{MEMORY_BASE}/memory/long/store",
        json={"session_id": session_id, "agent_id": TEST_AGENT_ID, "content": content},
        headers=mem_headers(tenant["id"]),
        timeout=15,
    )

    time.sleep(1)  # give Qdrant a moment to index

    # Retrieve — response is {"memories": [...]}
    r = httpx.post(
        f"{MEMORY_BASE}/memory/retrieve",
        json={"session_id": session_id, "query": "Python developer preferences", "top_k": 3},
        headers=mem_headers(tenant["id"]),
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    memories = body.get("memories", body) if isinstance(body, dict) else body
    assert isinstance(memories, list)
    found = any(content in m.get("content", "") for m in memories)
    assert found, f"Stored content not found in memories: {memories}"


def test_memory_enabled_agent_retrieves_context(client, tenant):
    """
    Create a memory-enabled agent, run two sessions, and verify the second
    session succeeds (memory context is fetched without errors).
    """
    from conftest import api_headers

    hdrs = api_headers(tenant["api_key"])

    r = client.post(
        "/api/agents",
        json={
            "name": "Memory Agent",
            "system_prompt": "You are helpful. Use context from memory when available.",
            "model": "llama3.2",
            "max_steps": 3,
            "token_budget": 4096,
            "session_timeout_seconds": 120,
            "memory_enabled": True,
        },
        headers=hdrs,
    )
    assert r.status_code == 201
    agent_id = r.json()["id"]

    client.post(
        "/api/sessions",
        json={"agent_id": agent_id, "message": "My favourite colour is turquoise."},
        headers=hdrs,
    )
    time.sleep(2)

    r2 = client.post(
        "/api/sessions",
        json={"agent_id": agent_id, "message": "What is my favourite colour?"},
        headers=hdrs,
    )
    assert r2.status_code == 201
    assert r2.json()["status"] == "completed"

    client.delete(f"/api/agents/{agent_id}", headers=hdrs)
