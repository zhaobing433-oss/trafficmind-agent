"""
上下文裁剪 — Phase 9.1
每个 Agent 只接收其角色允许的字段子集，不接收完整状态。
"""

import copy
from typing import Any, Dict, List
from backend.agent.collaboration.roles import get_agent_capability
from backend.grounding.rendering import render_grounded_context_for_agent


def project_context_for_agent(state: Dict[str, Any], agent_name: str) -> Dict[str, Any]:
    """根据 Agent 角色裁剪上下文。只返回该 Agent 被允许接收的字段。"""
    try:
        cap = get_agent_capability(agent_name)
    except ValueError:
        return {}

    allowed = set(cap.get("allowed_input_fields", []))
    if not allowed:
        return {}

    # Normalize state keys
    event = state.get("normalized_event", state)
    projected = {}
    for field in allowed:
        if field in event:
            projected[field] = event[field]
        elif field in state:
            projected[field] = state[field]

    grounding_context = state.get("grounding_context")
    if "groundedContext" in allowed and isinstance(grounding_context, dict) and grounding_context:
        rendered = render_grounded_context_for_agent(grounding_context)
        projected["groundedContext"] = copy.deepcopy(grounding_context)
        projected["groundingFacts"] = list(rendered.get("facts", []))
        projected["groundingEvidenceRefs"] = copy.deepcopy(rendered.get("evidenceRefs", []))

    # DispatchAgent special: needs domain agent results
    if agent_name == "DispatchAgent":
        projected["domain_results"] = _extract_domain_results(state)

    # ConflictArbiter special: only conflict data
    if agent_name == "ConflictArbiter":
        projected["conflict_data"] = state.get("conflicts", [])

    # FusionAgent special: completed results + arbitration
    if agent_name == "FusionAgent":
        projected["completed_results"] = state.get("task_results", {})
        projected["arbitration_results"] = state.get("arbitration_results", [])

    return projected


def _extract_domain_results(state: Dict[str, Any]) -> Dict[str, Any]:
    """提取领域 Agent 的结构化结果。"""
    task_results = state.get("task_results", {})
    domain = {}
    for agent in ["CongestionAgent", "SignalAgent", "PublicSafetyAgent"]:
        if agent in task_results:
            domain[agent] = {
                "findings": task_results[agent].get("findings", []),
                "confidence": task_results[agent].get("confidence", 0),
                "suggestion": task_results[agent].get("suggestion", ""),
                "urgency": task_results[agent].get("urgency", "low"),
            }
    return domain


def validate_required_fields(state: Dict[str, Any], agent_name: str) -> List[str]:
    """检查 Agent 必要输入字段是否齐全。返回缺失字段列表。"""
    try:
        cap = get_agent_capability(agent_name)
    except ValueError:
        return ["agent_not_registered"]
    required = set(cap.get("required_input_fields", []))
    event = state.get("normalized_event", state)
    return [f for f in required if f not in event and f not in state]
