"""
Tenant management E2E tests.
"""
import pytest
from conftest import admin_headers, api_headers, GATEWAY
import httpx


def test_create_tenant_success(client):
    r = client.post(
        "/admin/tenants",
        json={"name": "Temp Tenant", "rate_limit_per_minute": 30},
        headers=admin_headers(),
    )
    assert r.status_code in (200, 201)
    data = r.json()
    assert "tenant_id" in data
    assert "api_key" in data
    assert data["api_key"].startswith("tap_")
    assert "name" in data
    # Cleanup
    client.delete(f"/admin/tenants/{data['tenant_id']}", headers=admin_headers())


def test_create_tenant_missing_name(client):
    r = client.post(
        "/admin/tenants",
        json={"rate_limit_per_minute": 30},
        headers=admin_headers(),
    )
    assert r.status_code == 422


def test_create_tenant_wrong_admin_secret(client):
    r = client.post(
        "/admin/tenants",
        json={"name": "Bad Auth"},
        headers={"X-Admin-Secret": "wrong-secret", "Content-Type": "application/json"},
    )
    assert r.status_code in (401, 403)


def test_list_tenants(client, tenant):
    r = client.get("/admin/tenants", headers=admin_headers())
    assert r.status_code == 200
    tenants = r.json()
    assert isinstance(tenants, list)
    ids = [t["id"] for t in tenants]
    assert tenant["id"] in ids


def test_rotate_api_key(client):
    # Create a throwaway tenant
    r = client.post(
        "/admin/tenants",
        json={"name": "Rotate Key Test"},
        headers=admin_headers(),
    )
    data = r.json()
    tid = data["tenant_id"]
    old_key = data["api_key"]

    r = client.post(f"/admin/tenants/{tid}/rotate-key", headers=admin_headers())
    assert r.status_code == 200
    new_key = r.json()["api_key"]
    assert new_key != old_key
    assert new_key.startswith("tap_")

    # Old key must now be rejected
    r = client.get("/api/agents", headers=api_headers(old_key))
    assert r.status_code == 401

    # New key must work
    r = client.get("/api/agents", headers=api_headers(new_key))
    assert r.status_code == 200

    client.delete(f"/admin/tenants/{tid}", headers=admin_headers())


def test_api_key_required(client):
    r = client.get("/api/agents")
    assert r.status_code == 401


def test_invalid_api_key_rejected(client):
    r = client.get("/api/agents", headers={"X-API-Key": "tap_totallyinvalid"})
    assert r.status_code == 401


def test_rate_limit_enforced(client):
    """Create a tenant with limit=2 and hit it 5 times; expect 429."""
    r = client.post(
        "/admin/tenants",
        json={"name": "Rate Limit Test", "rate_limit_per_minute": 2},
        headers=admin_headers(),
    )
    data = r.json()
    tid = data["tenant_id"]
    key = data["api_key"]
    headers = api_headers(key)

    statuses = [client.get("/api/agents", headers=headers).status_code for _ in range(5)]
    assert 429 in statuses, f"Expected a 429 among {statuses}"

    client.delete(f"/admin/tenants/{tid}", headers=admin_headers())
