"""
evidence_evaluate 节点 — 证据评估。

评估 Agent 输出和 RAG 检索结果的证据质量：
  - 置信度检查
  - 证据充分性判断
  - 冲突/矛盾检测

不调用外部服务，完全确定性。
"""

from typing import Any, Dict, List

from backend.workflow.models import NodeConfig
from backend.workflow.state import TrafficWorkflowState


async def execute_evidence_evaluate(
    state: TrafficWorkflowState, config: NodeConfig
) -> Dict[str, Any]:
    """执行证据评估。

    Args:
        state: 工作流状态
        config: 节点配置
          - config.min_confidence: 最低置信度阈值（默认 0.3）
          - config.min_evidence_count: 最低证据数量（默认 1）

    Returns:
        证据评估结果
    """
    min_confidence = config.config.get("min_confidence", 0.3)
    min_evidence_count = config.config.get("min_evidence_count", 1)

    agent_outputs = state.agent_outputs or {}
    rag_ctx = state.rag_context or {}
    evidence_refs = state.evidence_refs or []

    # 评估维度
    agent_count = len(agent_outputs)
    total_confidence = 0.0
    all_findings: List[str] = []
    agent_evals: List[Dict[str, Any]] = []

    for name, output in agent_outputs.items():
        if isinstance(output, dict):
            conf = output.get("confidence", 0)
            if isinstance(conf, (int, float)):
                total_confidence += conf
            all_findings.extend(output.get("findings", []))

            agent_evals.append({
                "agentName": name,
                "confidence": conf,
                "meetsThreshold": conf >= min_confidence,
                "summary": output.get("summary", ""),
            })

    avg_confidence = total_confidence / agent_count if agent_count > 0 else 0

    # 证据充分性
    rag_count = len(rag_ctx.get("results", [])) if isinstance(rag_ctx, dict) else 0
    total_evidence = rag_count + len(evidence_refs)
    evidence_sufficient = total_evidence >= min_evidence_count

    # 整体评估
    if avg_confidence >= 0.7 and evidence_sufficient:
        quality = "sufficient"
        recommendation = "证据充分，可进入处置阶段"
    elif avg_confidence >= min_confidence or evidence_sufficient:
        quality = "partial"
        recommendation = "证据部分充分，建议人工复核"
    else:
        quality = "insufficient"
        recommendation = "证据不足，建议补充信息后重新研判"

    # 矛盾检测（简单规则：查找置信度极低的 Agent）
    has_low_confidence = any(
        e.get("confidence", 0) < 0.2 for e in agent_evals
    )

    result = {
        "quality": quality,
        "recommendation": recommendation,
        "avg_confidence": round(avg_confidence, 3),
        "agent_evaluations": agent_evals,
        "total_evidence_count": total_evidence,
        "evidence_sufficient": evidence_sufficient,
        "has_low_confidence_agent": has_low_confidence,
        "requires_human_review": quality == "insufficient" or has_low_confidence,
    }

    state.evidence_refs = evidence_refs
    state.add_audit_event("evidence_evaluated", config.node_id, {
        "quality": quality,
        "avgConfidence": avg_confidence,
        "evidenceCount": total_evidence,
        "requiresHumanReview": result["requires_human_review"],
    })

    return result
