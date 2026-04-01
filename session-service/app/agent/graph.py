"""
LangGraph StateGraph definition for the AI agent runtime.

Graph flow:
    load_config -> retrieve_memory -> call_llm
        -> [execute_tool -> check_budget -> call_llm (loop)]
        -> apply_guardrails -> END
        -> route_to_agent -> END
        -> END (on error / budget exceeded)
"""
import logging
import re

from langgraph.graph import StateGraph, END

from app.agent.state import AgentState
from app.agent import nodes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routing / conditional edge functions
# ---------------------------------------------------------------------------

_ROUTE_PATTERN = re.compile(r"^\[ROUTE:([^\]]+)\]")


def decide_after_llm(state: AgentState) -> str:
    """
    Decide what to do after the LLM responds.

    Returns one of: "execute_tool", "route", "guardrails", "end"
    """
    if state.get("error"):
        logger.debug("decide_after_llm -> end (error: %s)", state["error"])
        return "end"

    messages = state.get("messages", [])
    if not messages:
        return "guardrails"

    last = messages[-1]
    if last.get("role") != "assistant":
        return "guardrails"

    # Check for tool calls
    tool_calls = last.get("tool_calls")
    if tool_calls:
        logger.debug("decide_after_llm -> execute_tool")
        return "execute_tool"

    # Check for routing directive in content
    content = last.get("content") or ""
    route_match = _ROUTE_PATTERN.match(content.strip())
    if route_match:
        target_agent_id = route_match.group(1).strip()
        # Extract optional message after the route tag
        route_message = content[route_match.end():].strip()
        logger.debug("decide_after_llm -> route (target=%s)", target_agent_id)
        # Inject routing info into state-like update — LangGraph merges dicts
        # We update state directly since we are inside a conditional edge function
        # (state is passed by reference for TypedDict)
        state["route_to_agent_id"] = target_agent_id
        state["route_message"] = route_message
        return "route"

    logger.debug("decide_after_llm -> guardrails")
    return "guardrails"


def decide_after_budget(state: AgentState) -> str:
    """
    After checking the budget, either loop back to the LLM or end.

    Returns one of: "call_llm", "end"
    """
    if state.get("budget_exceeded"):
        logger.debug(
            "decide_after_budget -> end (reason: %s)", state.get("budget_reason", "unknown")
        )
        return "end"
    return "call_llm"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph():
    """Build and compile the LangGraph agent graph."""
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("load_config", nodes.load_config_node)
    graph.add_node("retrieve_memory", nodes.retrieve_memory_node)
    graph.add_node("call_llm", nodes.call_llm_node)
    graph.add_node("execute_tool", nodes.execute_tool_node)
    graph.add_node("check_budget", nodes.check_budget_node)
    graph.add_node("apply_guardrails", nodes.apply_guardrails_node)
    graph.add_node("route_to_agent", nodes.route_to_agent_node)

    # Entry point
    graph.set_entry_point("load_config")

    # Fixed edges
    graph.add_edge("load_config", "retrieve_memory")
    graph.add_edge("retrieve_memory", "call_llm")

    # After LLM: branch on tool calls, routing, or finalize
    graph.add_conditional_edges(
        "call_llm",
        decide_after_llm,
        {
            "execute_tool": "execute_tool",
            "route": "route_to_agent",
            "guardrails": "apply_guardrails",
            "end": END,
        },
    )

    # After tool execution: check budgets before looping back to LLM
    graph.add_edge("execute_tool", "check_budget")

    # After budget check: loop back to LLM or terminate
    graph.add_conditional_edges(
        "check_budget",
        decide_after_budget,
        {
            "call_llm": "call_llm",
            "end": END,
        },
    )

    # Terminal paths
    graph.add_edge("apply_guardrails", END)
    graph.add_edge("route_to_agent", END)

    return graph.compile()


# Module-level compiled graph — import and use in routes
agent_graph = build_graph()
