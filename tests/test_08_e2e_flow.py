"""
Full end-to-end flow tests that exercise the entire platform in sequence.
"""
import time
import pytest


def test_full_agent_lifecycle(client, auth, tenant):
    """
    Complete flow:
      1. Create agent
      2. Register tool and bind to agent
      3. Start a multi-turn session
      4. Verify audit trail
      5. Delete session, tool, agent
    """
    from conftest import api_headers

    hdrs = api_headers(tenant["api_key"])

    # 1. Create agent
    r = client.post(
        "/api/agents",
        json={
            "name": "Lifecycle Agent",
            "system_prompt": "You are a concise assistant.",
            "model": "llama3.2",
            "max_steps": 5,
            "token_budget": 8000,
            "memory_enabled": False,
        },
        headers=hdrs,
    )
    assert r.status_code == 201
    agent_id = r.json()["id"]

    # 2. Register a tool
    r = client.post(
        "/api/tools",
        json={
            "name": "lifecycle_tool",
            "description": "A lifecycle test tool",
            "endpoint_url": "https://httpbin.org/post",
            "http_method": "POST",
        },
        headers=hdrs,
    )
    assert r.status_code == 201
    tool_id = r.json()["id"]

    # Bind tool to agent
    r = client.post(f"/api/agents/{agent_id}/tools/{tool_id}", headers=hdrs)
    assert r.status_code == 201

    # Verify tool shows on agent
    r = client.get(f"/api/agents/{agent_id}/tools", headers=hdrs)
    assert any(t["tool_id"] == tool_id for t in r.json())

    # 3. Multi-turn session
    r = client.post(
        "/api/sessions",
        json={"agent_id": agent_id, "message": "What is the capital of France? Reply in one sentence."},
        headers=hdrs,
    )
    assert r.status_code == 201
    session_id = r.json()["session_id"]
    response_text = r.json()["response"].lower()
    assert "paris" in response_text or "france" in response_text, f"Unexpected response: {r.json()['response']}"

    r = client.post(
        f"/api/sessions/{session_id}/messages",
        json={"message": "And what is its population?"},
        headers=hdrs,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"

    # Verify session detail contains both turns
    r = client.get(f"/api/sessions/{session_id}", headers=hdrs)
    msgs = r.json()["messages"]
    roles = [m["role"] for m in msgs]
    assert roles.count("user") >= 2
    assert roles.count("assistant") >= 2

    # 4. Audit trail
    time.sleep(2)
    r = client.get("/api/audit/usage/summary", headers=hdrs)
    assert r.json()["total_sessions"] >= 1

    # 5. Cleanup
    client.delete(f"/api/sessions/{session_id}", headers=hdrs)
    client.delete(f"/api/agents/{agent_id}/tools/{tool_id}", headers=hdrs)
    client.delete(f"/api/tools/{tool_id}", headers=hdrs)
    client.delete(f"/api/agents/{agent_id}", headers=hdrs)


def test_new_tenant_full_onboarding(client):
    """
    Simulate a brand-new customer onboarding:
      1. Admin creates tenant → gets API key
      2. Tenant creates an agent
      3. Tenant starts a session
      4. Admin lists tenants — new tenant appears
      5. Admin deletes tenant
    """
    from conftest import admin_headers, api_headers

    # 1. Create tenant
    r = client.post(
        "/admin/tenants",
        json={"name": "New Customer Inc", "rate_limit_per_minute": 60},
        headers=admin_headers(),
    )
    assert r.status_code in (200, 201)
    tenant_id = r.json()["tenant_id"]
    api_key = r.json()["api_key"]
    hdrs = api_headers(api_key)

    # 2. Create agent
    r = client.post(
        "/api/agents",
        json={
            "name": "Onboarding Agent",
            "system_prompt": "You are a helpful onboarding assistant.",
            "model": "llama3.2",
            "max_steps": 3,
            "token_budget": 4096,
            "memory_enabled": False,
        },
        headers=hdrs,
    )
    assert r.status_code == 201
    agent_id = r.json()["id"]

    # 3. Start session
    r = client.post(
        "/api/sessions",
        json={"agent_id": agent_id, "message": "Hello, I am a new user."},
        headers=hdrs,
    )
    assert r.status_code == 201
    assert r.json()["status"] == "completed"

    # 4. Admin sees the tenant
    r = client.get("/admin/tenants", headers=admin_headers())
    ids = [t["id"] for t in r.json()]
    assert tenant_id in ids

    # 5. Cleanup
    client.delete(f"/api/agents/{agent_id}", headers=hdrs)
    client.delete(f"/admin/tenants/{tenant_id}", headers=admin_headers())


def test_concurrent_sessions(client, auth, agent):
    """Start three sessions in sequence and verify all complete successfully."""
    session_ids = []
    for i in range(3):
        r = client.post(
            "/api/sessions",
            json={"agent_id": agent["id"], "message": f"Concurrent test message {i}"},
            headers=auth,
        )
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "completed"
        session_ids.append(r.json()["session_id"])

    # All sessions should appear in list
    r = client.get("/api/sessions", headers=auth)
    listed_ids = [s["session_id"] for s in r.json()]
    for sid in session_ids:
        assert sid in listed_ids
