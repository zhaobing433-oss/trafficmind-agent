"""
工具策略 — Phase 16 Round 3

统一工具调用 policy 判断。

决策：
  ALLOW            — 允许执行
  REQUIRE_APPROVAL — 需要人工审批
  DENY             — 拒绝（未知/未注册工具 fail-closed）

默认安全策略：
  READ_ONLY  → ALLOW
  HIGH_RISK  → REQUIRE_APPROVAL
  WRITE      → 按 metadata approvalRequired 决定
  未知工具   → DENY（fail-closed）
"""
from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from backend.agent.tool_registry import ToolRisk, get_tool_registry


class PolicyDecision(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class ToolExecutionStatus(str, Enum):
    """工具执行结果统一语义（Section 17）。

    不得把 approval_required / timeout / denied 描述成 success。
    """
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    DENIED = "denied"
    APPROVAL_REQUIRED = "approval_required"


def evaluate_tool_request(
    tool_name: str,
    caller: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """评估工具调用请求。

    Args:
        tool_name: 工具名。
        caller: 调用方（Agent 名 / workflow run 等）。
        context: 额外上下文（可选）。

    Returns:
        {
          "decision": "allow" | "require_approval" | "deny",
          "reason": str,
          "riskLevel": str,
          "tool": tool_name,
          "caller": caller,
        }
    """
    registry = get_tool_registry()
    meta = registry.get(tool_name)

    # 未知工具 → fail-closed
    if meta is None:
        return {
            "decision": PolicyDecision.DENY.value,
            "reason": f"未注册工具 '{tool_name}'，拒绝执行（fail-closed）",
            "riskLevel": "unknown",
            "tool": tool_name,
            "caller": caller,
        }

    # READ_ONLY → ALLOW
    if meta.riskLevel == ToolRisk.READ_ONLY:
        return {
            "decision": PolicyDecision.ALLOW.value,
            "reason": "只读工具，允许执行",
            "riskLevel": meta.riskLevel.value,
            "tool": tool_name,
            "caller": caller,
        }

    # HIGH_RISK → REQUIRE_APPROVAL（或 DENY if no approval gate）
    if meta.riskLevel == ToolRisk.HIGH_RISK:
        return {
            "decision": PolicyDecision.REQUIRE_APPROVAL.value,
            "reason": f"高风险工具（{meta.description or tool_name}），需要人工审批",
            "riskLevel": meta.riskLevel.value,
            "tool": tool_name,
            "caller": caller,
            "approvalRequired": True,
        }

    # WRITE → 按 metadata approvalRequired 决定
    if meta.riskLevel == ToolRisk.WRITE:
        if meta.approvalRequired:
            return {
                "decision": PolicyDecision.REQUIRE_APPROVAL.value,
                "reason": f"写操作工具（{meta.description or tool_name}）要求审批",
                "riskLevel": meta.riskLevel.value,
                "tool": tool_name,
                "caller": caller,
                "approvalRequired": True,
            }
        return {
            "decision": PolicyDecision.ALLOW.value,
            "reason": f"写操作工具（{meta.description or tool_name}），按策略允许",
            "riskLevel": meta.riskLevel.value,
            "tool": tool_name,
            "caller": caller,
        }

    # 兜底（理论上不可达）
    return {
        "decision": PolicyDecision.DENY.value,
        "reason": f"工具 '{tool_name}' 风险等级无法判定，拒绝执行",
        "riskLevel": meta.riskLevel.value,
        "tool": tool_name,
        "caller": caller,
    }


def classify_tool_result(result: Any) -> ToolExecutionStatus:
    """工具执行结果 → 统一失败语义（Section 17）。

    识别「返回了失败结果但未抛异常」的执行：
      - None / 空结果 → FAILURE
      - {"sent": False} / {"saved": False} → FAILURE
      - {"status": "failed"/"denied"/"timeout"/...} → 对应状态
      - {"error": <非空>} → FAILURE

    确保 Agent / Action 不得把失败标记为 success。
    """
    if result is None:
        return ToolExecutionStatus.FAILURE

    if isinstance(result, dict):
        if result.get("sent") is False or result.get("saved") is False:
            return ToolExecutionStatus.FAILURE
        status = result.get("status")
        if isinstance(status, str):
            s = status.lower()
            if s in ("failed", "failure", "error"):
                return ToolExecutionStatus.FAILURE
            if s in ("denied", "deny"):
                return ToolExecutionStatus.DENIED
            if s in ("timeout", "timed_out"):
                return ToolExecutionStatus.TIMEOUT
            if s in ("approval_required", "require_approval"):
                return ToolExecutionStatus.APPROVAL_REQUIRED
        if result.get("error"):
            return ToolExecutionStatus.FAILURE

    return ToolExecutionStatus.SUCCESS


def enforce_tool_request(
    tool_name: str,
    caller: str = "",
    context: Optional[Dict[str, Any]] = None,
    is_approved: bool = False,
) -> Dict[str, Any]:
    """工具门禁：根据 ToolPolicy 决定是否放行（Section 11）。

    这是「阻止执行」的可复用原语：
      - DENY（未知/未注册）→ 放行 False，status=denied（fail-closed，绝不执行）
      - REQUIRE_APPROVAL 且未批准 → 放行 False，status=approval_required
      - 其余 → 放行 True

    Args:
        tool_name: 工具名。
        caller: 调用方标识。
        context: 额外上下文（可选）。
        is_approved: 是否已经过人工审批（如已在 approved_actions 中）。

    Returns:
        {
          "allowed": bool,
          "status": "allow" | "denied" | "approval_required",
          "decision": ...,
          "reason": str,
          "riskLevel": str,
          "tool": str,
          "caller": str,
          "approvalRequired": bool,
          "audit": {tool, caller, riskLevel, decision, reason, timestamp},
        }
    """
    decision = evaluate_tool_request(tool_name, caller, context)
    decision_name = decision["decision"]

    audit = {
        "tool": tool_name,
        "caller": caller,
        "riskLevel": decision.get("riskLevel", "unknown"),
        "decision": decision_name,
        "reason": decision.get("reason", ""),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # 未知/未注册工具 → fail-closed
    if decision_name == PolicyDecision.DENY.value:
        audit["status"] = ToolExecutionStatus.DENIED.value
        return {
            "allowed": False,
            "status": ToolExecutionStatus.DENIED.value,
            "decision": decision_name,
            "reason": decision["reason"],
            "riskLevel": decision.get("riskLevel", "unknown"),
            "tool": tool_name,
            "caller": caller,
            "approvalRequired": False,
            "audit": audit,
        }

    # 高风险/要求审批，且尚未经人工审批 → 阻止执行
    if decision_name == PolicyDecision.REQUIRE_APPROVAL.value and not is_approved:
        audit["status"] = ToolExecutionStatus.APPROVAL_REQUIRED.value
        return {
            "allowed": False,
            "status": ToolExecutionStatus.APPROVAL_REQUIRED.value,
            "decision": decision_name,
            "reason": decision["reason"],
            "riskLevel": decision.get("riskLevel", "unknown"),
            "tool": tool_name,
            "caller": caller,
            "approvalRequired": True,
            "audit": audit,
        }

    # 放行（READ_ONLY / WRITE 且已批准 / 要求审批但已批准）
    audit["status"] = ToolExecutionStatus.SUCCESS.value
    return {
        "allowed": True,
        "status": "allow",
        "decision": decision_name,
        "reason": decision["reason"],
        "riskLevel": decision.get("riskLevel", "unknown"),
        "tool": tool_name,
        "caller": caller,
        "approvalRequired": decision_name == PolicyDecision.REQUIRE_APPROVAL.value,
        "audit": audit,
    }
