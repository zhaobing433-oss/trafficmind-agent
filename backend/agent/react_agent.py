"""
受控 ReAct 诊断 Agent
-------------------
只能调用只读工具的诊断/复盘/分析 Agent。
不允许修改状态、派单、通知、改变风险评分。

设计原则：
- 只读工具白名单（硬编码，LLM 无法绕过）
- 最大步数限制（默认4步）
- 每步输出 thought/action/observation
- 所有结论必须引用 evidence
- LLM 不可用时规则模板降级
"""

from datetime import datetime
from typing import Dict, Any, List, Optional, Callable
from backend.config import LLM_ENABLED


# ======== 只读工具白名单 ========

READONLY_TOOLS: Dict[str, Dict[str, Any]] = {
    "get_stats": {
        "description": "获取仪表盘聚合统计数据",
        "params": [],
        "fn": None,  # 惰性赋值
    },
    "get_high_risk_roads": {
        "description": "获取高风险路口 TopN 统计",
        "params": ["days", "limit"],
        "fn": None,
    },
    "get_unclosed_alerts": {
        "description": "获取未闭环事件提醒列表",
        "params": ["hours", "min_risk"],
        "fn": None,
    },
    "search_rag": {
        "description": "语义检索交通知识库",
        "params": ["query", "limit"],
        "fn": None,
    },
    "ask_rag": {
        "description": "RAG 交通知识库问答",
        "params": ["question", "limit"],
        "fn": None,
    },
    "get_similar_cases_hybrid": {
        "description": "混合相似案例检索（规则+向量）",
        "params": ["event_id", "limit", "min_score"],
        "fn": None,
    },
    "get_daily_report": {
        "description": "生成交通事件日报",
        "params": ["date"],
        "fn": None,
    },
    "get_weekly_report": {
        "description": "生成交通事件周报",
        "params": ["start_date", "end_date"],
        "fn": None,
    },
    "get_history": {
        "description": "查询历史事件记录",
        "params": ["limit"],
        "fn": None,
    },
}

# ======== 禁止的工具（黑名单） ========

FORBIDDEN_TOOLS = [
    "update_event_status",
    "send_notification",
    "delete_event",
    "modify_risk_score",
    "analyze_event",
]


def _init_tool_functions():
    """惰性初始化工具函数绑定（避免循环导入）。"""
    from backend.tools.db_tools import get_stats, get_history
    from backend.tools.stat_tools import get_high_risk_roads
    from backend.tools.alert_tools import get_unclosed_events
    from backend.rag.semantic_retriever import semantic_search
    from backend.rag.rag_service import rag_ask
    from backend.tools.report_summary_tools import generate_daily_report, generate_weekly_report
    from backend.tools.similarity_tools import hybrid_similarity

    READONLY_TOOLS["get_stats"]["fn"] = lambda **kw: get_stats()
    READONLY_TOOLS["get_high_risk_roads"]["fn"] = lambda **kw: get_high_risk_roads(
        days=int(kw.get("days", 7)), limit=int(kw.get("limit", 10)), min_risk=kw.get("min_risk", "高风险")
    )
    READONLY_TOOLS["get_unclosed_alerts"]["fn"] = lambda **kw: get_unclosed_events(
        hours=int(kw.get("hours", 24)), min_risk=kw.get("min_risk", "中风险")
    )
    READONLY_TOOLS["search_rag"]["fn"] = lambda **kw: semantic_search(
        query=kw.get("query", ""), limit=int(kw.get("limit", 5))
    )
    READONLY_TOOLS["ask_rag"]["fn"] = lambda **kw: rag_ask(
        question=kw.get("question", ""), limit=int(kw.get("limit", 5))
    )
    READONLY_TOOLS["get_similar_cases_hybrid"]["fn"] = lambda **kw: hybrid_similarity(
        event_id=kw.get("event_id", ""), limit=int(kw.get("limit", 5)), min_score=float(kw.get("min_score", 0.4))
    )
    READONLY_TOOLS["get_daily_report"]["fn"] = lambda **kw: generate_daily_report(date=kw.get("date"))
    READONLY_TOOLS["get_weekly_report"]["fn"] = lambda **kw: generate_weekly_report(
        start_date=kw.get("start_date"), end_date=kw.get("end_date")
    )
    READONLY_TOOLS["get_history"]["fn"] = lambda **kw: get_history(limit=int(kw.get("limit", 50)))


