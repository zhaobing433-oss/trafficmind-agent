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
# Phase 13 Round 2: Workflow Bridge
# ═══════════════════════════════════════════════════════════════════════════════


class StartWorkflowRequest(BaseModel):
    """启动 Workflow Bridge 请求。"""
    eventId: str = ""
    sessionId: str = ""

    model_config = ConfigDict(extra="allow")


@router.post("/simulations/{run_id}/workflow", summary="启动 TrafficMind 研判 (Workflow Bridge)")
async def start_workflow_for_simulation(run_id: str, body: StartWorkflowRequest):
    """为仿真事件创建 Workflow Run。

    约束：
      - 防重复：同一 simulationRunId + trafficEventId 已有 active Workflow 时拒绝
      - current_event 仅保存事件事实
      - simulation_refs 独立保存
      - 返回 workflow_run_id 供前端关联
    """
    from backend.workflow.executor import get_executor
    from backend.workflow.repository import SQLiteWorkflowRepository

    run_data = _repo.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")

    event_id = body.eventId
    if not event_id:
        raise HTTPException(status_code=400, detail="缺少 eventId")

    # 获取空间上下文
    try:
        ctx = _provider.build_spatial_context(run_id, event_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 防重复：检查是否已有 active Workflow
    import sqlite3 as _sq
    import backend.config as _cfg
    conn = _sq.connect(_cfg.DB_PATH)
    conn.row_factory = _sq.Row
    active_statuses = ("pending", "running", "paused", "awaiting_approval")
    placeholders = ",".join("?" * len(active_statuses))
    rows = conn.execute(
        f"""SELECT wr.run_id, wr.state_json FROM workflow_runs wr
            WHERE wr.status IN ({placeholders})
            ORDER BY wr.updated_at DESC""",
        active_statuses,
    ).fetchall()
    conn.close()

    import json as _json
    for row in rows:
        try:
            state_raw = row["state_json"]
            if isinstance(state_raw, str):
                state = _json.loads(state_raw)
            else:
                state = state_raw or {}
            sim_refs = state.get("simulationRefs", state.get("simulation_refs", {}))
            if sim_refs.get("simulationRunId") == run_id and sim_refs.get("trafficEventId") == event_id:
                raise HTTPException(
                    status_code=409,
                    detail=f"该事件已有活跃 Workflow: {row['run_id']}。请等待其完成后重试。",
                )
        except HTTPException:
            raise
        except Exception:
            continue

    # 获取当前快照
    snap = _provider.get_snapshot(run_id)

    # 构建 current_event（仅事件事实）
    affected_road = ctx.affected_road
    event_road_id = ctx.event.road_id if ctx.event else ""
    ts = ctx.current_traffic_state.get(event_road_id)
    avg_speed = ts.avg_speed if ts else 0
    queue_len = ts.queue_length if ts else 0
    current_event = {
        "eventId": ctx.event.event_id if ctx.event else event_id,
        "eventType": ctx.event.event_type if ctx.event else "accident",
        "roadName": affected_road.name if affected_road else "",
        "avgSpeed": avg_speed,
        "queueLength": queue_len,
        "duration": 0,
        "description": ctx.event.description if ctx.event else "",
        "simulated": True,
    }

    # 构建 simulation_refs（独立于 current_event）
    simulation_refs = {
        "simulationRunId": run_id,
        "trafficEventId": event_id,
        "decisionSnapshotId": snap.snapshot_id,
        "latestSnapshotId": snap.snapshot_id,
        "spatialContextRef": {
            "simulationRunId": run_id,
            "trafficEventId": event_id,
            "snapshotId": snap.snapshot_id,
        },
    }

    # 启动 Workflow（simulation_refs 通过 _simulation_refs 元数据传递）
    initial_event_with_refs = dict(current_event)
    initial_event_with_refs["_simulation_refs"] = simulation_refs

    executor = get_executor()

    async def _stream():
        try:
            async for sse_str in executor.start(
                definition_id="simulation_bridge",
                session_id=body.sessionId or "",
                event_thread_id="",
                initial_event=initial_event_with_refs,
                triggered_by="simulation",
            ):
                yield sse_str
        except Exception as e:
            import traceback
            traceback.print_exc()
            from backend.agent.streaming import sse_error as _sse_err, sse_event as _sse_evt
            yield _sse_err(str(e).split("\n")[0][:200])
            yield _sse_evt("done", {"error": True})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SSE 流式端点
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
