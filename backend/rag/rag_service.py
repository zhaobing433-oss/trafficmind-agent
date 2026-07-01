"""
RAG 问答服务
----------
封装检索增强生成流程：检索 → 整理证据 → 生成回答。
"""

from typing import Dict, Any, List, Optional
from backend.rag.semantic_retriever import semantic_search
from backend.rag.vector_store import _CHROMA_AVAILABLE
from backend.config import LLM_ENABLED


def _build_local_answer(question: str, evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    基于规则模板生成回答（无 LLM 降级方案）。
    """
    if not evidence:
        return {
            "question": question,
            "answer": f"关于「{question}」，当前知识库中暂无直接相关记录。建议参考交通处置预案手册进行处理。",
            "evidence": [],
            "suggestions": ["请先重建知识库索引（POST /rag/rebuild_index）", "参考本地规则库 traffic_rules.md"],
            "confidence": 0.0,
            "usedLLM": False,
        }

    # 按 docType 分组
    rules = [e for e in evidence if e["docType"] == "rule"]
    experiences = [e for e in evidence if e["docType"] == "dispatch_experience"]
    reports = [e for e in evidence if e["docType"] in ("event_report", "daily_report", "weekly_report")]

    answer_parts = ["一、结论"]

    # 从规则和经验中提取关键处置建议
    key_actions = []
    for e in rules + experiences:
        content = e["content"][:500]
        for line in content.split("\n"):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("- ")):
                key_actions.append(line.lstrip("0123456789. -"))

    if key_actions:
        answer_parts.append("根据知识库检索，建议采取以下措施：")
        for i, action in enumerate(key_actions[:5], 1):
            answer_parts.append(f"{i}. {action}")
    else:
        answer_parts.append("根据检索到的相关知识，建议按标准交通事件处置流程处理。")

    # 依据
    answer_parts.append("\n二、依据")
    for e in evidence[:3]:
        answer_parts.append(f"- {e.get('reason', '')}")

    # 建议
    answer_parts.append("\n三、建议处置")
    answer_parts.append("1. 通知相关联动部门")
    answer_parts.append("2. 按预案流程执行处置")
    answer_parts.append("3. 做好记录和反馈")

    # 相似案例
    if reports:
        answer_parts.append("\n四、相似案例")
        for e in reports[:2]:
            answer_parts.append(f"- {e.get('eventId', '')}: {e.get('eventType', '')} / {e.get('roadName', '')} / {e.get('riskLevel', '')}")

    # 注意事项
    answer_parts.append("\n五、注意事项")
    answer_parts.append("- 本回答基于本地知识库模板生成，未经 LLM 润色")
    answer_parts.append("- 建议结合实时路况和现场信息综合判断")

    return {
        "question": question,
        "answer": "\n".join(answer_parts),
        "evidence": [
            {
                "content": e["content"][:300],
                "docType": e["docType"],
                "eventType": e.get("eventType", ""),
                "roadName": e.get("roadName", ""),
                "riskLevel": e.get("riskLevel", ""),
                "score": e.get("score", 0.0),
            }
            for e in evidence[:5]
        ],
        "suggestions": key_actions[:5],
        "confidence": min(0.8, len(evidence) * 0.15),
        "usedLLM": False,
    }


def _llm_answer(question: str, evidence: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """使用 LLM 生成回答。"""
    if not LLM_ENABLED:
        return None

    try:
        from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        from openai import OpenAI

        evidence_text = "\n---\n".join([
            f"[来源: {e['docType']} | 类型: {e.get('eventType', '')} | 路段: {e.get('roadName', '')}]\n{e['content'][:500]}"
            for e in evidence[:5]
        ])

        prompt = f"""你是智慧交通系统的AI调度员。请根据以下检索到的交通知识库内容，回答用户问题。

## 检索到的相关知识
{evidence_text}

## 用户问题
{question}

请按以下格式回答：
一、结论
二、依据（引用检索内容）
三、建议处置
四、相似案例
五、注意事项（如果知识库信息不足以回答，请明确说明）"""

        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是智慧交通系统的AI调度员，基于交通知识库提供专业的处置建议。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2048,
            timeout=30,
        )

        answer = response.choices[0].message.content.strip()
        return {
            "question": question,
            "answer": answer,
            "evidence": [
                {
                    "content": e["content"][:300],
                    "docType": e["docType"],
                    "eventType": e.get("eventType", ""),
                    "roadName": e.get("roadName", ""),
                    "riskLevel": e.get("riskLevel", ""),
                    "score": e.get("score", 0.0),
                }
                for e in evidence[:5]
            ],
            "suggestions": [e.get("reason", "") for e in evidence[:3]],
            "confidence": 0.85,
            "usedLLM": True,
        }
    except Exception as e:
        print(f"[RAG] LLM 调用失败: {e}")
        return None


def rag_ask(question: str, limit: int = 5) -> Dict[str, Any]:
    """
    RAG 问答主入口。

    Args:
        question: 用户问题
        limit: 检索文档数量

    Returns:
        问答结果字典
    """
    # 步骤 1：语义检索
    search_result = semantic_search(question, limit=limit)
    evidence = search_result.get("results", [])

    if not evidence and _CHROMA_AVAILABLE:
        # 尝试不加过滤条件重新搜索
        search_result = semantic_search(question, limit=limit)
        evidence = search_result.get("results", [])

    # 步骤 2：尝试 LLM 回答
    llm_result = _llm_answer(question, evidence) if evidence else None

    # 步骤 3：降级为模板回答
    if llm_result:
        return llm_result

    return _build_local_answer(question, evidence)
