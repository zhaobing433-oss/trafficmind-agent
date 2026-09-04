"""Phase21 G3-C hold-out ablation helpers.

This module is evaluation-only. It does not change production grounding,
planning, workflow, or case-memory semantics.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping


ABLATION_GROUPS = [
    "CURRENT_EVENT_ONLY",
    "REGIONAL",
    "REGIONAL_HISTORY_KNOWLEDGE",
    "FULL_GROUNDING",
]

BLOCKS_BY_GROUP = {
    "CURRENT_EVENT_ONLY": {"currentEvent"},
    "REGIONAL": {"currentEvent", "regionalContext"},
    "REGIONAL_HISTORY_KNOWLEDGE": {
        "currentEvent",
        "regionalContext",
        "historicalContext",
        "knowledgeContext",
    },
    "FULL_GROUNDING": {
        "currentEvent",
        "regionalContext",
        "historicalContext",
        "knowledgeContext",
        "caseMemoryContext",
    },
}

REF_TYPES_BY_BLOCK = {
    "regional_location": "regionalContext",
    "historical_traffic": "historicalContext",
    "knowledge_evidence": "knowledgeContext",
    "case_memory": "caseMemoryContext",
}

DYNAMIC_KEYS = {
    "assembledAt",
    "capturedAt",
    "createdAt",
    "updatedAt",
    "startedAt",
    "completedAt",
    "runId",
    "traceId",
    "sessionId",
    "planId",
    "definitionId",
    "caseId",
    "bindingId",
    "sourceSessionId",
    "sourceCollaborationRunId",
    "sourcePlanId",
    "sourceWorkflowRunId",
    "workflowRunId",
    "collaborationRunId",
    "eventThreadId",
}


def load_json(path: str | Path) -> Any:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str | Path, data: Mapping[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def stable_hash(value: Any) -> str:
    payload = json.dumps(_scrub_dynamic(value), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def mask_grounding_context(context: Mapping[str, Any], group: str) -> Dict[str, Any]:
    if group not in BLOCKS_BY_GROUP:
        raise ValueError(f"unknown ablation group: {group}")
    included = BLOCKS_BY_GROUP[group]
    masked = copy.deepcopy(dict(context))
    if "regionalContext" not in included:
        masked["regionalContext"] = _masked_block("regionalContext", group)
    if "historicalContext" not in included:
        masked["historicalContext"] = _masked_block("historicalContext", group)
    if "knowledgeContext" not in included:
        masked["knowledgeContext"] = _masked_block("knowledgeContext", group)
    if "caseMemoryContext" not in included:
        masked["caseMemoryContext"] = _masked_block("caseMemoryContext", group)

    refs = []
    for ref in masked.get("groundingRefs") or []:
        if not isinstance(ref, dict):
            continue
        block = REF_TYPES_BY_BLOCK.get(str(ref.get("type") or ""))
        if block and block in included:
            refs.append(ref)
    masked["groundingRefs"] = refs
    if group == "CURRENT_EVENT_ONLY":
        masked["groundingStatus"] = "MINIMAL"
    elif group in {"REGIONAL", "REGIONAL_HISTORY_KNOWLEDGE"}:
        masked["groundingStatus"] = "PARTIAL"
    else:
        masked["groundingStatus"] = str(masked.get("groundingStatus") or "FULL")
    masked["ablationGroup"] = group
    masked["ablationMask"] = {
        "evaluationOnly": True,
        "includedBlocks": sorted(included),
        "productionGroundedAssemblerChanged": False,
    }
    return masked


def summarize_grounding(context: Mapping[str, Any]) -> Dict[str, Any]:
    regional = _block(context, "regionalContext")
    history = _block(context, "historicalContext")
    knowledge = _block(context, "knowledgeContext")
    cases = _block(context, "caseMemoryContext")
    refs = [ref for ref in context.get("groundingRefs") or [] if isinstance(ref, dict)]
    case_items = [item for item in cases.get("cases") or [] if isinstance(item, dict)]
    sources = ["currentEvent"]
    if regional.get("status") == "READY":
        sources.append("regional")
    if history.get("status") == "READY" and int(history.get("eventCount") or 0) > 0:
        sources.append("history")
    if knowledge.get("evidence"):
        sources.append("knowledge")
    if case_items:
        sources.append("caseMemory")
    return {
        "regionalStatus": regional.get("status", ""),
        "historyStatus": history.get("status", ""),
        "knowledgeStatus": knowledge.get("status", ""),
        "caseStatus": cases.get("status", ""),
        "historyCount": int(history.get("eventCount") or 0),
        "knowledgeCount": len(knowledge.get("evidence") or []),
        "caseCount": len(case_items),
        "caseTotal": int(cases.get("total") or 0),
        "completedCaseRefs": sum(1 for item in case_items if item.get("finalStatus") == "completed"),
        "rejectedCaseRefs": sum(1 for item in case_items if item.get("finalStatus") == "rejected"),
        "evidenceRefCount": len(refs),
        "sourceDiversity": sources,
        "groundingBlockCoverage": len(sources),
        "contextItemCount": _context_item_count(regional, history, knowledge, case_items),
    }


def run_summary(
    *,
    event: Mapping[str, Any],
    group: str,
    grounding: Mapping[str, Any],
    agent_run: Mapping[str, Any],
    task_outputs: Iterable[Mapping[str, Any]],
    plan: Mapping[str, Any],
    leakage: Mapping[str, int],
    broken_ref_count: int,
) -> Dict[str, Any]:
    grounding_summary = summarize_grounding(grounding)
    task_outputs = list(task_outputs)
    grounded_task_count = sum(
        1
        for task in task_outputs
        if task.get("evidence_refs") or task.get("evidenceRefs")
    )
    plan_traceable = bool(
        plan.get("eventId")
        and (plan.get("constraints") or {}).get("agentGroundingAudit")
    )
    return {
        "eventId": event.get("eventId"),
        "eventType": event.get("eventType"),
        "location": event.get("roadName"),
        "riskLevel": event.get("riskLevel"),
        "createdAt": event.get("createdAt"),
        "group": group,
        "grounding": grounding_summary,
        "agentRunStatus": agent_run.get("status", ""),
        "selectedAgents": _json_field(agent_run.get("selected_agents"), []),
        "agentOutputHash": stable_hash(list(task_outputs)),
        "fusionHash": stable_hash(agent_run.get("final_decision")),
        "planFingerprint": plan.get("planFingerprint", ""),
        "planTraceable": plan_traceable,
        "groundedRecommendationCoverage": grounded_task_count,
        "leakage": dict(leakage),
        "brokenEvidenceRefCount": int(broken_ref_count),
    }


def build_report(
    *,
    package: Mapping[str, Any],
    spec: Mapping[str, Any],
    holdout_events: List[Mapping[str, Any]],
    results: List[Mapping[str, Any]],
    deterministic_replay_drift_count: int,
    holdout_case_memory_created: int,
) -> Dict[str, Any]:
    aggregate = aggregate_results(results)
    return {
        "packId": package.get("packId"),
        "regionId": package.get("regionId"),
        "frozenT0": package.get("frozenT0"),
        "holdoutReality": package.get("holdoutReality"),
        "historyReality": package.get("historyReality"),
        "regionalGeographyReality": package.get("regionalGeographyReality"),
        "knowledgeReality": package.get("knowledgeReality"),
        "caseReality": package.get("caseReality"),
        "agentProviderReality": package.get("agentProviderReality"),
        "productionTrafficEvaluation": package.get("productionTrafficEvaluation"),
        "liveModelEvaluationClaimed": spec.get("liveModelEvaluationClaimed"),
        "realTrafficEffectivenessClaimed": False,
        "holdoutEventCount": len(holdout_events),
        "ablationGroupCount": len(ABLATION_GROUPS),
        "expectedAgentEvalRuns": len(holdout_events) * len(ABLATION_GROUPS),
        "actualAgentEvalRuns": len(results),
        "metrics": list(spec.get("frozenMetrics") or []),
        "results": sorted(
            [dict(item) for item in results],
            key=lambda item: (str(item.get("eventId")), str(item.get("group"))),
        ),
        "aggregate": aggregate,
        "caseMemoryAddsTraceableContext": (
            aggregate["D_FULL"]["evidenceRefCount"]
            > aggregate["C_REGION_HISTORY_KNOWLEDGE"]["evidenceRefCount"]
        ),
        "deterministicReplayDriftCount": deterministic_replay_drift_count,
        "holdoutCaseMemoryCreated": holdout_case_memory_created,
        "limitations": [
            "No real traffic outcome labels are present.",
            "LLM_ENABLED=false; this is not a live model quality benchmark.",
            "Synthetic history is not official Hangzhou traffic history.",
            "The report measures grounding, traceability, and leakage guards, not production accuracy.",
        ],
    }


def aggregate_results(results: Iterable[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    buckets = {group: [] for group in ABLATION_GROUPS}
    for item in results:
        group = str(item.get("group") or "")
        if group in buckets:
            buckets[group].append(item)
    out: Dict[str, Dict[str, Any]] = {}
    for group, items in buckets.items():
        label = _aggregate_label(group)
        out[label] = {
            "groundingBlockCoverage": sum(_g(item, "groundingBlockCoverage") for item in items),
            "evidenceRefCount": sum(_g(item, "evidenceRefCount") for item in items),
            "traceableRefCount": sum(_g(item, "evidenceRefCount") - int(item.get("brokenEvidenceRefCount") or 0) for item in items),
            "eligibleContextItemCount": sum(_g(item, "contextItemCount") for item in items),
            "leakageCount": sum(sum(int(v or 0) for v in (item.get("leakage") or {}).values()) for item in items),
            "groundedRecommendationCoverage": sum(int(item.get("groundedRecommendationCoverage") or 0) for item in items),
            "planGroundingTraceability": sum(1 for item in items if item.get("planTraceable")),
            "sourceDiversity": round(
                sum(len((item.get("grounding") or {}).get("sourceDiversity") or []) for item in items) / len(items),
                2,
            ) if items else 0,
            "runCount": len(items),
        }
    return out


def report_markdown(report: Mapping[str, Any]) -> str:
    aggregate = report.get("aggregate") or {}
    lines = [
        "# Phase21 G3-C Hold-out Ablation Evaluation Report",
        "",
        f"- Pack: `{report.get('packId')}`",
        f"- Region: `{report.get('regionId')}`",
        f"- Frozen T0: `{report.get('frozenT0')}`",
        f"- Hold-out reality: `{report.get('holdoutReality')}`",
        f"- Agent provider: `{report.get('agentProviderReality')}`",
        f"- Production traffic evaluation: `{str(report.get('productionTrafficEvaluation')).lower()}`",
        "",
        "## Aggregate Metrics",
        "",
        "| Metric | A_CURRENT | B_REGIONAL | C_REGION_HISTORY_KNOWLEDGE | D_FULL |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    metric_keys = [
        "groundingBlockCoverage",
        "evidenceRefCount",
        "traceableRefCount",
        "eligibleContextItemCount",
        "leakageCount",
        "groundedRecommendationCoverage",
        "planGroundingTraceability",
        "sourceDiversity",
    ]
    for key in metric_keys:
        lines.append(
            "| {metric} | {a} | {b} | {c} | {d} |".format(
                metric=key,
                a=(aggregate.get("A_CURRENT") or {}).get(key, 0),
                b=(aggregate.get("B_REGIONAL") or {}).get(key, 0),
                c=(aggregate.get("C_REGION_HISTORY_KNOWLEDGE") or {}).get(key, 0),
                d=(aggregate.get("D_FULL") or {}).get(key, 0),
            )
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "- Regional context adds canonical location and nearby regional facts when the binding resolves.",
        "- History and knowledge add strict-past event summaries and eligible source-grounded evidence.",
        "- Case memory adds traceable prior system-closure experience in the full grounding group.",
        "- Leakage guards are evaluated for wrong-region, future, current-target, and ineligible evidence.",
        "",
        "## Limitations",
        "",
    ])
    for item in report.get("limitations") or []:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


def write_reports(root: str | Path, report: Mapping[str, Any]) -> None:
    root = Path(root)
    write_json(root / "evaluation_report.json", report)
    (root / "evaluation_report.md").write_text(report_markdown(report), encoding="utf-8")


def _masked_block(block: str, group: str) -> Dict[str, Any]:
    base = {
        "status": "MASKED",
        "reason": f"ABLATION_{group}",
        "provenance": {
            "sourceType": "evaluation_mask",
            "queryModel": "phase21_g3c_ablation_projection",
            "notes": ["evaluation_only_mask"],
        },
    }
    if block == "regionalContext":
        base.update({"region": None, "location": {}, "connectedRoads": [], "nearbyPois": []})
    elif block == "historicalContext":
        base.update({
            "window": {},
            "eventCount": 0,
            "eventTypeDistribution": {},
            "riskDistribution": {},
            "recentEventRefs": [],
        })
    elif block == "knowledgeContext":
        base.update({"regionalGroundingStatus": "MASKED", "scope": {}, "evidence": []})
    elif block == "caseMemoryContext":
        base.update({"scope": {}, "cases": [], "total": 0})
    return base


def _block(context: Mapping[str, Any], name: str) -> Dict[str, Any]:
    value = context.get(name)
    return dict(value) if isinstance(value, dict) else {}


def _context_item_count(
    regional: Mapping[str, Any],
    history: Mapping[str, Any],
    knowledge: Mapping[str, Any],
    cases: List[Mapping[str, Any]],
) -> int:
    count = 1
    if regional.get("status") == "READY":
        count += 1 + len(regional.get("connectedRoads") or []) + len(regional.get("nearbyPois") or [])
    count += int(history.get("eventCount") or 0)
    count += len(knowledge.get("evidence") or [])
    count += len(cases)
    return count


def _json_field(value: Any, default: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value) if value else default
        except json.JSONDecodeError:
            return default
    return value if value is not None else default


def _scrub_dynamic(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _scrub_dynamic(nested)
            for key, nested in value.items()
            if key not in DYNAMIC_KEYS
        }
    if isinstance(value, list):
        return [_scrub_dynamic(item) for item in value]
    return value


def _g(item: Mapping[str, Any], key: str) -> int:
    return int(((item.get("grounding") or {}).get(key)) or 0)


def _aggregate_label(group: str) -> str:
    return {
        "CURRENT_EVENT_ONLY": "A_CURRENT",
        "REGIONAL": "B_REGIONAL",
        "REGIONAL_HISTORY_KNOWLEDGE": "C_REGION_HISTORY_KNOWLEDGE",
        "FULL_GROUNDING": "D_FULL",
    }[group]
