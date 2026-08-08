"""
Phase 13 Tests — Traffic Map & Simulation V1

测试覆盖：
  - Scenario 加载
  - Simulation 创建
  - Network 读取
  - Snapshot
  - Event 注入 + capacity/speed/queue 变化
  - SpatialContext: upstream/downstream/adjacent
  - Camera observation
  - Action schema validation + idempotency
  - Diversion/signal action
  - Before/after snapshot: speed/queue improvement
  - Reset
  - current_event 不可被 simulation 覆盖
  - Simulation IDs 进入 Trace
  - 非审批 Action 不得执行
  - API 集成

所有测试确定性：固定初始状态 + 固定 Action → 确定性结果。
普通测试不加载 Qwen/DeepSeek。

Note: API 返回 model_dump() snake_case 格式（与 Pydantic 原生一致）。
"""

import json
import pytest
from fastapi.testclient import TestClient


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers — API 创建 Run（确保 SQLite repo 可见）
# ═══════════════════════════════════════════════════════════════════════════════


def _create_run_via_api(client: TestClient, scenario_id: str = "scenario_c_accident") -> dict:
    """通过 API 创建 Run，返回完整 response data。"""
    resp = client.post("/traffic-map/simulations", json={"scenarioId": scenario_id})
    assert resp.status_code == 200, f"创建失败: {resp.text}"
    return resp.json()


def _inject_event_via_api(client: TestClient, run_id: str, **overrides) -> dict:
    """通过 API 注入事件，返回完整 response data。"""
    body = {
        "eventType": "accident",
        "severity": "high",
        "roadId": "R01",
        "longitude": 116.397,
        "latitude": 39.907,
        "description": "API test accident",
    }
    body.update(overrides)
    resp = client.post(f"/traffic-map/simulations/{run_id}/events", json=body)
    assert resp.status_code == 200, f"注入事件失败: {resp.text}"
    return resp.json()


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def client():
    """创建 TestClient。"""
    from backend.app import app
    return TestClient(app)


@pytest.fixture
def provider():
    """获取 DemoSimulationProvider。"""
    from backend.simulation.demo_provider import get_demo_provider
    return get_demo_provider()


@pytest.fixture
def network():
    """获取 Demo 路网。"""
    from backend.simulation.demo_network import DEMO_NETWORK
    return DEMO_NETWORK


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario 加载
# ═══════════════════════════════════════════════════════════════════════════════


