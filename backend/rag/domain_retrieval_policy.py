"""交通指挥领域 RAG 检索策略 — intent + docType优先级 + metadata加权"""
from typing import Dict, Any, List, Optional
from backend.rag.intent_router import classify_traffic_intent, score_by_intent


def apply_domain_boost(
    query: str,
    results: List[Dict[str, Any]],
    event_info: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """对检索结果应用交通领域加权（意图 docType + metadata 匹配）。"""
    if not results:
        return results

    intent = classify_traffic_intent(query)

    boosted = []
    for r in results:
        bonus = 0.0
        meta = r.get("metadata", {})
        doc_type = meta.get("docType", r.get("docType", ""))

        # 1. docType 意图加权
        bonus += score_by_intent(intent, doc_type)

        # 2. eventType 匹配
        if event_info:
            evt = event_info.get("eventTypeCn", event_info.get("eventType", ""))
            if evt and meta.get("eventType") == evt:
                bonus += 0.06
            # roadName 匹配
            road = event_info.get("roadName", "")
            if road and meta.get("roadName") == road:
                bonus += 0.04
            # riskLevel 匹配
            risk = event_info.get("riskLevel", "")
            if risk and meta.get("riskLevel") == risk:
                bonus += 0.03
            # nearbyHospital
            if event_info.get("nearbyHospital"):
                bonus += 0.01
            # nearbySchool
            if event_info.get("nearbySchool"):
                bonus += 0.01

        original_score = r.get("score", r.get("originalScore", 0))
        final_score = min(original_score + bonus, 1.0)

        boosted.append({
            **r,
            "score": round(final_score, 4),
            "originalScore": round(original_score, 4),
            "intentBonus": round(bonus, 4),
            "detectedIntent": intent,
        })

    boosted.sort(key=lambda x: x["score"], reverse=True)
    return boosted


def domain_rerank_and_filter(
    query: str,
    results: List[Dict[str, Any]],
    event_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """完整的领域检索增强流程：intent → boost → rerank → threshold"""
    from backend.rag.retrieval_policy import apply_retrieval_threshold
    from backend.rag.context_builder import build_evidence_context

    intent = classify_traffic_intent(query)
    boosted = apply_domain_boost(query, results, event_info)
    policy = apply_retrieval_threshold(boosted)
    evidence = build_evidence_context(policy["accepted"])

    return {
        "intent": intent,
        "docPriority": get_doc_priority_from_intent(intent),
        "results": boosted[:10],
        "accepted": policy["accepted"],
        "abstain": policy["abstain"],
        "confidenceLevel": policy["level"],
        "evidence": evidence,
    }


def get_doc_priority_from_intent(intent: str) -> List[str]:
    from backend.rag.intent_router import get_doc_priority
    return get_doc_priority(intent)
