"""
Audit service E2E tests.
"""
import time
import pytest


def test_usage_summary(client, auth):
    r = client.get("/api/audit/usage/summary", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "total_sessions" in data
    assert "total_tokens" in data
    assert "estimated_cost_usd" in data
    assert isinstance(data["total_sessions"], int)
    assert isinstance(data["total_tokens"], int)


def test_usage_summary_counts_sessions(client, auth, agent):
    # Get baseline
    before = client.get("/api/audit/usage/summary", headers=auth).json()["total_sessions"]

    client.post(
        "/api/sessions",
        json={"agent_id": agent["id"], "message": "audit count test"},
        headers=auth,
    )
    time.sleep(2)  # Redis stream consumer writes to PG asynchronously

    after = client.get("/api/audit/usage/summary", headers=auth).json()["total_sessions"]
    assert after >= before + 1, f"Session count did not increase: {before} → {after}"


def test_usage_by_agent(client, auth, agent):
    client.post(
        "/api/sessions",
        json={"agent_id": agent["id"], "message": "by-agent test"},
        headers=auth,
    )
    time.sleep(2)

    r = client.get("/api/audit/usage/by-agent", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "agents" in data
    assert isinstance(data["agents"], list)


def test_audit_events_list(client, auth, agent):
    client.post(
        "/api/sessions",
        json={"agent_id": agent["id"], "message": "events list test"},
        headers=auth,
    )
    time.sleep(2)

    r = client.get("/api/audit/events", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "events" in data
    assert isinstance(data["events"], list)


def test_session_timeline(client, auth, agent):
    r = client.post(
        "/api/sessions",
        json={"agent_id": agent["id"], "message": "timeline test"},
        headers=auth,
    )
    session_id = r.json()["session_id"]
    time.sleep(2)

    r = client.get(f"/api/audit/sessions/{session_id}/timeline", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["session_id"] == session_id
    assert "events" in data


def test_tool_adoption(client, auth):
    r = client.get("/api/audit/usage/tool-adoption", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "tools" in data


def test_audit_tenant_isolation(client, tenant, agent):
    """Audit data from one tenant must not be visible to another."""
    from conftest import admin_headers, api_headers

    r = client.post(
        "/admin/tenants",
        json={"name": "Audit Isolation Tenant"},
        headers=admin_headers(),
    )
    other = r.json()
    other_auth = api_headers(other["api_key"])

    # Other tenant's summary should have zero sessions initially
    r = client.get("/api/audit/usage/summary", headers=other_auth)
    assert r.status_code == 200
    assert r.json()["total_sessions"] == 0

    client.delete(f"/admin/tenants/{other['tenant_id']}", headers=admin_headers())