class TestScenarioLoading:
    """场景加载测试。"""

    def test_list_scenarios_api(self, client):
        """API: 列出场景。"""
        resp = client.get("/traffic-map/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 3
        # model_dump() → snake_case keys
        scenario_ids = [s["scenario_id"] for s in data["scenarios"]]
        assert "scenario_c_accident" in scenario_ids

    def test_scenario_c_has_initial_events(self, provider):
        """Scenario C 包含初始事件定义。"""
        scenario = provider.get_scenario("scenario_c_accident")
        assert scenario is not None
        assert len(scenario.initial_events) >= 1
        evt = scenario.initial_events[0]
        assert evt["event_type"] == "accident"
        assert evt["road_id"] == "R01"


# ═══════════════════════════════════════════════════════════════════════════════
# Simulation 创建
# ═══════════════════════════════════════════════════════════════════════════════


class TestSimulationCreate:
    """Simulation 创建测试。"""

    def test_create_simulation_api(self, client):
        """API: 创建仿真运行 (snake_case keys from model_dump)。"""
        data = _create_run_via_api(client)
        run = data["run"]
        assert run["scenario_id"] == "scenario_c_accident"
        assert run["status"] == "running"
        assert "network" in data
        assert "snapshot" in data

    def test_create_run_returns_initial_snapshot(self, provider):
        """创建 Run 返回初始快照 (所有路段正常)。"""
        run = provider.create_run("scenario_c_accident")
        assert run.status.value == "running"
        snap = provider.get_snapshot(run.run_id)
        assert snap.sequence == 0
        assert len(snap.road_states) == 12
        for rs in snap.road_states.values():
            assert rs.congestion_level.value == "normal"
            assert rs.avg_speed > 20

    def test_create_run_deterministic(self, provider):
        """同一场景创建两次，初始状态完全相同。"""
        run1 = provider.create_run("scenario_c_accident")
        snap1 = provider.get_snapshot(run1.run_id)
        run2 = provider.create_run("scenario_c_accident")
        snap2 = provider.get_snapshot(run2.run_id)
        for rs1, rs2 in zip(
            sorted(snap1.road_states.values(), key=lambda r: r.road_id),
            sorted(snap2.road_states.values(), key=lambda r: r.road_id),
        ):
            assert rs1.road_id == rs2.road_id
            assert rs1.avg_speed == rs2.avg_speed
            assert rs1.congestion_level == rs2.congestion_level


# ═══════════════════════════════════════════════════════════════════════════════
# Network 读取
# ═══════════════════════════════════════════════════════════════════════════════


class TestNetworkReading:
    """路网读取测试。"""

    def test_network_has_all_roads(self, network):
        assert len(network.road_segments) == 12

    def test_network_has_all_intersections(self, network):
        assert len(network.intersections) == 6

    def test_network_has_all_cameras(self, network):
        assert len(network.cameras) == 6

    def test_network_geojson_api(self, client):
        """API: 获取路网 GeoJSON (通过 API 创建 run)。"""
        data = _create_run_via_api(client)
        run_id = data["run"]["run_id"]
        resp = client.get(f"/traffic-map/simulations/{run_id}/network")
        assert resp.status_code == 200, f"网络API失败: {resp.text}"
        geo = resp.json()
        assert geo["type"] == "FeatureCollection"
        assert len(geo["features"]) == 24  # 12 roads + 6 intersections + 6 cameras

    def test_network_geojson_feature_types(self, network):
        """GeoJSON feature 类型正确。"""
        geojson = network.to_geojson()
        types = {}
        for f in geojson["features"]:
            ft = f["properties"]["featureType"]
            types[ft] = types.get(ft, 0) + 1
        assert types.get("road") == 12
        assert types.get("intersection") == 6
        assert types.get("camera") == 6

    def test_camera_simulated_flag(self, network):
        """所有摄像头标记 simulated=true。"""
        for cam in network.cameras.values():
            assert cam.simulated is True


# ═══════════════════════════════════════════════════════════════════════════════
# Snapshot
# ═══════════════════════════════════════════════════════════════════════════════


class TestSnapshot:
    """快照测试。"""

    def test_snapshot_append_only(self, provider):
        """Snapshots are append-only, never overwritten。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run = provider.create_run("scenario_c_accident")
        assert len(provider.get_all_snapshots(run.run_id)) == 1

        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test accident",
        )
        provider.inject_event(run.run_id, event)
        snaps = provider.get_all_snapshots(run.run_id)
        assert len(snaps) == 2
        assert snaps[0].sequence == 0
        assert snaps[1].sequence == 1
        assert snaps[0].road_states["R01"].congestion_level.value == "normal"

    def test_snapshot_api(self, client):
        """API: 获取快照 (snake_case)。"""
        data = _create_run_via_api(client)
        run_id = data["run"]["run_id"]
        resp = client.get(f"/traffic-map/simulations/{run_id}/snapshot")
        assert resp.status_code == 200
        snap = resp.json()
        assert snap["sequence"] == 0
        assert "road_states" in snap


# ═══════════════════════════════════════════════════════════════════════════════
# Event 注入
# ═══════════════════════════════════════════════════════════════════════════════


class TestEventInjection:
    """事件注入测试。"""

    def test_inject_accident_reduces_capacity(self, provider):
        """事故注入后：capacity 下降。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run = provider.create_run("scenario_c_accident")
        before = provider.get_road_state(run.run_id, "R01")
        assert before.effective_capacity == 1800

        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test accident",
        )
        provider.inject_event(run.run_id, event)
        after = provider.get_road_state(run.run_id, "R01")
        assert after.effective_capacity < 1800
        assert after.effective_capacity < 500

    def test_inject_accident_reduces_speed(self, provider):
        """事故注入后：avg_speed 下降。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run = provider.create_run("scenario_c_accident")
        before = provider.get_road_state(run.run_id, "R01")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        after = provider.get_road_state(run.run_id, "R01")
        assert after.avg_speed < before.avg_speed
        assert after.avg_speed < 20

    def test_inject_accident_increases_queue(self, provider):
        """事故注入后：queue_length 增加。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run = provider.create_run("scenario_c_accident")
        before = provider.get_road_state(run.run_id, "R01")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        after = provider.get_road_state(run.run_id, "R01")
        assert after.queue_length > before.queue_length
        assert after.queue_length > 200

    def test_inject_accident_congestion_severe(self, provider):
        """事故注入后：congestion_level = severe。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        after = provider.get_road_state(run.run_id, "R01")
        assert after.congestion_level.value == "severe"

    def test_inject_deterministic(self, provider):
        """同一事件注入两次，结果完全相同。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run1 = provider.create_run("scenario_c_accident")
        run2 = provider.create_run("scenario_c_accident")

        e1 = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        e2 = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run1.run_id, e1)
        provider.inject_event(run2.run_id, e2)
        rs1 = provider.get_road_state(run1.run_id, "R01")
        rs2 = provider.get_road_state(run2.run_id, "R01")
        assert rs1.avg_speed == rs2.avg_speed
        assert rs1.queue_length == rs2.queue_length
        assert rs1.congestion_level == rs2.congestion_level
        assert rs1.effective_capacity == rs2.effective_capacity

    def test_inject_event_api(self, client):
        """API: 注入事件 (snake_case)。"""
        data = _create_run_via_api(client)
        run_id = data["run"]["run_id"]
        result = _inject_event_via_api(client, run_id)
        assert "event" in result
        assert "snapshot" in result
        assert "impact" in result
        assert result["impact"]["speedDelta"] < 0
        assert result["impact"]["queueDelta"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Spatial Context
# ═══════════════════════════════════════════════════════════════════════════════


class TestSpatialContext:
    """空间上下文测试。"""

    def test_spatial_context_upstream(self, provider):
        """上游路段计算正确。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        ctx = provider.build_spatial_context(run.run_id, event.event_id)
        upstream_ids = {r.road_id for r in ctx.upstream_roads}
        assert "R08" in upstream_ids  # 交通路 → I01
        assert "R12" in upstream_ids  # 演示北路 → I01

    def test_spatial_context_downstream(self, provider):
        """下游路段计算正确。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        ctx = provider.build_spatial_context(run.run_id, event.event_id)
        downstream_ids = {r.road_id for r in ctx.downstream_roads}
        assert "R02" in downstream_ids
        assert "R10" in downstream_ids

    def test_spatial_context_nearby_cameras(self, provider):
        """附近摄像头查询正确。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        ctx = provider.build_spatial_context(run.run_id, event.event_id)
        cam_ids = {c.camera_id for c in ctx.nearby_cameras}
        assert "CAM01" in cam_ids

    def test_spatial_context_nearby_intersections(self, provider):
        """附近路口查询正确。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        ctx = provider.build_spatial_context(run.run_id, event.event_id)
        inter_ids = {i.intersection_id for i in ctx.nearby_intersections}
        assert "I01" in inter_ids

    def test_spatial_context_api(self, client):
        """API: 获取空间上下文 (camelCase from _spatial_context_to_dict)。"""
        data = _create_run_via_api(client)
        run_id = data["run"]["run_id"]
        result = _inject_event_via_api(client, run_id)
        event_id = result["event"]["event_id"]
        resp = client.get(
            f"/traffic-map/simulations/{run_id}/spatial-context",
            params={"eventId": event_id},
        )
        assert resp.status_code == 200
        sc = resp.json()
        assert sc["simulated"] is True
        assert sc["affectedRoad"] is not None
        assert len(sc["upstreamRoads"]) > 0
        assert len(sc["downstreamRoads"]) > 0
        assert len(sc["nearbyCameras"]) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Camera Observation
# ═══════════════════════════════════════════════════════════════════════════════


class TestCameraObservation:
    """摄像头观测测试。"""

    def test_camera_returns_road_state(self, provider):
        """摄像头观测反映所在路段状态。"""
        run = provider.create_run("scenario_c_accident")
        obs = provider.get_camera_observation(run.run_id, "CAM01")
        assert obs.simulated is True
        assert obs.vehicle_count > 0

    def test_camera_detects_event(self, provider):
        """事故注入后，所在路段摄像头检测到事件。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        obs = provider.get_camera_observation(run.run_id, "CAM01")
        assert len(obs.detected_events) >= 1

    def test_camera_api(self, client):
        """API: 获取摄像头观测 (snake_case)。"""
        data = _create_run_via_api(client)
        run_id = data["run"]["run_id"]
        resp = client.get(f"/traffic-map/simulations/{run_id}/camera/CAM01")
        assert resp.status_code == 200, f"camera API: {resp.text}"
        obs = resp.json()
        assert obs["simulated"] is True
        assert obs["camera_id"] == "CAM01"


# ═══════════════════════════════════════════════════════════════════════════════
# Action — Diversion
# ═══════════════════════════════════════════════════════════════════════════════


class TestDiversionAction:
    """分流动作测试。"""

    def test_diversion_improves_speed(self, provider):
        """分流后：source road avg_speed 改善。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        before_action = provider.get_road_state(run.run_id, "R01")

        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07", "R05"],
            parameters={"diversionRatio": 0.4},
            source="manual",
        )
        provider.apply_action(run.run_id, action)
        after_action = provider.get_road_state(run.run_id, "R01")
        assert after_action.avg_speed > before_action.avg_speed
        assert action.after_snapshot_id != ""

    def test_diversion_reduces_queue(self, provider):
        """分流后：source road queue_length 减少。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        before = provider.get_road_state(run.run_id, "R01")

        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07", "R05"],
            parameters={"diversionRatio": 0.4},
            source="manual",
        )
        provider.apply_action(run.run_id, action)
        after = provider.get_road_state(run.run_id, "R01")
        assert after.queue_length < before.queue_length

    def test_diversion_snapshot_append(self, provider):
        """分流产生新快照 (append-only)。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        before_count = len(provider.get_all_snapshots(run.run_id))

        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07", "R05"],
            parameters={"diversionRatio": 0.4},
            source="manual",
        )
        provider.apply_action(run.run_id, action)
        assert len(provider.get_all_snapshots(run.run_id)) == before_count + 1

    def test_diversion_deterministic(self, provider):
        """同一事故 + 同一分流 → 完全相同的最终状态。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )

        def run_diversion():
            run = provider.create_run("scenario_c_accident")
            event = TrafficEvent(
                event_id=generate_event_id(),
                event_type="accident", severity="high", road_id="R01",
                longitude=116.397, latitude=39.907, description="Test",
            )
            provider.inject_event(run.run_id, event)
            action = TrafficSimulationAction(
                action_id=generate_action_id(),
                action_type=ActionType.TRAFFIC_DIVERSION,
                target_ids=["R01", "R07", "R05"],
                parameters={"diversionRatio": 0.4},
                source="manual",
            )
            provider.apply_action(run.run_id, action)
            return provider.get_road_state(run.run_id, "R01")

        rs1 = run_diversion()
        rs2 = run_diversion()
        assert rs1.avg_speed == rs2.avg_speed
        assert rs1.queue_length == rs2.queue_length
        assert rs1.congestion_level == rs2.congestion_level


# ═══════════════════════════════════════════════════════════════════════════════
# Action — Signal
# ═══════════════════════════════════════════════════════════════════════════════


class TestSignalAction:
    """信号配时动作测试。"""

    def test_signal_adjustment_improves_flow(self, provider):
        """信号调整后：目标路段改善。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="congestion", severity="medium", road_id="R03",
            longitude=116.3975, latitude=39.906, description="Test",
        )
        provider.inject_event(run.run_id, event)
        before = provider.get_road_state(run.run_id, "R03")

        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.SIGNAL_ADJUSTMENT,
            target_ids=["R03"],
            parameters={
                "intersectionId": "I03",
                "direction": "west_east",
                "greenExtensionSeconds": 30,
            },
            source="manual",
        )
        provider.apply_action(run.run_id, action)
        after = provider.get_road_state(run.run_id, "R03")
        assert after.avg_speed > before.avg_speed

    def test_signal_adjustment_updates_intersection(self, provider):
        """信号调整后：路口状态变为 adjusted。"""
        from backend.simulation.models import (
            TrafficSimulationAction,
            generate_action_id, ActionType,
        )
        run = provider.create_run("scenario_c_accident")
        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.SIGNAL_ADJUSTMENT,
            target_ids=["R03"],
            parameters={
                "intersectionId": "I03",
                "direction": "west_east",
                "greenExtensionSeconds": 30,
            },
            source="manual",
        )
        provider.apply_action(run.run_id, action)
        assert provider.get_intersection_state(run.run_id, "I03") == "adjusted"


