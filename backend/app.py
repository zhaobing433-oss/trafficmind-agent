"""
TrafficMind Agent - FastAPI 主应用
--------------------------------
提供交通事件智能分析 API：
  POST /analyze_event     - 分析交通事件
  GET  /history           - 查询历史记录
  GET  /event/{event_id}  - 查询单条事件详情
  POST /event/{event_id}/status - 更新事件状态
"""

import sys
import os
import json
from datetime import datetime
from contextlib import asynccontextmanager

# 确保 backend 的父目录在 sys.path 中，以便 `from backend.xxx` 可正常工作
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from typing import Any, Dict, List, Optional

from backend.agent.graph import build_graph
from backend.tools.db_tools import (
    init_db,
    get_history,
    get_event_by_id,
    update_event_status,
    get_stats,
)
from backend.config import EVENT_STATUSES, LLM_ENABLED

# -------------------- 应用生命周期 --------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动时初始化数据库。"""
    init_db()
    llm_status = "已启用 (DeepSeek)" if LLM_ENABLED else "未配置，将使用本地模板"
    print(f"TrafficMind Agent 启动完成")
    print(f"  LLM 状态: {llm_status}")
    print(f"  API 文档: http://localhost:8000/docs")
    yield


# -------------------- 创建 FastAPI 应用 --------------------

app = FastAPI(
    title="TrafficMind Agent API",
    description="面向智慧交通的事件研判与闭环处置 Agent - 第一阶段 MVP",
    version="1.0.0",
    lifespan=lifespan,
)

# 允许跨域（方便后续前端对接）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------- 请求/响应模型 --------------------

class AnalyzeEventRequest(BaseModel):
    """分析事件请求体（宽松模式，额外字段会被保留）"""
    eventId: str
    eventType: str
    cameraId: Optional[str] = ""
    roadName: str
    direction: Optional[str] = ""
    lane: Optional[str] = ""
    avgSpeed: float
    queueLength: float
    duration: float
    vehicleCount: Optional[int] = 0
    weather: Optional[str] = "clear"
    timePeriod: Optional[str] = "off_peak"
    isMainRoad: Optional[bool] = False
    nearbySchool: Optional[bool] = False
    nearbyHospital: Optional[bool] = False
    confidence: Optional[float] = 0.9

    model_config = ConfigDict(extra="allow")  # 允许额外字段


class StatusUpdateRequest(BaseModel):
    """状态更新请求体"""
    status: str


# -------------------- API 接口 --------------------

@app.post("/analyze_event", summary="分析交通事件")
async def analyze_event(request: AnalyzeEventRequest):
    """
    输入一条交通事件 JSON，Agent 自动完成：
      1. 事件解析与标准化
      2. 风险评分与等级判定
      3. 预案匹配
      4. 处置建议生成
      5. 调度话术生成
      6. 结构化报告生成
      7. 结果持久化保存

    返回完整的分析结果 JSON。
    """
    # 构建初始状态
    raw_event = request.model_dump()
    initial_state = {
        "raw_event": raw_event,
        "standard_event": {},
        "risk_result": {},
        "matched_rule": {},
        "suggestions": [],
        "dispatch_message": "",
        "public_message": "",
        "report": "",
        "result": {},
        "step": "",
        "error": None,
    }

    # 执行 LangGraph 工作流
    graph = build_graph()
    final_state = graph.invoke(initial_state)

    # 如果工作流出错
    if final_state.get("error"):
        raise HTTPException(status_code=400, detail=final_state["error"])

    # 返回结果
    return final_state.get("result", {})


@app.get("/history", summary="查询历史事件记录")
async def history(limit: int = 50):
    """
    查询 SQLite 中保存的历史事件分析记录。
    按更新时间倒序排列，默认返回最近 50 条。

    Args:
        limit: 最大返回条数（默认50）
    """
    records = get_history(limit=limit)
    return {"total": len(records), "records": records}


@app.get("/event/{event_id}", summary="查询单条事件详情")
async def get_event(event_id: str):
    """
    根据 eventId 查询单条事件的完整分析详情。

    Args:
        event_id: 事件编号（如 E202606290001）
    """
    record = get_event_by_id(event_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"事件 {event_id} 不存在")
    return record


