"""
Phase 17 Round 1 — Adapter 单元测试

覆盖：
  - 依赖方向（P16）：B.dependsOn=[A] → A.next_nodes=[B]，不反向
  - definition_id == planId
  - 入口 TRIGGER + 出口 CLOSE
  - high-risk action → 独立 approval gate（action_types 只含对应 actionType）
  - definition.validate() 通过
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.planning.adapter import plan_to_definition
from backend.planning.models import (
    GoalType,
    Plan,
    PlanDefinitionStatus,
    PlanStep,
    compute_fingerprint,
)
from backend.workflow.models import DefinitionStatus, NodeType


def _plan(steps, plan_id="plan_adapter_1") -> Plan:
    return Plan(
        planId=plan_id,
        planFingerprint=compute_fingerprint(steps),
        goal="测试",
        goalType=GoalType.GENERIC,
        definitionStatus=PlanDefinitionStatus.ACTIVE,
        version=1,
        steps=steps,
    )


class TestDependencyDirection:
    def test_a_b_c_direction(self):
        # A → B → C：B.dependsOn=[A], C.dependsOn=[B]
        steps = [
            PlanStep(stepId="A", stepType=NodeType.VALIDATE_EVENT),
            PlanStep(stepId="B", stepType=NodeType.RULE_ROUTER, dependsOn=["A"]),
            PlanStep(stepId="C", stepType=NodeType.CLOSE, dependsOn=["B"]),
        ]
        d = plan_to_definition(_plan(steps))
        node = {n.node_id: n for n in d.nodes}
        # 严格方向：A.next = [B], B.next = [C]，不得反向
        assert node["A"].next_nodes == ["B"]
        assert node["B"].next_nodes == ["C"]
        assert node["C"].next_nodes == []
        # 不得出现 B.next 包含 A
        assert "A" not in node["B"].next_nodes


class TestDefinitionMapping:
    def test_definition_id_equals_plan_id(self):
        steps = [
            PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT),
            PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["validate_event"]),
        ]
        d = plan_to_definition(_plan(steps, plan_id="plan_xyz"))
        assert d.id == "plan_xyz"
        assert d.entry_node_id == "trigger"
        assert d.status == DefinitionStatus.ACTIVE

    def test_validate_passes(self):
        steps = [
            PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT),
            PlanStep(stepId="rule_router", stepType=NodeType.RULE_ROUTER, dependsOn=["validate_event"]),
            PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["rule_router"]),
        ]
        d = plan_to_definition(_plan(steps))
        assert d.validate() == []


class TestApprovalGateMapping:
    def test_high_risk_action_gets_dedicated_gate(self):
        steps = [
            PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT),
            PlanStep(stepId="risk_gate", stepType=NodeType.RISK_GATE, dependsOn=["validate_event"]),
            PlanStep(stepId="human_approval_notify_wechat", stepType=NodeType.HUMAN_APPROVAL,
                     actionType="notify_wechat", riskLevel="high_risk", approvalRequired=True,
                     dependsOn=["risk_gate"]),
            PlanStep(stepId="action_notify_wechat", stepType=NodeType.ACTION,
                     actionType="notify_wechat", toolName="notify_wechat",
                     riskLevel="high_risk", approvalRequired=True,
                     dependsOn=["human_approval_notify_wechat"]),
            PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["action_notify_wechat"]),
        ]
        d = plan_to_definition(_plan(steps))
        node = {n.node_id: n for n in d.nodes}
        approval = node["human_approval_notify_wechat"]
        # approval node 只声明其对应 actionType，不压多个
        assert approval.config["action_types"] == ["notify_wechat"]
        # 依赖方向：approval → action
        assert approval.next_nodes == ["action_notify_wechat"]
        # risk_gate 有 condition
        assert node["risk_gate"].condition == "requires_approval"
