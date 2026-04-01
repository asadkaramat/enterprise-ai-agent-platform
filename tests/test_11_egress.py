"""
Egress allowlist E2E tests.
Covers: CRUD, URL validation (wildcard match, port, protocol), tenant isolation.
"""
import pytest


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def egress_entry(client, auth):
    """Create an egress entry; remove it after the test."""
    r = client.post(
        "/api/egress-allowlist",
        json={
            "endpoint_pattern": "api.example.com",
            "port": 443,
            "protocol": "https",
            "description": "Test entry",
        },
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    yield data
    client.delete(f"/api/egress-allowlist/{data['id']}", headers=auth)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_add_egress_entry(client, auth):
    r = client.post(
        "/api/egress-allowlist",
        json={"endpoint_pattern": "data.example.org", "port": 443, "protocol": "https"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["endpoint_pattern"] == "data.example.org"
    assert data["port"] == 443
    assert data["protocol"] == "https"
    assert data["is_active"] is True
    assert "id" in data

    client.delete(f"/api/egress-allowlist/{data['id']}", headers=auth)


def test_add_egress_entry_wildcard(client, auth):
    r = client.post(
        "/api/egress-allowlist",
        json={"endpoint_pattern": "*.example.com", "port": 443, "protocol": "https"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["endpoint_pattern"] == "*.example.com"
    client.delete(f"/api/egress-allowlist/{data['id']}", headers=auth)


def test_add_egress_entry_http_protocol(client, auth):
    r = client.post(
        "/api/egress-allowlist",
        json={"endpoint_pattern": "internal.corp", "port": 80, "protocol": "http"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    client.delete(f"/api/egress-allowlist/{r.json()['id']}", headers=auth)


def test_add_egress_entry_invalid_protocol(client, auth):
    r = client.post(
        "/api/egress-allowlist",
        json={"endpoint_pattern": "x.com", "port": 443, "protocol": "ftp"},
        headers=auth,
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_egress_entries(client, auth, egress_entry):
    r = client.get("/api/egress-allowlist", headers=auth)
    assert r.status_code == 200
    entries = r.json()
    assert isinstance(entries, list)
    ids = [e["id"] for e in entries]
    assert egress_entry["id"] in ids


def test_list_egress_only_active_entries(client, auth):
    """Removed entries must not appear in the list."""
    create = client.post(
        "/api/egress-allowlist",
        json={"endpoint_pattern": "gone.example.com", "port": 443, "protocol": "https"},
        headers=auth,
    )
    assert create.status_code == 201
    eid = create.json()["id"]

    client.delete(f"/api/egress-allowlist/{eid}", headers=auth)

    r = client.get("/api/egress-allowlist", headers=auth)
    ids = [e["id"] for e in r.json()]
    assert eid not in ids


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


def test_remove_egress_entry(client, auth):
    create = client.post(
        "/api/egress-allowlist",
        json={"endpoint_pattern": "tmp.example.com", "port": 443, "protocol": "https"},
        headers=auth,
    )
    assert create.status_code == 201
    eid = create.json()["id"]

    r = client.delete(f"/api/egress-allowlist/{eid}", headers=auth)
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_remove_nonexistent_entry(client, auth):
    r = client.delete(
        "/api/egress-allowlist/00000000-0000-0000-0000-000000000000",
        headers=auth,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------


def test_validate_url_default_open_when_no_entries(client, auth, tenant):
    """No allowlist entries → all URLs permitted (default-open posture)."""
    from conftest import admin_headers, api_headers

    # Create an isolated tenant with no egress entries
    r = client.post(
        "/admin/tenants",
        json={"name": "Egress Empty Tenant", "rate_limit_per_minute": 60},
        headers=admin_headers(),
    )
    assert r.status_code in (200, 201)
    other = r.json()
    other_auth = api_headers(other["api_key"])

    try:
        r2 = client.get(
            "/api/egress-allowlist/validate?url=https://anything.goes.com/path",
            headers=other_auth,
        )
        assert r2.status_code == 200
        assert r2.json()["allowed"] is True
    finally:
        client.delete(f"/admin/tenants/{other['tenant_id']}", headers=admin_headers())


def test_validate_url_allowed_exact_match(client, auth):
    """URL matches the pattern → allowed."""
    create = client.post(
        "/api/egress-allowlist",
        json={"endpoint_pattern": "api.allowed.com", "port": 443, "protocol": "https"},
        headers=auth,
    )
    assert create.status_code == 201
    eid = create.json()["id"]

    try:
        r = client.get(
            "/api/egress-allowlist/validate?url=https://api.allowed.com/v1/data",
            headers=auth,
        )
        assert r.status_code == 200
        assert r.json()["allowed"] is True
    finally:
        client.delete(f"/api/egress-allowlist/{eid}", headers=auth)


def test_validate_url_allowed_wildcard_match(client, auth):
    """Wildcard pattern *.trusted.com should match sub.trusted.com."""
    create = client.post(
        "/api/egress-allowlist",
        json={"endpoint_pattern": "*.trusted.com", "port": 443, "protocol": "https"},
        headers=auth,
    )
    assert create.status_code == 201
    eid = create.json()["id"]

    try:
        r = client.get(
            "/api/egress-allowlist/validate?url=https://sub.trusted.com/endpoint",
            headers=auth,
        )
        assert r.status_code == 200
        assert r.json()["allowed"] is True
    finally:
        client.delete(f"/api/egress-allowlist/{eid}", headers=auth)


def test_validate_url_denied(client, auth):
    """URL not matching any entry is denied when entries exist."""
    create = client.post(
        "/api/egress-allowlist",
        json={"endpoint_pattern": "only.allowed.com", "port": 443, "protocol": "https"},
        headers=auth,
    )
    assert create.status_code == 201
    eid = create.json()["id"]

    try:
        r = client.get(
            "/api/egress-allowlist/validate?url=https://not.allowed.com/secret",
            headers=auth,
        )
        assert r.status_code == 200
        assert r.json()["allowed"] is False
    finally:
        client.delete(f"/api/egress-allowlist/{eid}", headers=auth)


def test_validate_url_wrong_port_denied(client, auth):
    """Correct hostname but wrong port is denied."""
    create = client.post(
        "/api/egress-allowlist",
        json={"endpoint_pattern": "strict.port.com", "port": 443, "protocol": "https"},
        headers=auth,
    )
    assert create.status_code == 201
    eid = create.json()["id"]

    try:
        r = client.get(
            "/api/egress-allowlist/validate?url=https://strict.port.com:8443/path",
            headers=auth,
        )
        assert r.status_code == 200
        assert r.json()["allowed"] is False
    finally:
        client.delete(f"/api/egress-allowlist/{eid}", headers=auth)


def test_validate_url_wrong_protocol_denied(client, auth):
    """HTTPS entry must not permit an HTTP request to the same host."""
    create = client.post(
        "/api/egress-allowlist",
        json={"endpoint_pattern": "proto.example.com", "port": 443, "protocol": "https"},
        headers=auth,
    )
    assert create.status_code == 201
    eid = create.json()["id"]

    try:
        r = client.get(
            "/api/egress-allowlist/validate?url=http://proto.example.com/path",
            headers=auth,
        )
        assert r.status_code == 200
        assert r.json()["allowed"] is False
    finally:
        client.delete(f"/api/egress-allowlist/{eid}", headers=auth)


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


def test_egress_tenant_isolation(client, auth, egress_entry):
    """A second tenant must not see or delete the first tenant's egress entries."""
    from conftest import admin_headers, api_headers

    r = client.post(
        "/admin/tenants",
        json={"name": "Egress Isolation Tenant", "rate_limit_per_minute": 60},
        headers=admin_headers(),
    )
    assert r.status_code in (200, 201)
    other = r.json()
    other_auth = api_headers(other["api_key"])

    try:
        # Other tenant's list must not contain this entry
        r2 = client.get("/api/egress-allowlist", headers=other_auth)
        assert r2.status_code == 200
        ids = [e["id"] for e in r2.json()]
        assert egress_entry["id"] not in ids

        # Delete must 404
        r3 = client.delete(f"/api/egress-allowlist/{egress_entry['id']}", headers=other_auth)
        assert r3.status_code == 404
    finally:
        client.delete(f"/admin/tenants/{other['tenant_id']}", headers=admin_headers())
