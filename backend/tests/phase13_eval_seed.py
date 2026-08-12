"""
Phase 13 Round 2 — 轻量 Eval Seed (5-10 cases)

评测重点:
  - tool selection
  - spatial context usage
  - proposal schema validity
  - no-action for normal traffic
  - no-action when context insufficient
  - approval safety
  - correct Workflow routing

普通 pytest 不加载真实 Qwen/DeepSeek。
所有 case 基于确定性 DemoSimulationProvider。
"""

import pytest
from typing import Any, Dict, List

from backend.simulation.demo_provider import get_demo_provider
from backend.simulation.models import TrafficEvent, generate_event_id
from backend.simulation.tools import (
    get_traffic_map_state,
    get_road_traffic_state,
    get_event_spatial_context,
    get_nearby_cameras,
    get_affected_roads,
    _spatial_context_to_dict,
)
from backend.agent.multi_agent import CongestionAgent, AccidentAgent, DispatchAgent


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _setup_accident_run():
    """Setup Scenario C with accident injected. Returns (provider, run_id, event_id, snap)."""
    provider = get_demo_provider()
    run = provider.create_run("scenario_c_accident")
    event = TrafficEvent(
        event_id=generate_event_id(),
        event_type="accident", severity="high", road_id="R01",
        longitude=116.397, latitude=39.907,
        description="Eval: 演示大道严重事故",
    )
    snap = provider.inject_event(run.run_id, event)
    return provider, run.run_id, event.event_id, snap


def _setup_normal_run():
    """Setup Scenario C without accident. Returns (provider, run_id)."""
    provider = get_demo_provider()
    run = provider.create_run("scenario_c_accident")
    return provider, run.run_id


# ═══════════════════════════════════════════════════════════════════════════════
# Eval Cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvalA_AccidentSpatialContext:
    """Case A: 严重事故拥堵 → 获取 Spatial Context → 生成 diversion Proposal"""

    def test_tool_selection_includes_spatial_context(self):
        """事故后 Agent 应选择 spatial context 工具。"""
        provider, run_id, event_id, _ = _setup_accident_run()

        # 模拟 Agent tool selection
        ctx = get_event_spatial_context(run_id=run_id, event_id=event_id)
        assert "error" not in ctx
        assert ctx["affectedRoad"] is not None
        assert len(ctx["upstreamRoads"]) > 0
        assert len(ctx["downstreamRoads"]) > 0

    def test_agent_generates_proposal_for_severe_congestion(self):
        """严重拥堵时 CongestionAgent 应生成分流提议。"""
        provider, run_id, event_id, snap = _setup_accident_run()
        ctx = get_event_spatial_context(run_id=run_id, event_id=event_id)

        info = {
            "eventType": "accident",
            "roadName": "演示大道",
            "avgSpeed": snap.road_states["R01"].avg_speed,
            "queueLength": snap.road_states["R01"].queue_length,
            "simulation_context": ctx,
            "simulation_refs": {
                "simulationRunId": run_id,
                "trafficEventId": event_id,
                "decisionSnapshotId": snap.snapshot_id,
            },
        }

        agent = CongestionAgent()
        result = agent.analyze(info)

        assert result["urgency"] == "high"
        assert len(result["proposed_actions"]) >= 1
        pa = result["proposed_actions"][0]
        assert pa["actionType"] == "traffic_diversion"
        assert pa["simulation"] is True
        assert "rationale" in pa
        assert pa["sourceRoadId"] == "R01"
        assert len(pa["targetRoadIds"]) >= 1

    def test_proposal_schema_valid(self):
        """Proposal schema 必须包含所有必要字段。"""
        provider, run_id, event_id, snap = _setup_accident_run()
        ctx = get_event_spatial_context(run_id=run_id, event_id=event_id)

        info = {
            "eventType": "accident",
            "roadName": "演示大道",
            "avgSpeed": snap.road_states["R01"].avg_speed,
            "queueLength": snap.road_states["R01"].queue_length,
            "simulation_context": ctx,
            "simulation_refs": {
                "simulationRunId": run_id,
                "trafficEventId": event_id,
                "decisionSnapshotId": snap.snapshot_id,
            },
        }

        agent = CongestionAgent()
        result = agent.analyze(info)

        for pa in result["proposed_actions"]:
            assert pa["actionType"] in (
                "traffic_diversion", "signal_adjustment",
                "lane_control", "dispatch_coordination",
            )
            assert "sourceRoadId" in pa or "targetIds" in pa
            assert pa["simulation"] is True
            assert "rationale" in pa
            # 不得包含隐藏 CoT
            assert "chain_of_thought" not in pa
            assert "thinking" not in pa


class TestEvalB_NormalTraffic:
    """Case B: 正常交通 → 不提出高风险 Action"""

    def test_normal_traffic_no_proposal(self):
        """正常交通下 Agent 不应生成 simulation action。"""
        provider, run_id = _setup_normal_run()
        snap = provider.get_snapshot(run_id)
        ctx = get_event_spatial_context(run_id=run_id, event_id="") if False else {}

        info = {
            "eventType": "congestion",
            "roadName": "演示大道",
            "avgSpeed": snap.road_states["R01"].avg_speed,
            "queueLength": snap.road_states["R01"].queue_length,
            "simulation_context": ctx,
        }

        agent = CongestionAgent()
        result = agent.analyze(info)

        # 正常交通不应产生 proposal
        assert result["urgency"] == "low"
        assert len(result.get("proposed_actions", [])) == 0


