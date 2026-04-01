"""
Session E2E tests — exercises the full LangGraph agent loop via real Ollama.

These tests are slower than unit tests (~5-30s each) because they call the LLM.
"""
import time
import pytest


def test_create_session(client, auth, agent):
    r = client.post(
        "/api/sessions",
        json={"agent_id": agent["id"], "message": "Say the word OK and nothing else."},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert "session_id" in data
    assert data["agent_id"] == agent["id"]
    assert data["status"] == "completed"
    assert isinstance(data["response"], str)
    assert len(data["response"]) > 0


def test_session_response_is_string(client, auth, agent):
    r = client.post(
        "/api/sessions",
        json={"agent_id": agent["id"], "message": "What is 1+1? Reply with just the number."},
        headers=auth,
    )
    assert r.status_code == 201
    assert "2" in r.json()["response"]


def test_continue_session(client, auth, agent):
    # Turn 1
    r1 = client.post(
        "/api/sessions",
        json={"agent_id": agent["id"], "message": "My name is Alice. Remember that."},
        headers=auth,
    )
    assert r1.status_code == 201
    session_id = r1.json()["session_id"]

    # Turn 2 — model should recall the name from context
    r2 = client.post(
        f"/api/sessions/{session_id}/messages",
        json={"message": "What is my name?"},
        headers=auth,
    )
    assert r2.status_code == 200, r2.text
    response = r2.json()["response"].lower()
    assert "alice" in response, f"Expected 'alice' in: {response}"


def test_session_token_tracking(client, auth, agent):
    r = client.post(
        "/api/sessions",
        json={"agent_id": agent["id"], "message": "Hello"},
        headers=auth,
    )
    assert r.status_code == 201
    assert r.json()["token_count"] > 0


def test_get_session(client, auth, agent):
    r = client.post(
        "/api/sessions",
        json={"agent_id": agent["id"], "message": "ping"},
        headers=auth,
    )
    session_id = r.json()["session_id"]

    r = client.get(f"/api/sessions/{session_id}", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["session_id"] == session_id
    assert "messages" in data
    assert len(data["messages"]) >= 2  # at least user + assistant


def test_list_sessions(client, auth, agent):
    r = client.post(
        "/api/sessions",
        json={"agent_id": agent["id"], "message": "list test"},
        headers=auth,
    )
    sid = r.json()["session_id"]

    r = client.get("/api/sessions", headers=auth)
    assert r.status_code == 200
    sessions = r.json()
    assert isinstance(sessions, list)
    ids = [s["session_id"] for s in sessions]
    assert sid in ids


def test_list_sessions_filter_by_status(client, auth, agent):
    client.post(
        "/api/sessions",
        json={"agent_id": agent["id"], "message": "filter test"},
        headers=auth,
    )
    r = client.get("/api/sessions?status=completed", headers=auth)
    assert r.status_code == 200
    for s in r.json():
        assert s["status"] == "completed"


def test_session_unknown_agent(client, auth):
    r = client.post(
        "/api/sessions",
        json={"agent_id": "00000000-0000-0000-0000-000000000000", "message": "hi"},
        headers=auth,
    )
    # Should return an error, not 5xx
    assert r.status_code in (400, 404, 422), r.text


def test_delete_session(client, auth, agent):
    r = client.post(
        "/api/sessions",
        json={"agent_id": agent["id"], "message": "delete me"},
        headers=auth,
    )
    sid = r.json()["session_id"]

    r = client.delete(f"/api/sessions/{sid}", headers=auth)
    assert r.status_code == 204

    # After deletion the session status should be "terminated"
    r = client.get(f"/api/sessions/{sid}", headers=auth)
    assert r.status_code == 200
    assert r.json()["status"] == "terminated"


def test_budget_max_steps_enforced(client, auth, tenant):
    """Create an agent with max_steps=1; it should not loop infinitely."""
    from conftest import api_headers
    r = client.post(
        "/api/agents",
        json={
            "name": "Budget Agent",
            "system_prompt": "You are helpful.",
            "model": "llama3.2",
            "max_steps": 1,
            "token_budget": 999999,
            "session_timeout_seconds": 30,
            "memory_enabled": False,
        },
        headers=api_headers(tenant["api_key"]),
    )
    agent_id = r.json()["id"]

    r = client.post(
        "/api/sessions",
        json={"agent_id": agent_id, "message": "Hello"},
        headers=api_headers(tenant["api_key"]),
    )
    assert r.status_code == 201
    data = r.json()
    assert data["step_count"] <= 1

    client.delete(f"/api/agents/{agent_id}", headers=api_headers(tenant["api_key"]))


def test_pii_redaction(client, auth, agent):
    """SSNs in the response must be redacted by apply_guardrails_node."""
    r = client.post(
        "/api/sessions",
        json={
            "agent_id": agent["id"],
            "message": (
                "Repeat exactly this text and nothing else: "
                "My SSN is 123-45-6789 and card 4111-1111-1111-1111"
            ),
        },
        headers=auth,
    )
    assert r.status_code == 201
    response_text = r.json()["response"]
    assert "123-45-6789" not in response_text, "SSN was not redacted"
    assert "4111-1111-1111-1111" not in response_text, "Credit card was not redacted"
