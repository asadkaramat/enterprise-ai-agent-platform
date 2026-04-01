"""
Policy CRUD E2E tests.
Covers: tenant/agent/tool scoped policies, inline/rego/cedar languages,
        validation, update/disable, tenant isolation.
"""
import pytest


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_tenant_policy(client, auth):
    r = client.post(
        "/api/policies",
        json={
            "name": "no-ssn-policy",
            "scope": "tenant",
            "policy_lang": "inline",
            "policy_body": "block_pattern: \\d{3}-\\d{2}-\\d{4}",
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["name"] == "no-ssn-policy"
    assert data["scope"] == "tenant"
    assert data["scope_ref_id"] is None
    assert data["policy_lang"] == "inline"
    assert data["enabled"] is True
    assert data["version"] == 1
    assert "id" in data

    # Cleanup
    client.delete(f"/api/policies/{data['id']}", headers=auth)


def test_create_agent_policy(client, auth, agent):
    r = client.post(
        "/api/policies",
        json={
            "name": "agent-dlp",
            "scope": "agent",
            "scope_ref_id": agent["id"],
            "policy_lang": "inline",
            "policy_body": "deny_all: false",
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["scope"] == "agent"
    assert data["scope_ref_id"] == agent["id"]

    client.delete(f"/api/policies/{data['id']}", headers=auth)


def test_create_tool_policy(client, auth, tool):
    r = client.post(
        "/api/policies",
        json={
            "name": "tool-rate-policy",
            "scope": "tool",
            "scope_ref_id": tool["id"],
            "policy_lang": "inline",
            "policy_body": "max_calls: 10",
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["scope"] == "tool"
    assert data["scope_ref_id"] == tool["id"]

    client.delete(f"/api/policies/{data['id']}", headers=auth)


def test_create_policy_invalid_scope(client, auth):
    r = client.post(
        "/api/policies",
        json={
            "name": "bad",
            "scope": "galaxy",
            "policy_lang": "inline",
            "policy_body": "x",
        },
        headers=auth,
    )
    assert r.status_code == 400


def test_create_policy_agent_scope_missing_scope_ref(client, auth):
    """agent/tool scope requires scope_ref_id."""
    r = client.post(
        "/api/policies",
        json={
            "name": "missing-ref",
            "scope": "agent",
            "policy_lang": "inline",
            "policy_body": "x",
        },
        headers=auth,
    )
    assert r.status_code == 400


def test_create_policy_invalid_language(client, auth):
    r = client.post(
        "/api/policies",
        json={
            "name": "bad-lang",
            "scope": "tenant",
            "policy_lang": "javascript",
            "policy_body": "x",
        },
        headers=auth,
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# List & filter
# ---------------------------------------------------------------------------


@pytest.fixture()
def policy(client, auth):
    """Create a tenant-scoped policy; delete after the test."""
    r = client.post(
        "/api/policies",
        json={
            "name": "fixture-policy",
            "scope": "tenant",
            "policy_lang": "inline",
            "policy_body": "deny: false",
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    yield data
    client.delete(f"/api/policies/{data['id']}", headers=auth)


def test_list_policies(client, auth, policy):
    r = client.get("/api/policies", headers=auth)
    assert r.status_code == 200
    policies = r.json()
    assert isinstance(policies, list)
    ids = [p["id"] for p in policies]
    assert policy["id"] in ids


def test_list_policies_filter_by_scope(client, auth, policy):
    r = client.get("/api/policies?scope=tenant", headers=auth)
    assert r.status_code == 200
    for p in r.json():
        assert p["scope"] == "tenant"


def test_list_policies_filter_enabled(client, auth, policy):
    r = client.get("/api/policies?enabled=true", headers=auth)
    assert r.status_code == 200
    for p in r.json():
        assert p["enabled"] is True


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


def test_get_policy(client, auth, policy):
    r = client.get(f"/api/policies/{policy['id']}", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == policy["id"]
    assert data["name"] == policy["name"]
    assert data["policy_body"] == policy["policy_body"]


def test_get_policy_not_found(client, auth):
    r = client.get("/api/policies/00000000-0000-0000-0000-000000000000", headers=auth)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_policy_body_increments_version(client, auth, policy):
    original_version = policy["version"]
    r = client.put(
        f"/api/policies/{policy['id']}",
        json={"policy_body": "deny: true"},
        headers=auth,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["policy_body"] == "deny: true"
    assert data["version"] == original_version + 1


def test_update_policy_enable_disable(client, auth, policy):
    r = client.put(
        f"/api/policies/{policy['id']}",
        json={"enabled": False},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    r = client.put(
        f"/api/policies/{policy['id']}",
        json={"enabled": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is True


def test_update_policy_not_found(client, auth):
    r = client.put(
        "/api/policies/00000000-0000-0000-0000-000000000000",
        json={"policy_body": "x"},
        headers=auth,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Delete (soft-disable)
# ---------------------------------------------------------------------------


def test_delete_policy_soft_disables(client, auth):
    create = client.post(
        "/api/policies",
        json={"name": "to-delete", "scope": "tenant", "policy_lang": "inline", "policy_body": "x"},
        headers=auth,
    )
    assert create.status_code == 201
    pid = create.json()["id"]

    r = client.delete(f"/api/policies/{pid}", headers=auth)
    assert r.status_code == 200
    assert r.json()["enabled"] is False

    # Still retrievable, just disabled
    r2 = client.get(f"/api/policies/{pid}", headers=auth)
    assert r2.status_code == 200
    assert r2.json()["enabled"] is False


def test_delete_policy_not_found(client, auth):
    r = client.delete("/api/policies/00000000-0000-0000-0000-000000000000", headers=auth)
    assert r.status_code == 404


def test_disabled_policy_excluded_by_enabled_filter(client, auth):
    create = client.post(
        "/api/policies",
        json={"name": "filter-test", "scope": "tenant", "policy_lang": "inline", "policy_body": "x"},
        headers=auth,
    )
    pid = create.json()["id"]
    client.delete(f"/api/policies/{pid}", headers=auth)

    r = client.get("/api/policies?enabled=true", headers=auth)
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert pid not in ids


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


def test_policy_tenant_isolation(client, auth, policy):
    """A second tenant must not see or modify the first tenant's policies."""
    from conftest import admin_headers, api_headers

    # Create a second tenant
    r = client.post(
        "/admin/tenants",
        json={"name": "Policy Isolation Tenant", "rate_limit_per_minute": 60},
        headers=admin_headers(),
    )
    assert r.status_code in (200, 201)
    other = r.json()
    other_auth = api_headers(other["api_key"])

    try:
        # Other tenant must not see the first tenant's policy
        r2 = client.get(f"/api/policies/{policy['id']}", headers=other_auth)
        assert r2.status_code == 404

        # Other tenant must not be able to delete it
        r3 = client.delete(f"/api/policies/{policy['id']}", headers=other_auth)
        assert r3.status_code == 404
    finally:
        client.delete(f"/admin/tenants/{other['tenant_id']}", headers=admin_headers())
