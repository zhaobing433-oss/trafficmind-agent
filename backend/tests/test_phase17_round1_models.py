"""
Phase 17 Round 1 — Plan/PlanStep 模型单元测试

覆盖：
  - Plan/PlanStep 序列化往返
  - 枚举（terminal / non-terminal 集合）
  - fingerprint 确定性 + 结构敏感性
  - create_revision（同 lineage：planId 稳定，version+1，fingerprint 变）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.planning.models import (
    TERMINAL_STEP_STATUSES,
    NON_TERMINAL_STEP_STATUSES,
    GoalType,
    Plan,
    PlanDefinitionStatus,
    PlanStep,
    PlanStepStatus,
    PlanningMode,
    compute_fingerprint,
    create_revision,
    generate_plan_id,
)
from backend.workflow.models import NodeType


def _step(step_id: str, step_type: NodeType = NodeType.VALIDATE_EVENT, **kw) -> PlanStep:
    return PlanStep(stepId=step_id, stepType=step_type, **kw)


def _plan(steps) -> Plan:
    return Plan(
        planId="plan_test_0001",
        planFingerprint=compute_fingerprint(steps),
        goal="测试",
        goalType=GoalType.GENERIC,
        definitionStatus=PlanDefinitionStatus.DRAFT,
        version=1,
        steps=steps,
    )


class TestPlanStepStatus:
    def test_terminal_set(self):
        assert PlanStepStatus.BLOCKED in TERMINAL_STEP_STATUSES
        assert PlanStepStatus.DENIED in TERMINAL_STEP_STATUSES
        assert PlanStepStatus.SUCCEEDED in TERMINAL_STEP_STATUSES
        assert PlanStepStatus.FAILED in TERMINAL_STEP_STATUSES
        assert PlanStepStatus.SKIPPED in TERMINAL_STEP_STATUSES
        assert PlanStepStatus.CANCELLED in TERMINAL_STEP_STATUSES

    def test_non_terminal_set(self):
        assert PlanStepStatus.PENDING in NON_TERMINAL_STEP_STATUSES
        assert PlanStepStatus.READY in NON_TERMINAL_STEP_STATUSES
        assert PlanStepStatus.RUNNING in NON_TERMINAL_STEP_STATUSES
        assert PlanStepStatus.AWAITING_APPROVAL in NON_TERMINAL_STEP_STATUSES
        # 无交集
        assert not (TERMINAL_STEP_STATUSES & NON_TERMINAL_STEP_STATUSES)


class TestPlanStepRoundtrip:
    def test_roundtrip(self):
        s = PlanStep(
            stepId="action_notify_wechat",
            stepType=NodeType.ACTION,
            objective="通知",
            dependsOn=["risk_gate"],
            actionType="notify_wechat",
            toolName="notify_wechat",
            riskLevel="high_risk",
            approvalRequired=True,
            retryPolicy={"maxRetries": 1},
        )
        d = s.to_dict()
        s2 = PlanStep.from_dict(d)
        assert s2.stepId == s.stepId
        assert s2.stepType == NodeType.ACTION
        assert s2.dependsOn == ["risk_gate"]
        assert s2.actionType == "notify_wechat"
        assert s2.approvalRequired is True
        assert s2.riskLevel == "high_risk"


class TestPlanRoundtrip:
    def test_roundtrip(self):
        steps = [
            _step("validate_event"),
            _step("close", NodeType.CLOSE, dependsOn=["validate_event"]),
        ]
        p = _plan(steps)
        p.definitionStatus = PlanDefinitionStatus.ACTIVE
        d = p.to_dict()
        p2 = Plan.from_dict(d)
        assert p2.planId == p.planId
        assert p2.planFingerprint == p.planFingerprint
        assert p2.version == 1
        assert p2.definitionStatus == PlanDefinitionStatus.ACTIVE
        assert [s.stepId for s in p2.steps] == ["validate_event", "close"]


class TestFingerprint:
    def test_deterministic(self):
        steps = [_step("a"), _step("b", NodeType.CLOSE, dependsOn=["a"])]
        assert compute_fingerprint(steps) == compute_fingerprint(steps)

    def test_structure_change_changes_fingerprint(self):
        steps1 = [_step("a"), _step("b", NodeType.CLOSE, dependsOn=["a"])]
        steps2 = [_step("a"), _step("b", NodeType.CLOSE, dependsOn=["a"], objective="changed")]
        assert compute_fingerprint(steps1) != compute_fingerprint(steps2)

    def test_objective_change_changes_fingerprint(self):
        s1 = _step("a", objective="x")
        s2 = _step("a", objective="y")
        assert compute_fingerprint([s1]) != compute_fingerprint([s2])


class TestCreateRevision:
    def test_stable_plan_id_version_bump(self):
        steps = [_step("a"), _step("close", NodeType.CLOSE, dependsOn=["a"])]
        p = _plan(steps)
        new_steps = [
            _step("a"),
            _step("b", NodeType.RULE_ROUTER, dependsOn=["a"]),
            _step("close", NodeType.CLOSE, dependsOn=["b"]),
        ]
        r = create_revision(p, new_steps)
        assert r.planId == p.planId          # 同 lineage
        assert r.version == p.version + 1    # 版本递增
        assert r.planFingerprint != p.planFingerprint  # 结构变化

    def test_unchanged_steps_same_fingerprint(self):
        steps = [_step("a"), _step("close", NodeType.CLOSE, dependsOn=["a"])]
        p = _plan(steps)
        r = create_revision(p, steps)
        assert r.planId == p.planId
        assert r.version == p.version + 1
        assert r.planFingerprint == p.planFingerprint


class TestGeneratePlanId:
    def test_format_and_uniqueness(self):
        a = generate_plan_id()
        b = generate_plan_id()
        assert a.startswith("plan_")
        assert a != b
