"""
Minimal Intelligence Evaluation Summary — Phase19 Round4-Lite

评测中心数据源的最小结构化投影：从 evaluation report（EvalReport 序列化
dict，与 /evaluation/reports/{id} 现有输出同构）派生稳定 summary。

§16 不伪造 PASS：
  - overallStatus=PASS 需要 metrics 全通过 AND regression gate passed=True；
  - 缺 metrics / 缺 gate / totalCases 缺失或为 0 → 绝不默认 PASS（UNKNOWN）；
  - 任一 FAIL 信号 → FAIL。
§17/§18 commitSha / provider / model 只从 report input 的白名单字段读取，
  不读环境变量、不猜测；metadata 整体不投影，绝不返回 secret。
§14 source of truth：所有数字来自 report input（或测试 fixture），
  生产代码不硬编码任何测试计数。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_GATE_STATUS_VALUES = ("PASS", "FAIL", "UNKNOWN")

# 稳定 schema 的固定键集合（R4-27：Phase20-facing JSON schema 稳定）
SUMMARY_KEYS = (
    "evaluationId", "generatedAt", "commitSha", "provider", "model",
    "datasetVersion", "overallStatus", "metricsStatus", "gateStatus",
    "totalCases", "passedCases", "failedCases", "overallScore", "gates",
)


def _num_or_none(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _norm_status(value: Any, default: str = "UNKNOWN") -> str:
    s = str(value).upper().strip() if value is not None else ""
    return s if s in _GATE_STATUS_VALUES else default


def _metrics_status(metrics: Any) -> str:
    """metrics → PASS/FAIL/UNKNOWN（fail-closed：缺失 → UNKNOWN，绝不默认 PASS）。"""
    if not isinstance(metrics, dict):
        return "UNKNOWN"
    total = _num_or_none(metrics.get("totalCases"))
    passed = _num_or_none(metrics.get("passedCases"))
    failed = _num_or_none(metrics.get("failedCases"))
    if total is None or total <= 0:
        return "UNKNOWN"
    if failed is not None and failed > 0:
        return "FAIL"
    if passed is not None:
        if passed == total:
            return "PASS"
        if passed < total:
            return "FAIL"
    return "UNKNOWN"


def _derive_gates(report: Dict[str, Any]) -> tuple:
    """gate 状态 + per-gate 列表（显式 gates 列表优先，否则回归 gate dict）。"""
    explicit = report.get("gates")
    if isinstance(explicit, list) and explicit:
        out: List[Dict[str, Any]] = []
        for g in explicit:
            if not isinstance(g, dict):
                continue
            gate_id = str(g.get("gateId") or g.get("gate") or "")
            if not gate_id:
                continue
            out.append({
                "gateId": gate_id,
                "status": _norm_status(g.get("status")),
                "threshold": _num_or_none(g.get("threshold")),
                "actual": _num_or_none(g.get("actual")),
            })
        out.sort(key=lambda g: g["gateId"])
        statuses = {g["status"] for g in out}
        if "FAIL" in statuses:
            overall = "FAIL"
        elif statuses == {"PASS"}:
            overall = "PASS"
        else:
            overall = "UNKNOWN"
        return overall, out

    gate = report.get("regressionGate")
    if not isinstance(gate, dict) or not gate:
        return "UNKNOWN", []
    passed = gate.get("passed")
    thresholds = gate.get("thresholds") if isinstance(gate.get("thresholds"), dict) else {}
    failures = gate.get("failures") if isinstance(gate.get("failures"), list) else []
    failed_ids = {str(f.get("gate")) for f in failures
                  if isinstance(f, dict) and f.get("gate")}
    fail_actual = {str(f.get("gate")): f.get("actual") for f in failures
                   if isinstance(f, dict) and f.get("gate")}
    out = []
    for gate_id in sorted(thresholds.keys()):
        if gate_id in failed_ids:
            status = "FAIL"
        elif passed is True:
            status = "PASS"
        else:
            status = "UNKNOWN"
        out.append({
            "gateId": str(gate_id),
            "status": status,
            "threshold": _num_or_none(thresholds.get(gate_id)),
            "actual": _num_or_none(fail_actual.get(gate_id)) if gate_id in failed_ids else None,
        })
    if passed is True:
        overall = "FAIL" if any(g["status"] == "FAIL" for g in out) else "PASS"
    elif passed is False:
        overall = "FAIL"
    else:
        overall = "UNKNOWN"
    return overall, out


def build_eval_summary(report: Any, report_id: str = "") -> Dict[str, Any]:
    """evaluation report → 最小结构化 summary（只读投影，白名单字段）。

    Args:
        report: EvalReport 序列化 dict（metadata/metrics/caseResults/regressionGate
            或含显式 gates 列表的结构化 fixture）。
        report_id: 报告 ID（文件名/标识，evaluationId 缺失时兜底）。

    Returns:
        稳定 schema 的 summary dict（键序固定；gates 按 gateId 排序）。
        metadata 除白名单外一律不投影；不存在/缺失 → null 或 UNKNOWN。
    """
    if not isinstance(report, dict):
        report = {}
    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    metrics = report.get("metrics") if isinstance(report.get("metrics"), dict) else {}
    gate_overall, gates = _derive_gates(report)
    metrics_overall = _metrics_status(metrics)
    if metrics_overall == "FAIL" or gate_overall == "FAIL":
        overall = "FAIL"
    elif metrics_overall == "PASS" and gate_overall == "PASS":
        overall = "PASS"
    else:
        overall = "UNKNOWN"
    return {
        "evaluationId": _str_or_none(metadata.get("evaluationId")
                                     or report.get("evaluationId")
                                     or report_id) or "",
        "generatedAt": _str_or_none(metadata.get("generatedAt")),
        "commitSha": _str_or_none(metadata.get("commitSha")),
        "provider": _str_or_none(metadata.get("provider")),
        "model": _str_or_none(metadata.get("model")),
        "datasetVersion": _str_or_none(metadata.get("datasetVersion")),
        "overallStatus": overall,
        "metricsStatus": metrics_overall,
        "gateStatus": gate_overall,
        "totalCases": _num_or_none(metrics.get("totalCases")),
        "passedCases": _num_or_none(metrics.get("passedCases")),
        "failedCases": _num_or_none(metrics.get("failedCases")),
        "overallScore": _num_or_none(metrics.get("overallScore")),
        "gates": gates,
    }
