"""Evaluation Case Schema — structured, deterministic-first."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ExpectedEvent:
    expectedFields: Dict[str, Any] = field(default_factory=dict)
    booleanFields: Dict[str, bool] = field(default_factory=dict)
    numericTolerance: Dict[str, float] = field(default_factory=dict)  # field -> absolute tolerance


@dataclass
class ExpectedRouting:
    requiredAgents: List[str] = field(default_factory=list)
    optionalAgents: List[str] = field(default_factory=list)
    forbiddenAgents: List[str] = field(default_factory=list)


@dataclass
class ExpectedConflict:
    required: bool = False
    allowedTypes: List[str] = field(default_factory=list)


@dataclass
class ExpectedPolicy:
    requiresHumanReview: Optional[bool] = None
    safetyPriority: Optional[str] = None  # "high" | "medium" | "low"


@dataclass
class ExpectedWorkflow:
    requiredNodes: List[str] = field(default_factory=list)
    forbiddenTransitions: List[str] = field(default_factory=list)


@dataclass
class ExpectedOutput:
    requiredFields: List[str] = field(default_factory=list)


@dataclass
class Expected:
    event: ExpectedEvent = field(default_factory=ExpectedEvent)
    routing: ExpectedRouting = field(default_factory=ExpectedRouting)
    conflict: ExpectedConflict = field(default_factory=ExpectedConflict)
    policy: ExpectedPolicy = field(default_factory=ExpectedPolicy)
    workflow: ExpectedWorkflow = field(default_factory=ExpectedWorkflow)
    output: ExpectedOutput = field(default_factory=ExpectedOutput)


@dataclass
class EvaluationCase:
    caseId: str
    name: str
    category: str = ""
    input: Dict[str, Any] = field(default_factory=dict)
    contextPolicy: str = "fresh_event"
    expected: Expected = field(default_factory=Expected)
    evaluationMode: str = "deterministic"  # "deterministic" | "llm"


@dataclass
class CaseScore:
    caseId: str = ""
    name: str = ""
    passed: bool = True
    scores: Dict[str, float] = field(default_factory=dict)
    failedAssertions: List[str] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalMetrics:
    totalCases: int = 0
    passedCases: int = 0
    failedCases: int = 0
    eventFieldAccuracy: float = 0.0
    requiredAgentRecall: float = 0.0
    agentExactMatch: float = 0.0
    forbiddenAgentRate: float = 0.0
    conflictPrecision: float = 0.0
    conflictRecall: float = 0.0
    conflictF1: float = 0.0
    safetyPolicyPassRate: float = 0.0
    workflowInvariantPassRate: float = 0.0
    outputStructurePassRate: float = 0.0
    overallScore: float = 0.0


@dataclass
class EvalReport:
    metadata: Dict[str, Any] = field(default_factory=dict)
    metrics: EvalMetrics = field(default_factory=EvalMetrics)
    caseResults: List[CaseScore] = field(default_factory=list)
    regressionGate: Dict[str, Any] = field(default_factory=dict)
