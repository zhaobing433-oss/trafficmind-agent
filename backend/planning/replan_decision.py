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


class ReplanDecisionEngine:
    """deterministic 决策引擎。"""

    def decide(
        self,
        observation: Observation,
        lineage: Optional[ExecutionLineage] = None,
    ) -> DecisionResult:
        """根据 Observation + lineage 产生唯一 authoritative decision。"""
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
