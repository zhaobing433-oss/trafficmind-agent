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


# -------------------- 健康检查 --------------------

@app.get("/health", summary="健康检查")
async def health():
    return {"status": "ok", "service": "TrafficMind Agent"}


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
