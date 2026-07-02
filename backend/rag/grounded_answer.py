"""
基于证据生成回答 — 不编造，证据不足时拒答
"""
from typing import Dict, Any, List, Optional
from backend.config import LLM_ENABLED
from backend.rag.retrieval_policy import apply_retrieval_threshold
from backend.rag.context_builder import build_evidence_context, format_evidence_for_prompt


def generate_grounded_answer(
    question: str,
    evidence_list: List[Dict[str, Any]],
    memory_context: str = "",
    mode: str = "react",
) -> Dict[str, Any]:
    """基于证据生成回答。无证据则 abstain。"""
    policy = apply_retrieval_threshold(evidence_list)
    accepted = policy["accepted"]
    abstain = policy["abstain"]

    # Build evidence context
    evidence_ctx = build_evidence_context(accepted)

    # Try LLM first
    if LLM_ENABLED and not abstain:
        llm_answer = _llm_grounded_answer(question, evidence_ctx, memory_context, mode)
        if llm_answer:
            return {
                "answer": llm_answer,
                "evidence": evidence_ctx,
                "confidence": {"high": 0.85, "medium": 0.65, "low": 0.45, "none": 0.0}[policy["level"]],
                "abstained": False,
                "warnings": [],
                "usedLLM": True,
            }

    # Template or abstain
    if abstain:
        return {
            "answer": f"当前知识库没有检索到足够可靠的依据来回答「{question[:40]}」。\n\n建议：\n1. 尝试更具体的交通术语重新提问\n2. 通过 POST /rag/rebuild_index 扩充知识库\n3. 查看系统文档了解支持的问题类型",
            "evidence": [],
            "confidence": 0.0,
            "abstained": True,
            "warnings": [f"检索置信度: {policy['level']} ({policy['label']})", "系统已拒答以避免生成不可靠内容"],
            "usedLLM": False,
        }

    # Template with evidence
    parts = ["一、结论"]
    parts.append(f"根据知识库检索（{policy['label']}），关于「{question[:40]}」的相关依据如下：")
    parts.append("")
    parts.append("二、依据")
    for i, e in enumerate(evidence_ctx, 1):
        parts.append(f"{i}. [{e['docType']}] {e['content'][:150]}...（评分：{e['score']:.2f}）")
    parts.append("")
    parts.append("三、建议")
    parts.append("请参考上述依据，结合实时路况和现场信息综合判断。")
    parts.append("")
    parts.append("四、不确定性说明")
    parts.append(f"检索置信度为{policy['label']}，本回答仅基于知识库已有内容生成。")

    return {
        "answer": "\n".join(parts),
        "evidence": evidence_ctx,
        "confidence": {"high": 0.85, "medium": 0.65, "low": 0.45}[policy["level"]],
        "abstained": False,
        "warnings": [f"使用模板生成（LLM不可用）", f"检索置信度: {policy['level']}"],
        "usedLLM": False,
    }


def _llm_grounded_answer(question: str, evidence: List[Dict], memory: str, mode: str) -> Optional[str]:
    """LLM 生成基于证据的回答。"""
    if not LLM_ENABLED:
        return None
    try:
        from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        from openai import OpenAI

        ev_text = format_evidence_for_prompt(evidence)
        prompt = f"""你是智慧交通系统的AI助手。必须严格基于以下证据回答问题，不得编造。

## 证据
{ev_text}

## 对话历史
{memory or '（无）'}

## 用户问题
{question}

请按以下格式回答：
一、结论（基于证据总结）
二、依据（引用具体证据编号）
三、建议（基于证据的行动建议）
四、不确定性说明（如证据不足，必须明确指出）

注意：不要编造证据中没有的信息。如证据不足以得出结论，请明确说明。"""

        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL, messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=2048, timeout=30)
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"[GroundedAnswer] LLM err: {e}")
        return None