@app.post("/event/{event_id}/status", summary="更新事件状态")
async def update_status(event_id: str, body: StatusUpdateRequest):
    """
    更新事件处理状态。

    有效状态值：
        - 待研判
        - 待派单
        - 处置中
        - 已处置
        - 待复盘
        - 已归档

    Args:
        event_id: 事件编号
        body: { "status": "处置中" }
    """
    # 先检查事件是否存在
    record = get_event_by_id(event_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"事件 {event_id} 不存在")

    new_status = body.status
    if new_status not in EVENT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"无效状态值 '{new_status}'。有效值: {', '.join(EVENT_STATUSES)}",
        )

    ok = update_event_status(event_id, new_status)
    if not ok:
        raise HTTPException(status_code=500, detail="状态更新失败")

    return {
        "eventId": event_id,
        "status": new_status,
        "message": f"事件状态已更新为「{new_status}」",
    }


# -------------------- 第二阶段新增接口 --------------------

# 导入新增工具模块
from backend.tools.similarity_tools import find_similar_cases, hybrid_similarity
from backend.tools.report_summary_tools import generate_daily_report, generate_weekly_report
from backend.tools.alert_tools import get_unclosed_events
from backend.tools.stat_tools import get_high_risk_roads
# Phase 3
from backend.rag.knowledge_indexer import build_knowledge_index
from backend.rag.semantic_retriever import semantic_search
from backend.rag.rag_service import rag_ask
from backend.rag.vector_store import get_collection_stats
# Phase 4
from backend.agent.react_agent import controlled_react_diagnose
from backend.agent.chat_stream import chat_stream_generator
from backend.agent.streaming import sse_event, sse_error

COLLABORATION_ORCHESTRATOR_ENABLED = os.getenv("COLLABORATION_ORCHESTRATOR_ENABLED", "true").lower() == "true"

from backend.agent.router import route_agents
from backend.agent.conflict_resolver import detect_conflicts, resolve_conflicts
from backend.agent.event_chain import build_event_chain
from backend.agent.multi_agent import multi_agent_analyze, CongestionAgent, AccidentAgent, SignalAgent, DispatchAgent
from backend.chat.chat_db import (
    create_session, list_sessions, get_session, delete_session,
    add_message, get_session_messages, update_session_title,
    get_memory_summary as get_chat_memory_summary,
)
from backend.chat.memory_manager import build_context_for_llm, update_memory_summary
from backend.rag.grounded_answer import generate_grounded_answer
from backend.rag.semantic_retriever import semantic_search


@app.get("/similar_cases/{event_id}", summary="查找历史相似案例")
async def similar_cases(
    event_id: str,
    limit: int = 5,
    min_score: float = 0.4,
):
    """
    根据事件编号查询历史相似案例。

    参数：
      - limit: 返回数量上限（默认 5）
      - min_score: 最低相似度阈值（默认 0.4）

    第一阶段使用规则相似度；第三阶段计划引入 Chroma/FAISS 做语义检索。
    """
    result = find_similar_cases(event_id, limit=limit, min_score=min_score)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.get("/reports/daily", summary="生成交通事件日报")
async def daily_report(date: Optional[str] = None):
    """
    生成某一天的交通事件日报。

    参数：
      - date: 日期，格式 YYYY-MM-DD，默认今天
    """
    return generate_daily_report(date)


@app.get("/reports/weekly", summary="生成交通事件周报")
async def weekly_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """
    生成交通事件周报。

    参数：
      - start_date: 开始日期，格式 YYYY-MM-DD，默认 7 天前
      - end_date: 结束日期，格式 YYYY-MM-DD，默认今天
    """
    return generate_weekly_report(start_date, end_date)


@app.get("/alerts/unclosed", summary="未闭环事件提醒")
async def unclosed_alerts(
    hours: int = 24,
    min_risk: str = "中风险",
):
    """
    查询未完成处置闭环的事件。

    参数：
      - hours: 查询最近多少小时内的事件（默认 24）
      - min_risk: 最低风险等级筛选（默认"中风险"）
    """
    valid_risks = {"低风险", "中风险", "高风险", "重大风险"}
    if min_risk not in valid_risks:
        raise HTTPException(
            status_code=400,
            detail=f"无效风险等级 '{min_risk}'。有效值: {', '.join(valid_risks)}",
        )
    return get_unclosed_events(hours=hours, min_risk=min_risk)


