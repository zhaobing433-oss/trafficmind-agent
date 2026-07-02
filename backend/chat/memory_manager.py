"""
上下文记忆管理 — 短期上下文 + 长期摘要
"""
from typing import Dict, Any, List
from backend.chat.chat_db import (
    get_recent_messages, get_memory_summary, upsert_memory_summary,
    get_session_messages, update_session_summary,
)
from backend.config import LLM_ENABLED


def get_short_term_context(session_id: str) -> str:
    """取最近 4~6 条消息作为短期上下文。"""
    msgs = get_recent_messages(session_id, 6)
    if not msgs:
        return ""
    return "\n".join([
        f"[{'用户' if m['role'] == 'user' else '助手'}]: {m['content'][:200]}"
        for m in msgs
    ])


def get_long_term_summary(session_id: str) -> str:
    """获取长期记忆摘要。"""
    mem = get_memory_summary(session_id)
    if not mem:
        return ""
    parts = []
    if mem.get("summary"):
        parts.append("## 对话摘要\n" + mem["summary"])
    if mem.get("key_topics"):
        import json
        try:
            topics = json.loads(mem["key_topics"])
            if topics:
                parts.append("## 关键话题\n" + "、".join(topics))
        except Exception:
            pass
    if mem.get("unresolved_questions"):
        import json
        try:
            qs = json.loads(mem["unresolved_questions"])
            if qs:
                parts.append("## 未解决问题\n" + "；".join(qs))
        except Exception:
            pass
    return "\n".join(parts)


def build_context_for_llm(session_id: str, current_question: str) -> str:
    """组合长期摘要 + 短期上下文 + 当前问题。"""
    long_term = get_long_term_summary(session_id)
    short_term = get_short_term_context(session_id)
    parts = []
    if long_term:
        parts.append(long_term)
    if short_term:
        parts.append("## 最近对话\n" + short_term)
    parts.append(f"## 当前问题\n{current_question}")
    return "\n\n".join(parts)


def update_memory_summary(session_id: str):
    """当消息超过阈值时更新记忆摘要。"""
    msgs = get_session_messages(session_id, 50)
    if len(msgs) < 6:
        return  # 消息太少，不摘要

    user_msgs = [m for m in msgs if m["role"] == "user"]
    all_text = " ".join([m["content"] for m in msgs])
    all_text_lower = all_text.lower()

    # 规则提取关键话题
    topics = []
    if "医院" in all_text: topics.append("医院周边交通")
    if "学校" in all_text: topics.append("学校周边交通")
    if "事故" in all_text: topics.append("事故处置")
    if "拥堵" in all_text: topics.append("拥堵治理")
    if "信号" in all_text: topics.append("信号灯问题")
    if "高风险" in all_text: topics.append("高风险路段")
    if "未闭环" in all_text: topics.append("未闭环事件")

    # 未解决问题
    unresolved = []
    if len(user_msgs) >= 2:
        last_qs = [m["content"][:60] for m in user_msgs[-3:]]
        unresolved = [q for q in last_qs if "?" in q or "？" in q or "什么" in q or "怎么" in q]

    # 生成摘要
    summary = f"用户共进行了 {len(user_msgs)} 轮对话"
    if topics:
        summary += f"，主要讨论{'、'.join(topics)}"
    summary += "。"

    # 尝试 LLM 生成更好的摘要
    if LLM_ENABLED and len(msgs) > 10:
        try:
            from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
            from openai import OpenAI
            ctx = "\n".join([f"[{'用户' if m['role']=='user' else '助手'}]: {m['content'][:150]}" for m in msgs[-10:]])
            client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": f"请用一句话（不超过50字）总结以下交通管理对话：\n{ctx}\n\n总结："}],
                temperature=0.3, max_tokens=100, timeout=15)
            llm_summary = resp.choices[0].message.content.strip()
            if llm_summary:
                summary = llm_summary
        except Exception:
            pass

    upsert_memory_summary(session_id, summary, topics, unresolved)
    update_session_summary(session_id, summary)
