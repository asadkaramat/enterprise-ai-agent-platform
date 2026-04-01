import uuid

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.tool import AgentTool


async def check_tool_authorization(
    agent_id: uuid.UUID,
    tool_id: uuid.UUID,
    tenant_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    """
    Verify that:
      1. The agent exists and belongs to the given tenant.
      2. There is an agent_tools entry for (agent_id, tool_id) with is_authorized=True.

    Returns True only when both conditions hold; False otherwise.
    """
    # 1. Confirm the agent belongs to this tenant.
    agent_result = await db.execute(
        select(Agent.id).where(
            and_(
                Agent.id == agent_id,
                Agent.tenant_id == tenant_id,
                Agent.is_active.is_(True),
            )
        )
    )
    if agent_result.scalar_one_or_none() is None:
        return False

    # 2. Confirm the tool is bound and authorized for this agent.
    binding_result = await db.execute(
        select(AgentTool.is_authorized).where(
            and_(
                AgentTool.agent_id == agent_id,
                AgentTool.tool_id == tool_id,
            )
        )
    )
    is_authorized: bool | None = binding_result.scalar_one_or_none()

    if is_authorized is None:
        return False

    return bool(is_authorized)
