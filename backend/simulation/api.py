"""
Simulation API Router — Phase 13

REST + SSE 端点，遵循现有 workflow/api.py 风格。

端点:
  GET    /traffic-map/scenarios
  POST   /traffic-map/simulations
  GET    /traffic-map/simulations/{runId}
  GET    /traffic-map/simulations/{runId}/network
  GET    /traffic-map/simulations/{runId}/snapshot
  GET    /traffic-map/simulations/{runId}/snapshots
  GET    /traffic-map/simulations/{runId}/spatial-context
  GET    /traffic-map/simulations/{runId}/road/{roadId}/state
  GET    /traffic-map/simulations/{runId}/camera/{cameraId}
  POST   /traffic-map/simulations/{runId}/events
  POST   /traffic-map/simulations/{runId}/reset
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from backend.agent.streaming import sse_event, sse_error
from backend.simulation.models import (
    TrafficEvent,
    TrafficSimulationAction,
    TrafficSimulationRun,
    TrafficSnapshot,
    SimulationStatus,
    ActionType,
    EventStatus,
    SimulationContext,
    generate_event_id,
    generate_action_id,
)
from backend.simulation.demo_provider import get_demo_provider
from backend.simulation.repository import (
    SQLiteSimulationRepository,
    init_simulation_tables,
)
from backend.simulation.tools import _spatial_context_to_dict

# ═══════════════════════════════════════════════════════════════════════════════
# Router
# ═══════════════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/traffic-map", tags=["Traffic Map Simulation V1"])

init_simulation_tables()

_repo = SQLiteSimulationRepository()
_provider = get_demo_provider()


# ═══════════════════════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════════════════════


class CreateSimulationRequest(BaseModel):
    """创建仿真运行请求。"""
    scenarioId: str = "scenario_c_accident"
    sessionId: str = ""

    model_config = ConfigDict(extra="allow")


class InjectEventRequest(BaseModel):
    """注入模拟事件请求。"""
    eventType: str = "accident"
    severity: str = "high"
    roadId: str = "R01"
    intersectionId: str = ""
    longitude: float = 116.397
    latitude: float = 39.907
    description: str = ""

    model_config = ConfigDict(extra="allow")


class SpatialContextQuery(BaseModel):
    """空间上下文查询参数。"""
    eventId: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/scenarios", summary="列出预设仿真场景")
async def list_scenarios():
    """列出所有可用预设场景。"""
    scenarios = _provider.list_scenarios()
    return {
        "total": len(scenarios),
        "scenarios": [s.model_dump() for s in scenarios],
    }


@router.post("/simulations", summary="创建仿真运行")
async def create_simulation(body: CreateSimulationRequest):
    """创建新的仿真运行实例，返回初始状态。"""
    run = _provider.create_run(body.scenarioId)
    run.session_id = body.sessionId

    # 持久化
    _repo.save_run(run)

    # 初始快照也持久化
    snap = _provider.get_snapshot(run.run_id)
    _repo.save_snapshot(snap)

    return {
        "run": run.model_dump(),
        "network": _provider.get_network(run.run_id),
        "snapshot": snap.model_dump(),
        "description": "仿真已创建。路网处于正常状态。",
    }


@router.get("/simulations/{run_id}", summary="查询仿真运行详情")
async def get_simulation(run_id: str):
    """查询仿真运行的完整状态。"""
    run_data = _repo.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")

    try:
        snap = _provider.get_snapshot(run_id)
    except ValueError:
        snap = None

    events = _repo.list_run_events(run_id)
    actions = _repo.list_run_actions(run_id)
    db_snapshots = _repo.list_run_snapshots(run_id)

    return {
        "run": run_data,
        "snapshot": snap.model_dump() if snap else None,
        "events": events,
        "actions": actions,
        "snapshots": [
            {k: v for k, v in s.items() if k not in ("road_states_json", "intersection_states_json")}
            for s in db_snapshots
        ],
        "snapshotCount": len(db_snapshots),
        "eventCount": len(events),
    }


@router.get("/simulations/{run_id}/network", summary="获取路网 GeoJSON")
async def get_network(run_id: str):
    """获取 Demo 路网的 GeoJSON FeatureCollection。"""
    run_data = _repo.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")
    return _provider.get_network(run_id)


@router.get("/simulations/{run_id}/snapshot", summary="获取当前交通快照")
async def get_current_snapshot(run_id: str):
    """获取最新交通状态快照。"""
    run_data = _repo.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")
    try:
        snap = _provider.get_snapshot(run_id)
    except ValueError:
        raise HTTPException(status_code=500, detail="无可用快照")
    return snap.model_dump()


@router.get("/simulations/{run_id}/snapshots", summary="获取全部快照列表")
async def list_snapshots(run_id: str):
    """获取全部快照（append-only 顺序）。"""
    run_data = _repo.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")

    db_snapshots = _repo.list_run_snapshots(run_id)
    provider_snaps = _provider.get_all_snapshots(run_id)

    return {
        "runId": run_id,
        "snapshots": [
            {
                "snapshotId": s.snapshot_id,
                "sequence": s.sequence,
                "timestamp": s.timestamp,
                "description": s.description,
                "activeEventIds": s.active_event_ids,
                "roadCount": len(s.road_states),
            }
            for s in provider_snaps
        ],
        "count": len(provider_snaps),
        "dbCount": len(db_snapshots),
    }


@router.get("/simulations/{run_id}/road/{road_id}/state", summary="获取单条道路状态")
async def get_road_state(run_id: str, road_id: str):
    """获取单条道路当前交通状态。"""
    state = _provider.get_road_state(run_id, road_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Road '{road_id}' 无状态数据")
    return state.model_dump()


@router.get("/simulations/{run_id}/camera/{camera_id}", summary="获取模拟摄像头观测")
async def get_camera_observation(run_id: str, camera_id: str):
    """获取模拟摄像头当前观测数据。"""
    try:
        obs = _provider.get_camera_observation(run_id, camera_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return obs.model_dump()


@router.get("/simulations/{run_id}/spatial-context", summary="获取事件空间上下文")
async def get_spatial_context(run_id: str, eventId: str = Query(..., description="事件 ID")):
    """基于路网图计算事件的空间上下文。"""
    try:
        ctx = _provider.build_spatial_context(run_id, eventId)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _spatial_context_to_dict(ctx)


@router.post("/simulations/{run_id}/events", summary="注入模拟交通事件")
async def inject_event(run_id: str, body: InjectEventRequest):
    """注入模拟交通事件，产生新快照。

    事件注入后：受影响路段 capacity 下降、speed 下降、queue 增长。
    新快照 append-only，不覆盖历史。
    """
    run_data = _repo.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")

    event_id = generate_event_id()
    event = TrafficEvent(
        event_id=event_id,
        event_type=body.eventType,
        severity=body.severity,
        road_id=body.roadId,
        intersection_id=body.intersectionId,
        longitude=body.longitude,
        latitude=body.latitude,
        description=body.description or f"{body.eventType} on {body.roadId}",
        status="active",
        simulated=True,
    )

    # 持久化事件 (with run_id for FK constraint)
    _repo.save_event(event, run_id=run_id)

    # 注入 → 产生新快照
    new_snap = _provider.inject_event(run_id, event)

    # 持久化新快照
    _repo.save_snapshot(new_snap)
    _repo.update_run_status(
        run_id, run_data["status"],
        current_snapshot_id=new_snap.snapshot_id,
        snapshot_count=run_data.get("snapshot_count", 0) + 1,
    )

    # 构建 before/after 对比
    all_snaps = _provider.get_all_snapshots(run_id)
    before_snap = all_snaps[-2] if len(all_snaps) >= 2 else None
    before_state = {}
    if before_snap and body.roadId in before_snap.road_states:
        rs = before_snap.road_states[body.roadId]
        before_state = {
            "avgSpeed": rs.avg_speed,
            "queueLength": rs.queue_length,
            "congestionLevel": rs.congestion_level.value,
        }

    after_state = {}
    if body.roadId in new_snap.road_states:
        rs = new_snap.road_states[body.roadId]
        after_state = {
            "avgSpeed": rs.avg_speed,
            "queueLength": rs.queue_length,
            "congestionLevel": rs.congestion_level.value,
        }

    return {
        "event": event.model_dump(),
        "snapshot": new_snap.model_dump(),
        "beforeState": before_state,
        "afterState": after_state,
        "impact": {
            "speedDelta": round(after_state.get("avgSpeed", 0) - before_state.get("avgSpeed", 0), 1),
            "queueDelta": round(after_state.get("queueLength", 0) - before_state.get("queueLength", 0), 0),
        },
    }


@router.post("/simulations/{run_id}/reset", summary="重置仿真运行")
async def reset_simulation(run_id: str):
    """重置仿真到初始状态。"""
    run_data = _repo.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")

    run = _provider.reset_run(run_id)
    _repo.save_run(run)

    snap = _provider.get_snapshot(run_id)
    _repo.save_snapshot(snap)

    return {
        "run": run.model_dump(),
        "snapshot": snap.model_dump(),
        "description": "仿真已重置到初始状态。",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SSE 流式端点（预留：后续 Action 执行 + Workflow 集成）
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/simulations/{run_id}/stream", summary="仿真状态 SSE 流")
async def simulation_stream(run_id: str):
    """SSE 流式推送仿真状态更新（预留）。"""
    run_data = _repo.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")

    async def _stream():
        try:
            snap = _provider.get_snapshot(run_id)
            yield sse_event("snapshot_current", snap.model_dump())
            yield sse_event("done", {"runId": run_id})
        except Exception as e:
            yield sse_error(str(e))

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