# ═══════════════════════════════════════════════════════════════════════════════
# Action Schema Validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionValidation:
    """Action 验证测试。"""

    def test_action_idempotency_key_generated(self):
        """Action 自动生成 idempotency_key。"""
        from backend.simulation.models import TrafficSimulationAction, ActionType, generate_action_id
        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07"],
            parameters={},
            source="manual",
        )
        assert len(action.idempotency_key) == 16

    def test_action_idempotency_key_deterministic(self):
        """相同参数产生相同 idempotency_key。"""
        from backend.simulation.models import TrafficSimulationAction, ActionType, generate_action_id
        a1 = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07"],
            parameters={},
            source="manual",
            workflow_run_id="wf_run_1",
        )
        a2 = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07"],
            parameters={},
            source="manual",
            workflow_run_id="wf_run_1",
        )
        assert a1.idempotency_key == a2.idempotency_key

    def test_action_simulation_flag_true(self):
        """所有 Action simulation 标记必须为 True。"""
        from backend.simulation.models import TrafficSimulationAction, ActionType, generate_action_id
        for at in ActionType:
            action = TrafficSimulationAction(
                action_id=generate_action_id(),
                action_type=at,
                target_ids=["R01"],
                parameters={},
                source="manual",
            )
            assert action.simulation is True, f"ActionType {at} must have simulation=True"


