"""Read-only artifact repository for evaluation reports."""
from __future__ import annotations
import json, os, re
from typing import Any, Dict, List, Optional

ARTIFACT_DIR = "artifacts/evaluation"
FILENAME_RE = re.compile(r"^eval_report_(\d{8}_\d{6})\.json$")

def _safe_path(report_id: str) -> str | None:
    """Validate and resolve a report ID to a safe path."""
    if ".." in report_id or "/" in report_id or "\\" in report_id:
        return None
    fname = f"{report_id}.json"
    if not FILENAME_RE.match(fname):
        return None
    path = os.path.join(ARTIFACT_DIR, fname)
    if not os.path.isfile(path):
        return None
    return path

def list_reports(limit: int = 50) -> List[Dict[str, Any]]:
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    reports = []
    for fname in sorted(os.listdir(ARTIFACT_DIR), reverse=True):
        m = FILENAME_RE.match(fname)
        if not m: continue
        path = os.path.join(ARTIFACT_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        reports.append({
            "reportId": fname.replace(".json", ""),
            "generatedAt": data.get("metadata", {}).get("generatedAt", m.group(1)),
            "datasetVersion": data.get("metadata", {}).get("datasetVersion", "unknown"),
            "overallScore": data.get("metrics", {}).get("overallScore", 0),
            "passedCases": data.get("metrics", {}).get("passedCases", 0),
            "failedCases": data.get("metrics", {}).get("failedCases", 0),
            "totalCases": data.get("metrics", {}).get("totalCases", 0),
            "regressionGatePassed": data.get("regressionGate", {}).get("passed", False),
        })
        if len(reports) >= limit:
            break
    return reports

def get_report(report_id: str) -> Dict[str, Any] | None:
    path = _safe_path(report_id)
    if not path: return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_case(report_id: str, case_id: str) -> Dict[str, Any] | None:
    report = get_report(report_id)
    if not report: return None
    for c in report.get("caseResults", []):
        if c.get("caseId") == case_id:
            return c
    return None

def compare_reports(base_id: str, target_id: str) -> Dict[str, Any] | None:
    base = get_report(base_id)
    target = get_report(target_id)
    if not base or not target: return None
    bm = base.get("metrics", {})
    tm = target.get("metrics", {})
    bmeta = base.get("metadata", {})
    tmeta = target.get("metadata", {})

    def delta(key: str) -> float:
        return round(tm.get(key, 0) - bm.get(key, 0), 4)

    def pct_pp(key: str) -> float:
        """Percentage point difference."""
        return round((tm.get(key, 0) - bm.get(key, 0)) * 100, 2)

    keys = ["overallScore", "eventFieldAccuracy", "requiredAgentRecall",
            "forbiddenAgentRate", "conflictF1", "safetyPolicyPassRate",
            "workflowInvariantPassRate", "outputStructurePassRate"]
    metrics_delta = []
    for k in keys:
        d = delta(k)
        pp = pct_pp(k)
        status = "improved" if d > 0 else ("regressed" if d < 0 else "unchanged")
        metrics_delta.append({"metric": k, "base": bm.get(k, 0), "target": tm.get(k, 0),
                              "delta": d, "percentagePoints": pp, "status": status})

    return {
        "baseReportId": base_id, "targetReportId": target_id,
        "baseGeneratedAt": bmeta.get("generatedAt", ""),
        "targetGeneratedAt": tmeta.get("generatedAt", ""),
        "datasetVersionMatch": bmeta.get("datasetVersion") == tmeta.get("datasetVersion"),
        "frameworkVersionMatch": bmeta.get("frameworkVersion") == tmeta.get("frameworkVersion"),
        "baseGatePassed": base.get("regressionGate", {}).get("passed", False),
        "targetGatePassed": target.get("regressionGate", {}).get("passed", False),
        "metricsDelta": metrics_delta,
    }
