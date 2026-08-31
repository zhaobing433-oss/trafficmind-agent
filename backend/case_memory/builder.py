"""Build traffic case memories from persisted workflow source chains."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from backend.agent.collaboration.db_repository import SQLiteCollaborationRepository
from backend.case_memory.models import (
    CaseMemoryError,
    CaseMemoryQuality,
    TrafficCaseMemory,
    build_case_id,
)
from backend.planning.agent_planning_adapter import _extract_agent_outputs
from backend.planning.models import Plan
from backend.regional.repository import SQLiteRegionalRepository
from backend.tools.db_tools import get_event_by_id
from backend.workflow.models import (
    ActionStatus,
    ApprovalDecision,
    WorkflowActionRecord,
    WorkflowApproval,
    WorkflowRun,
)
from backend.workflow.repository import SQLiteWorkflowRepository


class TrafficCaseBuilder:
    def __init__(
        self,
        *,
        workflow_repo: Optional[SQLiteWorkflowRepository] = None,
        regional_repo: Optional[SQLiteRegionalRepository] = None,
        collaboration_repo: Optional[SQLiteCollaborationRepository] = None,
    ):
        self.workflow_repo = workflow_repo or SQLiteWorkflowRepository()
        self.regional_repo = regional_repo or SQLiteRegionalRepository()
        self.collaboration_repo = collaboration_repo or SQLiteCollaborationRepository()

    def build_from_workflow_run(self, run_id: str) -> TrafficCaseMemory:
        run = self.workflow_repo.get_run(run_id)
        if run is None:
            raise CaseMemoryError(
                "WORKFLOW_RUN_NOT_FOUND",
                f"workflow run not found: {run_id}",
                status_code=404,
            )
        if not run.is_terminal():
            raise CaseMemoryError(
                "CASE_NOT_BUILDABLE_WORKFLOW_NOT_TERMINAL",
                "case memory requires a terminal workflow run",
                status_code=409,
            )

        state = run.state if isinstance(run.state, dict) else {}
        event_id = _extract_state_event_id(state)
        if not event_id:
            raise CaseMemoryError(
                "CASE_NOT_BUILDABLE_EVENT_RELATION_MISSING",
                "workflow state must include currentEvent.eventId",
                status_code=409,
            )
        if _is_simulation_source(event_id, state):
            raise CaseMemoryError(
                "CASE_NOT_BUILDABLE_SIMULATION_SOURCE",
                "simulation-derived workflows cannot create traffic case memory",
                status_code=409,
            )
        authoritative_event = get_event_by_id(event_id)
        if not authoritative_event:
            raise CaseMemoryError(
                "CASE_NOT_BUILDABLE_EVENT_NOT_FOUND",
                f"source event not found: {event_id}",
                status_code=409,
            )
        if _is_simulation_source(event_id, authoritative_event):
            raise CaseMemoryError(
                "CASE_NOT_BUILDABLE_SIMULATION_SOURCE",
                "simulation-derived events cannot create traffic case memory",
                status_code=409,
            )

        binding = self.regional_repo.get_active_event_location_binding(event_id)
        if not binding or not binding.get("regionId"):
            raise CaseMemoryError(
                "CASE_NOT_BUILDABLE_CANONICAL_REGION_MISSING",
                "case memory requires a resolved canonical event location",
                status_code=409,
            )

        event_snapshot = _compact_event_snapshot(authoritative_event)
        event_type = str(event_snapshot.get("eventType") or "").strip()
        if not event_type:
            raise CaseMemoryError(
                "CASE_NOT_BUILDABLE_EVENT_TYPE_MISSING",
                "source event must include eventType",
                status_code=409,
            )

        plan, plan_provenance = self._recover_source_plan(run, event_id)
        if plan and plan.goalType.value == "simulation_evaluation":
            raise CaseMemoryError(
                "CASE_NOT_BUILDABLE_SIMULATION_SOURCE",
                "simulation evaluation plans cannot create traffic case memory",
                status_code=409,
            )
        collaboration_run_id = _source_collaboration_run_id(plan)
        collaboration_run, tasks, agent_provenance = self._recover_source_agent(
            collaboration_run_id,
            event_id,
            run.session_id,
        )

        approvals = self.workflow_repo.list_approvals(run.run_id)
        action_records = self.workflow_repo.list_action_records(run.run_id)
        plan_facts = _build_plan_facts(plan, run, self.workflow_repo) if plan else {}
        agent_facts = _build_agent_facts(collaboration_run, tasks) if collaboration_run else {}
        human_decisions = _build_human_decisions(approvals)
        workflow_outcome = _build_workflow_outcome(run, approvals, action_records)
        lessons = _build_lessons(run, human_decisions, action_records, agent_facts, plan_facts)

        quality = _quality_status(
            run=run,
            plan_facts=plan_facts,
            agent_facts=agent_facts,
            human_decisions=human_decisions,
            action_records=action_records,
        )
        case = TrafficCaseMemory(
            case_id=build_case_id(run.run_id),
            region_id=str(binding["regionId"]),
            event_id=event_id,
            event_type=event_type,
            road_id=binding.get("roadId"),
            intersection_id=binding.get("intersectionId"),
            source_session_id=run.session_id or None,
            source_collaboration_run_id=collaboration_run_id if collaboration_run else None,
            source_plan_id=plan.planId if plan else None,
            source_workflow_run_id=run.run_id,
            final_status=run.status.value,
            quality_status=quality,
            event_snapshot=event_snapshot,
            agent_facts=agent_facts,
            plan_facts=plan_facts,
            human_decisions=human_decisions,
            workflow_outcome=workflow_outcome,
            lessons=lessons,
            generated_summary=_build_generated_summary(event_snapshot, run),
            started_at=run.started_at or None,
            completed_at=run.completed_at or None,
            source_reference=f"workflow_runs:{run.run_id}",
            provenance={
                "sourceWorkflowRunId": run.run_id,
                "sourceEventId": event_id,
                "eventSource": "event_records",
                "eventLocationBindingId": binding.get("bindingId"),
                "canonicalLocation": {
                    "regionId": binding.get("regionId"),
                    "roadId": binding.get("roadId"),
                    "intersectionId": binding.get("intersectionId"),
                },
                "plan": plan_provenance,
                "agent": agent_provenance,
                "workflow": {
                    "approvals": len(approvals),
                    "actions": len(action_records),
                    "terminalStatus": run.status.value,
                },
                "rawTranscriptStored": False,
                "structuredFactsAuthoritative": True,
                "businessOutcomeInferred": False,
            },
        )
        return case

    def _recover_source_plan(
        self,
        run: WorkflowRun,
        event_id: str,
    ) -> Tuple[Optional[Plan], Dict[str, Any]]:
        definition_payload: Optional[Dict[str, Any]] = None
        definition_version = self.workflow_repo.get_definition_version(run.definition_id, run.version)
        if definition_version and isinstance(definition_version.definition_json, dict):
            definition_payload = definition_version.definition_json
        if definition_payload is None:
            definition = self.workflow_repo.get_definition(run.definition_id)
            if definition:
                definition_payload = definition.to_dict()

        metadata = (definition_payload or {}).get("metadata") or {}
        plan_payload = metadata.get("plan") if isinstance(metadata, dict) else None
        if not isinstance(plan_payload, dict):
            return None, {
                "status": "not_found",
                "source": "workflow_definition.metadata.plan",
            }

        try:
            plan = Plan.from_dict(plan_payload)
        except Exception as exc:
            raise CaseMemoryError(
                "CASE_SOURCE_PLAN_INVALID",
                f"source plan metadata is invalid: {exc}",
                status_code=409,
            ) from exc
        if plan.eventId and plan.eventId != event_id:
            raise CaseMemoryError(
                "CASE_SOURCE_PLAN_EVENT_MISMATCH",
                "source plan eventId does not match workflow currentEvent.eventId",
                status_code=409,
            )
        return plan, {
            "status": "attached",
            "source": "workflow_definition_version.metadata.plan"
            if definition_version
            else "workflow_definition.metadata.plan",
            "planId": plan.planId,
            "version": plan.version,
        }

    def _recover_source_agent(
        self,
        collaboration_run_id: Optional[str],
        event_id: str,
        workflow_session_id: str,
    ) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
        if not collaboration_run_id:
            return None, [], {
                "status": "not_found",
                "source": "plan.metadata.sourceAgent.collaborationRunId",
            }
        run = self.collaboration_repo.get_run(collaboration_run_id)
        if not run:
            return None, [], {
                "status": "not_found",
                "source": "collaboration_runs",
                "collaborationRunId": collaboration_run_id,
            }
        normalized_event = _parse_json(run.get("normalized_event"), {})
        if str(normalized_event.get("eventId") or "").strip() != event_id:
            return None, [], {
                "status": "event_mismatch",
                "source": "collaboration_runs.normalized_event.eventId",
                "collaborationRunId": collaboration_run_id,
            }
        if workflow_session_id and run.get("session_id") and run.get("session_id") != workflow_session_id:
            return None, [], {
                "status": "session_mismatch",
                "source": "collaboration_runs.session_id",
                "collaborationRunId": collaboration_run_id,
            }
        tasks = self.collaboration_repo.list_tasks(collaboration_run_id)
        return run, tasks, {
            "status": "attached",
            "source": "collaboration_runs + collaboration_tasks",
            "collaborationRunId": collaboration_run_id,
            "taskCount": len(tasks),
        }


def _extract_state_event_id(state: Dict[str, Any]) -> str:
    current = state.get("currentEvent") or state.get("current_event") or {}
    if not isinstance(current, dict):
        return ""
    return str(current.get("eventId") or current.get("event_id") or "").strip()


def _is_simulation_source(event_id: str, payload: Any) -> bool:
    if str(event_id or "").lower().startswith("simevt_"):
        return True
    return _contains_simulation_marker(payload)


def _contains_simulation_marker(payload: Any) -> bool:
    marker_keys = {
        "simulationrunid",
        "simulation_run_id",
        "simulationrefs",
        "simulation_refs",
        "scenarioid",
        "scenario_id",
        "simulationscenarioid",
        "simulation_scenario_id",
    }
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).replace("-", "_").lower()
            compact = normalized.replace("_", "")
            if normalized in marker_keys or compact in marker_keys:
                return True
            if _contains_simulation_marker(value):
                return True
    elif isinstance(payload, list):
        return any(_contains_simulation_marker(item) for item in payload)
    return False


def _compact_event_snapshot(event: Dict[str, Any]) -> Dict[str, Any]:
    standard = _parse_json(event.get("standardEvent"), {})
    full = _parse_json(event.get("fullResult"), {})
    full_standard = full.get("standardEvent") if isinstance(full, dict) else {}
    raw_event = _parse_json(event.get("rawEvent"), {})
    if not isinstance(standard, dict):
        standard = {}
    if not isinstance(full_standard, dict):
        full_standard = {}
    if not isinstance(raw_event, dict):
        raw_event = {}
    return {
        "eventId": _pick(event.get("eventId"), standard.get("eventId"), full_standard.get("eventId")),
        "eventType": _pick(event.get("eventType"), standard.get("eventType"), full_standard.get("eventType")),
        "eventTypeCn": _pick(
            event.get("eventTypeCn"),
            standard.get("eventTypeCn"),
            full_standard.get("eventTypeCn"),
        ),
        "roadName": _pick(event.get("roadName"), standard.get("roadName"), full_standard.get("roadName")),
        "direction": _pick(event.get("direction"), standard.get("direction"), full_standard.get("direction")),
        "riskScore": event.get("riskScore"),
        "riskLevel": event.get("riskLevel"),
        "status": event.get("status"),
        "duration": _pick(event.get("duration"), standard.get("duration"), full_standard.get("duration")),
        "avgSpeed": _pick(event.get("avgSpeed"), standard.get("avgSpeed"), full_standard.get("avgSpeed")),
        "queueLength": _pick(event.get("queueLength"), standard.get("queueLength"), full_standard.get("queueLength")),
        "weather": _pick(event.get("weather"), standard.get("weather"), full_standard.get("weather")),
        "timePeriod": _pick(event.get("timePeriod"), standard.get("timePeriod"), full_standard.get("timePeriod")),
        "isMainRoad": _pick(event.get("isMainRoad"), standard.get("isMainRoad"), full_standard.get("isMainRoad")),
        "nearbySchool": _pick(event.get("nearbySchool"), standard.get("nearbySchool"), full_standard.get("nearbySchool")),
        "nearbyHospital": _pick(event.get("nearbyHospital"), standard.get("nearbyHospital"), full_standard.get("nearbyHospital")),
        "createdAt": event.get("createdAt"),
        "updatedAt": event.get("updatedAt"),
        "report": _short_text(event.get("report")),
        "sourcePayloadStored": {
            "rawEvent": bool(raw_event),
            "fullResult": bool(full),
        },
    }


def _source_collaboration_run_id(plan: Optional[Plan]) -> Optional[str]:
    if plan is None:
        return None
    metadata = plan.metadata if isinstance(plan.metadata, dict) else {}
    source_agent = metadata.get("sourceAgent") if isinstance(metadata.get("sourceAgent"), dict) else {}
    return (
        str(source_agent.get("collaborationRunId") or "").strip()
        or str(metadata.get("collaborationRunId") or "").strip()
        or None
    )


def _build_agent_facts(
    collaboration_run: Dict[str, Any],
    tasks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    findings, recommendations, accepted, rejected, evidence_refs = _extract_agent_outputs(tasks)
    return {
        "source": "collaboration_tasks.output_snapshot",
        "collaborationRunId": collaboration_run.get("run_id"),
        "sessionId": collaboration_run.get("session_id"),
        "status": collaboration_run.get("status"),
        "selectedAgents": _parse_json(collaboration_run.get("selected_agents"), []),
        "failedAgents": _parse_json(collaboration_run.get("failed_agents"), []),
        "taskCount": len(tasks),
        "findings": _compact_json(findings, max_items=20),
        "recommendations": _compact_json(recommendations, max_items=20),
        "acceptedActions": _compact_json(accepted, max_items=20),
        "rejectedActions": _compact_json(rejected, max_items=20),
        "evidenceRefs": _compact_json(evidence_refs, max_items=20),
        "finalDecision": _compact_json(_parse_json(collaboration_run.get("final_decision"), {}), max_items=20),
        "rawMessagesStored": False,
    }


def _build_plan_facts(
    plan: Plan,
    run: WorkflowRun,
    workflow_repo: SQLiteWorkflowRepository,
) -> Dict[str, Any]:
    latest_version = workflow_repo.get_latest_version_number(plan.planId)
    replan_count = max(0, latest_version - 1)
    metadata = plan.metadata if isinstance(plan.metadata, dict) else {}
    return {
        "source": "workflow_definition.metadata.plan",
        "planId": plan.planId,
        "planFingerprint": plan.planFingerprint,
        "goal": plan.goal,
        "goalType": plan.goalType.value,
        "definitionStatus": plan.definitionStatus.value,
        "version": plan.version,
        "workflowVersion": run.version,
        "latestVersion": latest_version or plan.version,
        "replanCount": replan_count,
        "stepCount": len(plan.steps),
        "steps": [
            {
                "stepId": step.stepId,
                "stepType": step.stepType.value,
                "objective": step.objective,
                "agentType": step.agentType,
                "toolName": step.toolName,
                "actionType": step.actionType,
                "approvalRequired": bool(step.approvalRequired),
                "riskLevel": step.riskLevel,
                "expectedOutcome": step.expectedOutcome,
                "evidenceRefs": _compact_json(step.evidenceRefs, max_items=10),
            }
            for step in plan.steps
        ],
        "agentRecommendationAudit": _compact_json(
            metadata.get("agentRecommendationAudit") or {},
            max_items=20,
        ),
        "createdAt": plan.createdAt,
        "updatedAt": plan.updatedAt,
    }


def _build_human_decisions(approvals: List[WorkflowApproval]) -> List[Dict[str, Any]]:
    decisions: List[Dict[str, Any]] = []
    for approval in approvals:
        decisions.append({
            "approvalId": approval.approval_id,
            "nodeId": approval.node_id,
            "decision": approval.decision.value,
            "reviewer": approval.reviewer,
            "comment": _short_text(approval.comment),
            "proposedActions": [_compact_action(item) for item in approval.proposed_actions],
            "editedActions": [_compact_action(item) for item in approval.edited_actions],
            "editedActionCount": len(approval.edited_actions),
            "manualAdjustment": bool(approval.edited_actions),
            "createdAt": approval.created_at,
            "decidedAt": approval.decided_at,
        })
    return decisions


def _build_workflow_outcome(
    run: WorkflowRun,
    approvals: List[WorkflowApproval],
    action_records: List[WorkflowActionRecord],
) -> Dict[str, Any]:
    action_status_counts: Dict[str, int] = {}
    for record in action_records:
        action_status_counts[record.status.value] = action_status_counts.get(record.status.value, 0) + 1
    state = run.state if isinstance(run.state, dict) else {}
    errors = state.get("errors") if isinstance(state.get("errors"), list) else []
    audit_events = state.get("auditEvents") if isinstance(state.get("auditEvents"), list) else []
    return {
        "source": "workflow_runs + workflow_approvals + workflow_action_records",
        "workflowRunId": run.run_id,
        "definitionId": run.definition_id,
        "sessionId": run.session_id,
        "finalStatus": run.status.value,
        "systemTerminalStatus": True,
        "startedAt": run.started_at,
        "completedAt": run.completed_at,
        "updatedAt": run.updated_at,
        "currentNodeId": run.current_node_id,
        "approvalCounts": _approval_counts(approvals),
        "actionCounts": action_status_counts,
        "actions": [
            {
                "actionId": record.action_id,
                "nodeId": record.node_id,
                "actionType": record.action_type,
                "status": record.status.value,
                "error": _short_text(record.error),
                "result": _compact_json(record.result, max_items=20),
                "createdAt": record.created_at,
                "completedAt": record.completed_at,
            }
            for record in action_records
        ],
        "errors": _compact_json(errors, max_items=10),
        "auditEventTypes": [
            str(item.get("type") or item.get("eventType") or "")
            for item in audit_events[:20]
            if isinstance(item, dict)
        ],
        "businessOutcome": {
            "status": "unknown_without_external_evidence",
            "reason": "workflow terminal status is a system execution outcome only",
        },
    }


def _build_lessons(
    run: WorkflowRun,
    human_decisions: List[Dict[str, Any]],
    action_records: List[WorkflowActionRecord],
    agent_facts: Dict[str, Any],
    plan_facts: Dict[str, Any],
) -> List[Dict[str, Any]]:
    lessons: List[Dict[str, Any]] = []
    for item in agent_facts.get("rejectedActions") or []:
        lessons.append({
            "type": "agent_action_rejected",
            "source": "agentFacts.rejectedActions",
            "actionType": item.get("actionType"),
            "reason": item.get("reason"),
        })
    for decision in human_decisions:
        if decision.get("decision") == ApprovalDecision.REJECTED.value:
            lessons.append({
                "type": "human_approval_rejected",
                "source": "workflow_approvals",
                "approvalId": decision.get("approvalId"),
            })
        if decision.get("manualAdjustment"):
            lessons.append({
                "type": "human_edited_action",
                "source": "workflow_approvals.edited_actions",
                "approvalId": decision.get("approvalId"),
            })
    for record in action_records:
        if record.status == ActionStatus.FAILED:
            lessons.append({
                "type": "action_failed",
                "source": "workflow_action_records",
                "actionId": record.action_id,
                "actionType": record.action_type,
                "error": _short_text(record.error),
            })
    if run.status.value in {"failed", "rejected", "cancelled"}:
        lessons.append({
            "type": f"workflow_{run.status.value}",
            "source": "workflow_runs.status",
            "workflowRunId": run.run_id,
        })
    if int(plan_facts.get("replanCount") or 0) > 0:
        lessons.append({
            "type": "replan_occurred",
            "source": "workflow_definition_versions",
            "replanCount": plan_facts.get("replanCount"),
        })
    return lessons


def _quality_status(
    *,
    run: WorkflowRun,
    plan_facts: Dict[str, Any],
    agent_facts: Dict[str, Any],
    human_decisions: List[Dict[str, Any]],
    action_records: List[WorkflowActionRecord],
) -> CaseMemoryQuality:
    if not run.completed_at:
        return CaseMemoryQuality.LOW_EVIDENCE
    if plan_facts and (agent_facts or human_decisions or action_records):
        return CaseMemoryQuality.VALIDATED
    return CaseMemoryQuality.PARTIAL


def _build_generated_summary(event_snapshot: Dict[str, Any], run: WorkflowRun) -> str:
    road = str(event_snapshot.get("roadName") or "未知道路").strip()
    event_type = str(event_snapshot.get("eventTypeCn") or event_snapshot.get("eventType") or "交通事件").strip()
    return f"{road}{event_type}: workflow ended with {run.status.value}"


def _approval_counts(approvals: List[WorkflowApproval]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for approval in approvals:
        counts[approval.decision.value] = counts.get(approval.decision.value, 0) + 1
    return counts


def _compact_action(action: Any) -> Dict[str, Any]:
    if not isinstance(action, dict):
        return {"value": _short_text(action)}
    result: Dict[str, Any] = {}
    for key in (
        "actionType",
        "action_type",
        "actionStepId",
        "targetActionStepId",
        "stepId",
        "reason",
        "status",
    ):
        if key in action:
            result[key] = _compact_json(action[key])
    params = action.get("params") or action.get("paramsTemplate") or action.get("parameterHints")
    if isinstance(params, dict):
        result["params"] = _compact_json(_redact_sensitive(params), max_items=20)
    return result


def _compact_json(value: Any, max_items: int = 50, max_text: int = 500) -> Any:
    if isinstance(value, dict):
        items = list(value.items())[:max_items]
        return {str(k): _compact_json(v, max_items=max_items, max_text=max_text) for k, v in items}
    if isinstance(value, list):
        return [_compact_json(item, max_items=max_items, max_text=max_text) for item in value[:max_items]]
    return _short_text(value, max_text=max_text)


def _redact_sensitive(value: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, item in value.items():
        key_text = str(key)
        if any(token in key_text.lower() for token in ("secret", "token", "password", "apikey", "api_key")):
            out[key_text] = "[redacted]"
        elif isinstance(item, dict):
            out[key_text] = _redact_sensitive(item)
        else:
            out[key_text] = item
    return out


def _parse_json(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return value if value is not None else default
    try:
        return json.loads(value) if value else default
    except json.JSONDecodeError:
        return default


def _pick(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _short_text(value: Any, max_text: int = 500) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    if len(text) <= max_text:
        return text
    return text[: max_text - 1] + "..."