# ═══════════════════════════════════════════════════════════════════════════════
# Before/After
# ═══════════════════════════════════════════════════════════════════════════════


class TestBeforeAfter:
    """Before/After 对比测试。"""

    def test_action_records_before_snapshot(self, provider):
        """Action 记录 before_snapshot_id。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        before_snap = provider.get_snapshot(run.run_id)

        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07"],
            parameters={"diversionRatio": 0.4},
            source="manual",
        )
        provider.apply_action(run.run_id, action)
        assert action.before_snapshot_id == before_snap.snapshot_id
        assert action.after_snapshot_id != ""
        assert action.status == "succeeded"

    def test_speed_improvement_after_action(self, provider):
        """Action 后 speed 改善。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        speed_before = provider.get_road_state(run.run_id, "R01").avg_speed

        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07", "R05"],
            parameters={"diversionRatio": 0.4},
            source="manual",
        )
        provider.apply_action(run.run_id, action)
        speed_after = provider.get_road_state(run.run_id, "R01").avg_speed
        assert speed_after > speed_before

    def test_queue_improvement_after_action(self, provider):
        """Action 后 queue_length 减少。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        queue_before = provider.get_road_state(run.run_id, "R01").queue_length

        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07", "R05"],
            parameters={"diversionRatio": 0.4},
            source="manual",
        )
        provider.apply_action(run.run_id, action)
        queue_after = provider.get_road_state(run.run_id, "R01").queue_length
        assert queue_after < queue_before


# ═══════════════════════════════════════════════════════════════════════════════
# Reset
# ═══════════════════════════════════════════════════════════════════════════════


class TestReset:
    """重置测试。"""

    def test_reset_restores_normal_state(self, provider):
        """重置后所有路段恢复正常。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        assert provider.get_road_state(run.run_id, "R01").congestion_level.value == "severe"

        provider.reset_run(run.run_id)
        assert provider.get_road_state(run.run_id, "R01").congestion_level.value == "normal"

    def test_reset_api(self, client):
        """API: 重置仿真。"""
        data = _create_run_via_api(client)
        run_id = data["run"]["run_id"]
        resp = client.post(f"/traffic-map/simulations/{run_id}/reset")
        assert resp.status_code == 200
        result = resp.json()
        assert result["run"]["status"] == "reset"


