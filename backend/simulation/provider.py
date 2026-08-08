"""
TrafficSimulationProvider — 抽象接口

纯领域接口，不依赖 FastAPI、Workflow、Agent、React。

未来实现:
  - DemoSimulationProvider     (Phase 13)
  - SumoSimulationProvider     (Phase 14+)
  - RealTrafficProvider        (远期)
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from backend.simulation.models import (
    TrafficSimulationRun,
    TrafficSimulationAction,
    TrafficSnapshot,
    TrafficRoadState,
    TrafficSpatialContext,
    TrafficCameraObservation,
    TrafficMapScenario,
    SimulationStatus,
    TrafficEvent,
)


class TrafficSimulationProvider(ABC):
    """仿真提供者抽象。

    所有实现必须：
      - 纯领域逻辑，零 Web/Agent 框架依赖
      - Snapshot append-only
      - 确定性结果（同一初始状态 + 同一 Action → 同一结果）
      - simulation=True 标记
    """

    # ── 生命周期 ──────────────────────────────────────────────────────────

    @abstractmethod
    def create_run(self, scenario_id: str) -> TrafficSimulationRun:
        """创建仿真运行实例。"""
        ...

    @abstractmethod
    def reset_run(self, run_id: str) -> TrafficSimulationRun:
        """重置仿真运行到初始状态。"""
        ...

    # ── 路网查询 ──────────────────────────────────────────────────────────

    @abstractmethod
    def get_network(self, run_id: str) -> Dict[str, Any]:
        """获取路网 (GeoJSON FeatureCollection)。"""
        ...

    # ── 快照查询 ──────────────────────────────────────────────────────────

    @abstractmethod
    def get_snapshot(self, run_id: str) -> TrafficSnapshot:
        """获取当前最新快照。"""
        ...

    @abstractmethod
    def get_snapshot_by_id(self, run_id: str, snapshot_id: str) -> Optional[TrafficSnapshot]:
        """按 ID 获取历史快照。"""
        ...

    # ── 道路/路口/摄像头状态 ──────────────────────────────────────────────

    @abstractmethod
    def get_road_state(self, run_id: str, road_id: str) -> Optional[TrafficRoadState]:
        """获取单条道路当前状态。"""
        ...

    @abstractmethod
    def get_intersection_state(self, run_id: str, intersection_id: str) -> Optional[str]:
        """获取路口信号灯状态。"""
        ...

    @abstractmethod
    def get_camera_observation(self, run_id: str, camera_id: str) -> TrafficCameraObservation:
        """获取模拟摄像头观测值。"""
        ...

    # ── 事件注入 ──────────────────────────────────────────────────────────

    @abstractmethod
    def inject_event(self, run_id: str, event: TrafficEvent) -> TrafficSnapshot:
        """注入模拟交通事件，返回新快照 (append-only)。"""
        ...

    # ── 空间上下文 ──────────────────────────────────────────────────────────

    @abstractmethod
    def build_spatial_context(self, run_id: str, event_id: str) -> TrafficSpatialContext:
        """基于路网 Graph 计算事件的空间上下文。

        upstream/downstream/adjacent 使用路网拓扑结构计算。
        """
        ...

    # ── 动作执行 ──────────────────────────────────────────────────────────

    @abstractmethod
    def apply_action(self, run_id: str, action: TrafficSimulationAction) -> TrafficSnapshot:
        """执行受控模拟动作，返回新快照 (append-only)。

        必须经过 Workflow Risk Gate / Human Approval 后才能调用。
        每次调用产生新快照，不覆盖历史。
        """
        ...

    # ── 场景 ──────────────────────────────────────────────────────────────

    @abstractmethod
    def list_scenarios(self) -> List[TrafficMapScenario]:
        """列出可用预设场景。"""
        ...

    @abstractmethod
    def get_scenario(self, scenario_id: str) -> Optional[TrafficMapScenario]:
        """获取单个场景定义。"""
        ...
