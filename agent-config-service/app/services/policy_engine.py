"""
Policy evaluation engine.

Evaluation order (spec Section 6):
  1. Parameter constraints from ToolBinding.parameter_constraints — fast, always checked.
  2. Policies table, ordered by scope: tenant → agent → tool.
     - A single DENY at any scope immediately returns DENY.
     - If all policies ALLOW or ABSTAIN, the result is ALLOW.

Policy languages supported:
  inline — JSON rule set evaluated in-process (zero extra dependencies).
  rego   — placeholder; abstains until OPA is wired in.
  cedar  — placeholder; abstains until Cedar is wired in.

Inline policy_body JSON format:
  {
      "rules": [
          {"parameter": "query",       "allowed_prefixes": ["SELECT"]},
          {"parameter": "record_type", "enum": ["demographics", "appointments"]},
          {"parameter": "amount",      "max": 10000},
          {"parameter": "rate",        "min": 0}
      ]
  }
"""
import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy import and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy import Policy
from app.models.tool_binding import ToolBinding

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parameter constraint checking (from ToolBinding.parameter_constraints)
# ---------------------------------------------------------------------------

_ALLOW = ("ALLOW", None, None)


def _check_parameter_constraints(
    parameters: dict[str, Any],
    constraints: dict[str, Any],
) -> tuple[str, str | None, str | None]:
    """
    Validate parameters against constraints from ToolBinding.parameter_constraints.

    Returns (decision, reason, policy_id).
    decision is "ALLOW" or "DENY".
    """
    for param, rules in constraints.items():
        if not isinstance(rules, dict):
            continue
        value = parameters.get(param)
        if value is None:
            continue  # absent parameters are not constrained here

        if "enum" in rules:
            allowed = rules["enum"]
            if value not in allowed:
                return (
                    "DENY",
                    f"Parameter '{param}' value '{value}' not in allowed set {allowed}",
                    None,
                )

        if "max" in rules:
            try:
                if float(value) > float(rules["max"]):
                    return (
                        "DENY",
                        f"Parameter '{param}' value {value} exceeds maximum {rules['max']}",
                        None,
                    )
            except (TypeError, ValueError):
                pass

        if "min" in rules:
            try:
                if float(value) < float(rules["min"]):
                    return (
                        "DENY",
                        f"Parameter '{param}' value {value} is below minimum {rules['min']}",
                        None,
                    )
            except (TypeError, ValueError):
                pass

        if "allowed_prefixes" in rules:
            str_val = str(value).upper()
            prefixes = [str(p).upper() for p in rules["allowed_prefixes"]]
            if not any(str_val.startswith(p) for p in prefixes):
                return (
                    "DENY",
                    f"Parameter '{param}' must start with one of {rules['allowed_prefixes']}",
                    None,
                )

        if "pattern" in rules:
            try:
                if not re.match(rules["pattern"], str(value)):
                    return (
                        "DENY",
                        f"Parameter '{param}' value '{value}' does not match required pattern",
                        None,
                    )
            except re.error:
                pass  # bad pattern — don't block

    return _ALLOW


# ---------------------------------------------------------------------------
# Inline policy evaluation
# ---------------------------------------------------------------------------


