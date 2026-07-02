"""
RAG 重排序 — 多因子加权
"""
from typing import Dict, Any, List


def rerank_results(query: str, results: List[Dict[str, Any]], event_info: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """多因子加权重排序结果。"""
    if not results:
        return []

    scored = []
    for r in results:
        base = r.get("score", 0)
        bonus = 0.0

        meta = r.get("metadata", {})

        # docType 匹配
        if meta.get("docType") == "dispatch_experience":
            bonus += 0.05
        elif meta.get("docType") == "rule":
            bonus += 0.03

        # eventType 匹配
        if event_info:
            ev_type = event_info.get("eventTypeCn", event_info.get("eventType", ""))
            if ev_type and meta.get("eventType") == ev_type:
                bonus += 0.08

            # roadName 匹配
            road = event_info.get("roadName", "")
            if road and meta.get("roadName") == road:
                bonus += 0.06

            # riskLevel 匹配
            risk = event_info.get("riskLevel", "")
            if risk and meta.get("riskLevel") == risk:
                bonus += 0.04

        final_score = min(base + bonus, 1.0)
        scored.append({**r, "score": round(final_score, 4), "originalScore": round(base, 4)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored
