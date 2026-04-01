"""
Health-check tests — verify every service is reachable before running
the full E2E suite.
"""
import httpx
import pytest

SERVICES = [
    ("gateway",       "http://localhost:8000/health"),
    ("agent-config",  "http://localhost:8001/health"),
    ("session",       "http://localhost:8002/health"),
    ("memory",        "http://localhost:8003/health"),
    ("audit",         "http://localhost:8004/health"),
]


@pytest.mark.parametrize("name,url", SERVICES)
def test_service_healthy(name, url):
    r = httpx.get(url, timeout=10)
    assert r.status_code == 200, f"{name} returned {r.status_code}"
    body = r.json()
    assert body.get("status") in ("ok", "healthy"), f"{name} health body: {body}"


def test_gateway_metrics():
    r = httpx.get("http://localhost:8000/metrics", timeout=10)
    assert r.status_code == 200
    assert b"gateway_requests_total" in r.content


def test_prometheus_scrapes_gateway():
    r = httpx.get("http://localhost:9090/api/v1/targets", timeout=10)
    assert r.status_code == 200
    targets = r.json()["data"]["activeTargets"]
    names = [t["labels"].get("job", "") for t in targets]
    assert any("gateway" in n for n in names), f"gateway not in Prometheus targets: {names}"
