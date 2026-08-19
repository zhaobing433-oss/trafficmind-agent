"""
PlanCritic — Phase18 Round2

Critic 只做 bounded semantic review，输出 RECOMMENDATION（非 runtime command）。
权威仍：ReplanDecisionEngine / ExecutionBudget / LoopGuard / ToolPolicy / Approval /
WorkflowExecutor / RunDriver。

关键约束：
  - recommendation 仅 REPLAN / ABORT / ESCALATE_HUMAN（KEEP_PLAN / RETRY 已删除）
  - 其它任何值 → schema_invalid → deterministic SEMANTIC_REVIEW default = REPLAN
  - 不保存 CoT / raw prompt / raw response
  - Critic 不得 import/build revision / child / executor / tool
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from backend.planning.proposal import PlannerFailure, PlannerFailureCode
from backend.planning.replan_decision import classify_observation


class CriticRecommendationType(str, Enum):
    """Critic 允许的 recommendation（V2.1 已删除 KEEP_PLAN/RETRY）。"""
    REPLAN = "replan"
    ABORT = "abort"
    ESCALATE_HUMAN = "escalate_human"


_ALLOWED_RECOMMENDATIONS = {r.value for r in CriticRecommendationType}

_MAX_REASON_SUMMARY = 500
_MAX_LIST_ITEMS = 20
_MAX_ITEM_LENGTH = 200

# raw 字段黑名单（复用 proposal 的语义）
_FORBIDDEN_RAW_FIELDS = frozenset({
    "toolName", "agentType", "actionType", "stepId", "nodeId", "runId",
    "riskLevel", "approvalRequired", "retryPolicy", "timeoutSeconds",
    "executionActionType", "executionAgentType",
})


@dataclass
class CriticContext:
    """Critic 输入（最小化；observation/evidence 为 UNTRUSTED DATA）。"""
    goal: str = ""
    goalType: str = ""
    planSummary: List[Dict[str, Any]] = field(default_factory=list)
    planVersion: int = 1
    completedStepIds: List[str] = field(default_factory=list)
    currentStep: Dict[str, Any] = field(default_factory=dict)
    observation: Dict[str, Any] = field(default_factory=dict)
    budgetSummary: Dict[str, Any] = field(default_factory=dict)
    loopGuardSummary: Dict[str, Any] = field(default_factory=dict)
    rejectionConstraints: List[Dict[str, Any]] = field(default_factory=list)
    policyDenyConstraints: List[Dict[str, Any]] = field(default_factory=list)
    evidenceRefs: List[Dict[str, Any]] = field(default_factory=list)
    trajectorySummary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CriticRecommendation:
    """Critic 语义推荐（sanitized，不含 CoT / runtime command）。"""
    recommendation: str
    confidence: float = 0.0
    reasonSummary: str = ""
    semanticFailureType: str = ""
    evidenceGaps: List[str] = field(default_factory=list)
    unresolvedRisks: List[str] = field(default_factory=list)

    @classmethod
    def from_dict_strict(cls, d: Dict[str, Any]) -> "CriticRecommendation":
        from backend.planning.proposal import _require_type

        if not isinstance(d, dict):
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, "critic 输出不是 dict")
        allowed = {"recommendation", "confidence", "reasonSummary", "semanticFailureType",
                   "evidenceGaps", "unresolvedRisks"}
        for k in d:
            if k not in allowed:
                raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, f"未知字段 '{k}'")
            if k in _FORBIDDEN_RAW_FIELDS:
                raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, f"禁止字段 '{k}'")

        recommendation = d.get("recommendation")
        if not isinstance(recommendation, str) or recommendation.strip().lower() not in _ALLOWED_RECOMMENDATIONS:
            raise PlannerFailure(
                PlannerFailureCode.SCHEMA_INVALID,
                f"critic recommendation 非法 '{recommendation}'（仅 replan|abort|escalate_human）",
            )

        confidence = d.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)):
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, "confidence 类型错误")
        confidence = float(confidence)
        if confidence < 0.0 or confidence > 1.0:
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, "confidence 超出 [0,1]")

        reason_summary = d.get("reasonSummary", "")
        if not isinstance(reason_summary, str) or len(reason_summary) > _MAX_REASON_SUMMARY:
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, "reasonSummary 超限/类型错误")

        semantic_failure_type = d.get("semanticFailureType", "")
        if not isinstance(semantic_failure_type, str):
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, "semanticFailureType 类型错误")

        def _str_list(v, name):
            if not isinstance(v, list):
                raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, f"{name} 不是 list")
            if len(v) > _MAX_LIST_ITEMS:
                raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, f"{name} 超限")
            for item in v:
                if not isinstance(item, str) or len(item) > _MAX_ITEM_LENGTH:
                    raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, f"{name} 元素非法")
            return list(v)

        return cls(
            recommendation=recommendation.strip().lower(),
            confidence=confidence,
            reasonSummary=reason_summary,
            semanticFailureType=semantic_failure_type,
            evidenceGaps=_str_list(d.get("evidenceGaps", []), "evidenceGaps"),
            unresolvedRisks=_str_list(d.get("unresolvedRisks", []), "unresolvedRisks"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "reasonSummary": self.reasonSummary,
            "semanticFailureType": self.semanticFailureType,
            "evidenceGaps": list(self.evidenceGaps),
            "unresolvedRisks": list(self.unresolvedRisks),
        }


def critic_eligible(observation, lineage=None) -> bool:
    """是否为 SEMANTIC_REVIEW（唯一允许调用 Critic 的分类）。"""
    return classify_observation(observation, lineage) == "semantic_review"


def build_critic_invocation_key(
    root_run_id: str,
    run_id: str,
    plan_version: int,
    observation_type: str,
    failed_step_id: str,
) -> str:
    """criticInvocationKey：stable canonical inputs（不含 random observationId/timestamp）。

    同一 logical replan boundary restart 后 key 相同；不同 child run key 不同。
    """
    sid = failed_step_id or "unknown"
    return f"{root_run_id}:{run_id}:{plan_version}:{observation_type}:{sid}"


def invoke_critic_sync(client, ctx: CriticContext) -> CriticRecommendation:
    """sync 调用 provider → strict parse CriticRecommendation（sync continuation 路径）。"""
    from backend.planning.critic_prompts import build_critic_messages

    system, user = build_critic_messages(ctx)
    data, _usage, _attempts = client.call_structured_json_sync(system, user)
    return CriticRecommendation.from_dict_strict(data)