@app.get("/stats/high_risk_roads", summary="高风险路口 TopN 统计")
async def high_risk_roads(
    limit: int = 10,
    days: int = 7,
    min_risk: str = "高风险",
):
    """
    统计高风险事件多发的路口。

    参数：
      - limit: 返回数量上限（默认 10）
      - days: 统计最近多少天（默认 7）
      - min_risk: 最低风险等级筛选（默认"高风险"）
    """
    return get_high_risk_roads(limit=limit, days=days, min_risk=min_risk)


# -------------------- 第三阶段接口 --------------------

@app.post("/rag/rebuild_index", summary="重建 RAG 知识库索引")
async def rebuild_rag_index():
    result = build_knowledge_index()
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("message", "索引构建失败"))
    return result


@app.get("/rag/search", summary="语义检索交通知识库")
async def rag_search(query: str, limit: int = 5, doc_type: Optional[str] = None,
                     event_type: Optional[str] = None, road_name: Optional[str] = None,
                     risk_level: Optional[str] = None):
    return semantic_search(query=query, limit=limit, doc_type=doc_type,
                           event_type=event_type, road_name=road_name, risk_level=risk_level)


class AskRequest(BaseModel):
    question: str
    limit: Optional[int] = 5


@app.post("/rag/ask", summary="RAG 交通知识库问答")
async def rag_ask_endpoint(body: AskRequest):
    return rag_ask(body.question, body.limit or 5)


@app.get("/rag/status", summary="查看向量库状态")
async def rag_status():
    return get_collection_stats()


@app.get("/similar_cases_hybrid/{event_id}", summary="混合相似案例检索")
async def similar_cases_hybrid(event_id: str, limit: int = 5, min_score: float = 0.4):
    result = hybrid_similarity(event_id, limit=limit, min_score=min_score)
    if result.get("error") or result.get("currentEvent") is None:
        raise HTTPException(status_code=404, detail=result.get("error", f"事件 {event_id} 不存在"))
    return result


class MultiAgentRequest(BaseModel):
    eventId: str; eventType: str; roadName: str
    direction: Optional[str] = ""; avgSpeed: float; queueLength: float; duration: float
    vehicleCount: Optional[int] = 0; weather: Optional[str] = "clear"
    timePeriod: Optional[str] = "off_peak"; isMainRoad: Optional[bool] = False
    nearbySchool: Optional[bool] = False; nearbyHospital: Optional[bool] = False
    confidence: Optional[float] = 0.9
    model_config = ConfigDict(extra="allow")


@app.post("/agent/multi_analyze", summary="多 Agent 协同研判")
async def multi_agent_analyze_endpoint(body: MultiAgentRequest):
    return multi_agent_analyze(body.model_dump())


# -------------------- 第四阶段接口 --------------------

class ReactDiagnoseRequest(BaseModel):
    question: str
    max_steps: Optional[int] = 4


@app.post("/agent/react_diagnose", summary="受控 ReAct 诊断分析")
async def react_diagnose(body: ReactDiagnoseRequest):
    """
    受控 ReAct 诊断 Agent。只能调用只读工具（白名单），
    不允许修改状态、推送通知、改变风险评分。
    每步输出 thought/action/observation，最多 max_steps 步。
    """
    result = controlled_react_diagnose(body.question, body.max_steps or 4)
    return result


class RoutedAnalyzeRequest(BaseModel):
    eventId: str; eventType: str; roadName: str
    direction: Optional[str] = ""; avgSpeed: float; queueLength: float; duration: float
    vehicleCount: Optional[int] = 0; weather: Optional[str] = "clear"
    timePeriod: Optional[str] = "off_peak"; isMainRoad: Optional[bool] = False
    nearbySchool: Optional[bool] = False; nearbyHospital: Optional[bool] = False
    confidence: Optional[float] = 0.9
    model_config = ConfigDict(extra="allow")


