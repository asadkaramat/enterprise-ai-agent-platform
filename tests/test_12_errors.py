"""
Error scenario E2E tests.
Covers: 404s, 400s (input validation), cross-service error propagation,
        and edge cases not exercised by the happy-path test files.
"""


# ---------------------------------------------------------------------------
# Session errors
# ---------------------------------------------------------------------------


def test_get_nonexistent_session(client, auth):
    r = client.get("/api/sessions/00000000-0000-0000-0000-000000000000", headers=auth)
    assert r.status_code == 404


def test_continue_nonexistent_session(client, auth):
    r = client.post(
        "/api/sessions/00000000-0000-0000-0000-000000000000/messages",
        json={"message": "hello?"},
        headers=auth,
    )
    assert r.status_code in (404, 422), r.text


def test_delete_nonexistent_session(client, auth):
    r = client.delete("/api/sessions/00000000-0000-0000-0000-000000000000", headers=auth)
    assert r.status_code == 404


def test_session_missing_message_field(client, auth, agent):
    """Creating a session without the required 'message' field must return 422."""
    r = client.post(
        "/api/sessions",
        json={"agent_id": agent["id"]},
        headers=auth,
    )
    assert r.status_code == 422


def test_session_missing_agent_id_field(client, auth):
    r = client.post(
        "/api/sessions",
        json={"message": "hi"},
        headers=auth,
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Agent errors
# ---------------------------------------------------------------------------


def test_get_nonexistent_agent(client, auth):
    r = client.get("/api/agents/00000000-0000-0000-0000-000000000000", headers=auth)
    assert r.status_code == 404


def test_delete_nonexistent_agent(client, auth):
    r = client.delete("/api/agents/00000000-0000-0000-0000-000000000000", headers=auth)
    assert r.status_code == 404


def test_create_agent_missing_required_fields(client, auth):
    """name and system_prompt are required."""
    r = client.post("/api/agents", json={"model": "llama3.2"}, headers=auth)
    assert r.status_code == 422


def test_update_nonexistent_agent(client, auth):
    r = client.put(
        "/api/agents/00000000-0000-0000-0000-000000000000",
        json={"name": "ghost"},
        headers=auth,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tool errors
# ---------------------------------------------------------------------------


def test_get_nonexistent_tool(client, auth):
    r = client.get("/api/tools/00000000-0000-0000-0000-000000000000", headers=auth)
    assert r.status_code == 404


def test_delete_nonexistent_tool(client, auth):
    r = client.delete("/api/tools/00000000-0000-0000-0000-000000000000", headers=auth)
    assert r.status_code == 404


def test_create_tool_missing_required_fields(client, auth):
    """name, description, and endpoint_url are required."""
    r = client.post("/api/tools", json={"http_method": "GET"}, headers=auth)
    assert r.status_code == 422


def test_list_tool_schemas_nonexistent_tool(client, auth):
    r = client.get("/api/tools/00000000-0000-0000-0000-000000000000/schemas", headers=auth)
    assert r.status_code == 404


def test_publish_schema_nonexistent_tool(client, auth):
    r = client.put(
        "/api/tools/00000000-0000-0000-0000-000000000000/schemas",
        json={"schema_def": {"type": "object"}},
        headers=auth,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Agent version errors (covered in depth by test_09, spot-checks here)
# ---------------------------------------------------------------------------


def test_list_versions_nonexistent_agent(client, auth):
    r = client.get("/api/agents/00000000-0000-0000-0000-000000000000/versions", headers=auth)
    assert r.status_code == 404


def test_promote_missing_version_id_field(client, auth, agent):
    """version_id is required in the promote payload."""
    r = client.patch(f"/api/agents/{agent['id']}/active-version", json={}, headers=auth)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Policy errors
# ---------------------------------------------------------------------------


def test_get_nonexistent_policy(client, auth):
    r = client.get("/api/policies/00000000-0000-0000-0000-000000000000", headers=auth)
    assert r.status_code == 404


def test_update_nonexistent_policy(client, auth):
    r = client.put(
        "/api/policies/00000000-0000-0000-0000-000000000000",
        json={"policy_body": "x"},
        headers=auth,
    )
    assert r.status_code == 404


def test_delete_nonexistent_policy(client, auth):
    r = client.delete("/api/policies/00000000-0000-0000-0000-000000000000", headers=auth)
    assert r.status_code == 404


def test_create_policy_missing_required_fields(client, auth):
    """name, scope, and policy_body are required."""
    r = client.post("/api/policies", json={"scope": "tenant"}, headers=auth)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Egress errors
# ---------------------------------------------------------------------------


def test_delete_nonexistent_egress_entry(client, auth):
    r = client.delete(
        "/api/egress-allowlist/00000000-0000-0000-0000-000000000000",
        headers=auth,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Auth & rate-limit errors
# ---------------------------------------------------------------------------


def test_missing_api_key_returns_401(client):
    r = client.get("/api/agents")
    assert r.status_code == 401


def test_invalid_api_key_returns_401(client):
    r = client.get("/api/agents", headers={"X-API-Key": "totally-wrong-key"})
    assert r.status_code == 401


def test_admin_endpoint_requires_admin_secret(client):
    r = client.get("/admin/tenants")
    assert r.status_code in (401, 403)


def test_admin_endpoint_wrong_secret_rejected(client):
    r = client.get("/admin/tenants", headers={"X-Admin-Secret": "wrong"})
    assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Tool binding errors (agent-tool legacy endpoint)
# ---------------------------------------------------------------------------


def test_bind_nonexistent_tool_to_agent(client, auth, agent):
    r = client.post(
        f"/api/agents/{agent['id']}/tools",
        json={"tool_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth,
    )
    assert r.status_code in (400, 404), r.text


def test_bind_tool_to_nonexistent_agent(client, auth, tool):
    r = client.post(
        "/api/agents/00000000-0000-0000-0000-000000000000/tools",
        json={"tool_id": tool["id"]},
        headers=auth,
    )
    assert r.status_code in (400, 404), r.text


# ---------------------------------------------------------------------------
# Malformed UUID inputs
# ---------------------------------------------------------------------------


def test_malformed_uuid_in_agent_path(client, auth):
    r = client.get("/api/agents/not-a-uuid", headers=auth)
    assert r.status_code == 422


def test_malformed_uuid_in_session_path(client, auth):
    r = client.get("/api/sessions/not-a-uuid", headers=auth)
    assert r.status_code == 422


def test_malformed_uuid_in_policy_path(client, auth):
    r = client.get("/api/policies/not-a-uuid", headers=auth)
    assert r.status_code == 422
