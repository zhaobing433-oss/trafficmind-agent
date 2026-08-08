"""
Agent Tools — Phase 13 模拟交通环境只读工具

Agent 只允许读取交通环境并生成 Action Proposal，
不得直接执行 apply_simulation_action。

所有改变模拟交通状态的 Action 必须经过：
  Workflow Risk Gate → Human Approval → Action Node

工具返回 Dict[str, Any]，与现有 ReAct TOOLS 注册模式兼容。
"""

from typing import Any, Dict, List, Optional

from backend.simulation.demo_provider import get_demo_provider
from backend.simulation.models import (
    TrafficSpatialContext,
    TrafficRoadState,
    TrafficCameraObservation,
)
from backend.simulation.demo_network import DEMO_NETWORK


# ═══════════════════════════════════════════════════════════════════════════════
# 只读工具函数（Agent 可调用）
# ═══════════════════════════════════════════════════════════════════════════════


def get_traffic_map_state(run_id: str = "", **kwargs) -> Dict[str, Any]:
    """获取当前仿真交通态势摘要。

    Agent 可用此工具了解整体交通状况，但不应接收完整路网 JSON。

    Returns:
        {run_id, snapshot_id, road_count, roads_summary,
         active_events, congestion_summary}
    """
    provider = get_demo_provider()
    try:
        snap = provider.get_snapshot(run_id)
    except (ValueError, KeyError):
        return {"error": f"Run '{run_id}' 不存在或无快照", "simulated": True}

    roads_summary = []
    congestion_count = {"normal": 0, "slow": 0, "congested": 0, "severe": 0}
    for rs in snap.road_states.values():
        congestion_count[rs.congestion_level.value] = \
            congestion_count.get(rs.congestion_level.value, 0) + 1
        roads_summary.append({
            "roadId": rs.road_id,
            "avgSpeed": rs.avg_speed,
            "queueLength": rs.queue_length,
            "congestionLevel": rs.congestion_level.value,
        })

    return {
        "runId": run_id,
        "snapshotId": snap.snapshot_id,
        "sequence": snap.sequence,
        "roadCount": len(snap.road_states),
        "roadsSummary": roads_summary,
        "activeEvents": snap.active_event_ids,
        "congestionSummary": congestion_count,
        "description": snap.description,
        "simulated": True,
    }


def get_road_traffic_state(run_id: str = "", road_id: str = "", **kwargs) -> Dict[str, Any]:
    """获取单条道路的交通状态。

    Args:
        run_id: 仿真运行 ID
        road_id: 道路 ID
    """
    if not road_id:
        return {"error": "缺少 road_id 参数"}
    provider = get_demo_provider()
    state = provider.get_road_state(run_id, road_id)
    if state is None:
        return {"error": f"道路 '{road_id}' 在 Run '{run_id}' 中无状态数据", "simulated": True}

    road = DEMO_NETWORK.get_road(road_id)
    return {
        "roadId": state.road_id,
        "roadName": road.name if road else "",
        "avgSpeed": state.avg_speed,
        "vehicleCount": state.vehicle_count,
        "flow": state.flow,
        "occupancy": state.occupancy,
        "queueLength": state.queue_length,
        "congestionLevel": state.congestion_level.value,
        "effectiveCapacity": state.effective_capacity,
        "freeFlowSpeed": road.free_flow_speed if road else 0,
        "capacity": road.capacity if road else 0,
        "simulated": True,
    }


def get_event_spatial_context(run_id: str = "", event_id: str = "", **kwargs) -> Dict[str, Any]:
    """获取事件的空间上下文。

    基于路网图结构计算 upstream/downstream/adjacent。

    Args:
        run_id: 仿真运行 ID
        event_id: 事件 ID
    """
    if not event_id:
        return {"error": "缺少 event_id 参数"}
    provider = get_demo_provider()
    try:
        ctx = provider.build_spatial_context(run_id, event_id)
    except ValueError as e:
        return {"error": str(e)}

    return _spatial_context_to_dict(ctx)


