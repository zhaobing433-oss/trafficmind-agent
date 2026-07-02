"""RAG Q&A service — retrieve + generate answer (LLM or template fallback)"""
from typing import Dict, Any, List, Optional
from backend.rag.semantic_retriever import semantic_search
from backend.rag.vector_store import _CHROMA_AVAILABLE
from backend.config import LLM_ENABLED

def rag_ask(question: str, limit: int = 5) -> Dict[str, Any]:
    evidence = semantic_search(question, limit=limit).get("results", [])
    if not evidence and _CHROMA_AVAILABLE:
        evidence = semantic_search(question, limit=limit).get("results", [])

    # Try LLM
    if LLM_ENABLED and evidence:
        try:
            from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
            from openai import OpenAI
            ev_text = "\n---\n".join([f"[{e['docType']} | {e.get('eventType', '')}]\n{e['content'][:500]}" for e in evidence[:5]])
            client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
            resp = client.chat.completions.create(model=DEEPSEEK_MODEL, messages=[
                {"role": "system", "content": "你是智慧交通AI助手，基于知识库回答。格式：一、结论 二、依据 三、建议处置 四、相似案例 五、注意事项"},
                {"role": "user", "content": f"知识库:\n{ev_text}\n\n问题: {question}"}],
                temperature=0.3, max_tokens=2048, timeout=30)
            return {"question": question, "answer": resp.choices[0].message.content.strip(),
                "evidence": [{"content": e["content"][:300], "docType": e["docType"], "score": e.get("score", 0)} for e in evidence[:5]],
                "suggestions": [e.get("reason", "") for e in evidence[:3]], "confidence": 0.85, "usedLLM": True}
        except Exception as e: print(f"[RAG] LLM err: {e}")

    # Template fallback
    key_actions = []
    for e in evidence:
        for line in e["content"][:500].split("\n"):
            s = line.strip()
            if s and (s[0].isdigit() or s.startswith("- ")): key_actions.append(s.lstrip("0123456789. -"))
    parts = ["一、结论", "根据知识库检索，参考以下建议："]
    parts.extend(f"{i}. {a}" for i, a in enumerate(key_actions[:5], 1))
    parts.append("\n二、依据")
    parts.extend(f"- {e.get('reason', '')}" for e in evidence[:3])
    parts.append("\n三、注意事项\n- 本回答基于本地模板生成\n- 建议结合实时路况综合判断")
    return {"question": question, "answer": "\n".join(parts),
        "evidence": [{"content": e["content"][:300], "docType": e["docType"], "score": e.get("score", 0)} for e in evidence[:5]],
        "suggestions": key_actions[:5], "confidence": min(0.8, len(evidence) * 0.15), "usedLLM": False}
