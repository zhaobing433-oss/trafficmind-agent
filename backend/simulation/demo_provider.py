"""
DemoSimulationProvider — Phase 13 V1 确定性演示仿真引擎

纯领域实现，不依赖 FastAPI / Workflow / Agent / React。

设计原则：
  - 完全确定性：同一初始状态 + 同一 Action → 同一结果
  - Snapshot append-only，不覆盖历史
  - 规则简单可测试，非精确交通工程仿真
  - simulation=True 全程标记
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional

from backend.simulation.models import (
    TrafficSimulationRun,
    TrafficSimulationAction,
    TrafficSnapshot,
    TrafficRoadState,
    TrafficSpatialContext,
    TrafficCameraObservation,
    TrafficMapScenario,
    TrafficEvent,
    TrafficIntersection,
    TrafficRoadSegment,
    TrafficCameraSensor,
    SimulationStatus,
    CongestionLevel,
    ActionType,
    EventStatus,
    generate_run_id,
    generate_snapshot_id,
    generate_event_id,
)
from backend.simulation.provider import TrafficSimulationProvider
from backend.simulation.demo_network import DEMO_NETWORK, DemoNetwork


# ═══════════════════════════════════════════════════════════════════════════════
# 确定性默认状态
# ═══════════════════════════════════════════════════════════════════════════════

# 正常路段默认参数
NORMAL_DEFAULTS = {
    "avg_speed": 35.0,
    "vehicle_count": 45,
    "flow": 900.0,
    "occupancy": 0.35,
    "queue_length": 30.0,
    "congestion_level": CongestionLevel.NORMAL,
}


def _compute_default_road_state(road: TrafficRoadSegment) -> TrafficRoadState:
    """根据路段属性计算默认正常状态。"""
    ratio = road.capacity / 1200.0  # 相对标准容量
    return TrafficRoadState(
        road_id=road.road_id,
        avg_speed=min(road.free_flow_speed * 0.7, 50.0),
        vehicle_count=int(45 * ratio),
        flow=float(road.capacity * 0.5),
        occupancy=0.35,
        queue_length=30.0,
        congestion_level=CongestionLevel.NORMAL,
        effective_capacity=float(road.capacity),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 确定性事件注入规则
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_accident_effect(
    state: TrafficRoadState,
    road: TrafficRoadSegment,
    severity: str,
) -> TrafficRoadState:
    """事故对路段状态的影响（确定性规则）。

    severe ("critical"): capacity × 0.15
    medium ("high"):    capacity × 0.25
    light ("medium"):   capacity × 0.40
    """
    if severity == "critical":
        capacity_mult = 0.15
        speed_mult = 0.18
        queue_add = 300.0
        occupancy_set = 0.92
        congestion = CongestionLevel.SEVERE
    elif severity == "high":
        capacity_mult = 0.25
        speed_mult = 0.30
        queue_add = 200.0
        occupancy_set = 0.85
        congestion = CongestionLevel.SEVERE
    elif severity == "medium":
        capacity_mult = 0.40
        speed_mult = 0.50
        queue_add = 120.0
        occupancy_set = 0.72
        congestion = CongestionLevel.CONGESTED
    else:  # low
        capacity_mult = 0.60
        speed_mult = 0.70
        queue_add = 60.0
        occupancy_set = 0.55
        congestion = CongestionLevel.SLOW

    effective_cap = road.capacity * capacity_mult
    return TrafficRoadState(
        road_id=state.road_id,
        avg_speed=round(road.free_flow_speed * speed_mult, 1),
        vehicle_count=int(state.vehicle_count * 1.5) + 30,
        flow=round(effective_cap, 1),
        occupancy=occupancy_set,
        queue_length=round(state.queue_length + queue_add, 0),
        congestion_level=congestion,
        effective_capacity=round(effective_cap, 1),
    )


def _apply_congestion_effect(
    state: TrafficRoadState,
    road: TrafficRoadSegment,
    severity: str,
) -> TrafficRoadState:
    """拥堵事件对路段状态的影响。"""
    if severity in ("critical", "high"):
        speed_mult = 0.25
        capacity_mult = 0.30
        queue_add = 250.0
        congestion = CongestionLevel.SEVERE
    elif severity == "medium":
        speed_mult = 0.45
        capacity_mult = 0.50
        queue_add = 150.0
        congestion = CongestionLevel.CONGESTED
    else:
        speed_mult = 0.65
        capacity_mult = 0.70
        queue_add = 80.0
        congestion = CongestionLevel.SLOW

    effective_cap = road.capacity * capacity_mult
    return TrafficRoadState(
        road_id=state.road_id,
        avg_speed=round(road.free_flow_speed * speed_mult, 1),
        vehicle_count=int(state.vehicle_count * 1.4) + 25,
        flow=round(effective_cap, 1),
        occupancy=round(0.35 + (1 - capacity_mult) * 0.5, 2),
        queue_length=round(state.queue_length + queue_add, 0),
        congestion_level=congestion,
        effective_capacity=round(effective_cap, 1),
    )


EVENT_EFFECTS = {
    "accident": _apply_accident_effect,
    "congestion": _apply_congestion_effect,
    "construction": _apply_congestion_effect,   # 施工 = 拥堵相似
    "vehicle_stopped": _apply_accident_effect,  # 车辆滞留 = 事故相似
}


# ═══════════════════════════════════════════════════════════════════════════════
# 确定性动作规则
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_diversion_action(
    road_states: Dict[str, TrafficRoadState],
    roads: Dict[str, TrafficRoadSegment],
    action: TrafficSimulationAction,
) -> Dict[str, TrafficRoadState]:
    """分流动作：source road 状态改善，target roads 分担流量。

    diversionRatio 参数控制分流比例，默认 0.4。
    """
    result = deepcopy(road_states)
    ratio = action.parameters.get("diversionRatio", 0.4)

    # Source road: 恢复 capacity
    source_road_id = action.target_ids[0] if action.target_ids else ""
    if source_road_id in result and source_road_id in roads:
        src = result[source_road_id]
        src_road = roads[source_road_id]
        recovery = 0.4 + ratio * 0.5  # 恢复程度取决于分流比例
        new_cap = src_road.capacity * (src.effective_capacity / max(1, src_road.capacity) + recovery * 0.6)
        new_cap = min(new_cap, src_road.capacity * 0.85)
        result[source_road_id] = TrafficRoadState(
            road_id=src.road_id,
            avg_speed=round(src.avg_speed * (1.0 + ratio * 1.2), 1),
            vehicle_count=max(20, int(src.vehicle_count * (1.0 - ratio))),
            flow=round(new_cap, 1),
            occupancy=round(max(0.2, src.occupancy - ratio * 0.35), 2),
            queue_length=round(max(15.0, src.queue_length * (1.0 - ratio * 0.5)), 0),
            congestion_level=_determine_congestion_level(
                round(src.avg_speed * (1.0 + ratio * 1.2), 1),
                round(max(15.0, src.queue_length * (1.0 - ratio * 0.5)), 0),
            ),
            effective_capacity=round(new_cap, 1),
        )

    # Target roads: 增加流量
    for i, target_id in enumerate(action.target_ids[1:], start=1):
        if target_id in result and target_id in roads:
            tgt = result[target_id]
            tgt_road = roads[target_id]
            share = ratio / max(1, len(action.target_ids) - 1)
            result[target_id] = TrafficRoadState(
                road_id=tgt.road_id,
                avg_speed=round(max(5.0, tgt.avg_speed * (1.0 - share * 0.6)), 1),
                vehicle_count=int(tgt.vehicle_count * (1.0 + share * 0.4)),
                flow=round(tgt.flow * (1.0 + share * 0.3), 1),
                occupancy=round(min(0.95, tgt.occupancy + share * 0.2), 2),
                queue_length=round(tgt.queue_length + share * 50, 0),
                congestion_level=_determine_congestion_level(
                    round(max(5.0, tgt.avg_speed * (1.0 - share * 0.6)), 1),
                    round(tgt.queue_length + share * 50, 0),
                ),
                effective_capacity=tgt.effective_capacity,
            )

    return result


def _apply_signal_adjustment(
    road_states: Dict[str, TrafficRoadState],
    roads: Dict[str, TrafficRoadSegment],
    intersection_states: Dict[str, str],
    action: TrafficSimulationAction,
) -> Dict[str, TrafficRoadState]:
    """信号配时调整：指定方向绿灯延长，改善该方向通行。"""
    result = deepcopy(road_states)
    green_extension = action.parameters.get("greenExtensionSeconds", 15)
    direction = action.parameters.get("direction", "")

    improvement = min(0.3, green_extension / 60.0)  # 最多改善 30%

    for road_id in action.target_ids:
        if road_id in result and road_id in roads:
            r = result[road_id]
            result[road_id] = TrafficRoadState(
                road_id=r.road_id,
                avg_speed=round(r.avg_speed * (1.0 + improvement * 0.5), 1),
                vehicle_count=int(r.vehicle_count * (1.0 - improvement * 0.2)),
                flow=round(r.flow * (1.0 + improvement * 0.3), 1),
                occupancy=round(max(0.15, r.occupancy - improvement * 0.15), 2),
                queue_length=round(max(10.0, r.queue_length * (1.0 - improvement * 0.4)), 0),
                congestion_level=_determine_congestion_level(
                    round(r.avg_speed * (1.0 + improvement * 0.5), 1),
                    round(max(10.0, r.queue_length * (1.0 - improvement * 0.4)), 0),
                ),
                effective_capacity=r.effective_capacity,
            )

    # Update intersection signal state
    intersection_id = action.parameters.get("intersectionId", "")
    if intersection_id and intersection_id in intersection_states:
        intersection_states[intersection_id] = "adjusted"

    return result


def _determine_congestion_level(avg_speed: float, queue_length: float) -> CongestionLevel:
    """确定性拥堵等级判定。"""
    if avg_speed < 8 or queue_length > 250:
        return CongestionLevel.SEVERE
    elif avg_speed < 18 or queue_length > 150:
        return CongestionLevel.CONGESTED
    elif avg_speed < 28 or queue_length > 80:
        return CongestionLevel.SLOW
    return CongestionLevel.NORMAL


ACTION_HANDLERS = {
    ActionType.TRAFFIC_DIVERSION: _apply_diversion_action,
    ActionType.SIGNAL_ADJUSTMENT: _apply_signal_adjustment,
}


# ═══════════════════════════════════════════════════════════════════════════════
# DemoSimulationProvider
# ═══════════════════════════════════════════════════════════════════════════════


class DemoSimulationProvider(TrafficSimulationProvider):
    """确定性 Demo 仿真提供者。

    所有规则确定可测试。
    同一 (initial_state, action_sequence) → 同一结果。
    """

    def __init__(self, network: DemoNetwork | None = None):
        self._network = network or DEMO_NETWORK
        # In-memory 存储 (生产用 SQLite repository 作为持久化层)
        self._runs: Dict[str, TrafficSimulationRun] = {}
        self._snapshots: Dict[str, list[TrafficSnapshot]] = {}  # run_id → append-only list
        self._events: Dict[str, Dict[str, TrafficEvent]] = {}   # run_id → {event_id: event}
        self._actions: Dict[str, list[TrafficSimulationAction]] = {}

    # ── 持久化恢复 ────────────────────────────────────────────────────────

    def _ensure_run_loaded(self, run_id: str) -> TrafficSimulationRun:
        """确保 Run 已在 Provider 内存中。若不存在，从 Repository 恢复。

        Backend 重启后 Provider 内存清空，但 Repository 仍有持久化数据。
        通过此方法在首次访问时自动从 DB 恢复 in-memory state。
        """
        if run_id in self._runs:
            return self._runs[run_id]

        # 从 Repository 恢复
        from backend.simulation.repository import SQLiteSimulationRepository
        repo = SQLiteSimulationRepository()
        db_run = repo.get_run(run_id)
        if db_run is None:
            raise ValueError(f"Run '{run_id}' 不存在")

        # 恢复 Run
        status_raw = db_run.get("status", "created")
        try:
            status = SimulationStatus(status_raw)
        except ValueError:
            status = SimulationStatus.CREATED

        run = TrafficSimulationRun(
            run_id=run_id,
            scenario_id=db_run.get("scenario_id", ""),
            status=status,
            current_snapshot_id=db_run.get("current_snapshot_id", ""),
            snapshot_count=db_run.get("snapshot_count", 0),
            session_id=db_run.get("session_id", ""),
            created_at=db_run.get("created_at", ""),
        )
        self._runs[run_id] = run
        self._actions[run_id] = []

        # 恢复 Snapshots
        db_snaps = repo.list_run_snapshots(run_id)
        snaps: list[TrafficSnapshot] = []
        for s_raw in db_snaps:
            import json as _json
            road_states_raw = s_raw.get("road_states_json", "{}")
            if isinstance(road_states_raw, str):
                road_states_raw = _json.loads(road_states_raw)
            intersection_raw = s_raw.get("intersection_states_json", "{}")
            if isinstance(intersection_raw, str):
                intersection_raw = _json.loads(intersection_raw)
            active_ids_raw = s_raw.get("active_event_ids_json", "[]")
            if isinstance(active_ids_raw, str):
                active_ids_raw = _json.loads(active_ids_raw)

            road_states: dict = {}
            for rid, rs_dict in road_states_raw.items():
                road_states[rid] = TrafficRoadState(**rs_dict)

            snap = TrafficSnapshot(
                snapshot_id=s_raw["snapshot_id"],
                run_id=run_id,
                sequence=s_raw["sequence"],
                timestamp=s_raw.get("timestamp", ""),
                road_states=road_states,
                intersection_states=intersection_raw,
                active_event_ids=active_ids_raw,
                description=s_raw.get("description", ""),
            )
            snaps.append(snap)
        self._snapshots[run_id] = snaps

        # 恢复 Events
        db_events = repo.list_run_events(run_id)
        events: dict = {}
        for e_raw in db_events:
            evt = TrafficEvent(
                event_id=e_raw["event_id"],
                event_type=e_raw.get("event_type", ""),
                severity=e_raw.get("severity", "medium"),
                road_id=e_raw.get("road_id", ""),
                intersection_id=e_raw.get("intersection_id", ""),
                longitude=float(e_raw.get("longitude", 0)),
                latitude=float(e_raw.get("latitude", 0)),
                description=e_raw.get("description", ""),
                started_at=e_raw.get("started_at", ""),
                status=e_raw.get("status", "active"),
                simulated=bool(e_raw.get("simulated", True)),
            )
            events[evt.event_id] = evt
        self._events[run_id] = events

        return run

    # ── 生命周期 ──────────────────────────────────────────────────────────

    def create_run(self, scenario_id: str) -> TrafficSimulationRun:
        run_id = generate_run_id()
        run = TrafficSimulationRun(
            run_id=run_id,
            scenario_id=scenario_id,
            status=SimulationStatus.CREATED,
        )
        self._runs[run_id] = run
        self._snapshots[run_id] = []
        self._events[run_id] = {}
        self._actions[run_id] = []

        # 创建初始快照 (snapshot 0)
        initial = self._build_initial_snapshot(run_id)
        self._snapshots[run_id].append(initial)
        run.current_snapshot_id = initial.snapshot_id
        run.snapshot_count = 1
        run.status = SimulationStatus.RUNNING

        return run

    def reset_run(self, run_id: str) -> TrafficSimulationRun:
        self._ensure_run_loaded(run_id)
        if run_id not in self._runs:
            raise ValueError(f"Run '{run_id}' 不存在")

        run = self._runs[run_id]
        self._snapshots[run_id] = []
        self._events[run_id] = {}
        self._actions[run_id] = []

        initial = self._build_initial_snapshot(run_id)
        self._snapshots[run_id].append(initial)
        run.current_snapshot_id = initial.snapshot_id
        run.snapshot_count = 1
        run.status = SimulationStatus.RESET

        return run

    # ── 路网查询 ──────────────────────────────────────────────────────────

    def get_network(self, run_id: str) -> Dict[str, Any]:
        """返回 Demo 路网 GeoJSON。"""
        return self._network.to_geojson()

    # ── 快照查询 ──────────────────────────────────────────────────────────

    def get_snapshot(self, run_id: str) -> TrafficSnapshot:
        self._ensure_run_loaded(run_id)
        snaps = self._snapshots.get(run_id, [])
        if not snaps:
            raise ValueError(f"Run '{run_id}' 无快照")
        return snaps[-1]

    def get_snapshot_by_id(self, run_id: str, snapshot_id: str) -> Optional[TrafficSnapshot]:
        self._ensure_run_loaded(run_id)
        snaps = self._snapshots.get(run_id, [])
        for s in snaps:
            if s.snapshot_id == snapshot_id:
                return s
        return None

    def get_all_snapshots(self, run_id: str) -> list[TrafficSnapshot]:
        """获取全部快照列表（append-only 顺序）。"""
        self._ensure_run_loaded(run_id)
        return list(self._snapshots.get(run_id, []))

    # ── 道路/路口/摄像头状态 ──────────────────────────────────────────────

    def get_road_state(self, run_id: str, road_id: str) -> Optional[TrafficRoadState]:
        self._ensure_run_loaded(run_id)
        snap = self.get_snapshot(run_id)
        return snap.road_states.get(road_id)

    def get_intersection_state(self, run_id: str, intersection_id: str) -> Optional[str]:
        self._ensure_run_loaded(run_id)
        snap = self.get_snapshot(run_id)
        return snap.intersection_states.get(intersection_id)

    def get_camera_observation(self, run_id: str, camera_id: str) -> TrafficCameraObservation:
        self._ensure_run_loaded(run_id)
        camera = self._network.get_camera(camera_id)
        if not camera:
            raise ValueError(f"Camera '{camera_id}' 不存在")

        road_state = self.get_road_state(run_id, camera.road_id)
        active_events = []
        run_events = self._events.get(run_id, {})
        for eid, evt in run_events.items():
            if evt.road_id == camera.road_id and evt.status == "active":
                active_events.append(eid)

        return TrafficCameraObservation(
            camera_id=camera_id,
            vehicle_count=road_state.vehicle_count if road_state else 0,
            avg_speed=road_state.avg_speed if road_state else 0.0,
            queue_length=road_state.queue_length if road_state else 0.0,
            detected_events=active_events,
            simulated=True,
        )

    # ── 事件注入 ──────────────────────────────────────────────────────────

    def inject_event(self, run_id: str, event: TrafficEvent) -> TrafficSnapshot:
        """注入事件，产生新快照。"""
        self._ensure_run_loaded(run_id)
        current = self.get_snapshot(run_id)
        new_states = deepcopy(current.road_states)
        new_intersection = deepcopy(current.intersection_states)

        # 应用到受影响路段
        road = self._network.get_road(event.road_id)
        if road and event.road_id in new_states:
            effect_fn = EVENT_EFFECTS.get(event.event_type)
            if effect_fn:
                new_states[event.road_id] = effect_fn(
                    new_states[event.road_id], road, event.severity
                )

        # 存储事件
        if run_id in self._events:
            self._events[run_id][event.event_id] = event

        # 创建新快照
        new_snap = self._append_snapshot(
            run_id, new_states, new_intersection,
            list(self._events.get(run_id, {}).keys()),
            description=f"事件注入: {event.event_type} on {event.road_id} (severity={event.severity})",
        )
        return new_snap

    # ── 空间上下文 ──────────────────────────────────────────────────────────

    def build_spatial_context(self, run_id: str, event_id: str) -> TrafficSpatialContext:
        """基于路网 Graph 计算空间上下文。"""
        self._ensure_run_loaded(run_id)
        run_events = self._events.get(run_id, {})
        event = run_events.get(event_id)
        if not event:
            raise ValueError(f"Event '{event_id}' 不存在于 Run '{run_id}'")

        affected = self._network.get_road(event.road_id)
        snap = self.get_snapshot(run_id)

        # 计算 upstream/downstream/adjacent
        upstream = self._compute_upstream(event.road_id)
        downstream = self._compute_downstream(event.road_id)
        adjacent = self._compute_adjacent(event.road_id)

        # 附近路口和摄像头
        nearby_intersections = self._network.get_intersections_near_point(
            event.longitude, event.latitude, max_distance=0.015
        )
        nearby_cameras = self._network.get_cameras_near_point(
            event.longitude, event.latitude, max_distance=0.02
        )

        # 当前交通状态
        traffic_state: Dict[str, TrafficRoadState] = {}
        for rid in [event.road_id] + [r.road_id for r in upstream + downstream]:
            rs = snap.road_states.get(rid)
            if rs:
                traffic_state[rid] = rs

        return TrafficSpatialContext(
            event=event,
            affected_road=affected,
            upstream_roads=upstream,
            downstream_roads=downstream,
            adjacent_roads=adjacent,
            nearby_intersections=nearby_intersections,
            nearby_cameras=nearby_cameras,
            current_traffic_state=traffic_state,
        )

    def _compute_upstream(self, road_id: str) -> list[TrafficRoadSegment]:
        """基于路网拓扑计算上游路段。

        上游 = 进入本路段起始路口的所有其他路段。
        """
        road = self._network.get_road(road_id)
        if not road:
            return []
        upstream = []
        from_inter = self._network.get_intersection(road.from_intersection_id)
        if from_inter:
            for rid in from_inter.connected_road_ids:
                if rid == road_id:
                    continue
                r = self._network.get_road(rid)
                # 上游：流入起始路口的路段 (to == from_intersection)
                if r and r.to_intersection_id == road.from_intersection_id:
                    upstream.append(r)
        return upstream

    def _compute_downstream(self, road_id: str) -> list[TrafficRoadSegment]:
        """基于路网拓扑计算下游路段。

        下游 = 从本路段终点路口流出的所有其他路段。
        """
        road = self._network.get_road(road_id)
        if not road:
            return []
        downstream = []
        to_inter = self._network.get_intersection(road.to_intersection_id)
        if to_inter:
            for rid in to_inter.connected_road_ids:
                if rid == road_id:
                    continue
                r = self._network.get_road(rid)
                # 下游：从终点路口流出 (from == to_intersection)
                if r and r.from_intersection_id == road.to_intersection_id:
                    downstream.append(r)
        return downstream

    def _compute_adjacent(self, road_id: str) -> list[TrafficRoadSegment]:
        """基于路网拓扑计算邻接路段。

        邻接 = 共享同一路口的其他路段（不包括上游/下游已含的）。
        """
        road = self._network.get_road(road_id)
        if not road:
            return []
        adjacent: list[TrafficRoadSegment] = []
        seen = {road_id}
        for iid in (road.from_intersection_id, road.to_intersection_id):
            inter = self._network.get_intersection(iid)
            if inter:
                for rid in inter.connected_road_ids:
                    if rid not in seen:
                        seen.add(rid)
                        r = self._network.get_road(rid)
                        if r:
                            # 仅包含非严格上游/下游的连接路
                            adjacent.append(r)
        return adjacent

    # ── 动作执行 ──────────────────────────────────────────────────────────

    def apply_action(self, run_id: str, action: TrafficSimulationAction) -> TrafficSnapshot:
        """执行受控动作，产生新快照。"""
        self._ensure_run_loaded(run_id)
        current = self.get_snapshot(run_id)

        # 记录 before_snapshot_id
        action.before_snapshot_id = current.snapshot_id

        handler = ACTION_HANDLERS.get(action.action_type)
        if not handler:
            raise ValueError(f"不支持的动作类型: {action.action_type}")

        new_states = deepcopy(current.road_states)
        new_intersection = deepcopy(current.intersection_states)

        roads = self._network.road_segments

        if action.action_type == ActionType.TRAFFIC_DIVERSION:
            new_states = _apply_diversion_action(new_states, roads, action)
        elif action.action_type == ActionType.SIGNAL_ADJUSTMENT:
            new_states = _apply_signal_adjustment(new_states, roads, new_intersection, action)
        elif action.action_type in (ActionType.MONITOR, ActionType.CLOSE,
                                ActionType.LANE_CONTROL, ActionType.DISPATCH_COORDINATION):
            # monitor / close / lane_control / dispatch_coordination: 当前不做道路参数变化
            pass

        # 存储动作
        if run_id in self._actions:
            self._actions[run_id].append(action)

        # 创建新快照
        new_snap = self._append_snapshot(
            run_id, new_states, new_intersection,
            list(self._events.get(run_id, {}).keys()),
            description=f"动作执行: {action.action_type.value}",
        )

        action.after_snapshot_id = new_snap.snapshot_id
        action.status = "succeeded"

        return new_snap

    # ── 场景 ──────────────────────────────────────────────────────────────

    def list_scenarios(self) -> List[TrafficMapScenario]:
        from backend.simulation.scenarios import SCENARIOS
        return list(SCENARIOS.values())

    def get_scenario(self, scenario_id: str) -> Optional[TrafficMapScenario]:
        from backend.simulation.scenarios import SCENARIOS
        return SCENARIOS.get(scenario_id)

    # ── 内部方法 ──────────────────────────────────────────────────────────

    def _build_initial_snapshot(self, run_id: str) -> TrafficSnapshot:
        """构建初始快照 (所有路段正常状态)。"""
        road_states: Dict[str, TrafficRoadState] = {}
        for road in self._network.road_segments.values():
            road_states[road.road_id] = _compute_default_road_state(road)

        intersection_states: Dict[str, str] = {}
        for inter in self._network.intersections.values():
            intersection_states[inter.intersection_id] = inter.signal_state

        return TrafficSnapshot(
            snapshot_id=generate_snapshot_id(run_id, 0),
            run_id=run_id,
            sequence=0,
            road_states=road_states,
            intersection_states=intersection_states,
            active_event_ids=[],
            description="初始状态 (Initial)",
        )

    def _append_snapshot(
        self,
        run_id: str,
        road_states: Dict[str, TrafficRoadState],
        intersection_states: Dict[str, str],
        active_event_ids: List[str],
        description: str = "",
    ) -> TrafficSnapshot:
        """Append-only 添加新快照。"""
        snaps = self._snapshots.get(run_id, [])
        seq = len(snaps)
        new_snap = TrafficSnapshot(
            snapshot_id=generate_snapshot_id(run_id, seq),
            run_id=run_id,
            sequence=seq,
            road_states=road_states,
            intersection_states=intersection_states,
            active_event_ids=active_event_ids,
            description=description,
        )
        self._snapshots[run_id] = snaps + [new_snap]

        # 更新 run 引用
        if run_id in self._runs:
            self._runs[run_id].current_snapshot_id = new_snap.snapshot_id
            self._runs[run_id].snapshot_count = len(snaps) + 1

        return new_snap


# 全局单例
_provider: DemoSimulationProvider | None = None


def get_demo_provider() -> DemoSimulationProvider:
    """获取全局 DemoSimulationProvider 单例。"""
    global _provider
    if _provider is None:
        _provider = DemoSimulationProvider()
    return _provider
