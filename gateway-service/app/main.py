import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from app.database import create_tables, dispose_engine
from app.middleware.rate_limit import close_redis
from app.routes import proxy, tenants
from app.routes.proxy import set_http_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info("Gateway service starting up...")
    await create_tables()

    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=5.0),
        follow_redirects=False,
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
    )
    set_http_client(http_client)
    logger.info("Gateway service ready on port 8000.")
    yield

    logger.info("Gateway service shutting down...")
    await http_client.aclose()
    await close_redis()
    await dispose_engine()
    logger.info("Gateway service shut down cleanly.")


app = FastAPI(
    title="Enterprise AI Agent Platform — Gateway",
    description="Public-facing API gateway: auth, rate limiting, and reverse proxy.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tenants.router)
app.include_router(proxy.router)


@app.get("/health", tags=["health"])
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "gateway"})


@app.get("/metrics", tags=["observability"])
async def metrics(request: Request) -> Response:
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
