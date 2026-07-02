"""
RAG 检索策略 — 阈值过滤与召回质量控制
"""
from typing import Dict, Any, List


def apply_retrieval_threshold(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """根据 top1 分数判断置信度等级。"""
    if not results:
        return {"level": "none", "label": "无可靠依据", "accepted": [], "abstain": True}

    top1 = results[0].get("score", 0)

    if top1 < 0.35:
        return {"level": "none", "label": "无可靠依据", "accepted": [], "abstain": True}
    elif top1 < 0.55:
        accepted = [r for r in results[:3] if r.get("score", 0) >= 0.30]
        return {"level": "low", "label": "低置信度", "accepted": accepted, "abstain": len(accepted) == 0}
    elif top1 < 0.75:
        accepted = [r for r in results[:5] if r.get("score", 0) >= 0.35]
        return {"level": "medium", "label": "中置信度", "accepted": accepted, "abstain": False}
    else:
        accepted = [r for r in results[:5] if r.get("score", 0) >= 0.40]
        return {"level": "high", "label": "高置信度", "accepted": accepted, "abstain": False}


def should_abstain(results: List[Dict[str, Any]]) -> bool:
    """判断是否应拒绝回答（证据不足）。"""
    policy = apply_retrieval_threshold(results)
    return policy["abstain"]
