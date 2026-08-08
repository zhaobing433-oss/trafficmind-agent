"""
Phase 13 数据模型 — Traffic Map & Simulation V1

所有模型均为 Pydantic v2 BaseModel，用于：
  - API 请求/响应序列化
  - Provider 接口定义
  - SQLite JSON 持久化

设计约束：
  - current_event 不存放 simulation snapshot、道路动态指标
  - 独立 simulation_context / simulation_refs
  - Snapshot append-only，不覆盖历史
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ═══════════════════════════════════════════════════════════════════════════════
# 枚举
# ═══════════════════════════════════════════════════════════════════════════════


class SimulationStatus(str, Enum):
    """仿真运行状态。"""
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    RESET = "reset"


class CongestionLevel(str, Enum):
    """拥堵等级。"""
    NORMAL = "normal"
    SLOW = "slow"
    CONGESTED = "congested"
    SEVERE = "severe"


class ActionType(str, Enum):
    """受控模拟动作类型。"""
    TRAFFIC_DIVERSION = "traffic_diversion"
    SIGNAL_ADJUSTMENT = "signal_adjustment"
    LANE_CONTROL = "lane_control"
    DISPATCH_COORDINATION = "dispatch_coordination"
    MONITOR = "monitor"
    CLOSE = "close"


class EventStatus(str, Enum):
    """模拟事件状态。"""
    ACTIVE = "active"
    RESOLVED = "resolved"


# ═══════════════════════════════════════════════════════════════════════════════
# 路网静态元素
# ═══════════════════════════════════════════════════════════════════════════════


class TrafficIntersection(BaseModel):
    """交通路口 — 路网节点。

    Attributes:
        intersection_id: 路口唯一标识
        name: 路口名称（演示数据，标记为模拟）
        longitude: 经度 (WGS-84)
        latitude: 纬度 (WGS-84)
        connected_road_ids: 连接的道路 ID 列表
        signal_state: 信号灯状态 (normal / adjusted)
    """
    model_config = ConfigDict(extra="allow")

    intersection_id: str
    name: str
    longitude: float
    latitude: float
    connected_road_ids: List[str] = Field(default_factory=list)
    signal_state: str = "normal"


class TrafficRoadSegment(BaseModel):
    """道路路段 — 路网边。

    Attributes:
        road_id: 路段唯一标识
        name: 道路名称（演示数据）
        from_intersection_id: 起点路口 ID
        to_intersection_id: 终点路口 ID
        geometry: 折线坐标 [[lng, lat], ...]
        lanes: 车道数
        capacity: 通行能力 (veh/h)
        free_flow_speed: 自由流速度 (km/h)
    """
    model_config = ConfigDict(extra="allow")

    road_id: str
    name: str
    from_intersection_id: str
    to_intersection_id: str
    geometry: List[List[float]] = Field(default_factory=list)
    lanes: int = 2
    capacity: int = 1200
    free_flow_speed: float = 50.0


class TrafficCameraSensor(BaseModel):
    """模拟摄像头传感器。

    ALL simulated — 不连接真实设备、不处理视频流。

    Attributes:
        camera_id: 摄像头唯一标识
        name: 摄像头名称
        longitude: 经度
        latitude: 纬度
        road_id: 所属路段 ID
        status: 状态 (active / inactive)
        simulated: ALWAYS True
    """
    model_config = ConfigDict(extra="allow")

    camera_id: str
    name: str
    longitude: float
    latitude: float
    road_id: str
    status: str = "active"
    simulated: bool = True


# ═══════════════════════════════════════════════════════════════════════════════
# 运行时状态 (append-only snapshots)
# ═══════════════════════════════════════════════════════════════════════════════


class TrafficRoadState(BaseModel):
    """单条道路的交通状态快照。

    所有字段为瞬时观测值。确定性规则计算，不引入随机。
    """
    model_config = ConfigDict(extra="allow")

    road_id: str
    avg_speed: float = 35.0          # km/h
    vehicle_count: int = 0
    flow: float = 0.0                # veh/h
    occupancy: float = 0.0           # 0.0 - 1.0
    queue_length: float = 0.0        # m
    congestion_level: CongestionLevel = CongestionLevel.NORMAL
    effective_capacity: float = 0.0  # veh/h (事故/施工后下降)


class TrafficSnapshot(BaseModel):
    """交通状态完整快照 — append-only。

    每次事件注入或 Action 执行产生新快照，不覆盖历史。
    """
    model_config = ConfigDict(extra="allow")

    snapshot_id: str
    run_id: str
    sequence: int = 0                # 快照序号，从 0 起递增
    timestamp: str = ""
    road_states: Dict[str, TrafficRoadState] = Field(default_factory=dict)
    intersection_states: Dict[str, str] = Field(default_factory=dict)
    active_event_ids: List[str] = Field(default_factory=list)
    description: str = ""            # 描述（如 "事故注入后"、"分流执行后"）

    def __init__(self, **data):
        super().__init__(**data)
        if not self.timestamp:
            self.timestamp = _utc_now_iso()


class TrafficCameraObservation(BaseModel):
    """模拟摄像头观测值。

    每个 Camera 返回当前帧的模拟观测数据。
    """
    model_config = ConfigDict(extra="allow")

    camera_id: str
    vehicle_count: int = 0
    avg_speed: float = 0.0
    queue_length: float = 0.0
    detected_events: List[str] = Field(default_factory=list)
    timestamp: str = ""
    simulated: bool = True

    def __init__(self, **data):
        super().__init__(**data)
        if not self.timestamp:
            self.timestamp = _utc_now_iso()


# ═══════════════════════════════════════════════════════════════════════════════
# 事件与空间上下文
# ═══════════════════════════════════════════════════════════════════════════════


class TrafficEvent(BaseModel):
    """模拟交通事件。

    simulated ALWAYS True — 不得表示真实事件。
    """
    model_config = ConfigDict(extra="allow")

    event_id: str
    event_type: str                 # congestion / accident / ...
    severity: str = "medium"        # low / medium / high / critical
    road_id: str = ""
    intersection_id: str = ""
    longitude: float = 0.0
    latitude: float = 0.0
    description: str = ""
    started_at: str = ""
    status: str = "active"          # active / resolved
    simulated: bool = True

    def __init__(self, **data):
        super().__init__(**data)
        if not self.started_at:
            self.started_at = _utc_now_iso()


class TrafficSpatialContext(BaseModel):
    """事件空间上下文。

    基于路网图结构计算 upstream/downstream/adjacent。
    Agent 基于结构化上下文研判，不直接访问整张地图 JSON。

    Attributes:
        event: 当前交通事件
        affected_road: 受影响的主要路段
        upstream_roads: 上游路段
        downstream_roads: 下游路段
        adjacent_roads: 邻接路段
        nearby_intersections: 附近路口
        nearby_cameras: 附近摄像头
        current_traffic_state: 当前各路段交通状态摘要
    """
    model_config = ConfigDict(extra="allow")

    event: Optional[TrafficEvent] = None
    affected_road: Optional[TrafficRoadSegment] = None
    upstream_roads: List[TrafficRoadSegment] = Field(default_factory=list)
    downstream_roads: List[TrafficRoadSegment] = Field(default_factory=list)
    adjacent_roads: List[TrafficRoadSegment] = Field(default_factory=list)
    nearby_intersections: List[TrafficIntersection] = Field(default_factory=list)
    nearby_cameras: List[TrafficCameraSensor] = Field(default_factory=list)
    current_traffic_state: Dict[str, TrafficRoadState] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# 仿真运行与动作
# ═══════════════════════════════════════════════════════════════════════════════


class TrafficSimulationRun(BaseModel):
    """一次仿真运行实例。

    Attributes:
        run_id: 运行唯一 ID
        scenario_id: 使用的场景 ID
        status: 运行状态
        current_snapshot_id: 当前最新快照 ID
        snapshot_count: 快照总数
        session_id: 关联的 Chat Session ID
        created_at: 创建时间
    """
    model_config = ConfigDict(extra="allow")

    run_id: str
    scenario_id: str = ""
    status: SimulationStatus = SimulationStatus.CREATED
    current_snapshot_id: str = ""
    snapshot_count: int = 0
    session_id: str = ""
    created_at: str = ""

    def __init__(self, **data):
        super().__init__(**data)
        if not self.created_at:
            self.created_at = _utc_now_iso()


class TrafficSimulationAction(BaseModel):
    """受控模拟动作。

    约束：
      - simulation ALWAYS True
      - 必须经过 Workflow Risk Gate / Human Approval / Action Node
      - Agent 不得直接调用 apply_simulation_action
      - idempotency_key 保证幂等

    Attributes:
        action_id: 动作唯一 ID
        action_type: 动作类型 (6种受控类型)
        target_ids: 目标资源 ID 列表
        parameters: 动作参数 (schema 受限)
        source: 来源 (workflow / manual)
        workflow_run_id: 关联的 Workflow Run ID
        idempotency_key: 幂等键
        before_snapshot_id: 执行前快照 ID
        after_snapshot_id: 执行后快照 ID
        status: 执行状态
    """
    model_config = ConfigDict(extra="allow")

    action_id: str
    action_type: ActionType
    target_ids: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    source: str = "manual"
    workflow_run_id: str = ""
    idempotency_key: str = ""
    before_snapshot_id: str = ""
    after_snapshot_id: str = ""
    status: str = "pending"
    simulation: bool = True   # ALWAYS True

    def __init__(self, **data):
        super().__init__(**data)
        if not self.idempotency_key:
            self.idempotency_key = _compute_action_idempotency_key(
                self.action_type.value if isinstance(self.action_type, ActionType) else str(self.action_type),
                self.target_ids,
                self.workflow_run_id,
            )


class TrafficMapScenario(BaseModel):
    """预设场景定义。

    Attributes:
        scenario_id: 场景唯一 ID
        name: 场景名称
        description: 场景描述
        category: 分类 (peak_hour / school_zone / accident)
        initial_events: 初始事件列表 (注入指令)
    """
    model_config = ConfigDict(extra="allow")

    scenario_id: str
    name: str
    description: str = ""
    category: str = ""
    initial_events: List[Dict[str, Any]] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# 独立上下文对象 (不污染 current_event)
# ═══════════════════════════════════════════════════════════════════════════════


class SimulationContext(BaseModel):
    """发给 Agent 的模拟环境上下文（独立对象）。

    不混入 current_event，不覆盖事件事实。
    """
    model_config = ConfigDict(extra="allow")

    simulation_run_id: str = ""
    traffic_event_id: str = ""
    snapshot_id: str = ""
    spatial_context: Optional[TrafficSpatialContext] = None
    nearby_cameras_summary: List[Dict[str, Any]] = Field(default_factory=list)
    road_states_summary: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class SimulationRefs(BaseModel):
    """Workflow State 中存放的仿真引用（独立于 current_event）。

    decisionSnapshotId: Agent 分析基于的快照（固定不变）
    latestSnapshotId: 最新快照（Action 后更新）
    """
    model_config = ConfigDict(extra="allow")

    simulation_run_id: str = ""
    traffic_event_id: str = ""
    decision_snapshot_id: str = ""   # Agent 基于此快照做 Proposal
    latest_snapshot_id: str = ""     # Action 后更新为 after_snapshot_id
    workflow_run_id: str = ""
    spatial_context_ref: Dict[str, Any] = Field(default_factory=dict)
    # spatial_context_ref 只存 {simulationRunId, trafficEventId, snapshotId}
    # 恢复时通过 build_spatial_context() 重建


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════════════


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:8]
    return f"simrun_{ts}_{short}"


def generate_snapshot_id(run_id: str, seq: int) -> str:
    return f"snap_{run_id}_{seq:04d}"


def generate_event_id() -> str:
    return f"simevt_{uuid.uuid4().hex[:12]}"


def generate_action_id() -> str:
    return f"simact_{uuid.uuid4().hex[:12]}"


def _compute_action_idempotency_key(
    action_type: str,
    target_ids: List[str],
    workflow_run_id: str,
) -> str:
    raw = f"{action_type}:{','.join(sorted(target_ids))}:{workflow_run_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