# ═══════════════════════════════════════════════════════════════════════════════
# current_event 不可覆盖
# ═══════════════════════════════════════════════════════════════════════════════


class TestCurrentEventImmutability:
    """current_event 保护测试。"""

    def test_simulation_context_separate_from_current_event(self):
        """SimulationContext 不混入 current_event。"""
        from backend.simulation.models import SimulationContext
        current_event = {
            "eventId": "evt_001",
            "eventType": "accident",
            "roadName": "演示大道",
            "avgSpeed": 9.0,
        }
        ctx = SimulationContext(
            simulation_run_id="simrun_001",
            traffic_event_id="simevt_001",
            snapshot_id="snap_001",
        )
        assert "simulation_run_id" not in current_event
        assert ctx.simulation_run_id == "simrun_001"

    def test_simulation_refs_isolated(self):
        """SimulationRefs 独立于 current_event。"""
        from backend.simulation.models import SimulationRefs
        refs = SimulationRefs(
            simulation_run_id="sr_1",
            traffic_event_id="te_1",
            snapshot_id="sn_1",
            workflow_run_id="wr_1",
        )
        d = refs.model_dump()
        assert "simulation_run_id" in d


# ═══════════════════════════════════════════════════════════════════════════════
# Simulation IDs 进入 Trace
# ═══════════════════════════════════════════════════════════════════════════════


class TestSimulationTrace:
    """Trace 测试。"""

    def test_simulation_run_id_in_trace(self, provider):
        """Run ID 出现在快照中。"""
        run = provider.create_run("scenario_c_accident")
        snap = provider.get_snapshot(run.run_id)
        assert snap.run_id == run.run_id

    def test_snapshot_ids_sequential(self, provider):
        """快照 ID 有序。"""
        from backend.simulation.models import TrafficEvent, generate_event_id
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Test",
        )
        provider.inject_event(run.run_id, event)
        snaps = provider.get_all_snapshots(run.run_id)
        assert snaps[0].sequence == 0
        assert snaps[1].sequence == 1
        assert snaps[0].snapshot_id != snaps[1].snapshot_id


