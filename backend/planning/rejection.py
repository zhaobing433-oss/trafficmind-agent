"""
Action Intent / Constraints — Phase 17 Round 2

集中式 ActionIntentFamily 映射（不散落 if/else）+ RejectionConstraint /
PolicyDenyConstraint。约束属于 execution lineage（rootRunId），非 Plan 全局永久。

审批拒绝（rejection）绝不构成新 action 授权；等价 intent 必须重新审批。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ActionIntentFamily(str, Enum):
    NOTIFICATION = "notification"
    TRAFFIC_DIVERSION = "traffic_diversion"
    SIGNAL_CONTROL = "signal_control"
    SIMULATION = "simulation"
    PERSISTENCE = "persistence"
    GENERIC = "generic"


# 集中式 deterministic mapping（单一真相，禁止散落 if/else）
_ACTION_INTENT_FAMILY: Dict[str, ActionIntentFamily] = {
    # notification
    "notify_wechat": ActionIntentFamily.NOTIFICATION,
    "notify_dingtalk": ActionIntentFamily.NOTIFICATION,
    "send_email": ActionIntentFamily.NOTIFICATION,
    "send_wechat_work": ActionIntentFamily.NOTIFICATION,
    "send_dingtalk": ActionIntentFamily.NOTIFICATION,
    "notify_high_risk_event": ActionIntentFamily.NOTIFICATION,
    # traffic diversion
    "simulation_traffic_diversion": ActionIntentFamily.TRAFFIC_DIVERSION,
    "traffic_diversion": ActionIntentFamily.TRAFFIC_DIVERSION,
    # signal control
    "simulation_signal_adjustment": ActionIntentFamily.SIGNAL_CONTROL,
    "simulation_signal_adjust": ActionIntentFamily.SIGNAL_CONTROL,
    "signal_adjustment": ActionIntentFamily.SIGNAL_CONTROL,
    "signal_adjust": ActionIntentFamily.SIGNAL_CONTROL,
    # simulation (others)
    "simulation_lane_control": ActionIntentFamily.SIMULATION,
    "simulation_dispatch_coordination": ActionIntentFamily.SIMULATION,
    "simulation_monitor": ActionIntentFamily.SIMULATION,
    "simulation_close": ActionIntentFamily.SIMULATION,
    # persistence
    "save_result": ActionIntentFamily.PERSISTENCE,
    "save_event_analysis": ActionIntentFamily.PERSISTENCE,
}


def intent_family(action_type: str) -> ActionIntentFamily:
    """返回 actionType 的 intent family（未知 → 用 ToolRegistry category 兜底，再 GENERIC）。"""
    if action_type in _ACTION_INTENT_FAMILY:
        return _ACTION_INTENT_FAMILY[action_type]
    # 兜底：ToolRegistry category
    try:
        from backend.agent.tool_registry import get_tool_registry
        meta = get_tool_registry().get(action_type)
        if meta is not None:
            cat = meta.category
            if cat == "notification":
                return ActionIntentFamily.NOTIFICATION
            if cat == "simulation":
                return ActionIntentFamily.SIMULATION
            if cat == "persistence":
                return ActionIntentFamily.PERSISTENCE
    except Exception:
        pass
    return ActionIntentFamily.GENERIC


@dataclass
class RejectionConstraint:
    """人工审批拒绝约束（execution lineage 作用域）。"""
    actionType: str
    intentFamily: ActionIntentFamily
    approvalId: str = ""
    stepId: str = ""
    reason: str = ""
    rejectedAt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "actionType": self.actionType,
            "intentFamily": self.intentFamily.value,
            "approvalId": self.approvalId,
            "stepId": self.stepId,
            "reason": self.reason,
            "rejectedAt": self.rejectedAt,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RejectionConstraint":
        return cls(
            actionType=d.get("actionType", ""),
            intentFamily=ActionIntentFamily(d.get("intentFamily", "generic")),
            approvalId=d.get("approvalId", ""),
            stepId=d.get("stepId", ""),
            reason=d.get("reason", ""),
            rejectedAt=d.get("rejectedAt", ""),
        )


@dataclass
class PolicyDenyConstraint:
    """ToolPolicy DENY 约束（execution lineage 作用域）。"""
    toolName: str
    actionType: str
    intentFamily: ActionIntentFamily
    reason: str = ""
    policyDecision: str = "deny"
    recordedAt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "toolName": self.toolName,
            "actionType": self.actionType,
            "intentFamily": self.intentFamily.value,
            "reason": self.reason,
            "policyDecision": self.policyDecision,
            "recordedAt": self.recordedAt,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PolicyDenyConstraint":
        return cls(
            toolName=d.get("toolName", ""),
            actionType=d.get("actionType", ""),
            intentFamily=ActionIntentFamily(d.get("intentFamily", "generic")),
            reason=d.get("reason", ""),
            policyDecision=d.get("policyDecision", "deny"),
            recordedAt=d.get("recordedAt", ""),
        )


def is_intent_rejected(constraints: List[Dict[str, Any]], action_type: str) -> bool:
    """判断 actionType 的 intent family 是否已被拒绝约束覆盖。"""
    fam = intent_family(action_type)
    for c in constraints:
        if not isinstance(c, dict):
            continue
        try:
            c_fam = ActionIntentFamily(c.get("intentFamily", "generic"))
        except ValueError:
            c_fam = ActionIntentFamily.GENERIC
        # 同 actionType 或同 intent family 均视为被约束
        if c.get("actionType") == action_type or c_fam == fam:
            return True
    return False


def is_intent_denied(constraints: List[Dict[str, Any]], action_type: str) -> bool:
    """判断 actionType 是否被 PolicyDenyConstraint 覆盖。"""
    return is_intent_rejected(constraints, action_type)
