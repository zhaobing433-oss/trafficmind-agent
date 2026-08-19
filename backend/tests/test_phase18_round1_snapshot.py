"""
Phase 18 Round 1 — PlannerCapabilitySnapshot 单元测试

覆盖：
  - snapshot deterministic + stable hash
  - planner-eligible = end-to-end 有真实执行器的 action
  - no-op capability（simulation_monitor/close/lane_control/dispatch_coordination）plannerEligible=false（P18）
  - prompt projection 不含 execution identifiers（P25）
  - is_planner_executable_action 单一判定复用
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.planning.capability_snapshot import (
    ACTION_CAPABILITY_MAP,
    AGENT_CAPABILITY_MAP,
    is_planner_executable_action,
    build_planner_capability_snapshot,
)


class TestSnapshotDeterminism:
    def test_snapshot_hash_stable(self):
        s1 = build_planner_capability_snapshot()
        s2 = build_planner_capability_snapshot()
        assert s1.snapshotHash == s2.snapshotHash
        assert s1.snapshotVersion == s2.snapshotVersion

    def test_snapshot_agents_ordered(self):
        # deterministic 固定顺序（非字母序，但稳定）
        s = build_planner_capability_snapshot()
        ids = [a.agentCapabilityId for a in s.agents]
        assert ids == ["congestion_analysis", "accident_analysis", "signal_analysis", "dispatch_analysis"]

    def test_agent_capabilities(self):
        s = build_planner_capability_snapshot()
        assert {a.agentCapabilityId for a in s.agents} == {
            "congestion_analysis", "accident_analysis", "signal_analysis", "dispatch_analysis"
        }
        assert all(a.plannerEligible for a in s.agents)


class TestEndToEndEligibility:
    """P18：无端到端真实业务语义的 capability → plannerEligible=false。"""

    def test_no_op_simulation_actions_ineligible(self):
        # DemoSimulationProvider no-op：monitor/close/lane_control/dispatch_coordination
        for at in [
            "simulation_monitor", "simulation_close",
            "simulation_lane_control", "simulation_dispatch_coordination",
        ]:
            assert not is_planner_executable_action(at), f"{at} 应为 no-op（ineligible）"

    def test_real_actions_eligible(self):
        for at in [
            "notify_wechat", "notify_dingtalk", "save_result",
            "simulation_traffic_diversion", "simulation_signal_adjustment",
        ]:
            assert is_planner_executable_action(at), f"{at} 应为端到端可执行"

    def test_snapshot_actions_only_eligible(self):
        s = build_planner_capability_snapshot()
        assert all(a.plannerEligible for a in s.actions)
        # no-op 不在 snapshot.actions
        action_ids = {a.actionCapabilityId for a in s.actions}
        assert "simulation_monitor" not in action_ids


class TestPromptProjection:
    """P25：public prompt projection 不得包含 execution identifiers / raw 标识。"""

    def test_prompt_projection_no_execution_identifiers(self):
        s = build_planner_capability_snapshot()
        public = s.to_prompt_dict()
        blob = str(public)

        # 不含 execution identifiers
        assert "executionAgentType" not in blob
        assert "executionActionType" not in blob
        # 不含 raw class/tool identifiers
        for raw in ["CongestionAgent", "AccidentAgent", "SignalAgent", "DispatchAgent",
                    "save_result", "simulation_traffic_diversion", "simulation_signal_adjustment"]:
            assert raw not in blob, f"prompt projection 泄露 raw identifier: {raw}"

    def test_prompt_projection_contains_public_fields(self):
        s = build_planner_capability_snapshot()
        public = s.to_prompt_dict()
        assert "agentCapabilityId" in str(public["agents"][0])
        assert "actionCapabilityId" in str(public["actions"][0])
        assert "businessParamSchema" in str(public["actions"][0])

    def test_execution_mapping_present_internal(self):
        # 内部对象保留 execution mapping（供 compiler）
        s = build_planner_capability_snapshot()
        by_id = {a.agentCapabilityId: a for a in s.agents}
        assert by_id["congestion_analysis"].executionAgentType == "CongestionAgent"
        by_action = {a.actionCapabilityId: a for a in s.actions}
        assert by_action["simulate_traffic_diversion"].executionActionType == "simulation_traffic_diversion"


class TestCapabilityMaps:
    def test_agent_capability_map_covers_agents(self):
        assert AGENT_CAPABILITY_MAP["congestion_analysis"] == "CongestionAgent"

    def test_action_capability_map_covers_actions(self):
        assert ACTION_CAPABILITY_MAP["simulate_traffic_diversion"] == "simulation_traffic_diversion"
