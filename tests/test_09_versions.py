"""
Agent versioning E2E tests.
Covers: version creation, listing, retrieval, promotion/rollback,
        tool bindings, schema version pinning.
"""


def test_create_version(client, auth, agent):
    r = client.put(
        f"/api/agents/{agent['id']}/versions",
        json={"system_prompt": "v2 prompt", "model_id": "llama3.2"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["system_prompt"] == "v2 prompt"
    assert data["model_id"] == "llama3.2"
    assert data["version_number"] >= 1
    assert "version_id" in data
    assert data["tool_bindings"] == []


def test_version_numbers_are_sequential(client, auth, agent):
    r1 = client.put(
        f"/api/agents/{agent['id']}/versions",
        json={"system_prompt": "first", "model_id": "llama3.2"},
        headers=auth,
    )
    assert r1.status_code == 201
    v1_num = r1.json()["version_number"]

    r2 = client.put(
        f"/api/agents/{agent['id']}/versions",
        json={"system_prompt": "second", "model_id": "llama3.2"},
        headers=auth,
    )
    assert r2.status_code == 201
    assert r2.json()["version_number"] == v1_num + 1


def test_list_versions(client, auth, agent):
    client.put(
        f"/api/agents/{agent['id']}/versions",
        json={"system_prompt": "list test", "model_id": "llama3.2"},
        headers=auth,
    )
    r = client.get(f"/api/agents/{agent['id']}/versions", headers=auth)
    assert r.status_code == 200
    versions = r.json()
    assert isinstance(versions, list)
    assert len(versions) >= 1
    # Newest first
    if len(versions) > 1:
        assert versions[0]["version_number"] > versions[-1]["version_number"]


def test_get_version(client, auth, agent):
    create = client.put(
        f"/api/agents/{agent['id']}/versions",
        json={"system_prompt": "get test prompt", "model_id": "llama3.2"},
        headers=auth,
    )
    assert create.status_code == 201
    version_id = create.json()["version_id"]

    r = client.get(f"/api/agents/{agent['id']}/versions/{version_id}", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["version_id"] == version_id
    assert data["system_prompt"] == "get test prompt"
    assert "tool_bindings" in data
    assert "guardrail_config" in data


def test_get_version_not_found(client, auth, agent):
    r = client.get(
        f"/api/agents/{agent['id']}/versions/00000000-0000-0000-0000-000000000000",
        headers=auth,
    )
    assert r.status_code == 404


def test_promote_version(client, auth, agent):
    create = client.put(
        f"/api/agents/{agent['id']}/versions",
        json={"system_prompt": "promote me", "model_id": "llama3.2"},
        headers=auth,
    )
    assert create.status_code == 201
    version_id = create.json()["version_id"]

    r = client.patch(
        f"/api/agents/{agent['id']}/active-version",
        json={"version_id": version_id},
        headers=auth,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["active_version_id"] == version_id
    assert data["agent_id"] == agent["id"]


def test_rollback_returns_previous_version_id(client, auth, agent):
    v1_id = client.put(
        f"/api/agents/{agent['id']}/versions",
        json={"system_prompt": "v1", "model_id": "llama3.2"},
        headers=auth,
    ).json()["version_id"]

    v2_id = client.put(
        f"/api/agents/{agent['id']}/versions",
        json={"system_prompt": "v2", "model_id": "llama3.2"},
        headers=auth,
    ).json()["version_id"]

    # Promote to v2
    client.patch(
        f"/api/agents/{agent['id']}/active-version",
        json={"version_id": v2_id},
        headers=auth,
    )

    # Roll back to v1 — previous_version_id must reflect v2
    r = client.patch(
        f"/api/agents/{agent['id']}/active-version",
        json={"version_id": v1_id},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["previous_version_id"] == v2_id
    assert r.json()["active_version_id"] == v1_id


def test_create_version_unknown_agent(client, auth):
    r = client.put(
        "/api/agents/00000000-0000-0000-0000-000000000000/versions",
        json={"system_prompt": "ghost", "model_id": "llama3.2"},
        headers=auth,
    )
    assert r.status_code == 404


def test_promote_nonexistent_version(client, auth, agent):
    r = client.patch(
        f"/api/agents/{agent['id']}/active-version",
        json={"version_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth,
    )
    assert r.status_code == 404


def test_version_optional_fields(client, auth, agent):
    """Fallback model, memory, rollout percentage, and guardrails are optional."""
    r = client.put(
        f"/api/agents/{agent['id']}/versions",
        json={
            "system_prompt": "full config",
            "model_id": "llama3.2",
            "fallback_model_id": "llama3.2",
            "memory_enabled": True,
            "memory_retrieval_window_days": 7,
            "max_steps_per_turn": 5,
            "token_budget": 2048,
            "session_timeout_ms": 60000,
            "rollout_percentage": 50,
            "guardrail_config": {"block_pii": True},
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["rollout_percentage"] == 50
    assert data["memory_enabled"] is True
    assert data["guardrail_config"] == {"block_pii": True}
    assert data["fallback_model_id"] == "llama3.2"


# ---------------------------------------------------------------------------
# Tool schema version tests
# ---------------------------------------------------------------------------


def test_publish_tool_schema_version(client, auth, tool):
    r = client.put(
        f"/api/tools/{tool['id']}/schemas",
        json={
            "schema_def": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            }
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["tool_id"] == tool["id"]
    assert data["schema_version"] >= 1
    assert "checksum" in data
    assert len(data["checksum"]) == 64  # SHA-256 hex


def test_publish_schema_is_idempotent(client, auth, tool):
    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    r1 = client.put(f"/api/tools/{tool['id']}/schemas", json={"schema_def": schema, "schema_version": 1}, headers=auth)
    r2 = client.put(f"/api/tools/{tool['id']}/schemas", json={"schema_def": schema, "schema_version": 1}, headers=auth)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["checksum"] == r2.json()["checksum"]


def test_list_schema_versions(client, auth, tool):
    client.put(f"/api/tools/{tool['id']}/schemas", json={"schema_def": {"type": "object"}}, headers=auth)
    r = client.get(f"/api/tools/{tool['id']}/schemas", headers=auth)
    assert r.status_code == 200
    versions = r.json()
    assert isinstance(versions, list)
    assert len(versions) >= 1


def test_create_version_with_tool_binding(client, auth, agent, tool):
    # Publish a schema version so it can be pinned in the agent version
    schema_r = client.put(
        f"/api/tools/{tool['id']}/schemas",
        json={"schema_def": {"type": "object", "properties": {"text": {"type": "string"}}}},
        headers=auth,
    )
    assert schema_r.status_code == 201
    schema_version = schema_r.json()["schema_version"]

    r = client.put(
        f"/api/agents/{agent['id']}/versions",
        json={
            "system_prompt": "version with tool",
            "model_id": "llama3.2",
            "tool_bindings": [
                {
                    "tool_id": tool["id"],
                    "tool_schema_version": schema_version,
                    "max_calls_per_turn": 3,
                }
            ],
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert len(data["tool_bindings"]) == 1
    binding = data["tool_bindings"][0]
    assert binding["tool_id"] == tool["id"]
    assert binding["tool_schema_version"] == schema_version
    assert binding["max_calls_per_turn"] == 3
    assert binding["enabled"] is True


def test_create_version_invalid_tool_id(client, auth, agent):
    r = client.put(
        f"/api/agents/{agent['id']}/versions",
        json={
            "system_prompt": "bad tool",
            "model_id": "llama3.2",
            "tool_bindings": [
                {"tool_id": "00000000-0000-0000-0000-000000000000", "tool_schema_version": 1}
            ],
        },
        headers=auth,
    )
    assert r.status_code == 400


def test_create_version_invalid_schema_version(client, auth, agent, tool):
    """Referencing a schema version that was never published must fail."""
    r = client.put(
        f"/api/agents/{agent['id']}/versions",
        json={
            "system_prompt": "bad schema ver",
            "model_id": "llama3.2",
            "tool_bindings": [
                {"tool_id": tool["id"], "tool_schema_version": 9999}
            ],
        },
        headers=auth,
    )
    assert r.status_code == 400
