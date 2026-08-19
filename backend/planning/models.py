"""
Adaptive Planning 数据模型 — Phase 17 Round 1

定义 canonical Plan / PlanStep 及枚举：
  - GoalType: 计划目标类型
  - PlanningMode: 规划模式（Round1 仅 DETERMINISTIC）
  - PlanDefinitionStatus: 计划定义生命周期
  - PlanStepStatus: 步骤执行状态（投影层，非第二状态机）

关键不变量：
  - planId = stable lineage identity（跨 revision 恒定）
  - planFingerprint = deterministic structural content hash（结构变则变）
  - version = monotonically increasing revision
  - frozen Plan definition 不存 workflowRunId / executionStatus
  - PlanStepStatus 是对现有 NodeStatus / ToolExecutionStatus / WorkflowRunStatus
    的投影，不创建第二套状态机
  - UNKNOWN != ZERO：None 仍是 None，空证据 = []，不伪造 citation
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from backend.workflow.models import NodeType


# ═══════════════════════════════════════════════════════════════════════════════
# 枚举定义
# ═══════════════════════════════════════════════════════════════════════════════


class GoalType(str, Enum):
    """计划目标类型。"""
    CONGESTION_RESOLUTION = "congestion_resolution"
    ACCIDENT_RESPONSE = "accident_response"
    SIGNAL_OPTIMIZATION = "signal_optimization"
    PEDESTRIAN_SAFETY = "pedestrian_safety"
    DISPATCH = "dispatch"
    SIMULATION_EVALUATION = "simulation_evaluation"
    GENERIC = "generic"


class PlanningMode(str, Enum):
    """规划模式。"""
    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"
    # 预留（Round2+）：REPLAN


class PlanDefinitionStatus(str, Enum):
    """计划定义生命周期（区别于执行状态）。"""
    DRAFT = "draft"
    VALIDATED = "validated"
    ACTIVE = "active"


class PlanStepStatus(str, Enum):
    """步骤执行状态（投影层）。"""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class IssueSeverity(str, Enum):
    """校验问题严重度。"""
    ERROR = "error"
    WARNING = "warning"


# 终止状态集合（BLOCKED 对当前 plan revision 是 terminal）
TERMINAL_STEP_STATUSES = frozenset({
    PlanStepStatus.SUCCEEDED,
    PlanStepStatus.FAILED,
    PlanStepStatus.DENIED,
    PlanStepStatus.SKIPPED,
    PlanStepStatus.CANCELLED,
    PlanStepStatus.BLOCKED,
})

NON_TERMINAL_STEP_STATUSES = frozenset({
    PlanStepStatus.PENDING,
    PlanStepStatus.READY,
    PlanStepStatus.RUNNING,
    PlanStepStatus.AWAITING_APPROVAL,
})

# 允许作为 PlanStep 的 NodeType 子集（TRIGGER/PARALLEL/JOIN 是 adapter 生成的结构节点）
VALID_PLAN_STEP_TYPES = frozenset({
    NodeType.VALIDATE_EVENT,
    NodeType.RULE_ROUTER,
    NodeType.RAG_RETRIEVE,
    NodeType.MEMORY_CONTEXT,
    NodeType.AGENT_TASK,
    NodeType.EVIDENCE_EVALUATE,
    NodeType.RISK_GATE,
    NodeType.HUMAN_APPROVAL,
    NodeType.ACTION,
    NodeType.CLOSE,
})

# 计划最大步数（与 executor 的 max_steps=100 对齐）
MAX_PLAN_STEPS = 100

# Agent 分类（source-of-truth：router 的 selectedAgents → PlanStep 映射）
# 可执行领域 Agent（multi_agent.py 有 analyze() 实现）
EXECUTABLE_AGENT_TYPES = frozenset({
    "CongestionAgent", "AccidentAgent", "SignalAgent", "DispatchAgent",
})
# 结构性 fusion/report 角色（multi_agent.py 仅有 summarize()，无 analyze()）
# 由 evidence_evaluate + close 节点承载，不生成 agent_task 步骤
STRUCTURAL_AGENT_TYPES = frozenset({"FusionAgent", "ReportAgent"})
# Router 可能选中但无运行时实现
UNSUPPORTED_AGENT_TYPES = frozenset({"PublicSafetyAgent"})


def _utc_now_iso() -> str:
    """返回 UTC 时间 ISO 格式字符串。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_plan_id() -> str:
    """生成 Plan lineage identity（唯一，非内容派生）。

    与项目现有 ID 风格一致（wfrun_<ts>_<short>）。
    不引入外部 ID 依赖。
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"plan_{ts}_{short}"


# ═══════════════════════════════════════════════════════════════════════════════
# ValidationIssue
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ValidationIssue:
    """计划校验问题。"""
    severity: IssueSeverity
    code: str
    message: str
    stepId: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "stepId": self.stepId,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ValidationIssue":
        return cls(
            severity=IssueSeverity(d.get("severity", "error")),
            code=d.get("code", ""),
            message=d.get("message", ""),
            stepId=d.get("stepId"),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PlanStep
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class PlanStep:
    """单个计划步骤（canonical）。

    stepType 复用现有 NodeType（不新造第二套 enum）。
    frozen definition 不存执行状态；status 是投影层概念（见 status_projection.py）。
    """
    stepId: str
    stepType: NodeType
    objective: str = ""
    dependsOn: List[str] = field(default_factory=list)
    agentType: Optional[str] = None
    toolName: Optional[str] = None
    actionType: Optional[str] = None
    preconditions: List[str] = field(default_factory=list)
    expectedOutcome: str = ""
    riskLevel: str = "unknown"
    approvalRequired: bool = False
    evidenceRefs: List[Dict[str, Any]] = field(default_factory=list)
    retryPolicy: Dict[str, Any] = field(default_factory=dict)
    timeoutSeconds: int = 60
    resultRef: str = ""
    failureReason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stepId": self.stepId,
            "stepType": self.stepType.value,
            "objective": self.objective,
            "dependsOn": list(self.dependsOn),
            "agentType": self.agentType,
            "toolName": self.toolName,
            "actionType": self.actionType,
            "preconditions": list(self.preconditions),
            "expectedOutcome": self.expectedOutcome,
            "riskLevel": self.riskLevel,
            "approvalRequired": self.approvalRequired,
            "evidenceRefs": list(self.evidenceRefs),
            "retryPolicy": dict(self.retryPolicy),
            "timeoutSeconds": self.timeoutSeconds,
            "resultRef": self.resultRef,
            "failureReason": self.failureReason,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PlanStep":
        return cls(
            stepId=d["stepId"],
            stepType=NodeType(d["stepType"]),
            objective=d.get("objective", ""),
            dependsOn=list(d.get("dependsOn", [])),
            agentType=d.get("agentType"),
            toolName=d.get("toolName"),
            actionType=d.get("actionType"),
            preconditions=list(d.get("preconditions", [])),
            expectedOutcome=d.get("expectedOutcome", ""),
            riskLevel=d.get("riskLevel", "unknown"),
            approvalRequired=bool(d.get("approvalRequired", False)),
            evidenceRefs=list(d.get("evidenceRefs", [])),
            retryPolicy=dict(d.get("retryPolicy", {})),
            timeoutSeconds=int(d.get("timeoutSeconds", 60)),
            resultRef=d.get("resultRef", ""),
            failureReason=d.get("failureReason", ""),
            metadata=dict(d.get("metadata", {})),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Plan
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class Plan:
    """canonical 计划。

    planId: stable lineage identity（revision 间恒定）
    planFingerprint: deterministic structural content hash
    version: monotonically increasing revision

    不含 workflowRunId / executionStatus —— 这些属于 execution projection。
    """
    planId: str
    planFingerprint: str
    goal: str
    goalType: GoalType
    definitionStatus: PlanDefinitionStatus
    version: int
    steps: List[PlanStep]
    planningMode: PlanningMode = PlanningMode.DETERMINISTIC
    createdBy: str = "planner:deterministic_v1"
    createdAt: str = ""
    updatedAt: str = ""
    eventId: Optional[str] = None
    confidence: Optional[float] = None
    assumptions: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    evidenceRefs: List[Dict[str, Any]] = field(default_factory=list)
    memoryRefs: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    approvalIdentityVersion: int = 1
    plannerAudit: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.createdAt:
            self.createdAt = _utc_now_iso()
        if not self.updatedAt:
            self.updatedAt = self.createdAt

    def to_dict(self) -> Dict[str, Any]:
        return {
            "planId": self.planId,
            "planFingerprint": self.planFingerprint,
            "goal": self.goal,
            "goalType": self.goalType.value,
            "definitionStatus": self.definitionStatus.value,
            "version": self.version,
            "steps": [s.to_dict() for s in self.steps],
            "planningMode": self.planningMode.value,
            "createdBy": self.createdBy,
            "createdAt": self.createdAt,
            "updatedAt": self.updatedAt,
            "eventId": self.eventId,
            "confidence": self.confidence,
            "assumptions": list(self.assumptions),
            "constraints": dict(self.constraints),
            "evidenceRefs": list(self.evidenceRefs),
            "memoryRefs": list(self.memoryRefs),
            "metadata": dict(self.metadata),
            "approvalIdentityVersion": self.approvalIdentityVersion,
            "plannerAudit": dict(self.plannerAudit),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Plan":
        return cls(
            planId=d["planId"],
            planFingerprint=d.get("planFingerprint", ""),
            goal=d.get("goal", ""),
            goalType=GoalType(d.get("goalType", "generic")),
            definitionStatus=PlanDefinitionStatus(d.get("definitionStatus", "draft")),
            version=int(d.get("version", 1)),
            steps=[PlanStep.from_dict(s) for s in d.get("steps", [])],
            planningMode=PlanningMode(d.get("planningMode", "deterministic")),
            createdBy=d.get("createdBy", "planner:deterministic_v1"),
            createdAt=d.get("createdAt", ""),
            updatedAt=d.get("updatedAt", ""),
            eventId=d.get("eventId"),
            confidence=d.get("confidence"),
            assumptions=list(d.get("assumptions", [])),
            constraints=dict(d.get("constraints", {})),
            evidenceRefs=list(d.get("evidenceRefs", [])),
            memoryRefs=list(d.get("memoryRefs", [])),
            metadata=dict(d.get("metadata", {})),
            approvalIdentityVersion=int(d.get("approvalIdentityVersion", 1)),
            plannerAudit=dict(d.get("plannerAudit", {})),
        )

    def get_step(self, step_id: str) -> Optional[PlanStep]:
        """按 stepId 获取步骤。"""
        for s in self.steps:
            if s.stepId == step_id:
                return s
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Fingerprint
# ═══════════════════════════════════════════════════════════════════════════════


def compute_fingerprint(steps: List[PlanStep]) -> str:
    """计算 canonical structural fingerprint。

    只依赖结构性内容：step type / objective / dependsOn / agent/tool/action /
    ordering / risk/approval annotation / timeout / retryPolicy。

    不包含 createdAt / updatedAt / runId / 随机值 / 执行状态。
    """
    canon: List[Dict[str, Any]] = []
    for s in steps:
        canon.append({
            "stepType": s.stepType.value,
            "objective": s.objective,
            "dependsOn": list(s.dependsOn),
            "agentType": s.agentType,
            "toolName": s.toolName,
            "actionType": s.actionType,
            "riskLevel": s.riskLevel,
            "approvalRequired": s.approvalRequired,
            "timeoutSeconds": s.timeoutSeconds,
            "retryPolicy": s.retryPolicy,
            "resultRef": s.resultRef,
            "metadata": s.metadata,
        })
    payload = json.dumps(canon, sort_keys=True, ensure_ascii=False, default=str)
    return "fp_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════════════
# Revision helper（非 Replanner，仅模型层版本演进工具）
# ═══════════════════════════════════════════════════════════════════════════════


def create_revision(plan: Plan, new_steps: List[PlanStep]) -> Plan:
    """创建同一 lineage 的新 revision（Round1 模型层工具，不实现 Replanner）。

    保持 planId 不变，version + 1，重算 fingerprint。
    """
    now = _utc_now_iso()
    return Plan(
        planId=plan.planId,
        planFingerprint=compute_fingerprint(new_steps),
        goal=plan.goal,
        goalType=plan.goalType,
        definitionStatus=PlanDefinitionStatus.DRAFT,
        version=plan.version + 1,
        steps=new_steps,
        planningMode=plan.planningMode,
        createdBy=plan.createdBy,
        createdAt=plan.createdAt,
        updatedAt=now,
        eventId=plan.eventId,
        confidence=plan.confidence,
        assumptions=list(plan.assumptions),
        constraints=dict(plan.constraints),
        evidenceRefs=list(plan.evidenceRefs),
        memoryRefs=list(plan.memoryRefs),
        metadata=dict(plan.metadata),
    )
