import logging
import time
import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import create_tables, dispose_engine, get_db
from app.metrics import agent_config_requests_total
from app.models.agent import Agent
from app.models.tool import AgentTool, Tool
from app.routes.agents import AgentFullResponse, AgentResponse, ToolWithSchema
from app.routes.agents import router as agents_router
from app.routes.tools import router as tools_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("agent-config-service starting up …")
    await create_tables()
    yield
    logger.info("agent-config-service shutting down …")
    await dispose_engine()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Agent Config Service",
    description="CRUD for agent configurations and tool registry. Enforces tenant isolation via X-Tenant-ID header.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins (internal service; gateway enforces auth)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Prometheus instrumentation middleware
# ---------------------------------------------------------------------------


@app.middleware("http")
async def prometheus_middleware(request: Request, call_next):
    start = time.perf_counter()
    response: Response = await call_next(request)
    duration = time.perf_counter() - start  # noqa: F841 — kept for future histogram use

    agent_config_requests_total.labels(
        method=request.method,
        path=request.url.path,
        status=str(response.status_code),
    ).inc()

    return response


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(agents_router)
app.include_router(tools_router)


# ---------------------------------------------------------------------------
# Built-in endpoints
# ---------------------------------------------------------------------------


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok", "service": "agent-config"}


@app.get("/metrics", tags=["ops"], include_in_schema=False)
async def metrics() -> Response:
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Internal route — called by gateway/session-service; not in public schema
# ---------------------------------------------------------------------------


@app.get(
    "/internal/agents/{agent_id}/full",
    response_model=AgentFullResponse,
    tags=["internal"],
    include_in_schema=False,
)
async def get_agent_full(
    agent_id: uuid.UUID,
    x_internal_secret: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AgentFullResponse:
    """
    Return the full agent config plus all bound tools with schemas.
    Secured by X-Internal-Secret header.
    """
    if x_internal_secret != settings.INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden: invalid or missing X-Internal-Secret.")

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found.")

    tools_result = await db.execute(
        select(Tool, AgentTool.is_authorized)
        .join(AgentTool, AgentTool.tool_id == Tool.id)
        .where(
            and_(
                AgentTool.agent_id == agent_id,
                Tool.is_active.is_(True),
            )
        )
    )
    tools_rows = tools_result.all()

    tools = [
        ToolWithSchema(
            tool_id=tool.id,
            name=tool.name,
            endpoint_url=tool.endpoint_url,
            http_method=tool.http_method,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            auth_type=tool.auth_type,
            auth_config=tool.auth_config,
            is_authorized=is_authorized,
        )
        for tool, is_authorized in tools_rows
    ]

    return AgentFullResponse(agent=AgentResponse.from_orm(agent), tools=tools)