def get_nearby_cameras(
    run_id: str = "", longitude: float = 0.0, latitude: float = 0.0, **kwargs
) -> Dict[str, Any]:
    """获取指定位置附近的模拟摄像头。

    Args:
        run_id: 仿真运行 ID
        longitude: 经度
        latitude: 纬度
    """
    if not longitude or not latitude:
        return {"error": "缺少经纬度参数"}
    provider = get_demo_provider()
    cameras = DEMO_NETWORK.get_cameras_near_point(longitude, latitude, max_distance=0.02)
    result = []
    for cam in cameras:
        obs = provider.get_camera_observation(run_id, cam.camera_id)
        result.append({
            "cameraId": cam.camera_id,
            "name": cam.name,
            "longitude": cam.longitude,
            "latitude": cam.latitude,
            "roadId": cam.road_id,
            "vehicleCount": obs.vehicle_count,
            "avgSpeed": obs.avg_speed,
            "queueLength": obs.queue_length,
            "detectedEvents": obs.detected_events,
            "simulated": True,
        })
    return {"cameras": result, "count": len(result), "simulated": True}


def get_nearby_intersections(
    longitude: float = 0.0, latitude: float = 0.0, **kwargs
) -> Dict[str, Any]:
    """获取指定位置附近的路口。

    Args:
        longitude: 经度
        latitude: 纬度
    """
    if not longitude or not latitude:
        return {"error": "缺少经纬度参数"}
    intersections = DEMO_NETWORK.get_intersections_near_point(
        longitude, latitude, max_distance=0.015
    )
    result = []
    for inter in intersections:
        result.append({
            "intersectionId": inter.intersection_id,
            "name": inter.name,
            "longitude": inter.longitude,
            "latitude": inter.latitude,
            "connectedRoads": inter.connected_road_ids,
            "signalState": inter.signal_state,
        })
    return {"intersections": result, "count": len(result), "simulated": True}


def get_affected_roads(run_id: str = "", event_id: str = "", **kwargs) -> Dict[str, Any]:
    """获取受事件影响的路段及其状态。

    Args:
        run_id: 仿真运行 ID
        event_id: 事件 ID
    """
    if not event_id:
        return {"error": "缺少 event_id 参数"}
    provider = get_demo_provider()
    try:
        ctx = provider.build_spatial_context(run_id, event_id)
    except ValueError as e:
        return {"error": str(e)}

    affected = []
    if ctx.affected_road:
        rs = ctx.current_traffic_state.get(ctx.affected_road.road_id)
        affected.append({
            "roadId": ctx.affected_road.road_id,
            "name": ctx.affected_road.name,
            "relation": "affected",
            "avgSpeed": rs.avg_speed if rs else 0,
            "queueLength": rs.queue_length if rs else 0,
            "congestionLevel": rs.congestion_level.value if rs else "unknown",
        })
    for road in ctx.upstream_roads:
        rs = ctx.current_traffic_state.get(road.road_id)
        affected.append({
            "roadId": road.road_id,
            "name": road.name,
            "relation": "upstream",
            "avgSpeed": rs.avg_speed if rs else 0,
            "queueLength": rs.queue_length if rs else 0,
            "congestionLevel": rs.congestion_level.value if rs else "unknown",
        })
    for road in ctx.downstream_roads:
        rs = ctx.current_traffic_state.get(road.road_id)
        affected.append({
            "roadId": road.road_id,
            "name": road.name,
            "relation": "downstream",
            "avgSpeed": rs.avg_speed if rs else 0,
            "queueLength": rs.queue_length if rs else 0,
            "congestionLevel": rs.congestion_level.value if rs else "unknown",
        })

    return {"affectedRoads": affected, "count": len(affected), "simulated": True}


