import logging

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.metrics import requests_total
from app.middleware.auth import authenticate_request
from app.middleware.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["proxy"])

_STRIP_HEADERS = {"x-api-key", "host", "content-length", "transfer-encoding"}

_http_client: httpx.AsyncClient | None = None


def set_http_client(client: httpx.AsyncClient) -> None:
    global _http_client
    _http_client = client


def get_http_client() -> httpx.AsyncClient:
    if _http_client is None:
        raise RuntimeError("HTTP client not initialized")
    return _http_client


async def _proxy(
    service_base_url: str,
    path: str,
    request: Request,
    segment: str,
    service_prefix: str = "",
) -> StreamingResponse:
    tenant = await authenticate_request(request)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    await check_rate_limit(tenant)

    client = get_http_client()

    # Reconstruct the upstream path, preserving the service-specific prefix.
    # e.g. /api/agents/123 → /agents/123 on agent-config-service
    prefix = service_prefix.strip("/")
    if prefix and path:
        full_path = f"{prefix}/{path}"
    elif prefix:
        full_path = prefix
    else:
        full_path = path

    target_url = f"{service_base_url.rstrip('/')}/{full_path}" if full_path else service_base_url.rstrip("/")
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    forward_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _STRIP_HEADERS
    }
    forward_headers["X-Tenant-ID"] = str(tenant.id)
    forward_headers["X-Tenant-Name"] = tenant.name

    body = await request.body()

    logger.info(
        "Proxying %s /api/%s/%s → %s for tenant %s",
        request.method, segment, path, target_url, tenant.id,
    )

    try:
        upstream_request = client.build_request(
            method=request.method,
            url=target_url,
            headers=forward_headers,
            content=body,
        )
        upstream_response = await client.send(upstream_request, stream=True)
    except httpx.ConnectError as exc:
        logger.error("Cannot connect to upstream %s: %s", target_url, exc)
        requests_total.labels(
            tenant_id=str(tenant.id), method=request.method,
            path=f"/api/{segment}", status=502,
        ).inc()
        raise HTTPException(status_code=502, detail="Upstream service unavailable")
    except httpx.TimeoutException as exc:
        logger.error("Upstream timeout %s: %s", target_url, exc)
        requests_total.labels(
            tenant_id=str(tenant.id), method=request.method,
            path=f"/api/{segment}", status=504,
        ).inc()
        raise HTTPException(status_code=504, detail="Upstream service timed out")

    requests_total.labels(
        tenant_id=str(tenant.id), method=request.method,
        path=f"/api/{segment}", status=upstream_response.status_code,
    ).inc()

    response_headers = {
        k: v for k, v in upstream_response.headers.items()
        if k.lower() not in {"transfer-encoding", "content-encoding", "content-length"}
    }

    return StreamingResponse(
        content=upstream_response.aiter_bytes(),
        status_code=upstream_response.status_code,
        headers=response_headers,
    )


_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


@router.api_route("/api/agents", methods=_METHODS)
@router.api_route("/api/agents/{path:path}", methods=_METHODS)
async def proxy_agents(request: Request, path: str = "") -> StreamingResponse:
    return await _proxy(settings.AGENT_CONFIG_SERVICE_URL, path, request, "agents", "agents")


@router.api_route("/api/tools", methods=_METHODS)
@router.api_route("/api/tools/{path:path}", methods=_METHODS)
async def proxy_tools(request: Request, path: str = "") -> StreamingResponse:
    return await _proxy(settings.AGENT_CONFIG_SERVICE_URL, path, request, "tools", "tools")


@router.api_route("/api/sessions", methods=_METHODS)
@router.api_route("/api/sessions/{path:path}", methods=_METHODS)
async def proxy_sessions(request: Request, path: str = "") -> StreamingResponse:
    return await _proxy(settings.SESSION_SERVICE_URL, path, request, "sessions", "sessions")


@router.api_route("/api/memory", methods=_METHODS)
@router.api_route("/api/memory/{path:path}", methods=_METHODS)
async def proxy_memory(request: Request, path: str = "") -> StreamingResponse:
    return await _proxy(settings.MEMORY_SERVICE_URL, path, request, "memory", "memory")


@router.api_route("/api/audit", methods=_METHODS)
@router.api_route("/api/audit/{path:path}", methods=_METHODS)
async def proxy_audit(request: Request, path: str = "") -> StreamingResponse:
    return await _proxy(settings.AUDIT_SERVICE_URL, path, request, "audit", "audit")
