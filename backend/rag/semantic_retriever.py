"""
语义检索器
--------
支持按文本查询进行语义检索，可按 docType / eventType / roadName / riskLevel 过滤。
"""

from typing import Dict, Any, List, Optional
from backend.rag.vector_store import search_similar, _CHROMA_AVAILABLE


def semantic_search(
    query: str,
    limit: int = 5,
    doc_type: Optional[str] = None,
    event_type: Optional[str] = None,
    road_name: Optional[str] = None,
    risk_level: Optional[str] = None,
) -> Dict[str, Any]:
    """
    语义检索交通知识库。

    Args:
        query: 检索查询文本
        limit: 返回数量
        doc_type: 按文档类型过滤 (rule/event_report/daily_report/weekly_report/dispatch_experience)
        event_type: 按事件类型过滤
        road_name: 按路段名过滤
        risk_level: 按风险等级过滤

    Returns:
        {"query": str, "results": [...]}
    """
    if not _CHROMA_AVAILABLE:
        return {
            "query": query,
            "results": [],
            "error": "向量库不可用。请先安装 chromadb 并重建索引。",
        }

    # 构建过滤条件
    where = {}
    if doc_type:
        where["docType"] = doc_type
    if event_type:
        where["eventType"] = event_type
    if road_name:
        where["roadName"] = road_name
    if risk_level:
        where["riskLevel"] = risk_level
    if not where:
        where = None

    results = search_similar(query, limit=limit, where=where)

    formatted = []
    for r in results:
        meta = r.get("metadata", {})
        formatted.append({
            "content": r.get("content", ""),
            "docType": meta.get("docType", ""),
            "eventId": meta.get("eventId", ""),
            "eventType": meta.get("eventType", ""),
            "roadName": meta.get("roadName", ""),
            "riskLevel": meta.get("riskLevel", ""),
            "score": r.get("score", 0.0),
            "metadata": meta,
            "reason": _format_reason(meta, r.get("score", 0.0)),
        })

    return {
        "query": query,
        "results": formatted,
    }


def _format_reason(meta: Dict[str, Any], score: float) -> str:
    """生成检索理由文本。"""
    doc_type_cn = {
        "rule": "交通处置预案",
        "event_report": "历史事件报告",
        "daily_report": "交通事件日报",
        "weekly_report": "交通事件周报",
        "dispatch_experience": "调度经验",
    }
    dt = meta.get("docType", "未知")
    cn = doc_type_cn.get(dt, dt)
    parts = [f"来源：{cn}"]
    if meta.get("eventType"):
        parts.append(f"事件类型：{meta['eventType']}")
    if meta.get("roadName"):
        parts.append(f"路段：{meta['roadName']}")
    if meta.get("riskLevel"):
        parts.append(f"风险：{meta['riskLevel']}")
    parts.append(f"相似度：{score:.2f}")
    return " | ".join(parts)