def get_simulation_snapshot(run_id: str = "", **kwargs) -> Dict[str, Any]:
    """获取完整仿真快照摘要。

    Agent 可用此工具获取当前交通全貌。
    """
    return get_traffic_map_state(run_id=run_id, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════════════


def _spatial_context_to_dict(ctx: TrafficSpatialContext) -> Dict[str, Any]:
    """将 TrafficSpatialContext 转为 Agent 友好的 dict。"""
    return {
        "event": {
            "eventId": ctx.event.event_id if ctx.event else "",
            "eventType": ctx.event.event_type if ctx.event else "",
            "severity": ctx.event.severity if ctx.event else "",
            "roadId": ctx.event.road_id if ctx.event else "",
            "description": ctx.event.description if ctx.event else "",
            "simulated": True,
        },
        "affectedRoad": {
            "roadId": ctx.affected_road.road_id,
            "name": ctx.affected_road.name,
            "lanes": ctx.affected_road.lanes,
            "capacity": ctx.affected_road.capacity,
        } if ctx.affected_road else None,
        "upstreamRoads": [
            {"roadId": r.road_id, "name": r.name} for r in ctx.upstream_roads
        ],
        "downstreamRoads": [
            {"roadId": r.road_id, "name": r.name} for r in ctx.downstream_roads
        ],
        "adjacentRoads": [
            {"roadId": r.road_id, "name": r.name} for r in ctx.adjacent_roads
        ],
        "nearbyIntersections": [
            {"intersectionId": i.intersection_id, "name": i.name}
            for i in ctx.nearby_intersections
        ],
        "nearbyCameras": [
            {"cameraId": c.camera_id, "name": c.name, "roadId": c.road_id}
            for c in ctx.nearby_cameras
        ],
        "currentTrafficState": {
            rid: {
                "avgSpeed": rs.avg_speed,
                "queueLength": rs.queue_length,
                "congestionLevel": rs.congestion_level.value,
            }
            for rid, rs in ctx.current_traffic_state.items()
        },
        "simulated": True,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Tool 注册清单（与 ReAct READONLY_TOOLS 兼容）
# ═══════════════════════════════════════════════════════════════════════════════

SIMULATION_READONLY_TOOLS: Dict[str, Dict[str, Any]] = {
    "get_traffic_map_state": {
        "description": "获取当前仿真交通态势摘要（拥堵分布、活跃事件、快照信息）",
        "params": {"run_id": "仿真运行 ID"},
        "fn": get_traffic_map_state,
    },
    "get_road_traffic_state": {
        "description": "获取单条道路的详细交通状态（速度、排队、占有率、通行能力）",
        "params": {"run_id": "仿真运行 ID", "road_id": "道路 ID"},
        "fn": get_road_traffic_state,
    },
    "get_event_spatial_context": {
        "description": "获取事件的空间上下文（受影响路段、上下游、附近路口和摄像头）",
        "params": {"run_id": "仿真运行 ID", "event_id": "事件 ID"},
        "fn": get_event_spatial_context,
    },
    "get_nearby_cameras": {
        "description": "获取指定位置附近的模拟摄像头实时观测",
        "params": {"run_id": "仿真运行 ID", "longitude": "经度", "latitude": "纬度"},
        "fn": get_nearby_cameras,
    },
    "get_nearby_intersections": {
        "description": "获取指定位置附近的路口信息",
        "params": {"longitude": "经度", "latitude": "纬度"},
        "fn": get_nearby_intersections,
    },
    "get_affected_roads": {
        "description": "获取受事件影响的所有路段（受影响、上游、下游）及状态",
        "params": {"run_id": "仿真运行 ID", "event_id": "事件 ID"},
        "fn": get_affected_roads,
    },
    "get_simulation_snapshot": {
        "description": "获取完整仿真快照摘要（同 get_traffic_map_state）",
        "params": {"run_id": "仿真运行 ID"},
        "fn": get_simulation_snapshot,
    },
}
