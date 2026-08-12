"""Load evaluation datasets from JSON files."""
import json
from pathlib import Path
from typing import List, Optional
from backend.evaluation.models import (
    EvaluationCase, Expected, ExpectedEvent, ExpectedRouting,
    ExpectedConflict, ExpectedPolicy, ExpectedWorkflow, ExpectedOutput,
)


def _d(d: dict, key: str, default=None):
    return d.get(key, default)


def load_dataset(path: str) -> List[EvaluationCase]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cases = []
    for raw in data.get("cases", []):
        exp = raw.get("expected", {})
        ev = exp.get("event", {})
        rt = exp.get("routing", {})
        cf = exp.get("conflict", {})
        pl = exp.get("policy", {})
        wf = exp.get("workflow", {})
        out = exp.get("output", {})
        case = EvaluationCase(
            caseId=raw["caseId"], name=raw.get("name", ""),
            category=raw.get("category", ""),
            input=raw.get("input", {}),
            contextPolicy=raw.get("contextPolicy", "fresh_event"),
            expected=Expected(
                event=ExpectedEvent(
                    expectedFields=ev.get("expectedFields", {}),
                    booleanFields=ev.get("booleanFields", {}),
                    numericTolerance=ev.get("numericTolerance", {}),
                ),
                routing=ExpectedRouting(
                    requiredAgents=rt.get("requiredAgents", []),
                    optionalAgents=rt.get("optionalAgents", []),
                    forbiddenAgents=rt.get("forbiddenAgents", []),
                ),
                conflict=ExpectedConflict(
                    required=cf.get("required", False),
                    allowedTypes=cf.get("allowedTypes", []),
                ),
                policy=ExpectedPolicy(
                    requiresHumanReview=pl.get("requiresHumanReview"),
                    safetyPriority=pl.get("safetyPriority"),
                ),
                workflow=ExpectedWorkflow(
                    requiredNodes=wf.get("requiredNodes", []),
                    forbiddenTransitions=wf.get("forbiddenTransitions", []),
                ),
                output=ExpectedOutput(
                    requiredFields=out.get("requiredFields", []),
                ),
            ),
            evaluationMode=raw.get("evaluationMode", "deterministic"),
        )
        cases.append(case)
    return cases