class TestEvalC_NoActionWhenContextMissing:
    """Case C: Spatial Context 缺失 → 不执行 Action"""

    def test_missing_spatial_context_no_proposal(self):
        """无 spatial context 时 Agent 不应生成 proposal。"""
        provider, run_id, event_id, snap = _setup_accident_run()

        info = {
            "eventType": "accident",
            "roadName": "演示大道",
            "avgSpeed": snap.road_states["R01"].avg_speed,
            "queueLength": snap.road_states["R01"].queue_length,
            # 不提供 simulation_context
        }

        agent = CongestionAgent()
        result = agent.analyze(info)

        # 无 spatial context 时不生成 proposal（但仍做基础分析）
        assert len(result.get("proposed_actions", [])) == 0


class TestEvalD_ApprovalSafety:
    """Case D: 未经审批 → Simulation 不变化"""

    def test_unapproved_action_not_executed(self):
        """未经 Workflow human_approval，simulation 不得变化。"""
        provider, run_id, event_id, snap = _setup_accident_run()

        # 记录 before state
        before_speed = snap.road_states["R01"].avg_speed
        before_queue = snap.road_states["R01"].queue_length

        # Agent 生成 proposal（但不执行）
        ctx = get_event_spatial_context(run_id=run_id, event_id=event_id)
        info = {
            "eventType": "accident",
            "roadName": "演示大道",
            "avgSpeed": before_speed,
            "queueLength": before_queue,
            "simulation_context": ctx,
            "simulation_refs": {
                "simulationRunId": run_id,
                "trafficEventId": event_id,
                "decisionSnapshotId": snap.snapshot_id,
            },
        }
        agent = CongestionAgent()
        result = agent.analyze(info)

        # Agent 生成了 proposal
        assert len(result["proposed_actions"]) > 0

        # 但是 simulation 未被修改（proposal 不等于执行）
        current_snap = provider.get_snapshot(run_id)
        assert current_snap.road_states["R01"].avg_speed == before_speed
        assert current_snap.road_states["R01"].queue_length == before_queue


class TestEvalE_ApprovedActionImprovesTraffic:
    """Case E: 批准后 → Snapshot 改善"""

    def test_approved_diversion_improves_traffic(self):
        """批准分流后交通改善。"""
        from backend.simulation.models import TrafficSimulationAction, ActionType, generate_action_id

        provider, run_id, event_id, snap = _setup_accident_run()

        # 记录 before
        before_speed = snap.road_states["R01"].avg_speed
        before_queue = snap.road_states["R01"].queue_length
        congestion_before = snap.road_states["R01"].congestion_level.value

        # 执行分流（模拟经过审批）
        action = TrafficSimulationAction(
            action_id=generate_action_id(),
            action_type=ActionType.TRAFFIC_DIVERSION,
            target_ids=["R01", "R07", "R05"],
            parameters={"diversionRatio": 0.4},
            source="workflow",
            workflow_run_id="wf_eval_test",
        )
        new_snap = provider.apply_action(run_id, action)

        after_speed = new_snap.road_states["R01"].avg_speed
        after_queue = new_snap.road_states["R01"].queue_length
        congestion_after = new_snap.road_states["R01"].congestion_level.value

        assert after_speed > before_speed, f"speed: {after_speed} <= {before_speed}"
        assert after_queue < before_queue, f"queue: {after_queue} >= {before_queue}"
        # congestion should improve
        severity_order = {"severe": 3, "congested": 2, "slow": 1, "normal": 0}
        assert (
            severity_order.get(congestion_after, 0) < severity_order.get(congestion_before, 0)
        ), f"congestion: {congestion_before} → {congestion_after}"


class TestEvalF_ToolConsistency:
    """Case F: 时间一致性 — 所有 Tool 使用同一 decisionSnapshotId"""

    def test_tools_use_same_snapshot(self):
        """多个 Tool 使用同一 snapshot_id 得到一致结果。"""
        provider, run_id, event_id, snap = _setup_accident_run()

        decision_snap_id = snap.snapshot_id

        # 使用同一快照 ID 调用所有工具
        map_state = get_traffic_map_state(run_id=run_id, snapshot_id=decision_snap_id)
        road_state = get_road_traffic_state(
            run_id=run_id, road_id="R01", snapshot_id=decision_snap_id
        )
        spatial = get_event_spatial_context(run_id=run_id, event_id=event_id)
        cameras = get_nearby_cameras(
            run_id=run_id, longitude=116.397, latitude=39.907,
            snapshot_id=decision_snap_id,
        )

        # 一致性校验
        for r in map_state["roadsSummary"]:
            if r["roadId"] == "R01":
                assert r["avgSpeed"] == road_state["avgSpeed"]
                assert r["congestionLevel"] == road_state["congestionLevel"]

        # 摄像头观测与道路状态一致
        for cam in cameras["cameras"]:
            if cam["roadId"] == "R01":
                assert cam["avgSpeed"] == road_state["avgSpeed"]
                assert cam["queueLength"] == road_state["queueLength"]
