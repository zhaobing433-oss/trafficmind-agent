"""Data contracts for persisted traffic case memory."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class CaseMemoryQuality(str, Enum):
    VALIDATED = "validated"
    PARTIAL = "partial"
    LOW_EVIDENCE = "low_evidence"
    ARCHIVED = "archived"


class CaseMemoryError(Exception):
    """Expected case-memory domain error."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_case_id(source_workflow_run_id: str) -> str:
    """Stable case identity: one case per source workflow run."""

    digest = hashlib.sha256(source_workflow_run_id.encode("utf-8")).hexdigest()[:16]
    return f"case_{digest}"


@dataclass
class TrafficCaseMemory:
    case_id: str
    region_id: str
    event_id: str
    event_type: str
    source_workflow_run_id: str
    final_status: str
    quality_status: CaseMemoryQuality
    road_id: Optional[str] = None
    intersection_id: Optional[str] = None
    source_session_id: Optional[str] = None
    source_collaboration_run_id: Optional[str] = None
    source_plan_id: Optional[str] = None
    event_snapshot: Dict[str, Any] = field(default_factory=dict)
    agent_facts: Dict[str, Any] = field(default_factory=dict)
    plan_facts: Dict[str, Any] = field(default_factory=dict)
    human_decisions: List[Dict[str, Any]] = field(default_factory=list)
    workflow_outcome: Dict[str, Any] = field(default_factory=dict)
    lessons: List[Dict[str, Any]] = field(default_factory=list)
    generated_summary: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    source_type: str = "workflow_case_builder"
    source_reference: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = utc_now_iso()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = self.created_at
        if isinstance(self.quality_status, str):
            self.quality_status = CaseMemoryQuality(self.quality_status)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "caseId": self.case_id,
            "regionId": self.region_id,
            "eventId": self.event_id,
            "eventType": self.event_type,
            "roadId": self.road_id,
            "intersectionId": self.intersection_id,
            "sourceSessionId": self.source_session_id,
            "sourceCollaborationRunId": self.source_collaboration_run_id,
            "sourcePlanId": self.source_plan_id,
            "sourceWorkflowRunId": self.source_workflow_run_id,
            "finalStatus": self.final_status,
            "qualityStatus": self.quality_status.value,
            "eventSnapshot": self.event_snapshot,
            "agentFacts": self.agent_facts,
            "planFacts": self.plan_facts,
            "humanDecisions": self.human_decisions,
            "workflowOutcome": self.workflow_outcome,
            "lessons": self.lessons,
            "generatedSummary": self.generated_summary,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
            "sourceType": self.source_type,
            "sourceReference": self.source_reference,
            "provenance": self.provenance,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrafficCaseMemory":
        return cls(
            case_id=data["caseId"],
            region_id=data["regionId"],
            event_id=data["eventId"],
            event_type=data.get("eventType", ""),
            road_id=data.get("roadId"),
            intersection_id=data.get("intersectionId"),
            source_session_id=data.get("sourceSessionId"),
            source_collaboration_run_id=data.get("sourceCollaborationRunId"),
            source_plan_id=data.get("sourcePlanId"),
            source_workflow_run_id=data["sourceWorkflowRunId"],
            final_status=data.get("finalStatus", ""),
            quality_status=CaseMemoryQuality(data.get("qualityStatus", "partial")),
            event_snapshot=data.get("eventSnapshot") or {},
            agent_facts=data.get("agentFacts") or {},
            plan_facts=data.get("planFacts") or {},
            human_decisions=data.get("humanDecisions") or [],
            workflow_outcome=data.get("workflowOutcome") or {},
            lessons=data.get("lessons") or [],
            generated_summary=data.get("generatedSummary"),
            started_at=data.get("startedAt"),
            completed_at=data.get("completedAt"),
            source_type=data.get("sourceType", "workflow_case_builder"),
            source_reference=data.get("sourceReference", ""),
            provenance=data.get("provenance") or {},
            created_at=data.get("createdAt", ""),
            updated_at=data.get("updatedAt", ""),
        )


@dataclass
class CaseBuildResult:
    case: TrafficCaseMemory
    created: bool
    rebuilt: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case": self.case.to_dict(),
            "created": self.created,
            "rebuilt": self.rebuilt,
            "newCases": 1 if self.created else 0,
        }


@dataclass
class CaseQueryResult:
    cases: List[TrafficCaseMemory]
    total: int
    limit: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cases": [case.to_dict() for case in self.cases],
            "total": self.total,
            "limit": self.limit,
        }