@app.post("/agent/routed_analyze", summary="动态路由多 Agent 协同研判（含冲突检测）")
async def routed_analyze(body: RoutedAnalyzeRequest):
    """
    第四阶段增强版多 Agent 协同研判：
    1. 动态路由选择 Agent
    2. 各 Agent 独立分析
    3. 冲突检测与融合
    4. 事件驱动链式协同
    """
    event_info = body.model_dump()
    event_info["eventTypeCn"] = event_info.get("eventType", "")  # will be normalized later

    # Step 1: 路由
    routing = route_agents(event_info)

    # Step 2: 执行选中的 Agent
    agent_map = {
        "CongestionAgent": CongestionAgent,
        "AccidentAgent": AccidentAgent,
        "SignalAgent": SignalAgent,
        "DispatchAgent": DispatchAgent,
    }

    # Normalize event info for agents (add defaults for computed fields)
    from backend.agent.multi_agent import _get_event_info
    normalized_info = _get_event_info(event_info)

    agent_results = []
    for name in routing["selectedAgents"]:
        cls = agent_map.get(name)
        if cls:
            result = cls().analyze(normalized_info)
            agent_results.append(result)

    # Step 3: 事件驱动链
    chain_result = build_event_chain(normalized_info, agent_results)

    # Step 4: 冲突检测与融合
    conflicts = detect_conflicts(agent_results)
    resolution = resolve_conflicts(conflicts, agent_results, normalized_info)

    # Step 5: 风险警告
    risk_warnings = list(resolution.get("riskWarnings", []))
    if normalized_info.get("weather", "clear") in ("rain", "snow", "fog"):
        risk_warnings.append(f"天气预警：{normalized_info['weather']}")

    # Step 6: 报告
    from datetime import datetime
    report_lines = [
        "=" * 50,
        "   TrafficMind Agent 动态路由协同研判报告",
        "=" * 50,
        f"事件类型：{normalized_info.get('eventType', event_info.get('eventType', ''))}",
        f"路段：{normalized_info['roadName']}",
        "",
        f"路由选择：{', '.join(routing['selectedAgents'])}",
        f"路由理由：{'；'.join(routing['routingReasons'][:3])}",
        "",
    ]
    for r in agent_results:
        report_lines.append(f"[{r.get('agentName', '')}] urgency={r.get('urgency', '')}")
        for f in r.get("findings", []):
            report_lines.append(f"  - {f}")
    if conflicts:
        report_lines.append(f"\n检测到 {len(conflicts)} 个建议冲突，已融合处理")
    report_lines += ["", "=" * 50]

    return {
        "eventSummary": {
            "eventType": event_info.get("eventType", ""),
            "roadName": event_info["roadName"],
            "analyzedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "selectedAgents": routing["selectedAgents"],
        "routingReasons": routing["routingReasons"],
        "agentResults": agent_results,
        "conflicts": conflicts,
        "resolvedPlan": resolution.get("resolvedPlan", {}),
        "finalDecision": resolution.get("finalDecision", ""),
        "dispatchPlan": {
            "urgency": resolution.get("resolvedPlan", {}).get("urgency", "low"),
            "actions": resolution.get("resolvedPlan", {}).get("mergedSuggestions", []),
        },
        "riskWarnings": risk_warnings,
        "report": "\n".join(report_lines),
        # 链式协同信息
        "eventChain": {
            "triggerReasons": chain_result.get("triggerReasons", []),
            "triggeredAgents": chain_result.get("finalPlan", {}).get("triggeredAgents", []),
        },
    }


# ==================== 第六阶段：Chat 会话 API ====================

@app.post("/chat/sessions", summary="创建新会话")
async def create_chat_session(body: Dict[str, Any] = {"mode": "react"}):
    sid = "sess_" + datetime.now().strftime("%Y%m%d%H%M%S") + "_" + str(int(datetime.now().timestamp() * 1000) % 100000)
    return create_session(sid, body.get("mode", "react"))


@app.get("/chat/sessions", summary="获取最近会话列表")
async def list_chat_sessions(limit: int = 30):
    return {"sessions": list_sessions(limit)}


@app.get("/chat/sessions/{session_id}", summary="获取会话详情")
async def get_chat_session(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = get_session_messages(session_id)
    mem = get_chat_memory_summary(session_id) or {}
    return {"session": session, "messages": messages, "memorySummary": mem}


@app.patch("/chat/sessions/{session_id}/title", summary="重命名会话")
async def rename_chat_session(session_id: str, body: Dict[str, Any]):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    from backend.chat.chat_db import update_session_title
    update_session_title(session_id, body.get("title", "")[:50])
    return {"success": True, "title": body.get("title", "")[:50]}


@app.delete("/chat/sessions/{session_id}", summary="删除会话")
async def delete_chat_session(session_id: str):
    ok = delete_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"success": True, "sessionId": session_id}


class ChatMessageRequest(BaseModel):
    content: str
    mode: Optional[str] = "react"


@app.post("/chat/sessions/{session_id}/messages", summary="发送消息并获取回答")
async def send_chat_message(session_id: str, body: ChatMessageRequest):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    q = body.content.strip()
    if not q:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    mode = body.mode or "react"

    # 1. Save user message
    user_msg_id = "um_" + str(int(datetime.now().timestamp() * 1000))
    add_message(user_msg_id, session_id, "user", q, mode)

    # 2. Build context from memory
    memory_ctx = ""
    try:
        memory_ctx = build_context_for_llm(session_id, q)
    except Exception:
        pass

    # 3. RAG retrieval + grounded answer
    rag_results = semantic_search(q, limit=10).get("results", [])
    ga = generate_grounded_answer(q, rag_results, memory_ctx, mode)

    # 4. Save assistant message
    asst_msg_id = "am_" + str(int(datetime.now().timestamp() * 1000))
    result_summary = {
        "confidence": ga["confidence"],
        "usedLLM": ga.get("usedLLM", False),
        "abstained": ga.get("abstained", False),
        "evidenceCount": len(ga.get("evidence", [])),
    }
    add_message(asst_msg_id, session_id, "assistant", ga["answer"], mode, result_summary)

    # 5. Update title if first message
    if session.get("title") == "新对话":
        from backend.chat.chat_db import update_session_title
        update_session_title(session_id, q[:20])

    # 6. Update memory summary
    try:
        update_memory_summary(session_id)
    except Exception:
        pass

    return {
        "sessionId": session_id,
        "userMessage": {"id": user_msg_id, "role": "user", "content": q, "mode": mode},
        "assistantMessage": {
            "id": asst_msg_id, "role": "assistant", "content": ga["answer"],
            "mode": mode, "confidence": ga["confidence"],
            "abstained": ga.get("abstained", False), "usedLLM": ga.get("usedLLM", False),
        },
        "evidence": ga.get("evidence", []),
        "confidence": ga["confidence"],
        "abstained": ga.get("abstained", False),
        "warnings": ga.get("warnings", []),
    }


# -------------------- Phase 8: SSE 流式接口 --------------------

from fastapi.responses import StreamingResponse
from backend.agent.multi_agent import _get_event_info


class StreamRequest(BaseModel):
    sessionId: Optional[str] = None
    content: str
    mode: Optional[str] = "react"


VALID_MODES = {"react", "routed", "rag", "hybrid", "report", "collaboration"}


@app.post("/chat/stream", summary="Chat SSE 流式对话")
async def chat_stream(body: StreamRequest):
    """SSE 流式对话。支持 react/routed/rag/hybrid/report/collaboration。"""
    m = body.mode or "react"
    if m not in VALID_MODES:
        m = "react"

    async def event_generator():
        try:
            async for event in chat_stream_generator(session_id=body.sessionId, content=body.content, mode=m):
                yield event
        except Exception as e:
            yield sse_error(str(e))
    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class RoutedStreamRequest(BaseModel):
    sessionId: Optional[str] = None
    content: Optional[str] = None  # NL content for parsing
    eventId: Optional[str] = None
    eventType: str = "congestion"
    roadName: str = "未知路段"
    direction: Optional[str] = ""
    avgSpeed: Optional[float] = None
    queueLength: Optional[float] = None
    duration: Optional[float] = None
    weather: Optional[str] = "clear"
    timePeriod: Optional[str] = "off_peak"
    isMainRoad: Optional[bool] = False
    nearbySchool: Optional[bool] = False
    nearbyHospital: Optional[bool] = False
    confidence: Optional[float] = 0.9
    contextPolicy: Optional[str] = "fresh_event"
    model_config = ConfigDict(extra="allow")


@app.post("/agent/routed_analyze/stream", summary="协同分析 SSE 流式")
async def routed_analyze_stream(body: RoutedStreamRequest):
    """多 Agent 协同分析 SSE 流式。

    COLLABORATION_ORCHESTRATOR_ENABLED=true → Orchestrator 执行
    COLLABORATION_ORCHESTRATOR_ENABLED=false → 旧实现
    """
    if COLLABORATION_ORCHESTRATOR_ENABLED:
        return await _orchestrated_analyze_stream(body)
    return await _legacy_analyze_stream(body)


async def _orchestrated_analyze_stream(body: RoutedStreamRequest):
    """使用 CollaborationOrchestrator 执行协同分析。"""
    import asyncio as _asyncio
    from backend.agent.multi_agent import _get_event_info
    from backend.agent.router import route_agents
    from backend.agent.collaboration.orchestrator import CollaborationOrchestrator, AgentExecutionResult
    from backend.agent.collaboration.budget import ExecutionBudget

    async def agent_stream():
        from backend.agent.collaboration.event_parser import parse_content_to_event, build_current_event
        from backend.agent.collaboration.db_repository import load_previous_run_context

        # ===== Step 1: Parse CURRENT message ONLY =====
        content_text = body.content or (body.model_dump().get("content", ""))
        context_policy = body.contextPolicy or "fresh_event"

        nl_parsed = {}
        if content_text:
            nl_parsed = parse_content_to_event(content_text)

        # ===== Step 2: Build currentEvent — STRICTLY from current message =====
        # NEVER merge previous run data into currentEvent
        explicit = body.model_dump()
        current_event = build_current_event(nl_parsed, explicit, context_policy)
        field_sources = current_event.get("fieldSources", {})

        # ===== Step 3: Load previous run context — SEPARATE object =====
        sid = body.sessionId
        if not sid:
            sess = create_session(f"sess_{datetime.now().strftime('%Y%m%d%H%M%S')}_{id(datetime.now()) % 100000}", "collaboration")
            sid = sess["sessionId"]
            yield sse_event("session_created", {"sessionId": sid})

        previous_run_context = load_previous_run_context(sid) if sid else None

        # ===== Step 4: Build info from currentEvent only =====
        raw = current_event
        raw["originalInput"] = content_text or ""
        raw["contextPolicy"] = context_policy
        raw["fieldSources"] = field_sources
        info = _get_event_info(raw)
        info["fieldSources"] = field_sources
        info["contextPolicy"] = context_policy
        info["originalInput"] = content_text or ""

        run_id = f"run_{int(datetime.now().timestamp() * 1000)}"
        trace_id = f"trace_{run_id}"

        # Generate title from user query content — not from default roadName
        query_text = content_text or ""
        if info.get("nearbySchool") and "冲突" in query_text:
            title = "学校门口信号冲突研判"
        elif info.get("nearbySchool"):
            title = "学校周边交通研判"
        elif info.get("conflictIntent"):
            title = "交通冲突协同研判"
        elif any(w in query_text for w in ["信号", "绿灯", "配时"]):
            title = "信号灯协同研判"
        elif any(w in query_text for w in ["事故", "碰撞", "追尾"]):
            title = "交通事故协同研判"
        elif any(w in query_text for w in ["拥堵", "堵车", "排队"]):
            title = "拥堵路段协同研判"
        elif info.get("roadName") and "未命名" not in str(info.get("roadName", "")):
            title = f"{str(info.get('roadName', ''))[:12]}协同研判"
        else:
            # Fallback: first 16 chars of user query
            title = (query_text[:16] or "协同分析") + "协同研判"
        # Ensure 8-16 chars
        title = title[:20]

        # Save user message
        user_content = query_text[:100] or "协同分析请求"
        um_id = f"um_{int(datetime.now().timestamp() * 1000)}"
        add_message(um_id, sid, "user", user_content, "collaboration")
        # Generate title on first round only — never overwrite on subsequent rounds
        from backend.chat.chat_db import get_session
        sess_check = get_session(sid)
        if sess_check and (not sess_check.get("title") or sess_check.get("title") == "新对话"):
            update_session_title(sid, title[:20])

        routing = route_agents(info)
        selected = routing["selectedAgents"][:4]  # Cap at 4 agents

        degraded = False
        fallback_reason = ""
        fusion_summary = ""
        try:
            orchestrator = CollaborationOrchestrator()
            budget = ExecutionBudget(max_agents=4, max_agent_calls=2, max_retries=1, max_total_seconds=90)
            async for event_str in orchestrator.execute(
                run_id, sid, info, selected,
                routing.get("skippedAgents", []),
                routing.get("routingReasons", []), budget,
                previous_run_context=previous_run_context,
            ):
                # Capture fusionSummary from fusion_done event
                if 'event: fusion_done' in event_str:
                    import re as _re
                    match = _re.search(r'\"fusionSummary\":\s*\"([^\"]+)\"', event_str)
                    if match: fusion_summary = match.group(1)
                yield event_str
            # Orchestrator handles its own done event — wrapper does NOT send duplicate
        except Exception as e:
            # Non-retryable: don't silently fallback
            if any(kw in str(e) for kw in ["ValidationError", "缺少", "未注册", "非法"]):
                yield sse_error(str(e))
                return
            # System error: degraded fallback
            degraded = True; fallback_reason = str(e)
            yield sse_event("fallback_started", {"reason": fallback_reason, "fallbackFrom": "orchestrator"})
            async for ev in _legacy_analyze_stream_inner(body, sid):
                yield ev

        # Save assistant message with REAL fusion summary (not placeholder)
        assistant_content = fusion_summary or "协同分析已完成，请查看运行详情获取融合决策。"
        am_id = f"am_{int(datetime.now().timestamp() * 1000)}"
        add_message(am_id, sid, "assistant", assistant_content, "collaboration",
                    {"runId": run_id, "executionEngine": "orchestrator", "degraded": degraded, "fusionSummary": assistant_content})

    return StreamingResponse(agent_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _legacy_analyze_stream(body: RoutedStreamRequest):
    """旧协同分析实现。"""
    import asyncio as _asyncio
    async def agent_stream():
        async for ev in _legacy_analyze_stream_inner(body, body.sessionId):
            yield ev
    return StreamingResponse(agent_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _legacy_analyze_stream_inner(body: RoutedStreamRequest, sid: str):
    import asyncio as _asyncio
    if not sid:
        sess = create_session(f"sess_{datetime.now().strftime('%Y%m%d%H%M%S')}_{id(datetime.now()) % 100000}", "collaboration")
        sid = sess["sessionId"]
        yield sse_event("session_created", {"sessionId": sid})
    user_content = f"协同分析: {body.eventType} {body.roadName} {body.direction or ''}"
    title = f"{body.roadName}协同研判" if body.roadName != "未知路段" else "协同分析"
    update_session_title(sid, title[:20])
    um_id = f"um_{int(datetime.now().timestamp() * 1000)}"
    add_message(um_id, sid, "user", user_content, "collaboration")

    info = _get_event_info(body.model_dump())
    routing = route_agents(info)
    agents_order = [a for a in routing["selectedAgents"] if a != "ReportAgent"]

    yield sse_event("event_parse_start", {"text": "正在解析事件信息..."})
    await _asyncio.sleep(0.3)
    yield sse_event("event_parse_done", {"eventType": info.get("eventType"), "roadName": info.get("roadName")})
    yield sse_event("agent_route_done", {"selectedAgents": routing["selectedAgents"], "routingReasons": routing["routingReasons"]})

    from backend.agent.multi_agent import CongestionAgent, SignalAgent, DispatchAgent
    agent_map = {"CongestionAgent": CongestionAgent, "SignalAgent": SignalAgent, "DispatchAgent": DispatchAgent}
    all_results = []
    for name in agents_order:
        yield sse_event("agent_start", {"agentName": name, "text": f"{name} 正在分析..."})
        await _asyncio.sleep(0.3)
        cls = agent_map.get(name)
        if cls:
            result = cls().analyze(info)
            all_results.append(result)
            yield sse_event("agent_result", result)

    yield sse_event("conflict_check_start", {"text": "正在检测 Agent 建议冲突..."})
    conflicts = detect_conflicts(all_results)
    yield sse_event("conflict_check_done", {"conflicts": conflicts, "conflictCount": len(conflicts)})

    yield sse_event("fusion_start", {"text": "正在融合各 Agent 结论..."})
    fusion = f"综合 {len(all_results)} 个 Agent 的分析，核心风险为{'高' if routing['riskTriggers'] else '待评估'}。紧急度评估为{'高' if len(routing['riskTriggers']) >= 2 else '中'}。"
    if conflicts: fusion += f"检测到 {len(conflicts)} 个建议冲突，已按安全优先和急救通道优先原则融合处理。"
    for r in all_results:
        if r.get("suggestion"): fusion += f"[{r['agentName']}] {r['suggestion']}。"
    for chunk in _text_chunks(fusion):
        yield sse_event("fusion_delta", {"text": chunk})
        await _asyncio.sleep(0.03)
    yield sse_event("fusion_done", {"fusionSummary": fusion})

    am_id = f"am_{int(datetime.now().timestamp() * 1000)}"
    add_message(am_id, sid, "assistant", fusion, "collaboration",
                {"selectedAgents": routing["selectedAgents"], "conflictCount": len(conflicts)})
    yield sse_event("done", {"sessionId": sid, "assistantMessageId": am_id, "title": title[:20], "agentResults": all_results, "fusionSummary": fusion})


def _text_chunks(text: str, size: int = 6) -> list:
    if not text: return [""]
    chunks = []; start = 0
    for i, ch in enumerate(text):
        if ch in "。\n？！，；" and i - start >= size:
            chunks.append(text[start:i + 1]); start = i + 1
    if start < len(text): chunks.append(text[start:])
    return chunks if chunks else [text[i:i + size] for i in range(0, len(text), size)]


# -------------------- 健康检查 --------------------

@app.get("/health", summary="健康检查")
async def health():
    from backend.config import LLM_ENABLED, DEEPSEEK_MODEL
    from backend.rag.vector_store import _CHROMA_AVAILABLE
    from backend.rag.vector_store import get_collection_stats as rag_stats
    return {
        "status": "ok",
        "service": "TrafficMind Agent",
        "llmAvailable": LLM_ENABLED,
        "llmProvider": "DeepSeek" if LLM_ENABLED else None,
        "llmModel": DEEPSEEK_MODEL if LLM_ENABLED else None,
        "llmMode": "llm" if LLM_ENABLED else "template_fallback",
        "chromaAvailable": _CHROMA_AVAILABLE,
        "collaborationOrchestratorEnabled": COLLABORATION_ORCHESTRATOR_ENABLED,
        "collaborationProtocolVersion": "1.0",
        "collaborationRepositoryType": "sqlite",
        "collaborationFallbackEnabled": True,
    }


# -------------------- 仪表盘统计 --------------------

@app.get("/stats", summary="仪表盘统计数据")
async def stats():
    """
    返回仪表盘所需的聚合统计数据：
      - 总事件数 / 高风险事件数 / 平均风险分 / 待派单数
      - 风险等级分布 / 事件类型分布 / 状态分布
      - 近 7 天每日事件趋势
    """
    return get_stats()


# -------------------- Phase 9.3: 协作审计 API --------------------

@app.get("/collaboration/runs/{run_id}", summary="查询协作运行详情")
async def get_collaboration_run(run_id: str):
    """返回某次协作运行的完整审计记录。"""
    from backend.agent.collaboration.db_repository import SQLiteCollaborationRepository
    repo = SQLiteCollaborationRepository()
    run = repo.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} 不存在")
    return {
        "run": _safe_parse_json_fields(run),
        "tasks": [_safe_parse_json_fields(t) for t in _list_collab_tasks(run_id)],
        "messages": repo.list_messages(run_id),
        "conflicts": repo.list_conflicts(run_id),
        "events": repo.list_events(run_id),
    }


def _safe_parse_json_fields(d: dict) -> dict:
    """将 SQLite 中的 JSON 字符串字段解析为对象。"""
    json_fields = ["selected_agents", "skipped_agents", "failed_agents", "normalized_event",
                   "budget_usage", "final_decision", "depends_on", "input_snapshot",
                   "output_snapshot", "payload", "proposals"]
    for key in json_fields:
        if key in d and isinstance(d[key], str):
            try: d[key] = json.loads(d[key])
            except: pass
    return d


def _list_collab_tasks(run_id: str):
    from backend.agent.collaboration.db_repository import SQLiteCollaborationRepository
    repo = SQLiteCollaborationRepository()
    init_collab = __import__('backend.agent.collaboration.db_repository', fromlist=['init_collaboration_tables']).init_collaboration_tables
    init_collab()
    import sqlite3
    from backend.config import DB_PATH
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM collaboration_tasks WHERE run_id=?", (run_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/collaboration/sessions/{session_id}/runs", summary="查询会话的协作运行列表")
async def get_session_collaboration_runs(session_id: str):
    from backend.agent.collaboration.db_repository import SQLiteCollaborationRepository
    repo = SQLiteCollaborationRepository()
    init_collab = __import__('backend.agent.collaboration.db_repository', fromlist=['init_collaboration_tables']).init_collaboration_tables
    init_collab()
    import sqlite3
    from backend.config import DB_PATH
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM collaboration_runs WHERE session_id=? ORDER BY updated_at DESC", (session_id,)).fetchall()
    conn.close()
    return {"runs": [dict(r) for r in rows]}