# ═══════════════════════════════════════════════════════════════════════════════
# 非审批 Action 不得执行
# ═══════════════════════════════════════════════════════════════════════════════


class TestActionGuard:
    """Action 安全守卫测试。"""

    def test_agent_tools_are_readonly(self):
        """Agent 工具都是只读的 (不暴露 apply_simulation_action)。"""
        from backend.simulation.tools import SIMULATION_READONLY_TOOLS
        tool_names = list(SIMULATION_READONLY_TOOLS.keys())
        assert "apply_simulation_action" not in tool_names
        for name in tool_names:
            assert name.startswith("get_"), f"Tool '{name}' should be read-only"


# ═══════════════════════════════════════════════════════════════════════════════
# API 集成测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestAPIEndpoints:
    """API 端点集成测试。"""

    def test_scenarios_list(self, client):
        """场景 API 返回至少 3 个场景。"""
        resp = client.get("/traffic-map/scenarios")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 3

    def test_full_simulation_flow(self, client):
        """完整 API 流程: 创建 → 路网 → 注入事件 → 快照 → 空间上下文 → 重置。"""
        # Create
        data = _create_run_via_api(client)
        run_id = data["run"]["run_id"]

        # Network (snake_case)
        resp = client.get(f"/traffic-map/simulations/{run_id}/network")
        assert resp.status_code == 200

        # Snapshot
        resp = client.get(f"/traffic-map/simulations/{run_id}/snapshot")
        assert resp.status_code == 200

        # Inject event
        result = _inject_event_via_api(client, run_id)
        event_id = result["event"]["event_id"]
        assert result["impact"]["speedDelta"] < 0
        assert result["impact"]["queueDelta"] > 0

        # Spatial context
        resp = client.get(
            f"/traffic-map/simulations/{run_id}/spatial-context",
            params={"eventId": event_id},
        )
        assert resp.status_code == 200

        # Road state (snake_case)
        resp = client.get(f"/traffic-map/simulations/{run_id}/road/R01/state")
        assert resp.status_code == 200
        assert resp.json()["congestion_level"] == "severe"

        # Camera (snake_case)
        resp = client.get(f"/traffic-map/simulations/{run_id}/camera/CAM01")
        assert resp.status_code == 200
        assert resp.json()["simulated"] is True

        # Snapshots list
        resp = client.get(f"/traffic-map/simulations/{run_id}/snapshots")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

        # Sim detail
        resp = client.get(f"/traffic-map/simulations/{run_id}")
        assert resp.status_code == 200

        # Reset
        resp = client.post(f"/traffic-map/simulations/{run_id}/reset")
        assert resp.status_code == 200

        # After reset: normal
        resp = client.get(f"/traffic-map/simulations/{run_id}/road/R01/state")
        assert resp.json()["congestion_level"] == "normal"

    def test_nonexistent_run_404(self, client):
        """不存在的 Run 返回 404。"""
        resp = client.get("/traffic-map/simulations/nonexistent_run")
        assert resp.status_code == 404

    def test_nonexistent_road_404(self, client):
        """不存在的 Road 返回 404。"""
        data = _create_run_via_api(client)
        run_id = data["run"]["run_id"]
        resp = client.get(f"/traffic-map/simulations/{run_id}/road/NONEXISTENT/state")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# 确定性验证
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeterminism:
    """确定性验证测试。"""

    def test_full_scenario_c_deterministic(self, provider):
        """Scenario C 完整流程确定性。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )

        def run_scenario():
            run = provider.create_run("scenario_c_accident")
            event = TrafficEvent(
                event_id=generate_event_id(),
                event_type="accident", severity="high", road_id="R01",
                longitude=116.397, latitude=39.907,
                description="Scenario C test",
            )
            provider.inject_event(run.run_id, event)
            action = TrafficSimulationAction(
                action_id=generate_action_id(),
                action_type=ActionType.TRAFFIC_DIVERSION,
                target_ids=["R01", "R07", "R05"],
                parameters={"diversionRatio": 0.4},
                source="manual",
            )
            provider.apply_action(run.run_id, action)
            return provider.get_road_state(run.run_id, "R01")

        result1 = run_scenario()
        result2 = run_scenario()

        assert result1.avg_speed == result2.avg_speed
        assert result1.queue_length == result2.queue_length
        assert result1.congestion_level == result2.congestion_level
        assert result1.effective_capacity == result2.effective_capacity
        assert result1.occupancy == result2.occupancy
        assert result1.flow == result2.flow


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT: current_event 边界 — simulation 不污染 current_event
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditCurrentEventBoundary:
    """审计四：current_event 不被 simulation 污染。"""

    def test_simulation_refs_not_in_current_event(self):
        """simulation_refs 独立存储，不在 current_event 中。"""
        from backend.workflow.state import TrafficWorkflowState
        from backend.workflow.models import WorkflowRunStatus

        state = TrafficWorkflowState(
            workflow_run_id="wf_test",
            current_event={
                "eventId": "evt_001",
                "eventType": "accident",
                "roadName": "演示大道",
                "avgSpeed": 35.0,
            },
            simulation_refs={
                "simulationRunId": "simrun_test",
                "trafficEventId": "simevt_test",
                "snapshotId": "snap_test",
                "workflowRunId": "wf_test",
            },
        )

        # current_event 不包含 simulation 字段
        ce = state.current_event
        assert "simulationRunId" not in ce
        assert "snapshotId" not in ce
        assert "trafficEventId" not in ce
        assert "workflowRunId" not in ce
        assert "simulated" not in ce

        # simulation_refs 独立存在
        assert state.simulation_refs["simulationRunId"] == "simrun_test"

    def test_current_event_unchanged_after_simulation_ops(self, provider):
        """执行 simulation 操作后 current_event 原型不变。"""
        from backend.simulation.models import TrafficEvent, generate_event_id

        current_event = {
            "eventId": "evt_audit",
            "eventType": "accident",
            "roadName": "演示大道",
            "avgSpeed": 35.0,
        }
        before = dict(current_event)

        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Audit",
        )
        provider.inject_event(run.run_id, event)
        _ = provider.build_spatial_context(run.run_id, event.event_id)

        # current_event 未被修改
        assert current_event == before

    def test_simulation_context_model_separate(self):
        """SimulationContext Pydantic 模型字段独立于事件字段。"""
        from backend.simulation.models import SimulationContext
        ctx = SimulationContext(
            simulation_run_id="sr_1",
            traffic_event_id="te_1",
            snapshot_id="sn_1",
        )
        d = ctx.model_dump()
        # 不含事件字段
        assert "eventId" not in d
        assert "roadName" not in d
        assert "avgSpeed" not in d
        # 含 simulation 字段
        assert d["simulation_run_id"] == "sr_1"


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT: Snapshot append-only
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditSnapshotAppendOnly:
    """审计五：Snapshot append-only。"""

    def test_three_distinct_snapshot_ids(self, provider):
        """S0 normal, S1 accident, S2 action → 三条不同记录。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )
        run = provider.create_run("scenario_c_accident")
        s0 = provider.get_snapshot(run.run_id)
        assert s0.sequence == 0

        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Audit",
        )
        s1 = provider.inject_event(run.run_id, event)
        assert s1.sequence == 1
        assert s1.snapshot_id != s0.snapshot_id

        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07", "R05"],
            parameters={"diversionRatio": 0.4},
            source="manual",
        )
        s2 = provider.apply_action(run.run_id, action)
        assert s2.sequence == 2
        assert s2.snapshot_id != s1.snapshot_id
        assert s2.snapshot_id != s0.snapshot_id

    def test_historic_snapshots_unchanged(self, provider):
        """新快照不覆盖历史快照内容。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )
        run = provider.create_run("scenario_c_accident")
        s0 = provider.get_snapshot(run.run_id)
        s0_speed = s0.road_states["R01"].avg_speed

        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Audit",
        )
        provider.inject_event(run.run_id, event)
        # Read S0 again — must be unchanged
        s0_re_read = provider.get_snapshot_by_id(run.run_id, s0.snapshot_id)
        assert s0_re_read is not None
        assert s0_re_read.road_states["R01"].avg_speed == s0_speed
        assert s0_re_read.road_states["R01"].congestion_level.value == "normal"

        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07", "R05"],
            parameters={"diversionRatio": 0.4},
            source="manual",
        )
        provider.apply_action(run.run_id, action)
        # S0 still unchanged
        s0_final = provider.get_snapshot_by_id(run.run_id, s0.snapshot_id)
        assert s0_final is not None
        assert s0_final.road_states["R01"].avg_speed == s0_speed

    def test_before_after_snapshot_different(self, provider):
        """before_snapshot_id != after_snapshot_id。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )
        run = provider.create_run("scenario_c_accident")
        event = TrafficEvent(
            event_id=generate_event_id(),
            event_type="accident", severity="high", road_id="R01",
            longitude=116.397, latitude=39.907, description="Audit",
        )
        provider.inject_event(run.run_id, event)

        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07", "R05"],
            parameters={"diversionRatio": 0.4},
            source="manual",
        )
        provider.apply_action(run.run_id, action)
        assert action.before_snapshot_id != action.after_snapshot_id
        assert action.before_snapshot_id != ""
        assert action.after_snapshot_id != ""


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT: DemoSimulation 确定性 (跨 Run 对比)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditDeterminismCrossRun:
    """审计六：同一 Scenario + Event + Action → 两个独立 Run 结果一致。"""

    def test_full_determinism_across_runs(self, provider):
        """两个独立 Run，相同操作序列，所有指标一致。"""
        from backend.simulation.models import (
            TrafficEvent, TrafficSimulationAction,
            generate_event_id, generate_action_id, ActionType,
        )

        def run_full():
            run = provider.create_run("scenario_c_accident")
            event = TrafficEvent(
                event_id=generate_event_id(),
                event_type="accident", severity="high", road_id="R01",
                longitude=116.397, latitude=39.907, description="Audit",
            )
            provider.inject_event(run.run_id, event)
            action = TrafficSimulationAction(
                action_id=generate_action_id(),
                action_type=ActionType.TRAFFIC_DIVERSION,
                target_ids=["R01", "R07", "R05"],
                parameters={"diversionRatio": 0.4},
                source="manual",
            )
            provider.apply_action(run.run_id, action)
            return provider.get_road_state(run.run_id, "R01")

        r1 = run_full()
        r2 = run_full()

        for attr in ["avg_speed", "queue_length", "occupancy",
                      "effective_capacity", "vehicle_count", "flow"]:
            v1 = getattr(r1, attr)
            v2 = getattr(r2, attr)
            assert v1 == v2, f"{attr}: r1={v1} r2={v2} mismatch"
        assert r1.congestion_level == r2.congestion_level

    def test_camera_observation_deterministic(self, provider):
        """同一状态 → 同一 Camera 观测值一致。"""
        run1 = provider.create_run("scenario_c_accident")
        run2 = provider.create_run("scenario_c_accident")
        obs1 = provider.get_camera_observation(run1.run_id, "CAM01")
        obs2 = provider.get_camera_observation(run2.run_id, "CAM01")
        assert obs1.vehicle_count == obs2.vehicle_count
        assert obs1.avg_speed == obs2.avg_speed
        assert obs1.queue_length == obs2.queue_length

    def test_no_random_in_provider(self, provider):
        """Provider 中不引入 random。"""
        import inspect
        from backend.simulation import demo_provider as dp
        source = inspect.getsource(dp)
        assert "random" not in source.lower(), "Provider source contains 'random'"


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT: Agent 只读权限边界
# ═══════════════════════════════════════════════════════════════════════════════


