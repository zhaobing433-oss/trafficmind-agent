"""
Plan Proposal DTO + PlannerFailure + PlannerAudit — Phase 18 Round 1

Authoring 层数据模型（LLM 只 PROPOSE，不直接产出 canonical Plan）。

关键不变量：
  - PlanProposal / PlanProposalStep 是 proposal-local 模型，不含任何 runtime identity
  - proposalStepId 只是 proposal-local 引用 ID，绝不成为 canonical stepId / approval identity
  - 禁止 LLM 输出 raw toolName / agentType / actionType / approvalRequired / riskLevel /
    retryPolicy / timeoutSeconds —— 这些由 compiler / registry 决定
  - from_dict_strict：unknown field / 错误 primitive type / 重复 proposalStepId / raw 字段 → 拒绝
  - PlannerFailure 是统一异常，canonical code 单一真相（各层禁止自由拼字符串再 contains 判断）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════════════════════
# PlannerFailure — 统一 canonical 失败
# ═══════════════════════════════════════════════════════════════════════════════

# canonical 失败 code（单一真相）
class PlannerFailureCode:
    LLM_UNAVAILABLE = "llm_unavailable"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"
    INVALID_JSON = "invalid_json"
    SCHEMA_INVALID = "schema_invalid"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    UNSUPPORTED_PLAN_SHAPE = "unsupported_plan_shape"
    COMPILE_ERROR = "compile_error"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    SNAPSHOT_MISMATCH = "snapshot_mismatch"
    INVALID_PARAMETER_HINTS = "invalid_parameter_hints"


class PlannerFailure(Exception):
    """统一 planner 失败（canonical code + message + retryable）。"""

    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(f"[{code}] {message}")

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


# raw 字段黑名单：LLM 偷偷输出这些 → schema reject
_FORBIDDEN_RAW_FIELDS = frozenset({
    "toolName", "tool_name",
    "agentType", "agent_type",
    "actionType", "action_type",
    "approvalRequired", "approval_required",
    "riskLevel", "risk_level",
    "retryPolicy", "retry_policy",
    "timeoutSeconds", "timeout_seconds",
    "stepId", "step_id",
    "nodeId", "node_id",
})

# ── proposal 资源边界（保守上限，防止 schema-legal 但资源爆炸）──────────────
MAX_PROPOSAL_STEPS = 30
MAX_INTENT_LENGTH = 200
MAX_SUMMARY_LENGTH = 500          # goalSummary / expectedOutcome / plannerReasonSummary
MAX_ASSUMPTIONS = 20
MAX_EVIDENCE_NEEDS = 10
MAX_PARAMETER_HINT_KEYS = 20
MAX_JSON_CHARS = 100_000          # raw LLM JSON 最大长度（llm_client 在 parse 前强制）


# ═══════════════════════════════════════════════════════════════════════════════
# 严格类型校验 helper
# ═══════════════════════════════════════════════════════════════════════════════

def _require_type(value: Any, types, name: str) -> Any:
    """校验 primitive 类型，错误则 raise PlannerFailure(schema_invalid)。"""
    if isinstance(types, type):
        types = (types,)
    if not isinstance(value, types):
        raise PlannerFailure(
            PlannerFailureCode.SCHEMA_INVALID,
            f"字段 '{name}' 类型错误：期望 {[t.__name__ for t in types]}，实际 {type(value).__name__}",
        )
    return value


def _reject_unknown_fields(allowed: set, d: Dict[str, Any], where: str) -> None:
    """unknown field → schema reject。"""
    for k in d:
        if k not in allowed:
            raise PlannerFailure(
                PlannerFailureCode.SCHEMA_INVALID,
                f"未知字段 '{k}' 出现在 {where}",
            )


def _reject_raw_fields(d: Dict[str, Any], where: str) -> None:
    """raw tool/agent/action/risk/approval 字段 → schema reject。"""
    for k in d:
        if k in _FORBIDDEN_RAW_FIELDS:
            raise PlannerFailure(
                PlannerFailureCode.SCHEMA_INVALID,
                f"禁止字段 '{k}' 出现在 {where}（raw runtime identifier 由 compiler 决定）",
            )


def _str_list(value: Any, name: str) -> List[str]:
    """校验 list[str]。"""
    _require_type(value, list, name)
    out: List[str] = []
    for i, item in enumerate(value):
        _require_type(item, str, f"{name}[{i}]")
        out.append(item)
    return out


def _optional_str(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    return _require_type(value, str, name)


# ═══════════════════════════════════════════════════════════════════════════════
# PlanProposalStep
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PlanProposalStep:
    """单个 proposal step（proposal-local，semantic intent only）。

    禁止：canonical stepId / raw toolName / raw agentType / raw actionType /
          approvalRequired / canonical riskLevel / retryPolicy / timeoutSeconds。
    """
    proposalStepId: str
    intent: str
    expectedOutcome: str = ""
    requiredCapabilities: List[str] = field(default_factory=list)
    evidenceNeeds: List[str] = field(default_factory=list)
    riskHint: Optional[str] = None
    dependsOnProposalStepIds: List[str] = field(default_factory=list)
    actionIntent: Optional[str] = None
    parameterHints: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict_strict(cls, d: Dict[str, Any]) -> "PlanProposalStep":
        _require_type(d, dict, "step")
        _reject_raw_fields(d, "PlanProposalStep")
        allowed = {
            "proposalStepId", "intent", "expectedOutcome", "requiredCapabilities",
            "evidenceNeeds", "riskHint", "dependsOnProposalStepIds",
            "actionIntent", "parameterHints",
        }
        _reject_unknown_fields(allowed, d, "PlanProposalStep")

        proposal_step_id = _require_type(d.get("proposalStepId"), str, "proposalStepId")
        intent = _require_type(d.get("intent"), str, "intent")
        expected_outcome = _require_type(d.get("expectedOutcome", ""), str, "expectedOutcome")
        required_caps = _str_list(d.get("requiredCapabilities", []), "requiredCapabilities")
        evidence_needs = _str_list(d.get("evidenceNeeds", []), "evidenceNeeds")
        risk_hint = _optional_str(d.get("riskHint"), "riskHint")
        depends_on = _str_list(d.get("dependsOnProposalStepIds", []), "dependsOnProposalStepIds")
        action_intent = _optional_str(d.get("actionIntent"), "actionIntent")
        parameter_hints = d.get("parameterHints", {})
        _require_type(parameter_hints, dict, "parameterHints")

        # 资源边界（schema-legal 但资源爆炸 → schema_invalid）
        if len(intent) > MAX_INTENT_LENGTH:
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID,
                                 f"intent 长度 {len(intent)} 超过上限 {MAX_INTENT_LENGTH}")
        if len(expected_outcome) > MAX_SUMMARY_LENGTH:
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID,
                                 f"expectedOutcome 长度超过上限 {MAX_SUMMARY_LENGTH}")
        if len(evidence_needs) > MAX_EVIDENCE_NEEDS:
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID,
                                 f"evidenceNeeds 数量超过上限 {MAX_EVIDENCE_NEEDS}")
        if len(parameter_hints) > MAX_PARAMETER_HINT_KEYS:
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID,
                                 f"parameterHints key 数量超过上限 {MAX_PARAMETER_HINT_KEYS}")

        return cls(
            proposalStepId=proposal_step_id,
            intent=intent,
            expectedOutcome=expected_outcome,
            requiredCapabilities=required_caps,
            evidenceNeeds=evidence_needs,
            riskHint=risk_hint,
            dependsOnProposalStepIds=depends_on,
            actionIntent=action_intent,
            parameterHints=parameter_hints,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PlanProposal
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PlanProposal:
    """LLM 产出的 plan proposal（authoring，非 canonical）。

    不保存 chainOfThought / thinking / rawReasoning / systemPrompt / rawLLMResponse。
    """
    proposalId: str
    goal: str
    goalSummary: str = ""
    assumptions: List[str] = field(default_factory=list)
    steps: List[PlanProposalStep] = field(default_factory=list)
    requiredCapabilities: List[str] = field(default_factory=list)
    evidenceNeeds: List[str] = field(default_factory=list)
    riskHints: List[str] = field(default_factory=list)
    confidence: float = 0.0
    plannerModel: str = ""
    plannerReasonSummary: str = ""
    capabilitySnapshotHash: str = ""
    planningModeUsed: str = "llm"
    fallbackReason: Optional[str] = None

    @classmethod
    def from_dict_strict(cls, d: Dict[str, Any]) -> "PlanProposal":
        """严格解析。unknown field / 类型错误 / 重复 proposalStepId / raw 字段 → reject。

        不做宽松的 PlanProposal(**json) —— nested dict 会被逐字段校验。
        """
        _require_type(d, dict, "proposal")
        _reject_raw_fields(d, "PlanProposal")
        allowed = {
            "proposalId", "goal", "goalSummary", "assumptions", "steps",
            "requiredCapabilities", "evidenceNeeds", "riskHints", "confidence",
            "plannerModel", "plannerReasonSummary", "capabilitySnapshotHash",
            "planningModeUsed", "fallbackReason",
        }
        _reject_unknown_fields(allowed, d, "PlanProposal")

        proposal_id = _require_type(d.get("proposalId"), str, "proposalId")
        goal = _require_type(d.get("goal"), str, "goal")
        goal_summary = _require_type(d.get("goalSummary", ""), str, "goalSummary")
        assumptions = _str_list(d.get("assumptions", []), "assumptions")
        required_caps = _str_list(d.get("requiredCapabilities", []), "requiredCapabilities")
        evidence_needs = _str_list(d.get("evidenceNeeds", []), "evidenceNeeds")
        risk_hints = _str_list(d.get("riskHints", []), "riskHints")
        planner_model = _require_type(d.get("plannerModel", ""), str, "plannerModel")
        planner_reason_summary = _require_type(d.get("plannerReasonSummary", ""), str, "plannerReasonSummary")
        capability_snapshot_hash = _require_type(d.get("capabilitySnapshotHash", ""), str, "capabilitySnapshotHash")
        planning_mode_used = _require_type(d.get("planningModeUsed", "llm"), str, "planningModeUsed")
        fallback_reason = _optional_str(d.get("fallbackReason"), "fallbackReason")

        confidence = d.get("confidence", 0.0)
        _require_type(confidence, (int, float), "confidence")
        confidence = float(confidence)
        if confidence < 0.0 or confidence > 1.0:
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID,
                                 f"confidence {confidence} 超出 [0.0, 1.0] 范围")

        steps_raw = d.get("steps", [])
        _require_type(steps_raw, list, "steps")
        if len(steps_raw) > MAX_PROPOSAL_STEPS:
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID,
                                 f"steps 数量 {len(steps_raw)} 超过上限 {MAX_PROPOSAL_STEPS}")
        steps = [PlanProposalStep.from_dict_strict(s) for s in steps_raw]

        # 重复 proposalStepId → reject
        seen: set = set()
        for s in steps:
            if s.proposalStepId in seen:
                raise PlannerFailure(
                    PlannerFailureCode.SCHEMA_INVALID,
                    f"重复 proposalStepId '{s.proposalStepId}'",
                )
            seen.add(s.proposalStepId)

        # 资源边界
        if len(goal_summary) > MAX_SUMMARY_LENGTH:
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, "goalSummary 长度超限")
        if len(planner_reason_summary) > MAX_SUMMARY_LENGTH:
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, "plannerReasonSummary 长度超限")
        if len(assumptions) > MAX_ASSUMPTIONS:
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, "assumptions 数量超限")
        if len(evidence_needs) > MAX_EVIDENCE_NEEDS:
            raise PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, "evidenceNeeds 数量超限")

        return cls(
            proposalId=proposal_id,
            goal=goal,
            goalSummary=goal_summary,
            assumptions=assumptions,
            steps=steps,
            requiredCapabilities=required_caps,
            evidenceNeeds=evidence_needs,
            riskHints=risk_hints,
            confidence=float(confidence),
            plannerModel=planner_model,
            plannerReasonSummary=planner_reason_summary,
            capabilitySnapshotHash=capability_snapshot_hash,
            planningModeUsed=planning_mode_used,
            fallbackReason=fallback_reason,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PlannerAudit — sanitized planner 元数据（持久化 + 观测）
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PlannerAudit:
    """sanitized planner audit。不存 raw prompt / raw response / CoT。

    deterministic 时：plannerModel=null / proposalId=null / attemptCount=0，不伪造值。
    """
    planningModeRequested: str = "deterministic"
    planningModeUsed: str = "deterministic"
    plannerModel: Optional[str] = None
    proposalId: Optional[str] = None
    confidence: Optional[float] = None
    assumptions: List[str] = field(default_factory=list)
    plannerReasonSummary: str = ""
    capabilitySnapshotVersion: Optional[int] = None
    capabilitySnapshotHash: str = ""
    attemptCount: int = 0
    latencyMs: float = 0.0
    usageSummary: Dict[str, Any] = field(default_factory=dict)
    fallbackReason: Optional[str] = None
    goalCoverage: str = "UNKNOWN"  # FULL / PARTIAL / UNKNOWN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "planningModeRequested": self.planningModeRequested,
            "planningModeUsed": self.planningModeUsed,
            "plannerModel": self.plannerModel,
            "proposalId": self.proposalId,
            "confidence": self.confidence,
            "assumptions": list(self.assumptions),
            "plannerReasonSummary": self.plannerReasonSummary,
            "capabilitySnapshotVersion": self.capabilitySnapshotVersion,
            "capabilitySnapshotHash": self.capabilitySnapshotHash,
            "attemptCount": self.attemptCount,
            "latencyMs": self.latencyMs,
            "usageSummary": dict(self.usageSummary),
            "fallbackReason": self.fallbackReason,
            "goalCoverage": self.goalCoverage,
        }
