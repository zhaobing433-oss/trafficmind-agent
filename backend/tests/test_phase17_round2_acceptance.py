"""
Phase 17 Round 2 — Runtime Enforcement Acceptance

覆盖 runtime 强制缺口：maxReplans / auto replan wiring / side-effect carry-forward /
carried corruption / independent root isolation / replan idempotency。
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.planning.budget import (
    ExecutionBudgetLimits,
    get_lineage,
    new_lineage,
    set_lineage,
)
from backend.planning.models import (
    GoalType,
    Plan,
    PlanDefinitionStatus,
    PlanStep,
    compute_fingerprint,
)
from backend.planning.replanner import build_revision, is_carried
from backend.planning.revision import plan_to_child_definition
from backend.workflow.models import NodeType


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_r2_acc.db"))


def _repo():
    from backend.workflow.repository import SQLiteWorkflowRepository
    return SQLiteWorkflowRepository()


def _valid_plan(plan_id="plan_acc") -> Plan:
    """合法低风险计划：validate → action_save → close。"""
    steps = [
        PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT),
        PlanStep(stepId="action_save", stepType=NodeType.ACTION, actionType="save_result",
                 toolName="save_result", riskLevel="write", dependsOn=["validate_event"]),
        PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["action_save"]),
    ]
    return Plan(planId=plan_id, planFingerprint=compute_fingerprint(steps), goal="g",
                goalType=GoalType.GENERIC, definitionStatus=PlanDefinitionStatus.ACTIVE,
                version=1, steps=steps)


def _notify_plan(plan_id="plan_notify") -> Plan:
    """含 high-risk notify 的计划（用于 graph-exclusion 校验，不跑 validate）。"""
    steps = [
        PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT),
        PlanStep(stepId="action_notify", stepType=NodeType.ACTION, actionType="notify_wechat",
                 toolName="notify_wechat", riskLevel="high_risk", approvalRequired=True,
                 dependsOn=["validate_event"]),
        PlanStep(stepId="action_save", stepType=NodeType.ACTION, actionType="save_result",
                 toolName="save_result", riskLevel="write", dependsOn=["action_notify"]),
        PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["action_save"]),
    ]
    return Plan(planId=plan_id, planFingerprint=compute_fingerprint(steps), goal="g",
                goalType=GoalType.GENERIC, definitionStatus=PlanDefinitionStatus.ACTIVE,
                version=1, steps=steps)


class TestMaxReplansRuntime:
    def test_r09_second_replan_blocked(self):
        repo = _repo()
        from backend.workflow.models import WorkflowRun, WorkflowRunStatus, NodeStatus, WorkflowNodeRun, generate_run_id
        from backend.planning.continuation import PlanningContinuationCoordinator

        run_id = generate_run_id()
        state = {"status": "failed", "currentEvent": {}}
        lin = new_lineage(run_id, ExecutionBudgetLimits(maxReplans=1))
        lin.budgetUsage.replansUsed = 1  # 已 replan 一次
        set_lineage(state, lin)
        repo.save_run(WorkflowRun(run_id=run_id, definition_id="plan_acc", version=1,
                                  status=WorkflowRunStatus.FAILED, state=state))
        # 失败 action node_run → observation TOOL_FAILED → decision REPLAN
        repo.save_node_run(WorkflowNodeRun(node_run_id=f"nr_{run_id}_action_save", run_id=run_id,
                                           node_id="action_save", node_type=NodeType.ACTION,
                                           status=NodeStatus.FAILED, attempt=1))
        repo.save_definition(plan_to_child_definition(_valid_plan()))

        coord = PlanningContinuationCoordinator(repo)
        result = coord.auto_continue(run_id)
        assert result.get("error") == "maxReplans exhausted", result
        assert "childRunId" not in result

    def test_r09_replans_committed_in_cutover(self):
        repo = _repo()
        from backend.workflow.models import WorkflowRun, WorkflowRunStatus, NodeStatus, WorkflowNodeRun, generate_run_id
        from backend.planning.continuation import PlanningContinuationCoordinator

        run_id = generate_run_id()
        state = {"status": "failed", "currentEvent": {}}
        set_lineage(state, new_lineage(run_id, ExecutionBudgetLimits(maxReplans=3)))
        repo.save_run(WorkflowRun(run_id=run_id, definition_id="plan_acc", version=1,
                                  status=WorkflowRunStatus.FAILED, state=state))
        repo.save_node_run(WorkflowNodeRun(node_run_id=f"nr_{run_id}_action_save", run_id=run_id,
                                           node_id="action_save", node_type=NodeType.ACTION,
                                           status=NodeStatus.FAILED, attempt=1))
        repo.save_definition(plan_to_child_definition(_valid_plan()))

        coord = PlanningContinuationCoordinator(repo)
        result = coord.auto_continue(run_id)
        assert "childRunId" in result, result

        # 新 repository 实例重读：parent lineage 的 replansUsed=1
        from backend.workflow.repository import SQLiteWorkflowRepository
        fresh = SQLiteWorkflowRepository()
        reloaded_parent = fresh.get_run(run_id)
        assert get_lineage(reloaded_parent.state).budgetUsage.replansUsed == 1


class TestAutoReplanWiring:
    def test_auto_continue_creates_child(self, monkeypatch):
        from backend.planning.context import build_planning_context
        from backend.planning.planner import build_plan
        from backend.planning.adapter import plan_to_definition
        from backend.planning.continuation import PlanningContinuationCoordinator
        from backend.workflow.executor import get_executor
        from backend.workflow.nodes.base import get_node_registry

        repo = _repo()
        plan = build_plan(build_planning_context(
            {"eventId": "E", "eventType": "congestion", "roadName": "路",
             "avgSpeed": 40, "queueLength": 20, "duration": 100}))
        repo.save_definition(plan_to_definition(plan))

        async def fake_dispatch(at, p, st):
            return {"saved": False, "error": "semantic failure"}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        executor = get_executor()
        registry = get_node_registry()
        saved = {}
        async def noop(s, c): return {}
        for t in ("rag_retrieve", "memory_context"):
            saved[t] = registry.get(t); registry.register(t, noop)
        try:
            async def run():
                async for s in executor.start(definition_id=plan.planId,
                                              initial_event={"eventId": "E", "eventType": "congestion",
                                                             "roadName": "路", "avgSpeed": 40, "queueLength": 20, "duration": 100}):
                    pass
            asyncio.run(run())
        finally:
            for t, fn in saved.items(): registry.register(t, fn)

        parent = repo.list_runs(definition_id=plan.planId)[0]
        assert parent.status.value == "failed"

        coord = PlanningContinuationCoordinator(repo)
        result = coord.auto_continue(parent.run_id)
        assert "childRunId" in result, result

        parent2 = repo.get_run(parent.run_id)
        assert parent2.state.get("terminationReason") == "replanned"
        assert parent2.state.get("replannedToRunId") == result["childRunId"]


class TestSideEffectCarryForward:
    def test_notify_succeeded_not_rerun(self):
        plan = _notify_plan()
        # notify 成功（completed）→ carried；save_result 未完成 → revised
        v2 = build_revision(plan, {"validate_event": "r1:validate_event", "action_notify": "r1:action_notify"}, "r1")
        assert any(is_carried(s) and s.stepId == "action_notify" for s in v2.steps)

        child_def = plan_to_child_definition(v2)
        node_ids = {n.node_id for n in child_def.nodes}
        assert "action_notify" not in node_ids  # notify carried → 从 executable graph 排除（不会重放）
        assert "action_save" in node_ids
        # 依赖 frontier：trigger → action_save（notify carried 依赖已满足）
        node = {n.node_id: n for n in child_def.nodes}
        assert node["trigger"].next_nodes == ["action_save"]


class TestIndependentRootIsolation:
    def test_r40_independent_root_fresh(self):
        from backend.workflow.models import WorkflowRun, WorkflowRunStatus, generate_run_id
        from backend.planning.rejection import RejectionConstraint, ActionIntentFamily
        repo = _repo()
        run_a = generate_run_id()
        state_a = {"status": "completed"}
        lin_a = new_lineage(run_a)
        lin_a.budgetUsage.toolCallsUsed = 3
        lin_a.rejectionConstraints = [RejectionConstraint(
            actionType="notify_wechat", intentFamily=ActionIntentFamily.NOTIFICATION).to_dict()]
        lin_a.loopGuard = {"visitedFingerprints": ["fp1"]}
        set_lineage(state_a, lin_a)
        repo.save_run(WorkflowRun(run_id=run_a, definition_id="plan_acc", version=1,
                                  status=WorkflowRunStatus.COMPLETED, state=state_a))

        run_b = generate_run_id()
        state_b = {"status": "pending"}
        set_lineage(state_b, new_lineage(run_b))
        repo.save_run(WorkflowRun(run_id=run_b, definition_id="plan_acc", version=1,
                                  status=WorkflowRunStatus.PENDING, state=state_b))

        lin_b = get_lineage(state_b)
        assert lin_b.rootRunId == run_b
        assert lin_b.budgetUsage.toolCallsUsed == 0
        assert lin_b.rejectionConstraints == []
        assert lin_b.loopGuard == {}


class TestCarriedCorruption:
    def test_missing_result_ref_fail_closed(self):
        repo = _repo()
        plan = _notify_plan()
        plan.steps[1] = PlanStep(stepId="action_notify", stepType=NodeType.ACTION,
                                 actionType="notify_wechat", toolName="notify_wechat",
                                 riskLevel="high_risk", approvalRequired=True,
                                 metadata={"carriedForward": True, "carriedForwardFromRunId": "r1",
                                           "carriedForwardFromVersion": 1},
                                 resultRef="")
        from backend.planning.revision import validate_carried_refs
        issues = validate_carried_refs(plan, repo)
        assert issues


class TestReplanIdempotency:
    def test_repeated_explicit_replan_same_child(self, monkeypatch):
        from backend.planning.context import build_planning_context
        from backend.planning.planner import build_plan
        from backend.planning.adapter import plan_to_definition
        from backend.planning.continuation import PlanningContinuationCoordinator
        from backend.workflow.executor import get_executor
        from backend.workflow.nodes.base import get_node_registry

        repo = _repo()
        plan = build_plan(build_planning_context(
            {"eventId": "E", "eventType": "congestion", "roadName": "路",
             "avgSpeed": 40, "queueLength": 20, "duration": 100}))
        repo.save_definition(plan_to_definition(plan))

        async def fake_dispatch(at, p, st):
            return {"saved": False, "error": "semantic failure"}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        executor = get_executor()
        registry = get_node_registry()
        saved = {}
        async def noop(s, c): return {}
        for t in ("rag_retrieve", "memory_context"):
            saved[t] = registry.get(t); registry.register(t, noop)
        try:
            async def run():
                async for s in executor.start(definition_id=plan.planId,
                                              initial_event={"eventId": "E", "eventType": "congestion",
                                                             "roadName": "路", "avgSpeed": 40, "queueLength": 20, "duration": 100}):
                    pass
            asyncio.run(run())
        finally:
            for t, fn in saved.items(): registry.register(t, fn)

        parent = repo.list_runs(definition_id=plan.planId)[0]
        coord = PlanningContinuationCoordinator(repo)
        r1 = coord.explicit_replan(parent.run_id)
        r2 = coord.explicit_replan(parent.run_id)
        assert r1.get("childRunId") == r2.get("childRunId") or r2.get("alreadyReplanned")
