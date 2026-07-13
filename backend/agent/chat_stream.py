"""
Chat SSE 流式 — /chat/stream 端点逻辑
Phase 8.1: 修复 mode 路由 + 标题生成 + DeepSeek 真流式
"""
import json, asyncio
from datetime import datetime
from typing import Dict, Any, AsyncGenerator

from backend.config import LLM_ENABLED, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from backend.chat.chat_db import create_session, add_message, update_session_title
from backend.chat.memory_manager import build_context_for_llm
from backend.rag.semantic_retriever import semantic_search
from backend.rag.grounded_answer import generate_grounded_answer
from backend.rag.domain_retrieval_policy import domain_rerank_and_filter
from backend.rag.intent_router import classify_traffic_intent
from backend.agent.streaming import sse_event


def _generate_title(content: str, answer: str = "") -> str:
    """根据用户问题和助手回答，用 LLM 生成标题（不可用时规则降级）。"""
    # Try LLM first
    if LLM_ENABLED:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
            prompt = f"请根据用户问题和助手回答，生成一个 8 到 15 个中文字符的简洁标题。只输出标题，不要标点，不要解释，不要引号。\n\n用户问题：{content[:200]}\n助手回答：{answer[:200]}"
            resp = client.chat.completions.create(
                model=DEEPSEEK_MODEL, messages=[{"role": "user", "content": prompt}],
                temperature=0.3, max_tokens=30, timeout=10,
            )
            title = resp.choices[0].message.content.strip()
            if title and 4 <= len(title) <= 30:
                return title
        except Exception as e:
            print(f"[Title] LLM failed: {e}")

    # Rule fallback
    q = content.strip()
    for prefix in ["请分析", "帮我分析", "帮我看看", "请问", "请", "帮我"]:
        if q.startswith(prefix):
            q = q[len(prefix):]
            break
    # Try to extract meaningful part
    keywords = []
    if "学校" in q: keywords.append("学校周边")
    if "医院" in q: keywords.append("医院周边")
    if "拥堵" in q: keywords.append("拥堵")
    if "事故" in q: keywords.append("事故")
    if "信号" in q: keywords.append("信号")
    if "匝道" in q: keywords.append("匝道")
    if "高峰" in q: keywords.append("高峰")
    if "协同" in q or "多Agent" in q: keywords.append("协同研判")
    if "风险" in q: keywords.append("风险")
    if "未闭环" in q: keywords.append("未闭环")
    if keywords:
        return "".join(keywords[:3]) + "分析" if not any(k.endswith("分析") for k in keywords) else "".join(keywords[:3])
    return q[:16] + ("..." if len(q) > 16 else "")


async def _llm_stream_deltas(prompt: str) -> AsyncGenerator[str, None]:
    """DeepSeek stream=true 真流式转发 delta。"""
    if not LLM_ENABLED:
        return
    try:
        from openai import OpenAI
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        stream = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=2048, stream=True, timeout=30,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
    except Exception as e:
        print(f"[LLM stream] err: {e}")


