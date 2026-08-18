"""
Canonical Observation — Phase 17 Round 2

Replanning 的输入模型。每个 runtime 结果可转为 Observation。

关键不变量：
  - retryable 是 DERIVED（不持久化自由 bool），由 type/status/failureCode 确定性派生
  - UNKNOWN_OUTCOME 是正式 ObservationType（不得 retry/replay）
  - compatibility validator fail-closed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class ObservationScope(str, Enum):
    STEP = "step"
    RUN = "run"
    PLAN = "plan"


class ObservationType(str, Enum):
    NODE_FAILED = "node_failed"
    TOOL_FAILED = "tool_failed"
    TOOL_DENIED = "tool_denied"
    TOOL_REQUIRE_APPROVAL = "tool_require_approval"
    APPROVAL_REJECTED = "approval_rejected"
    AGENT_FAILED = "agent_failed"
    AGENT_LOW_CONFIDENCE = "agent_low_confidence"
    RAG_NO_EVIDENCE = "rag_no_evidence"
    SIMULATION_FAILED = "simulation_failed"
    TIMEOUT = "timeout"
    RETRY_EXHAUSTED = "retry_exhausted"
    MISSING_DATA = "missing_data"
    UPSTREAM_BLOCKED = "upstream_blocked"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    LOOP_DETECTED = "loop_detected"
    UNKNOWN_OUTCOME = "unknown_outcome"


class ObservationStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_REJECTED = "approval_rejected"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class ObservationSource(str, Enum):
    NODE = "node"
    AGENT = "agent"
    TOOL = "tool"
    APPROVAL = "approval"
    RISK = "risk"
    RAG = "rag"
    MEMORY = "memory"
    SIMULATION = "simulation"
    BUDGET = "budget"
    LOOP = "loop"
    SYSTEM = "system"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_observation_id(run_id: str = "") -> str:
    """全局唯一 Observation ID（非 MAX(seq)+1，避免 race）。"""
    import uuid
    return f"obs_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


@dataclass
class Observation:
    """canonical 观察。identity 字段 REQUIRED。"""
    observationId: str
    planId: str
    planVersion: int
    runId: str
    type: ObservationType
    status: ObservationStatus
    scope: ObservationScope
    source: ObservationSource
    timestamp: str = field(default_factory=_utc_now_iso)
    stepId: Optional[str] = None
    output: Optional[Dict[str, Any]] = None
    confidence: Optional[float] = None
    evidenceRefs: List[Dict[str, Any]] = field(default_factory=list)
    failureCode: Optional[str] = None
    failureReason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = _utc_now_iso()

    @property
    def retryable(self) -> bool:
        """DERIVED（非持久化）。由 type/status/failureCode 确定性派生。"""
        if self.type == ObservationType.TIMEOUT:
            return True
        if self.type == ObservationType.TOOL_FAILED:
            code = self.failureCode or ""
            return code.startswith("transient") or code.startswith("network")
        if self.type in (
            ObservationType.TOOL_DENIED,
            ObservationType.APPROVAL_REJECTED,
            ObservationType.UNKNOWN_OUTCOME,
            ObservationType.RETRY_EXHAUSTED,
            ObservationType.LOOP_DETECTED,
            ObservationType.BUDGET_EXHAUSTED,
            ObservationType.CANCELLED,
        ):
            return False
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observationId": self.observationId,
            "planId": self.planId,
            "planVersion": self.planVersion,
            "runId": self.runId,
            "type": self.type.value,
            "status": self.status.value,
            "scope": self.scope.value,
            "source": self.source.value,
            "timestamp": self.timestamp,
            "stepId": self.stepId,
            "output": self.output,
            "confidence": self.confidence,
            "evidenceRefs": self.evidenceRefs,
            "failureCode": self.failureCode,
            "failureReason": self.failureReason,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Observation":
        return cls(
            observationId=d["observationId"],
            planId=d.get("planId", ""),
            planVersion=int(d.get("planVersion", 1)),
            runId=d.get("runId", ""),
            type=ObservationType(d["type"]),
            status=ObservationStatus(d["status"]),
            scope=ObservationScope(d["scope"]),
            source=ObservationSource(d["source"]),
            timestamp=d.get("timestamp", ""),
            stepId=d.get("stepId"),
            output=d.get("output"),
            confidence=d.get("confidence"),
            evidenceRefs=list(d.get("evidenceRefs", [])),
            failureCode=d.get("failureCode"),
            failureReason=d.get("failureReason"),
            metadata=dict(d.get("metadata", {})),
        )


# ── compatibility matrix（fail-closed）─────────────────────────────────────

# (type, status) 非法组合
_INVALID_TYPE_STATUS = frozenset({
    (ObservationType.TOOL_DENIED, ObservationStatus.SUCCESS),
    (ObservationType.APPROVAL_REJECTED, ObservationStatus.SUCCESS),
    (ObservationType.LOOP_DETECTED, ObservationStatus.SUCCESS),
    (ObservationType.UNKNOWN_OUTCOME, ObservationStatus.SUCCESS),
    (ObservationType.BUDGET_EXHAUSTED, ObservationStatus.SUCCESS),
    (ObservationType.CANCELLED, ObservationStatus.SUCCESS),
})

# type → 期望 scope（若非期望则 warning/error）
_TYPE_SCOPE = {
    ObservationType.TOOL_FAILED: ObservationScope.STEP,
    ObservationType.TOOL_DENIED: ObservationScope.STEP,
    ObservationType.TOOL_REQUIRE_APPROVAL: ObservationScope.STEP,
    ObservationType.APPROVAL_REJECTED: ObservationScope.STEP,
    ObservationType.AGENT_FAILED: ObservationScope.STEP,
    ObservationType.AGENT_LOW_CONFIDENCE: ObservationScope.STEP,
    ObservationType.SIMULATION_FAILED: ObservationScope.STEP,
    ObservationType.TIMEOUT: ObservationScope.STEP,
    ObservationType.RETRY_EXHAUSTED: ObservationScope.STEP,
    ObservationType.MISSING_DATA: ObservationScope.STEP,
    ObservationType.UPSTREAM_BLOCKED: ObservationScope.STEP,
    ObservationType.UNKNOWN_OUTCOME: ObservationScope.STEP,
    ObservationType.BUDGET_EXHAUSTED: ObservationScope.RUN,
    ObservationType.LOOP_DETECTED: ObservationScope.PLAN,
    ObservationType.CANCELLED: ObservationScope.RUN,
}


def validate_observation(obs: Observation) -> List[str]:
    """compatibility validator。返回问题列表，空 = 合法。"""
    issues: List[str] = []

    if (obs.type, obs.status) in _INVALID_TYPE_STATUS:
        issues.append(f"非法 type/status 组合: {obs.type.value} + {obs.status.value}")

    if obs.scope == ObservationScope.STEP and not obs.stepId:
        issues.append("STEP scope 必须携带 stepId")

    if not obs.planId or not obs.runId or not obs.observationId:
        issues.append("identity 不完整：planId/runId/observationId 不能为空")

    expected_scope = _TYPE_SCOPE.get(obs.type)
    if expected_scope is not None and obs.scope != expected_scope:
        # 允许 BUDGET_EXHAUSTED 在 RUN 或 PLAN；其余严格
        if not (obs.type == ObservationType.BUDGET_EXHAUSTED and obs.scope == ObservationScope.PLAN):
            issues.append(f"type {obs.type.value} 期望 scope {expected_scope.value}，实际 {obs.scope.value}")

    return issues