class TestAuditAgentReadOnly:
    """审计三：Agent 只有只读权限。"""

    def test_tools_dont_expose_write_operations(self):
        """tools.py 不导出写操作函数。"""
        import backend.simulation.tools as st
        forbidden = [
            "apply_simulation_action",
            "apply_action",
            "execute_action",
            "modify_road_state",
            "set_signal",
            "inject_event",
        ]
        exported = [n for n in dir(st) if not n.startswith("_")]
        for name in forbidden:
            assert name not in exported, f"tools.py exports forbidden: {name}"

    def test_tools_only_readonly_in_registry(self):
        """SIMULATION_READONLY_TOOLS 注册表全部只读。"""
        from backend.simulation.tools import SIMULATION_READONLY_TOOLS
        for name, spec in SIMULATION_READONLY_TOOLS.items():
            assert name.startswith("get_"), \
                f"Tool '{name}' should be read-only (get_*)"

    def test_action_write_only_in_workflow(self):
        """写操作仅在 workflow/nodes/action.py 中。"""
        import ast, os
        # Check agent/ directory doesn't reference DemoSimulationProvider.apply_action
        agent_dir = os.path.join(
            os.path.dirname(__file__), "..", "agent"
        )
        for root, _, files in os.walk(agent_dir):
            for fname in files:
                if fname.endswith(".py"):
                    with open(os.path.join(root, fname), encoding="utf-8") as f:
                        content = f.read()
                    assert "apply_action" not in content or "DemoSimulationProvider" not in content, \
                        f"{os.path.join(root, fname)} should not call simulation write ops"
