"""
Replan Decision Engine — Phase 17 Round 2

deterministic-first。一个 Observation 最多产生一个 authoritative decision。
Round2 LLM calls = 0。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from backend.planning.budget import ExecutionLineage
from backend.planning.observation import Observation, ObservationType


class ReplanDecision(str, Enum):
    NO_REPLAN = "no_replan"
    RETRY = "retry"
    FALLBACK = "fallback"
    REPLAN = "replan"
    WAIT_FOR_APPROVAL = "wait_for_approval"
    ABORT = "abort"
    ESCALATE_HUMAN = "escalate_human"


@dataclass
class DecisionResult:
    decision: ReplanDecision
    reason: str
    triggerObservationId: str = ""
    budgetSnapshot: Dict[str, Any] = field(default_factory=dict)
    constraintRefs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "triggerObservationId": self.triggerObservationId,
            "budgetSnapshot": self.budgetSnapshot,
            "constraintRefs": self.constraintRefs,
        }


def classify_observation(
    observation: Observation,
    lineage: Optional[ExecutionLineage] = None,
) -> str:
    """确定性 pre-classification（Phase18 Round2）。

    返回：
      hard_retry / hard_replan / hard_abort / hard_escalate /
      wait_for_approval / no_replan / semantic_review

    只有 semantic_review 才允许调用 Critic；其余分类永不调用 Critic。
    语义与 Phase17 decide() 完全一致（I2），不改变 baseline fallback。
    """
    t = observation.type
    if t == ObservationType.TIMEOUT:
        if lineage is not None and lineage.budgetUsage.retriesUsed >= lineage.budgetLimits.maxRetries:
            return "hard_replan"
        return "hard_retry"
    if t == ObservationType.TOOL_FAILED:
        return "hard_retry" if observation.retryable else "semantic_review"
    if t == ObservationType.RETRY_EXHAUSTED:
        return "hard_replan"
    if t == ObservationType.TOOL_DENIED:
        return "hard_escalate"
    if t == ObservationType.TOOL_REQUIRE_APPROVAL:
        return "wait_for_approval"
    if t == ObservationType.APPROVAL_REJECTED:
        return "no_replan"
    if t in (ObservationType.AGENT_FAILED, ObservationType.SIMULATION_FAILED,
             ObservationType.MISSING_DATA, ObservationType.UPSTREAM_BLOCKED):
        return "semantic_review"
    if t == ObservationType.UNKNOWN_OUTCOME:
        return "hard_escalate"
    if t in (ObservationType.BUDGET_EXHAUSTED, ObservationType.LOOP_DETECTED):
        return "hard_abort"
    if t == ObservationType.CANCELLED:
        return "no_replan"
    # informational：NODE_FAILED / AGENT_LOW_CONFIDENCE / RAG_NO_EVIDENCE 等 → NO_REPLAN
    return "no_replan"


def _apply_critic(observation: Observation, critic: Any) -> DecisionResult:
    """SEMANTIC_REVIEW 下的 critic 组合。

    允许的 recommendation 只有 REPLAN / ABORT / ESCALATE_HUMAN（duck-typed）。
    REPLAN（默认）→ REPLAN；ABORT → ABORT（安全升级）；ESCALATE_HUMAN → ESCALATE_HUMAN。
    任何其它值（KEEP_PLAN/RETRY/未知）→ 确定性默认 REPLAN。
    """
    rec = (getattr(critic, "recommendation", "") or "").strip().lower()
    if rec == "abort":
        return DecisionResult(ReplanDecision.ABORT, "critic: abort (irrecoverable semantic failure)", observation.observationId)
    if rec == "escalate_human":
        return DecisionResult(ReplanDecision.ESCALATE_HUMAN, "critic: escalate to human", observation.observationId)
    return DecisionResult(ReplanDecision.REPLAN, "semantic failure → replan", observation.observationId)


class ReplanDecisionEngine:
    """deterministic 决策引擎。"""

    def decide(
        self,
        observation: Observation,
        lineage: Optional[ExecutionLineage] = None,
        critic: Optional[Any] = None,
    ) -> DecisionResult:
        """根据 Observation + lineage（+ 可选 CriticRecommendation）产生唯一 authoritative decision。

        Critic 只在 SEMANTIC_REVIEW 分类下、且 critic 非空时参与；其 recommendation
        仅能 confirm REPLAN 或安全升级 ABORT/ESCALATE_HUMAN，绝不覆盖 hard rules。
        critic=None / 失败时，结果与 Phase17 deterministic decide() 完全一致（I2）。
        """
        if critic is not None and classify_observation(observation, lineage) == "semantic_review":
            return _apply_critic(observation, critic)
        t = observation.type

        if t == ObservationType.TIMEOUT:
            if lineage is not None and lineage.budgetUsage.retriesUsed >= lineage.budgetLimits.maxRetries:
                return DecisionResult(ReplanDecision.REPLAN, "retry budget exhausted", observation.observationId)
            return DecisionResult(ReplanDecision.RETRY, "transient timeout, retryable", observation.observationId)

        if t == ObservationType.TOOL_FAILED:
            if observation.retryable:
                return DecisionResult(ReplanDecision.RETRY, "transient tool failure", observation.observationId)
            return DecisionResult(ReplanDecision.REPLAN, "semantic tool failure", observation.observationId)

        if t == ObservationType.RETRY_EXHAUSTED:
            return DecisionResult(ReplanDecision.REPLAN, "retry exhausted", observation.observationId)

        if t == ObservationType.TOOL_DENIED:
            return DecisionResult(ReplanDecision.ESCALATE_HUMAN, "policy deny, no retry/alias", observation.observationId)

        if t == ObservationType.TOOL_REQUIRE_APPROVAL:
            return DecisionResult(ReplanDecision.WAIT_FOR_APPROVAL, "requires approval", observation.observationId)

        if t == ObservationType.APPROVAL_REJECTED:
            return DecisionResult(ReplanDecision.NO_REPLAN, "rejected; explicit replan required", observation.observationId)

        if t in (ObservationType.AGENT_FAILED, ObservationType.SIMULATION_FAILED):
            return DecisionResult(ReplanDecision.REPLAN, f"{t.value} → replan", observation.observationId)

        if t == ObservationType.MISSING_DATA:
            return DecisionResult(ReplanDecision.REPLAN, "required data missing", observation.observationId)

        if t == ObservationType.UPSTREAM_BLOCKED:
            return DecisionResult(ReplanDecision.REPLAN, "upstream blocked, replan suffix", observation.observationId)

        if t == ObservationType.UNKNOWN_OUTCOME:
            return DecisionResult(ReplanDecision.ESCALATE_HUMAN, "unknown outcome, no auto replay", observation.observationId)

        if t == ObservationType.BUDGET_EXHAUSTED:
            return DecisionResult(ReplanDecision.ABORT, "budget exhausted", observation.observationId)

        if t == ObservationType.LOOP_DETECTED:
            return DecisionResult(ReplanDecision.ABORT, "loop detected", observation.observationId)

        if t == ObservationType.CANCELLED:
            return DecisionResult(ReplanDecision.NO_REPLAN, "cancelled", observation.observationId)

        # 信息性观察
        return DecisionResult(ReplanDecision.NO_REPLAN, f"{t.value} is informational", observation.observationId)
