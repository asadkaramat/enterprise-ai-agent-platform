"""
Agent CRUD E2E tests.
"""
import pytest


def test_create_agent(client, auth):
    r = client.post(
        "/api/agents",
        json={
            "name": "CRUD Test Agent",
            "system_prompt": "You are helpful.",
            "model": "llama3.2",
            "max_steps": 5,
            "token_budget": 4096,
            "session_timeout_seconds": 120,
            "memory_enabled": False,
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["name"] == "CRUD Test Agent"
    assert data["model"] == "llama3.2"
    assert "id" in data
    # Cleanup
    client.delete(f"/api/agents/{data['id']}", headers=auth)


def test_list_agents(client, auth, agent):
    r = client.get("/api/agents", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body
    ids = [a["id"] for a in body["items"]]
    assert agent["id"] in ids


def test_get_agent(client, auth, agent):
    r = client.get(f"/api/agents/{agent['id']}", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == agent["id"]
    assert data["name"] == agent["name"]


def test_get_agent_not_found(client, auth):
    r = client.get("/api/agents/00000000-0000-0000-0000-000000000000", headers=auth)
    assert r.status_code == 404


def test_update_agent(client, auth, agent):
    r = client.put(
        f"/api/agents/{agent['id']}",
        json={"name": "Updated Name", "max_steps": 7},
        headers=auth,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Updated Name"
    assert data["max_steps"] == 7


def test_delete_agent(client, auth):
    r = client.post(
        "/api/agents",
        json={
            "name": "To Delete",
            "system_prompt": "delete me",
            "model": "llama3.2",
        },
        headers=auth,
    )
    assert r.status_code == 201
    aid = r.json()["id"]

    r = client.delete(f"/api/agents/{aid}", headers=auth)
    assert r.status_code == 204

    # Should no longer appear in list
    r = client.get("/api/agents", headers=auth)
    ids = [a["id"] for a in r.json()["items"]]
    assert aid not in ids


def test_tenant_isolation(client, tenant):
    """Agents created by one tenant must not be visible to another."""
    from conftest import admin_headers, api_headers
    r = client.post(
        "/admin/tenants",
        json={"name": "Isolation Tenant"},
        headers=admin_headers(),
    )
    other = r.json()
    other_auth = api_headers(other["api_key"])

    # Create agent as the other tenant
    r = client.post(
        "/api/agents",
        json={"name": "Other Tenant Agent", "system_prompt": "s", "model": "llama3.2"},
        headers=other_auth,
    )
    assert r.status_code == 201
    other_agent_id = r.json()["id"]

    # Main tenant cannot see it
    r = client.get("/api/agents", headers=api_headers(tenant["api_key"]))
    ids = [a["id"] for a in r.json()["items"]]
    assert other_agent_id not in ids

    # Cleanup
    client.delete(f"/api/agents/{other_agent_id}", headers=other_auth)
    client.delete(f"/admin/tenants/{other['tenant_id']}", headers=admin_headers())