def _select_tools_rule_based(question: str) -> List[str]:
    """
    基于关键词规则选择工具（LLM 不可用时的降级方案）。
    可审计、可解释 — 每个工具选择都有对应理由。
    """
    q = question.lower()
    tools = []

    # 统计类
    if any(w in q for w in ["统计", "多少", "数量", "多少个", "dashboard"]):
        tools.append("get_stats")
    # 风险/路口类
    if any(w in q for w in ["高风险", "重点路口", "哪个路", "多发", "top", "风险事件多"]):
        tools.append("get_high_risk_roads")
    # 未闭环
    if any(w in q for w in ["未闭环", "还没处理", "没完成", "还有多少没", "pending"]):
        tools.append("get_unclosed_alerts")
    # RAG 知识检索
    if any(w in q for w in ["怎么处理", "如何处置", "预案", "流程", "经验", "方法"]):
        tools.append("search_rag")
    # RAG 问答
    if any(w in q for w in ["建议", "怎么办", "分析", "评估"]):
        tools.append("ask_rag")
    # 相似案例
    if any(w in q for w in ["相似", "类似", "过往", "历史案例"]):
        tools.append("get_similar_cases_hybrid")
    # 日报/周报
    if any(w in q for w in ["日报", "今天", "今日报告"]):
        tools.append("get_daily_report")
    if any(w in q for w in ["周报", "这周", "本周", "最近七天"]):
        tools.append("get_weekly_report")
    # 历史记录
    if any(w in q for w in ["历史", "记录", "所有事件"]):
        tools.append("get_history")

    # 如果没有匹配，默认检索知识库
    if not tools:
        tools = ["search_rag", "get_stats"]

    return tools[:4]  # 最多 4 个工具


def _build_llm_react_prompt(question: str, step_num: int, previous_observations: List[str]) -> str:
    """构建 ReAct 提示词（LLM 模式）。"""
    tool_list = "\n".join([f"- {name}: {info['description']}" for name, info in READONLY_TOOLS.items()])
    prev_text = "\n".join(previous_observations[-4:]) if previous_observations else "（无）"

    return f"""你是智慧交通诊断分析助手。根据用户问题，逐步选择合适的只读工具来收集信息。

## 可用工具（只能调用这些）
{tool_list}

## 之前观察到的信息
{prev_text}

## 用户问题
{question}

## 当前第 {step_num} 步

请按以下格式输出（每条一行）：
THOUGHT: <你的分析思路>
ACTION: <工具名>
ACTION_INPUT: <JSON参数>

如果信息已经足够回答问题，输出：
THOUGHT: 信息已足够
ACTION: FINAL_ANSWER
FINAL_ANSWER: <综合回答>"""


def _parse_llm_response(text: str) -> Dict[str, str]:
    """解析 LLM 输出的 ReAct 格式。"""
    result = {"thought": "", "action": "", "action_input": "{}", "final_answer": ""}
    for line in text.split("\n"):
        line = line.strip()
        if line.upper().startswith("THOUGHT:"):
            result["thought"] = line.split(":", 1)[1].strip()
        elif line.upper().startswith("ACTION:"):
            result["action"] = line.split(":", 1)[1].strip()
        elif line.upper().startswith("ACTION_INPUT:") or line.upper().startswith("ACTION INPUT:"):
            result["action_input"] = line.split(":", 1)[1].strip()
        elif line.upper().startswith("FINAL_ANSWER:"):
            result["final_answer"] = line.split(":", 1)[1].strip()
    return result


def _call_llm(prompt: str) -> Optional[str]:
    """调用 LLM。"""
    if not LLM_ENABLED:
        return None
    try:
        from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        from openai import OpenAI
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=1024, timeout=30,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[ReAct] LLM failed: {e}")
        return None


