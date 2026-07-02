"""Semantic retriever — search knowledge base with filters"""
from typing import Dict, Any, List, Optional
from backend.rag.vector_store import search_similar, _CHROMA_AVAILABLE

def semantic_search(query: str, limit: int = 5, doc_type: Optional[str] = None,
                    event_type: Optional[str] = None, road_name: Optional[str] = None,
                    risk_level: Optional[str] = None) -> Dict[str, Any]:
    if not _CHROMA_AVAILABLE: return {"query": query, "results": [], "error": "向量库不可用"}
    where = {}
    if doc_type: where["docType"] = doc_type
    if event_type: where["eventType"] = event_type
    if road_name: where["roadName"] = road_name
    if risk_level: where["riskLevel"] = risk_level
    if not where: where = None
    results = search_similar(query, limit=limit, where=where)
    doc_cn = {"rule": "交通处置预案", "event_report": "历史事件报告", "daily_report": "日报",
              "weekly_report": "周报", "dispatch_experience": "调度经验"}
    formatted = [{"content": r.get("content", ""), "docType": r.get("metadata", {}).get("docType", ""),
        "eventId": r.get("metadata", {}).get("eventId", ""), "eventType": r.get("metadata", {}).get("eventType", ""),
        "roadName": r.get("metadata", {}).get("roadName", ""), "riskLevel": r.get("metadata", {}).get("riskLevel", ""),
        "score": r.get("score", 0.0), "metadata": r.get("metadata", {}),
        "reason": f"来源：{doc_cn.get(r.get('metadata', {}).get('docType', ''), '未知')} | 相似度：{r.get('score', 0):.2f}"}
        for r in results]
    return {"query": query, "results": formatted}
