"""
Tool registry E2E tests.
"""
import pytest


TOOL_PAYLOAD = {
    "name": "weather_tool",
    "description": "Returns weather for a city",
    "endpoint_url": "https://api.example.com/weather",
    "http_method": "POST",
    "input_schema": {
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
}


def test_create_tool(client, auth):
    r = client.post("/api/tools", json=TOOL_PAYLOAD, headers=auth)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["name"] == "weather_tool"
    assert "id" in data
    client.delete(f"/api/tools/{data['id']}", headers=auth)


def test_list_tools(client, auth, tool):
    r = client.get("/api/tools", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    ids = [t["id"] for t in body["items"]]
    assert tool["id"] in ids


def test_get_tool(client, auth, tool):
    r = client.get(f"/api/tools/{tool['id']}", headers=auth)
    assert r.status_code == 200
    assert r.json()["id"] == tool["id"]


def test_get_tool_not_found(client, auth):
    r = client.get("/api/tools/00000000-0000-0000-0000-000000000000", headers=auth)
    assert r.status_code == 404


def test_update_tool(client, auth, tool):
    r = client.put(
        f"/api/tools/{tool['id']}",
        json={"description": "Updated description"},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["description"] == "Updated description"


def test_delete_tool(client, auth):
    r = client.post("/api/tools", json=TOOL_PAYLOAD, headers=auth)
    tid = r.json()["id"]
    r = client.delete(f"/api/tools/{tid}", headers=auth)
    assert r.status_code == 204

    r = client.get("/api/tools", headers=auth)
    ids = [t["id"] for t in r.json()["items"]]
    assert tid not in ids


def test_bind_tool_to_agent(client, auth, agent, tool):
    r = client.post(f"/api/agents/{agent['id']}/tools/{tool['id']}", headers=auth)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["agent_id"] == agent["id"]
    assert data["tool_id"] == tool["id"]


def test_list_agent_tools(client, auth, agent, tool):
    client.post(f"/api/agents/{agent['id']}/tools/{tool['id']}", headers=auth)
    r = client.get(f"/api/agents/{agent['id']}/tools", headers=auth)
    assert r.status_code == 200
    tools = r.json()
    assert isinstance(tools, list)
    tool_ids = [t["tool_id"] for t in tools]
    assert tool["id"] in tool_ids


def test_unbind_tool_from_agent(client, auth, agent, tool):
    client.post(f"/api/agents/{agent['id']}/tools/{tool['id']}", headers=auth)
    r = client.delete(f"/api/agents/{agent['id']}/tools/{tool['id']}", headers=auth)
    assert r.status_code == 204

    r = client.get(f"/api/agents/{agent['id']}/tools", headers=auth)
    tool_ids = [t["tool_id"] for t in r.json()]
    assert tool["id"] not in tool_ids


def test_authorize_tool(client, auth, agent, tool):
    client.post(f"/api/agents/{agent['id']}/tools/{tool['id']}", headers=auth)
    r = client.put(
        f"/api/agents/{agent['id']}/tools/{tool['id']}/authorize",
        json={"is_authorized": True},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["is_authorized"] is True
