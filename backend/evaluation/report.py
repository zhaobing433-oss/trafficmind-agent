"""Generate JSON and Markdown evaluation reports."""
import json
import os
from datetime import datetime
from backend.evaluation.models import EvalReport, EvalMetrics, CaseScore


def generate_reports(report: EvalReport, output_dir: str = "artifacts/evaluation"):
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON report
    json_path = os.path.join(output_dir, f"eval_report_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(_serialize(report), f, ensure_ascii=False, indent=2)

    # Markdown report
    md_path = os.path.join(output_dir, f"eval_report_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_markdown(report))

    return json_path, md_path


def _serialize(report: EvalReport) -> dict:
    from dataclasses import asdict
    return asdict(report)


def _markdown(report: EvalReport) -> str:
    m = report.metrics
    gate = report.regressionGate
    lines = [
        "# TrafficMind Agent Evaluation Report",
        f"**Version**: {report.metadata.get('datasetVersion', 'v1')}",
        f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Summary",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Cases | {m.totalCases} |",
        f"| Passed | {m.passedCases} |",
        f"| Failed | {m.failedCases} |",
        "",
        "## Metrics",
        f"| Metric | Score |",
        f"|--------|-------|",
        f"| Overall Score | {m.overallScore:.2%} |",
        f"| Event Field Accuracy | {m.eventFieldAccuracy:.2%} |",
        f"| Required Agent Recall | {m.requiredAgentRecall:.2%} |",
        f"| Agent Exact Match | {m.agentExactMatch:.2%} |",
        f"| Forbidden Agent Rate | {m.forbiddenAgentRate:.2%} |",
        f"| Conflict F1 | {m.conflictF1:.2%} |",
        f"| Safety Policy Pass Rate | {m.safetyPolicyPassRate:.2%} |",
        f"| Workflow Invariant Pass Rate | {m.workflowInvariantPassRate:.2%} |",
        f"| Output Structure Pass Rate | {m.outputStructurePassRate:.2%} |",
        "",
        "## Regression Gate",
        f"**Result**: {'PASS' if gate.get('passed') else 'FAIL'}",
    ]
    if gate.get("failures"):
        lines.append("")
        for f in gate["failures"]:
            lines.append(f"- **{f['gate']}**: {f['actual']:.2%} < {f['threshold']:.2%}")

    lines += ["", "## Case Results"]
    for c in report.caseResults:
        status = "PASS" if c.passed else "FAIL"
        lines.append(f"- **{status}** {c.caseId}: {c.name} (overall={c.scores.get('overall',0):.2%})")
        if c.failedAssertions:
            for fa in c.failedAssertions[:3]:
                lines.append(f"  - {fa}")

    return "\n".join(lines)
