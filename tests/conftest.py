"""
Shared fixtures for the E2E test suite.

Requires the full Docker Compose stack to be running:
  docker compose up -d

All tests run against localhost — no mocking, real services.
"""
import os
import time
import pytest
import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GATEWAY = os.getenv("GATEWAY_URL", "http://localhost:8000")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "changeme-admin-secret")
TIMEOUT = 60.0  # seconds — LLM calls can be slow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def admin_headers() -> dict:
    return {"X-Admin-Secret": ADMIN_SECRET, "Content-Type": "application/json"}


def api_headers(api_key: str) -> dict:
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Session-scoped: one tenant + API key shared across all tests
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def client():
    """Synchronous httpx client for the whole test session."""
    with httpx.Client(base_url=GATEWAY, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="session")
def tenant(client):
    """Create a dedicated test tenant; delete it after all tests."""
    r = client.post(
        "/admin/tenants",
        json={"name": "E2E Test Tenant", "rate_limit_per_minute": 120},
        headers=admin_headers(),
    )
    assert r.status_code in (200, 201), f"Failed to create tenant: {r.text}"
    data = r.json()
    tenant_id = data["tenant_id"]
    api_key = data["api_key"]
    yield {"id": tenant_id, "api_key": api_key}
    # Teardown: deactivate the tenant
    client.delete(f"/admin/tenants/{tenant_id}", headers=admin_headers())


@pytest.fixture(scope="session")
def auth(tenant):
    """Return api_headers dict for the test tenant."""
    return api_headers(tenant["api_key"])


# ---------------------------------------------------------------------------
# Function-scoped: fresh agent per test that needs one
# ---------------------------------------------------------------------------
@pytest.fixture()
def agent(client, auth):
    """Create a minimal test agent; delete it after the test."""
    r = client.post(
        "/api/agents",
        json={
            "name": "E2E Agent",
            "system_prompt": "You are a concise test assistant. Always reply briefly.",
            "model": "llama3.2",
            "max_steps": 3,
            "token_budget": 4096,
            "session_timeout_seconds": 120,
            "memory_enabled": False,
        },
        headers=auth,
    )
    assert r.status_code == 201, f"Failed to create agent: {r.text}"
    data = r.json()
    yield data
    client.delete(f"/api/agents/{data['id']}", headers=auth)


@pytest.fixture()
def tool(client, auth):
    """Create a minimal test tool; delete it after the test."""
    r = client.post(
        "/api/tools",
        json={
            "name": "e2e_echo_tool",
            "description": "Echoes the input back",
            "endpoint_url": "http://httpbin.org/post",
            "http_method": "POST",
            "input_schema": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
        headers=auth,
    )
    assert r.status_code == 201, f"Failed to create tool: {r.text}"
    data = r.json()
    yield data
    client.delete(f"/api/tools/{data['id']}", headers=auth)