def _execute_tool(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """执行只读工具调用。"""
    if tool_name not in READONLY_TOOLS:
        return {"error": f"工具 '{tool_name}' 不在只读白名单中", "success": False}
    if READONLY_TOOLS[tool_name]["fn"] is None:
        _init_tool_functions()
    try:
        result = READONLY_TOOLS[tool_name]["fn"](**params)
        return {"result": result, "success": True}
    except Exception as e:
        return {"error": str(e), "success": False}


def _collapse_observations(observations: List[str], results: List[Dict]) -> str:
    """将工具调用结果压缩为诊断摘要文本。"""
    parts = []
    for obs, res in zip(observations[-4:], results[-4:]):
        r = res.get("result", {})
        if isinstance(r, dict):
            keys = list(r.keys())[:3]
            snippet = str(dict(list(r.items())[:4]))[:200]
            parts.append(f"工具返回 ({', '.join(keys)}): {snippet}")
    return "\n".join(parts) if parts else "无观测数据"


# ======== 主入口 ========


def controlled_react_diagnose(question: str, max_steps: int = 4) -> Dict[str, Any]:
    """
    受控 ReAct 诊断主入口。

    流程：
    1. 选择工具（LLM 或规则降级）
    2. 逐步执行 thought → action → observation
    3. 最多 max_steps 步
    4. 综合生成 finalAnswer + evidence

    Returns:
        ReactDiagnoseResponse 结构
    """
    _init_tool_functions()
    steps: List[Dict] = []
    tool_calls: List[Dict] = []
    observations: List[str] = []
    warnings: List[str] = []
    final_answer = ""
    all_evidence: List[Dict] = []
    used_llm = LLM_ENABLED

    # 步骤 1：选工具
    selected_tools = _select_tools_rule_based(question)
    if used_llm:
        prompt = _build_llm_react_prompt(question, 1, [])
        llm_output = _call_llm(prompt)
        if llm_output:
            parsed = _parse_llm_response(llm_output)
            if parsed["action"] and parsed["action"] != "FINAL_ANSWER":
                # 用 LLM 选择的工具（但必须在白名单内）
                llm_tools = [t.strip() for t in parsed["action"].split(",") if t.strip() in READONLY_TOOLS]
                if llm_tools:
                    selected_tools = llm_tools[:4]
            if parsed.get("final_answer"):
                final_answer = parsed["final_answer"]
        else:
            used_llm = False
            warnings.append("LLM 不可用，使用规则模板选择工具")

    # 步骤 2- max_steps：逐步执行
    for step_num in range(1, max_steps + 1):
        if not selected_tools:
            break

        tool_name = selected_tools[step_num - 1] if step_num - 1 < len(selected_tools) else selected_tools[-1]
        step_thought = f"第{step_num}步：调用 '{tool_name}' 获取数据"

        # 执行工具
        params = {"query": question, "question": question, "limit": 5, "days": 7, "hours": 24}
        if tool_name in ("get_similar_cases_hybrid",):
            # 尝试从前面步骤获取 event_id
            for prev in tool_calls:
                r = prev.get("result", {})
                if isinstance(r, dict):
                    records = r.get("records", [])
                    if records:
                        params["event_id"] = records[0].get("eventId", "")
                        break

        exec_result = _execute_tool(tool_name, params)

        # 验证是不在黑名单
        is_forbidden = any(fb in tool_name for fb in FORBIDDEN_TOOLS)

        obs_text = ""
        if is_forbidden:
            obs_text = f"[安全拦截] 工具 '{tool_name}' 被禁止调用（黑名单）"
            warnings.append(obs_text)
            exec_result = {"error": obs_text, "success": False}
        elif not exec_result.get("success"):
            obs_text = f"调用失败: {exec_result.get('error', '未知错误')}"
            warnings.append(f"[Step {step_num}] {obs_text}")
        else:
            r = exec_result.get("result", {})
            if isinstance(r, dict):
                obs_text = str(dict(list(r.items())[:4]))[:300]
                # 收集 evidence
                for key in ["results", "topRoads", "similarCases", "alerts"]:
                    if key in r and isinstance(r[key], list):
                        all_evidence.extend(r[key][:3])

        observations.append(obs_text)
        tool_calls.append({"tool": tool_name, "params": params, "result": exec_result.get("result"), "success": exec_result.get("success", False)})
        steps.append({
            "step": step_num,
            "thought": step_thought,
            "action": tool_name,
            "actionInput": params,
            "observation": obs_text[:500],
            "error": exec_result.get("error"),
        })

    # 步骤 3：生成 finalAnswer
    if not final_answer:
        collapsed = _collapse_observations(observations, tool_calls)
        if used_llm:
            summary_prompt = f"""基于以下诊断数据，简洁回答用户问题。

数据: {collapsed}
问题: {question}

请用中文简洁回答（200字以内），必须引用数据。"""
            llm_summary = _call_llm(summary_prompt)
            if llm_summary:
                final_answer = llm_summary
            else:
                used_llm = False

        if not final_answer:
            final_answer = f"基于 {len(steps)} 步诊断分析，共调用 {len(tool_calls)} 个工具。\n{collapsed}\n\n建议：如需详细处置方案，请使用 /rag/ask 或 /agent/routed_analyze。"
            warnings.append("最终回答使用模板生成（LLM 不可用）")

    return {
        "question": question,
        "steps": steps,
        "toolCalls": tool_calls,
        "observations": observations,
        "finalAnswer": final_answer,
        "evidence": all_evidence[:8],
        "confidence": 0.70 if used_llm else 0.55,
        "warnings": warnings,
        "usedLLM": used_llm,
    }
