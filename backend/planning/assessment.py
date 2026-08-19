"""
ExecutionAssessment — Phase18 Round2

terminal semantic assessment layer（不属于 runtime status machine）。
WorkflowRunStatus.COMPLETED != goal achieved。

关键不变量：
  - 绝不修改 run.status / cursor / steps / terminationReason / replannedToRunId
  - hard safety facts 优先（UNKNOWN_OUTCOME / approval rejection / budget exhausted /
    terminal failed objective）→ goalAchievement 不能 ACHIEVED
  - exactly-once（assessmentKey + STARTED/COMPLETED registry）
  - 消耗 lineage LLM budget（reserve_llm_call + assessmentCallsUsed 原子）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class AssessmentStatus:
    ASSESSED = "assessed"
    NOT_ASSESSED = "not_assessed"
    FALLBACK = "fallback"


class GoalAchievement:
    ACHIEVED = "achieved"
    NOT_ACHIEVED = "not_achieved"
    UNKNOWN = "unknown"


@dataclass
class ExecutionAssessment:
    assessmentStatus: str = AssessmentStatus.NOT_ASSESSED
    goalAchievement: str = GoalAchievement.UNKNOWN
    confidence: float = 0.0
    evidenceCoverage: str = "unknown"
    unresolvedRisks: List[str] = field(default_factory=list)
    failedObjectives: List[str] = field(default_factory=list)
    shouldEscalate: bool = False
    assessmentReason: str = ""
    assessmentMode: str = "deterministic"
    assessmentModel: Optional[str] = None
    assessmentFallbackReason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assessmentStatus": self.assessmentStatus,
            "goalAchievement": self.goalAchievement,
            "confidence": self.confidence,
            "evidenceCoverage": self.evidenceCoverage,
            "unresolvedRisks": list(self.unresolvedRisks),
            "failedObjectives": list(self.failedObjectives),
            "shouldEscalate": self.shouldEscalate,
            "assessmentReason": self.assessmentReason,
            "assessmentMode": self.assessmentMode,
            "assessmentModel": self.assessmentModel,
            "assessmentFallbackReason": self.assessmentFallbackReason,
        }


def build_assessment_key(root_run_id: str, run_id: str, plan_version: int) -> str:
    """assessmentKey = rootRunId + finalLeafRunId + finalPlanVersion。"""
    return f"{root_run_id}:{run_id}:{plan_version}"


def assessment_eligible(run) -> bool:
    """仅 terminal 且 canonical lineage leaf（无 child、非 replanned parent）。"""
    if run is None:
        return False
    if not run.is_terminal():
        return False
    state = run.state if isinstance(run.state, dict) else {}
    if state.get("replannedToRunId"):
        return False  # parent，已被 child 接续
    if state.get("terminationReason") == "replanned":
        return False
    return True


def _collect_hard_facts(repo, run) -> List[str]:
    """收集阻止 ACHIEVED 的 hard safety facts。"""
    facts: List[str] = []
    status = run.status.value
    if status == "rejected":
        facts.append("approval_rejected")
    if status == "failed":
        facts.append("terminal_failed_objective")
    for e in repo.list_observations(run.run_id):
        payload = e.payload if isinstance(e.payload, dict) else {}
        t = payload.get("type", "")
        if t == "unknown_outcome":
            facts.append("unknown_outcome")
        elif t == "budget_exhausted":
            facts.append("budget_exhausted")
        elif t == "tool_denied":
            facts.append("policy_deny")
    return facts


def deterministic_assessment(repo, run) -> ExecutionAssessment:
    """deterministic assessment gate（不调 LLM）。"""
    status = run.status.value
    if status == "cancelled":
        return ExecutionAssessment(
            assessmentStatus=AssessmentStatus.NOT_ASSESSED,
            goalAchievement=GoalAchievement.UNKNOWN,
            assessmentReason="run cancelled",
        )
    if status == "rejected":
        return ExecutionAssessment(
            assessmentStatus=AssessmentStatus.ASSESSED,
            goalAchievement=GoalAchievement.NOT_ACHIEVED,
            assessmentReason="approval rejected",
        )
    if status == "failed":
        return ExecutionAssessment(
            assessmentStatus=AssessmentStatus.ASSESSED,
            goalAchievement=GoalAchievement.NOT_ACHIEVED,
            failedObjectives=["terminal_failed_objective"],
            assessmentReason="run failed before objective completion",
        )
    # COMPLETED → hard-fact gate
    facts = _collect_hard_facts(repo, run)
    if facts:
        if "unknown_outcome" in facts:
            return ExecutionAssessment(
                assessmentStatus=AssessmentStatus.ASSESSED,
                goalAchievement=GoalAchievement.UNKNOWN,
                unresolvedRisks=facts,
                assessmentReason="hard safety facts present (unknown_outcome)",
            )
        return ExecutionAssessment(
            assessmentStatus=AssessmentStatus.ASSESSED,
            goalAchievement=GoalAchievement.NOT_ACHIEVED,
            unresolvedRisks=facts,
            assessmentReason="hard safety facts present",
        )
    # no hard facts → LLM semantic eligible
    return ExecutionAssessment(
        assessmentStatus=AssessmentStatus.ASSESSED,
        goalAchievement=GoalAchievement.UNKNOWN,
        assessmentReason="completed, semantic assessment pending",
    )


async def _llm_semantic_assessment(client, run, repo) -> ExecutionAssessment:
    """LLM semantic assessment（严格 parse + hard-fact override）。"""
    from backend.planning.assessment_prompts import build_assessment_messages, parse_assessment

    state = run.state if isinstance(run.state, dict) else {}
    root_run_id = (state.get("executionLineage", {}) or {}).get("rootRunId", run.run_id)
    system, user = build_assessment_messages(run, root_run_id)
    data, _usage, _attempts = await client.call_structured_json(system, user)
    result = parse_assessment(data)
    return result


async def assess_terminal_run(repo, run_id: str, client=None, lineage_root_run_id: str = "") -> Optional[ExecutionAssessment]:
    """terminal assessment orchestration（idempotent，绝不修改 run.status）。"""
    run = repo.get_run(run_id)
    if run is None or not assessment_eligible(run):
        return None

    state = run.state if isinstance(run.state, dict) else {}
    root_run_id = lineage_root_run_id or (state.get("executionLineage", {}) or {}).get("rootRunId", run_id)
    key = build_assessment_key(root_run_id, run_id, run.version)

    # 无需 LLM 的 terminal state → deterministic 直接写（不做 claim/provider）
    status = run.status.value
    if status in ("cancelled", "rejected", "failed"):
        result = deterministic_assessment(repo, run)
        repo.complete_assessment_tx(run_id, key, result.to_dict())
        _save_assessment_event(repo, run_id, key, result)
        return result

    # COMPLETED → hard-fact gate
    facts = _collect_hard_facts(repo, run)
    if facts:
        result = deterministic_assessment(repo, run)
        repo.complete_assessment_tx(run_id, key, result.to_dict())
        _save_assessment_event(repo, run_id, key, result)
        return result

    # semantic assessment → claim + reserve + STARTED → provider → COMPLETED
    if client is None:
        # production wiring：从现有 config 解析 planning LLM client（无 key → None）
        from backend.planning.llm_client import get_planning_llm_client_optional
        client = get_planning_llm_client_optional()
    if client is None:
        # 无 key → deterministic UNKNOWN（不使 run 失败）
        result = ExecutionAssessment(
            assessmentStatus=AssessmentStatus.FALLBACK,
            goalAchievement=GoalAchievement.UNKNOWN,
            assessmentFallbackReason="client_unavailable",
        )
        repo.complete_assessment_tx(run_id, key, result.to_dict())
        _save_assessment_event(repo, run_id, key, result)
        return result

    claim = repo.claim_assessment_tx(run_id, key)
    if claim.get("result") == "already_completed":
        return _from_dict(claim.get("assessment", {}))
    if claim.get("result") in ("already_started", "budget_exhausted", "not_eligible"):
        # interrupted / no budget → FALLBACK/UNKNOWN，不 replay provider
        result = ExecutionAssessment(
            assessmentStatus=AssessmentStatus.FALLBACK,
            goalAchievement=GoalAchievement.UNKNOWN,
            assessmentFallbackReason=claim.get("result"),
        )
        repo.complete_assessment_tx(run_id, key, result.to_dict())
        _save_assessment_event(repo, run_id, key, result)
        return result

    # claimed → provider
    try:
        result = await _llm_semantic_assessment(client, run, repo)
        result.assessmentStatus = AssessmentStatus.ASSESSED
        result.assessmentMode = "llm"
        result.assessmentModel = getattr(client, "_model", None)
    except Exception as e:
        result = ExecutionAssessment(
            assessmentStatus=AssessmentStatus.FALLBACK,
            goalAchievement=GoalAchievement.UNKNOWN,
            assessmentFallbackReason=str(e)[:200],
        )
    repo.complete_assessment_tx(run_id, key, result.to_dict())
    _save_assessment_event(repo, run_id, key, result)
    return result


def _from_dict(d: Dict[str, Any]) -> ExecutionAssessment:
    return ExecutionAssessment(
        assessmentStatus=d.get("assessmentStatus", AssessmentStatus.NOT_ASSESSED),
        goalAchievement=d.get("goalAchievement", GoalAchievement.UNKNOWN),
        confidence=float(d.get("confidence", 0.0)),
        evidenceCoverage=d.get("evidenceCoverage", "unknown"),
        unresolvedRisks=list(d.get("unresolvedRisks", [])),
        failedObjectives=list(d.get("failedObjectives", [])),
        shouldEscalate=bool(d.get("shouldEscalate", False)),
        assessmentReason=d.get("assessmentReason", ""),
        assessmentMode=d.get("assessmentMode", "deterministic"),
        assessmentModel=d.get("assessmentModel"),
        assessmentFallbackReason=d.get("assessmentFallbackReason"),
    )


def _save_assessment_event(repo, run_id: str, key: str, result: ExecutionAssessment) -> None:
    """audit event（sanitized，不存 raw prompt/response/CoT）。"""
    try:
        from backend.workflow.models import WorkflowEvent
        evt = WorkflowEvent(
            event_id=f"wfevent_assessment_{key[:40]}",
            run_id=run_id,
            event_type="assessment_completed",
            payload=result.to_dict(),
            sequence=0,
        )
        repo.save_event(evt)
    except Exception:
        pass
