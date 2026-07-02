"""
RAG 上下文构建 — 打包证据供 LLM/模板生成回答
"""
from typing import Dict, Any, List


def build_evidence_context(results: List[Dict[str, Any]], max_evidence: int = 5) -> List[Dict[str, Any]]:
    """从检索结果中构建证据上下文。"""
    evidence = []
    for r in results[:max_evidence]:
        evidence.append({
            "evidenceId": r.get("id", ""),
            "content": r.get("content", "")[:500],
            "docType": r.get("docType", r.get("metadata", {}).get("docType", "")),
            "score": r.get("score", 0),
            "metadata": r.get("metadata", {}),
        })
    return evidence


def format_evidence_for_prompt(evidence: List[Dict[str, Any]]) -> str:
    """将证据格式化为 LLM prompt 可用文本。"""
    if not evidence:
        return "（无有效证据）"
    parts = []
    for i, e in enumerate(evidence, 1):
        parts.append(f"[证据{i}] 来源:{e['docType']} 评分:{e['score']:.2f}\n{e['content']}")
    return "\n\n".join(parts)
