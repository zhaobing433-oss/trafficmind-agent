"""
Phase 18 Round 1 — Approval Identity V2 单元测试

覆盖 P16（runtime）/ P17 / legacy V1 兼容 / duplicate_semantic_action：
  - V2 exact actionStepId 匹配
  - V2 缺 actionStepId → 不 fallback actionType（fail closed）
  - legacy V1 actionType 匹配（回归）
  - 批准 A 不得授权 B（P17）
  - 同 actionType 同 params 同 objective → duplicate_semantic_action（compiler 拒绝）
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.workflow.models import NodeConfig, NodeType
from backend.workflow.state import TrafficWorkflowState
from backend.workflow.nodes.action import is_current_action_approved

from backend.planning.capability_snapshot import build_planner_capability_snapshot
from backend.planning.context import build_planning_context
from backend.planning.proposal import PlannerFailure, PlannerFailureCode, PlanProposal, PlanProposalStep
from backend.planning.proposal_compiler import compile_proposal


def _v2_config(node_id: str) -> NodeConfig:
    return NodeConfig(node_id=node_id, node_type=NodeType.ACTION,
                      config={"approval_identity_version": 2, "action_type": "notify_wechat"})


def _v1_config(node_id: str) -> NodeConfig:
    return NodeConfig(node_id=node_id, node_type=NodeType.ACTION,
                      config={"action_type": "notify_wechat"})


class TestApprovalV2ExactMatch:
    def test_v2_exact_action_step_id_match(self):
        state = TrafficWorkflowState()
        state.approved_actions = [
            {"actionType": "notify_wechat", "actionStepId": "action_notify_wechat_01", "source": "compiled_plan"},
        ]
        assert is_current_action_approved(state, "notify_wechat", _v2_config("action_notify_wechat_01"))

    def test_p17_approve_A_does_not_authorize_B(self):
        state = TrafficWorkflowState()
        state.approved_actions = [
            {"actionType": "notify_wechat", "actionStepId": "action_notify_wechat_01", "source": "compiled_plan"},
        ]
        assert is_current_action_approved(state, "notify_wechat", _v2_config("action_notify_wechat_01"))
        # 同 actionType 但不同 instance → 未批准
        assert not is_current_action_approved(state, "notify_wechat", _v2_config("action_notify_wechat_02"))

    def test_v2_no_action_step_id_no_fallback(self):
        # V2 缺 actionStepId → 绝不 fallback actionType
        state = TrafficWorkflowState()
        state.approved_actions = [
            {"actionType": "notify_wechat", "source": "workflow_template"},  # 无 actionStepId
        ]
        assert not is_current_action_approved(state, "notify_wechat", _v2_config("action_notify_wechat_01"))

    def test_v2_empty_approved(self):
        state = TrafficWorkflowState()
        state.approved_actions = []
        assert not is_current_action_approved(state, "notify_wechat", _v2_config("action_notify_wechat_01"))


class TestLegacyV1:
    def test_v1_action_type_match(self):
        # legacy V1：actionType 匹配（回归）
        state = TrafficWorkflowState()
        state.approved_actions = [
            {"actionType": "notify_wechat", "source": "workflow_template"},
        ]
        assert is_current_action_approved(state, "notify_wechat", _v1_config("action_x"))

    def test_v1_action_type_mismatch(self):
        state = TrafficWorkflowState()
        state.approved_actions = [
            {"actionType": "notify_dingtalk", "source": "workflow_template"},
        ]
        assert not is_current_action_approved(state, "notify_wechat", _v1_config("action_x"))


class TestDuplicateSemanticAction:
    def _accident_ctx(self):
        return build_planning_context({
            "eventId": "E_ACC", "eventType": "accident", "roadName": "A路",
            "avgSpeed": 8, "queueLength": 150, "duration": 600,
            "isMainRoad": True, "nearbyHospital": True,
        }, user_goal="通知")

    def test_duplicate_semantic_action_rejected(self):
        snap = build_planner_capability_snapshot()
        ctx = self._accident_ctx()
        proposal = PlanProposal(
            proposalId="p1", goal="通知", goalSummary="通知",
            steps=[
                PlanProposalStep(proposalStepId="s1", intent="notify A",
                                 actionIntent="notify", requiredCapabilities=["notify_wechat"],
                                 expectedOutcome="通知相关人员"),
                PlanProposalStep(proposalStepId="s2", intent="notify B",
                                 actionIntent="notify", requiredCapabilities=["notify_wechat"],
                                 expectedOutcome="通知相关人员"),  # same objective + same params
            ],
            confidence=0.9, plannerModel="fake", plannerReasonSummary="test",
            capabilitySnapshotHash=snap.snapshotHash,
        )
        with pytest.raises(PlannerFailure) as ei:
            compile_proposal(proposal, snap, ctx)
        # compiler 复用 validate_plan → duplicate_semantic_action 归为 COMPILE_ERROR
        assert ei.value.code == PlannerFailureCode.COMPILE_ERROR
        assert "duplicate_semantic_action" in ei.value.message


class TestPlanIdentityVersion:
    def test_deterministic_plan_v1(self):
        # deterministic build_plan 保持 approvalIdentityVersion=1（legacy 兼容）
        from backend.planning.planner import build_plan
        ctx = build_planning_context({
            "eventId": "E_CONG", "eventType": "congestion", "roadName": "C路",
            "avgSpeed": 8, "queueLength": 200, "duration": 1200,
        })
        plan = build_plan(ctx)
        assert plan.approvalIdentityVersion == 1

    def test_compiled_plan_v2(self):
        snap = build_planner_capability_snapshot()
        ctx = build_planning_context({
            "eventId": "E_ACC", "eventType": "accident", "roadName": "A路",
            "avgSpeed": 8, "queueLength": 150, "duration": 600, "nearbyHospital": True,
        }, user_goal="分析事故")
        proposal = PlanProposal(
            proposalId="p1", goal="分析事故", goalSummary="分析事故",
            steps=[PlanProposalStep(proposalStepId="s1", intent="analyze accident",
                                    requiredCapabilities=["accident_analysis"])],
            confidence=0.9, plannerModel="fake", plannerReasonSummary="test",
            capabilitySnapshotHash=snap.snapshotHash,
        )
        plan = compile_proposal(proposal, snap, ctx)
        assert plan.approvalIdentityVersion == 2