def _evaluate_inline_policy(
    policy_body: str,
    parameters: dict[str, Any],
) -> tuple[str, str | None]:
    """
    Evaluate a JSON-encoded inline policy against parameters.
    Returns (decision, reason): "ALLOW" | "DENY" | "ABSTAIN".
    """
    try:
        policy = json.loads(policy_body)
    except (json.JSONDecodeError, ValueError):
        logger.warning("policy_engine: inline policy_body is not valid JSON — abstaining")
        return "ABSTAIN", None

    rules = policy.get("rules", [])
    if not isinstance(rules, list):
        return "ABSTAIN", None

    for rule in rules:
        param = rule.get("parameter")
        if not param:
            continue
        value = parameters.get(param)
        if value is None:
            continue

        if "enum" in rule and value not in rule["enum"]:
            return (
                "DENY",
                f"Parameter '{param}' value '{value}' not in allowed set {rule['enum']}",
            )
        if "allowed_prefixes" in rule:
            str_val = str(value).upper()
            prefixes = [str(p).upper() for p in rule["allowed_prefixes"]]
            if not any(str_val.startswith(p) for p in prefixes):
                return (
                    "DENY",
                    f"Parameter '{param}' must start with one of {rule['allowed_prefixes']}",
                )
        if "max" in rule:
            try:
                if float(value) > float(rule["max"]):
                    return (
                        "DENY",
                        f"Parameter '{param}' {value} exceeds maximum {rule['max']}",
                    )
            except (TypeError, ValueError):
                pass
        if "min" in rule:
            try:
                if float(value) < float(rule["min"]):
                    return (
                        "DENY",
                        f"Parameter '{param}' {value} is below minimum {rule['min']}",
                    )
            except (TypeError, ValueError):
                pass

    # All inline rules passed — explicit ALLOW
    return "ALLOW", None


# ---------------------------------------------------------------------------
# Main evaluation entry point
# ---------------------------------------------------------------------------


async def evaluate(
    *,
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    agent_version_id: uuid.UUID,
    tool_id: uuid.UUID,
    parameters: dict[str, Any],
    db: AsyncSession,
) -> dict:
    """
    Evaluate whether the tool call is authorized.

    Returns:
        {"decision": "ALLOW"|"DENY", "reason": str, "policy_id": str|None}
    """
    # ── Step 1: Verify binding exists and check parameter constraints ──
    binding_result = await db.execute(
        select(ToolBinding).where(
            and_(
                ToolBinding.version_id == agent_version_id,
                ToolBinding.tool_id == tool_id,
                ToolBinding.enabled.is_(True),
            )
        )
    )
    binding = binding_result.scalar_one_or_none()

    if binding is None:
        return {
            "decision": "DENY",
            "reason": "no active tool binding found for this agent version",
            "policy_id": None,
        }

    decision, reason, _ = _check_parameter_constraints(
        parameters, binding.parameter_constraints
    )
    if decision == "DENY":
        return {"decision": "DENY", "reason": reason, "policy_id": None}

    # ── Step 2: Evaluate policies (tenant → agent → tool) ──
    policies_result = await db.execute(
        select(Policy)
        .where(
            and_(
                Policy.tenant_id == tenant_id,
                Policy.enabled.is_(True),
                or_(
                    and_(Policy.scope == "tenant", Policy.scope_ref_id.is_(None)),
                    and_(Policy.scope == "agent", Policy.scope_ref_id == agent_id),
                    and_(Policy.scope == "tool", Policy.scope_ref_id == tool_id),
                ),
            )
        )
        .order_by(
            case(
                (Policy.scope == "tenant", 1),
                (Policy.scope == "agent", 2),
                (Policy.scope == "tool", 3),
                else_=4,
            )
        )
    )
    policies = policies_result.scalars().all()

    any_explicit_allow = False

    for policy in policies:
        if policy.policy_lang == "inline":
            pol_decision, pol_reason = _evaluate_inline_policy(
                policy.policy_body, parameters
            )
            if pol_decision == "DENY":
                return {
                    "decision": "DENY",
                    "reason": pol_reason,
                    "policy_id": str(policy.id),
                }
            if pol_decision == "ALLOW":
                any_explicit_allow = True
        else:
            # OPA (rego) / Cedar: not yet integrated — abstain
            logger.info(
                "policy_engine: policy %s uses '%s' (not integrated) — abstaining",
                policy.id,
                policy.policy_lang,
            )

    # If no policies are defined, ALLOW by default (no restrictions configured).
    return {
        "decision": "ALLOW",
        "reason": "all policies passed" if any_explicit_allow or not policies else "no policies defined",
        "policy_id": None,
    }
