"""
Phase 17 Round 1 — Validator 单元测试

覆盖 fail-closed 校验：
  - 合法计划通过
  - unknown tool → ERROR（P04/P18）
  - high-risk 审批标注（P05）
  - 循环依赖拒绝（P06）
  - 缺失依赖拒绝（P07）
  - 同 actionType 双 high-risk → ERROR（P22）
  - 不同 high-risk 各自独立门禁（P23）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.planning.models import (
    GoalType,
    Plan,
    PlanDefinitionStatus,
    PlanStep,
    compute_fingerprint,
)
from backend.planning.validator import has_errors, validate_plan
from backend.workflow.models import NodeType


def _step(step_id, step_type, **kw) -> PlanStep:
    return PlanStep(stepId=step_id, stepType=step_type, **kw)


def _plan(steps) -> Plan:
    return Plan(
        planId="plan_v",
        planFingerprint=compute_fingerprint(steps),
        goal="测试",
        goalType=GoalType.GENERIC,
        definitionStatus=PlanDefinitionStatus.DRAFT,
        version=1,
        steps=steps,
    )


def _valid_steps() -> list:
    return [
        _step("validate_event", NodeType.VALIDATE_EVENT),
        _step("rule_router", NodeType.RULE_ROUTER, dependsOn=["validate_event"]),
        _step("agent_x", NodeType.AGENT_TASK, agentType="CongestionAgent", dependsOn=["rule_router"]),
        _step("risk_gate", NodeType.RISK_GATE, dependsOn=["agent_x"]),
        _step("action_save", NodeType.ACTION, actionType="save_result", toolName="save_result", riskLevel="write", approvalRequired=False, dependsOn=["risk_gate"]),
        _step("close", NodeType.CLOSE, dependsOn=["action_save"]),
    ]


class TestValidPlan:
    def test_valid_passes(self):
        assert not has_errors(validate_plan(_plan(_valid_steps())))


class TestUnknownTool:
    def test_unknown_tool_error(self):
        steps = _valid_steps()
        steps[-2] = _step(
            "action_bad", NodeType.ACTION, actionType="totally_unknown_tool",
            toolName="totally_unknown_tool", riskLevel="unknown", approvalRequired=False,
            dependsOn=["risk_gate"],
        )
        steps[-1] = _step("close", NodeType.CLOSE, dependsOn=["action_bad"])
        issues = validate_plan(_plan(steps))
        assert any(i.code == "unknown_tool" and i.severity.value == "error" for i in issues)
        assert has_errors(issues)


class TestHighRiskAnnotation:
    def test_high_risk_requires_approval(self):
        steps = _valid_steps()
        # 高风险 notify，approvalRequired=False → high_risk_missing_approval（禁止绕过）
        steps.insert(-1, _step(
            "action_notify", NodeType.ACTION, actionType="notify_wechat",
            toolName="notify_wechat", riskLevel="high_risk", approvalRequired=False,
            dependsOn=["risk_gate"],
        ))
        steps[-1] = _step("close", NodeType.CLOSE, dependsOn=["action_notify"])
        codes = {i.code for i in validate_plan(_plan(steps))}
        assert "high_risk_missing_approval" in codes

    def test_high_risk_missing_gate(self):
        steps = _valid_steps()
        # 高风险 notify，approvalRequired=True 但缺独立 human_approval gate
        steps.insert(-1, _step(
            "action_notify", NodeType.ACTION, actionType="notify_wechat",
            toolName="notify_wechat", riskLevel="high_risk", approvalRequired=True,
            dependsOn=["risk_gate"],
        ))
        steps[-1] = _step("close", NodeType.CLOSE, dependsOn=["action_notify"])
        codes = {i.code for i in validate_plan(_plan(steps))}
        assert "missing_approval_gate" in codes


class TestCyclic:
    def test_cyclic_rejected(self):
        steps = [
            _step("a", NodeType.VALIDATE_EVENT, dependsOn=["b"]),
            _step("b", NodeType.CLOSE, dependsOn=["a"]),
        ]
        issues = validate_plan(_plan(steps))
        assert any(i.code == "cyclic_dependency" for i in issues)


class TestMissingDependency:
    def test_missing_dependency_rejected(self):
        steps = [
            _step("a", NodeType.VALIDATE_EVENT, dependsOn=["nonexistent"]),
            _step("b", NodeType.CLOSE, dependsOn=["a"]),
        ]
        issues = validate_plan(_plan(steps))
        assert any(i.code == "missing_dependency" for i in issues)


class TestDuplicateHighRisk:
    def test_duplicate_same_action_type_fail_closed(self):
        steps = _valid_steps()
        steps.insert(-1, _step(
            "human_approval_notify", NodeType.HUMAN_APPROVAL, actionType="notify_wechat",
            riskLevel="high_risk", approvalRequired=True, dependsOn=["risk_gate"],
        ))
        steps.insert(-1, _step(
            "action_notify_1", NodeType.ACTION, actionType="notify_wechat",
            toolName="notify_wechat", riskLevel="high_risk", approvalRequired=True,
            dependsOn=["human_approval_notify"],
        ))
        steps.insert(-1, _step(
            "action_notify_2", NodeType.ACTION, actionType="notify_wechat",
            toolName="notify_wechat", riskLevel="high_risk", approvalRequired=True,
            dependsOn=["action_notify_1"],
        ))
        steps[-1] = _step("close", NodeType.CLOSE, dependsOn=["action_notify_2"])
        issues = validate_plan(_plan(steps))
        assert any(i.code == "duplicate_high_risk_action_type" for i in issues)


class TestIndependentGates:
    def test_two_distinct_high_risk_actions(self):
        # 两个不同 high-risk action，各自独立 approval gate → 合法
        steps = [
            _step("validate_event", NodeType.VALIDATE_EVENT),
            _step("risk_gate", NodeType.RISK_GATE, dependsOn=["validate_event"]),
            _step("human_approval_a", NodeType.HUMAN_APPROVAL, actionType="notify_wechat", riskLevel="high_risk", approvalRequired=True, dependsOn=["risk_gate"]),
            _step("action_a", NodeType.ACTION, actionType="notify_wechat", toolName="notify_wechat", riskLevel="high_risk", approvalRequired=True, dependsOn=["human_approval_a"]),
            _step("human_approval_b", NodeType.HUMAN_APPROVAL, actionType="simulation_monitor", riskLevel="high_risk", approvalRequired=True, dependsOn=["action_a"]),
            _step("action_b", NodeType.ACTION, actionType="simulation_monitor", toolName="simulation_monitor", riskLevel="high_risk", approvalRequired=True, dependsOn=["human_approval_b"]),
            _step("close", NodeType.CLOSE, dependsOn=["action_b"]),
        ]
        issues = validate_plan(_plan(steps))
        assert not has_errors(issues), [i.to_dict() for i in issues]