async def chat_stream_generator(
    session_id: str | None,
    content: str,
    mode: str = "react",
) -> AsyncGenerator[str, None]:
    """Chat SSE 流式生成器。"""

    # --- 1. Create session ---
    if not session_id:
        sess = create_session(f"sess_{datetime.now().strftime('%Y%m%d%H%M%S')}_{id(datetime.now()) % 100000}", mode)
        session_id = sess["sessionId"]
        yield sse_event("session_created", {"sessionId": session_id})

    user_msg_id = f"um_{int(datetime.now().timestamp() * 1000)}"
    add_message(user_msg_id, session_id, "user", content, mode)
    yield sse_event("message_saved", {"userMessageId": user_msg_id})

    memory_ctx = ""
    try: memory_ctx = build_context_for_llm(session_id, content)
    except: pass

    # --- 2. Dispatch by mode ---
    if mode == "rag":
        yield sse_event("step", {"stage": "intent", "text": "正在识别交通问题意图..."})
        intent = classify_traffic_intent(content)
        yield sse_event("step", {"stage": "retrieval", "text": "正在检索交通知识库..."})
        raw = semantic_search(content, limit=10).get("results", [])
        yield sse_event("step", {"stage": "rerank", "text": "正在重排证据..."})
        reranked = domain_rerank_and_filter(content, raw)
        evidence_items = reranked.get("evidence", [])
        if evidence_items:
            yield sse_event("evidence", {"items": evidence_items[:5]})

        yield sse_event("step", {"stage": "llm", "text": "正在基于证据生成回答..."})
        answer = ""
        if LLM_ENABLED:
            ev_text = "\n".join([f"[{e['docType']}] {e['content'][:300]}" for e in evidence_items[:5]])
            prompt = f"基于以下知识库证据回答用户问题。只能基于证据回答，证据不足请明确说明。\n\n证据:\n{ev_text}\n\n用户问题: {content}\n\n请用中文简洁回答（格式：结论/依据/建议/不确定性说明）："
            async for delta in _llm_stream_deltas(prompt):
                answer += delta
                yield sse_event("delta", {"text": delta})
                await asyncio.sleep(0.01)

        if not answer:
            ga = generate_grounded_answer(content, raw, memory_ctx, mode)
            answer = ga.get("answer", "")
            for chunk in _text_chunks(answer):
                yield sse_event("delta", {"text": chunk})
                await asyncio.sleep(0.02)

        asst_id = f"am_{int(datetime.now().timestamp() * 1000)}"
        add_message(asst_id, session_id, "assistant", answer, mode)
        ti = _finalize_title_and_done(session_id, content, answer)
        yield sse_event("done", {**ti, "sessionId": session_id, "assistantMessageId": asst_id, "abstained": len(evidence_items) == 0, "usedLLM": LLM_ENABLED and bool(answer)})

    elif mode == "react":
        # 智能诊断 — 受控 ReAct，不输出多 Agent 报告
        yield sse_event("step", {"stage": "react", "text": "正在进行受控诊断分析..."})
        from backend.agent.react_agent import controlled_react_diagnose
        result = controlled_react_diagnose(content, max_steps=3)
        answer = result.get("finalAnswer", "")
        for chunk in _text_chunks(answer):
            yield sse_event("delta", {"text": chunk})
            await asyncio.sleep(0.02)
        asst_id = f"am_{int(datetime.now().timestamp() * 1000)}"
        add_message(asst_id, session_id, "assistant", answer, mode)
        ti = _finalize_title_and_done(session_id, content, answer)
        yield sse_event("done", {**ti, "sessionId": session_id, "assistantMessageId": asst_id, "usedLLM": result.get("usedLLM", False)})

    elif mode == "routed":
        # 事件研判 — 风险分析 + 处置建议，不输出多 Agent 报告
        yield sse_event("step", {"stage": "routed", "text": "正在进行事件风险研判..."})
        from backend.tools.risk_tools import calculate_risk_score
        from backend.tools.rule_tools import retrieve_rule
        from backend.tools.dispatch_tools import generate_dispatch_message, generate_public_message
        from backend.rag.semantic_retriever import semantic_search as search_rag
        # Extract event info from content (simple heuristic)
        se = {"eventType": "congestion", "eventTypeCn": "拥堵", "roadName": "未知路段",
              "avgSpeed": 10, "queueLength": 100, "duration": 300, "weather": "clear",
              "timePeriod": "off_peak", "isMainRoad": False, "nearbySchool": False, "nearbyHospital": False}
        risk = calculate_risk_score(se)
        rule = retrieve_rule("拥堵")
        dispatch = generate_dispatch_message(se, risk, rule)
        public = generate_public_message(se, risk)
        rag_results = search_rag(content, limit=3).get("results", [])

        lines = [
            "## 事件风险研判",
            f"风险等级：{risk['riskLevel']}（{risk['riskScore']}分）",
            "", "**风险原因**：",
        ]
        lines.extend(f"- {r}" for r in risk.get("riskReasons", []))
        lines.append("")
        lines.append("**处置建议**：")
        lines.append(dispatch)
        lines.append("")
        lines.append("**公众提示**：")
        lines.append(public)
        if rag_results:
            lines.append("")
            lines.append("**检索依据**：")
            lines.extend(f"- [{r['docType']}] {r['content'][:120]}..." for r in rag_results[:3])
        answer = "\n".join(lines)
        for chunk in _text_chunks(answer):
            yield sse_event("delta", {"text": chunk})
            await asyncio.sleep(0.02)
        asst_id = f"am_{int(datetime.now().timestamp() * 1000)}"
        add_message(asst_id, session_id, "assistant", answer, mode)
        ti = _finalize_title_and_done(session_id, content, answer)
        yield sse_event("done", {**ti, "sessionId": session_id, "assistantMessageId": asst_id})

    elif mode == "hybrid":
        yield sse_event("step", {"stage": "hybrid", "text": "正在计算规则相似度和向量相似度..."})
        from backend.tools.similarity_tools import hybrid_similarity
        hs = hybrid_similarity("E202606300001", limit=5, min_score=0.3)
        cases = hs.get("similarCases", [])
        answer = f"共找到 {len(cases)} 个相似案例。\n\n"
        for i, c in enumerate(cases[:5]):
            answer += f"{i+1}. {c.get('roadName','')} | 综合相似度 {(c.get('finalSimilarity',0)*100):.0f}%\n"
        for chunk in _text_chunks(answer):
            yield sse_event("delta", {"text": chunk})
            await asyncio.sleep(0.02)
        asst_id = f"am_{int(datetime.now().timestamp() * 1000)}"
        add_message(asst_id, session_id, "assistant", answer, mode)
        ti = _finalize_title_and_done(session_id, content, answer)
        yield sse_event("done", {**ti, "sessionId": session_id, "assistantMessageId": asst_id})

    elif mode == "collaboration":
        # 协同分析 → delegate to routed_analyze/stream logic
        yield sse_event("step", {"stage": "collaboration", "text": "正在启动多Agent协同分析..."})
        from backend.agent.multi_agent import multi_agent_analyze
        info = {"eventId": f"E_{int(datetime.now().timestamp())}", "eventType": "congestion", "roadName": "人民路",
                "direction": "东向西", "avgSpeed": 8.0, "queueLength": 180, "duration": 600,
                "weather": "rain", "timePeriod": "morning_peak", "isMainRoad": True}
        result = multi_agent_analyze(info)
        answer = result.get("report", "")
        for chunk in _text_chunks(answer):
            yield sse_event("delta", {"text": chunk})
            await asyncio.sleep(0.02)
        asst_id = f"am_{int(datetime.now().timestamp() * 1000)}"
        add_message(asst_id, session_id, "assistant", answer, mode)
        ti = _finalize_title_and_done(session_id, content, answer)
        yield sse_event("done", {**ti, "sessionId": session_id, "assistantMessageId": asst_id})

    else:
        # report / default
        yield sse_event("step", {"stage": "report", "text": "正在生成报告..."})
        from backend.tools.report_summary_tools import generate_daily_report
        dr = generate_daily_report()
        answer = dr.get("reportText", "")
        for chunk in _text_chunks(answer):
            yield sse_event("delta", {"text": chunk})
            await asyncio.sleep(0.02)
        asst_id = f"am_{int(datetime.now().timestamp() * 1000)}"
        add_message(asst_id, session_id, "assistant", answer, mode)
        ti = _finalize_title_and_done(session_id, content, answer)
        yield sse_event("done", {**ti, "sessionId": session_id, "assistantMessageId": asst_id})


def _finalize_title_and_done(session_id: str, content: str, answer: str) -> dict:
    """生成标题并构建 done event data。只在 title 为默认值时设置一次。"""
    from backend.chat.chat_db import get_session
    final_title = None
    sess = get_session(session_id)
    if sess and (not sess.get("title") or sess.get("title") == "新对话"):
        final_title = _generate_title(content, answer)
        update_session_title(session_id, final_title)
    return {"title": final_title or (sess.get("title") if sess else "新对话"), "titleUpdated": final_title is not None}


def _text_chunks(text: str, size: int = 6) -> list:
    if not text: return [""]
    chunks = []; start = 0
    for i, ch in enumerate(text):
        if ch in "。\n？！，；" and i - start >= size:
            chunks.append(text[start:i + 1]); start = i + 1
    if start < len(text): chunks.append(text[start:])
    return chunks if chunks else [text[i:i + size] for i in range(0, len(text), size)]
