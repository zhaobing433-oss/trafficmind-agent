"""
Phase 17 Round 2 — 评估用例 R01-R40

覆盖 Observation / Decision / Budget / Loop Guard / Rejection / Replanner /
Child Transaction / Carried-forward / Idempotency / Budget enforcement。
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.planning.budget import (
    ActiveTimeTracker,
    BUDGETED_NODE_TYPES,
    ExecutionBudgetLimits,
    ExecutionLineage,
    get_lineage,
    inherit_lineage,
    new_lineage,
    reserve_replan,
    reserve_retry,
    reserve_step,
    reserve_tool_call,
    set_lineage,
    should_count_step,
)
from backend.planning.loop_guard import (
    LoopGuard,
    canonical_action_signature,
)
from backend.planning.observation import (
    Observation,
    ObservationScope,
    ObservationSource,
    ObservationStatus,
    ObservationType,
    validate_observation,
)
from backend.planning.rejection import (
    ActionIntentFamily,
    intent_family,
    is_intent_rejected,
)
from backend.planning.replan_decision import (
    ReplanDecision,
    ReplanDecisionEngine,
)
from backend.planning.replanner import build_revision, is_carried
from backend.planning.revision import (
    plan_to_child_definition,
    validate_carried_refs,
)
from backend.planning.models import (
    GoalType,
    Plan,
    PlanDefinitionStatus,
    PlanStep,
    compute_fingerprint,
)
from backend.workflow.models import NodeType


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_r2.db"))


def _obs(typ, status, scope=ObservationScope.STEP, step="s1", **kw) -> Observation:
    return Observation(
        observationId="obs_1", planId="p", planVersion=1, runId="r",
        type=typ, status=status, scope=scope, source=ObservationSource.SYSTEM,
        stepId=step if scope == ObservationScope.STEP else None, **kw,
    )


def _engine() -> ReplanDecisionEngine:
    return ReplanDecisionEngine()


# ═══════════════════════════════════════════════════════════════════════════════
# Observation + validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestObservation:
    def test_r35_unknown_outcome_canonical_never_retry(self):
        o = _obs(ObservationType.UNKNOWN_OUTCOME, ObservationStatus.UNKNOWN)
        assert validate_observation(o) == []
        assert o.retryable is False

    def test_unknown_outcome_success_invalid(self):
        o = _obs(ObservationType.UNKNOWN_OUTCOME, ObservationStatus.SUCCESS)
        assert any("非法" in i for i in validate_observation(o))

    def test_tool_denied_success_invalid(self):
        o = _obs(ObservationType.TOOL_DENIED, ObservationStatus.SUCCESS)
        assert any("非法" in i for i in validate_observation(o))

    def test_step_scope_requires_step_id(self):
        o = _obs(ObservationType.TOOL_FAILED, ObservationStatus.FAILURE, step=None)
        assert any("stepId" in i for i in validate_observation(o))

    def test_r03_tool_denied_not_retryable(self):
        o = _obs(ObservationType.TOOL_DENIED, ObservationStatus.DENIED)
        assert o.retryable is False

    def test_r04_approval_rejected_not_retryable(self):
        o = _obs(ObservationType.APPROVAL_REJECTED, ObservationStatus.APPROVAL_REJECTED)
        assert o.retryable is False

    def test_timeout_retryable(self):
        o = _obs(ObservationType.TIMEOUT, ObservationStatus.TIMEOUT)
        assert o.retryable is True


# ═══════════════════════════════════════════════════════════════════════════════
# Decision Engine
# ═══════════════════════════════════════════════════════════════════════════════


class TestDecision:
    def test_r01_timeout_retry(self):
        d = _engine().decide(_obs(ObservationType.TIMEOUT, ObservationStatus.TIMEOUT))
        assert d.decision == ReplanDecision.RETRY

    def test_r02_retry_exhausted_replan(self):
        d = _engine().decide(_obs(ObservationType.RETRY_EXHAUSTED, ObservationStatus.FAILURE))
        assert d.decision == ReplanDecision.REPLAN

    def test_r03_tool_denied_no_retry(self):
        d = _engine().decide(_obs(ObservationType.TOOL_DENIED, ObservationStatus.DENIED))
        assert d.decision in (ReplanDecision.ABORT, ReplanDecision.ESCALATE_HUMAN)

    def test_r14_unknown_outcome_escalate(self):
        d = _engine().decide(_obs(ObservationType.UNKNOWN_OUTCOME, ObservationStatus.UNKNOWN))
        assert d.decision == ReplanDecision.ESCALATE_HUMAN

    def test_r19_cancelled_no_replan(self):
        d = _engine().decide(_obs(ObservationType.CANCELLED, ObservationStatus.CANCELLED, scope=ObservationScope.RUN, step=None))
        assert d.decision == ReplanDecision.NO_REPLAN

    def test_require_approval_wait(self):
        d = _engine().decide(_obs(ObservationType.TOOL_REQUIRE_APPROVAL, ObservationStatus.APPROVAL_REQUIRED))
        assert d.decision == ReplanDecision.WAIT_FOR_APPROVAL


# ═══════════════════════════════════════════════════════════════════════════════
# Budget
# ═══════════════════════════════════════════════════════════════════════════════


class TestBudget:
    def test_r09_max_replans_stop(self):
        lin = new_lineage("root", ExecutionBudgetLimits(maxReplans=1))
        assert reserve_replan(lin) is True
        assert reserve_replan(lin) is False

    def test_r10_tool_budget_stop(self):
        lin = new_lineage("root", ExecutionBudgetLimits(maxToolCalls=2))
        assert reserve_tool_call(lin) is True
        assert reserve_tool_call(lin) is True
        assert reserve_tool_call(lin) is False

    def test_r23_r31_budget_inherited(self):
        lin = new_lineage("root", ExecutionBudgetLimits(maxToolCalls=5))
        reserve_tool_call(lin)
        reserve_step(lin)
        child = inherit_lineage(lin)
        assert child.rootRunId == "root"
        assert child.budgetUsage.toolCallsUsed == 1
        assert child.budgetUsage.stepsUsed == 1

    def test_r30_independent_root_fresh(self):
        a = new_lineage("rootA")
        reserve_tool_call(a)
        b = new_lineage("rootB")
        assert b.budgetUsage.toolCallsUsed == 0
        assert b.rootRunId == "rootB"

    def test_r33_structural_nodes_not_counted(self):
        assert should_count_step(NodeType.AGENT_TASK) is True
        assert should_count_step(NodeType.ACTION) is True
        assert should_count_step(NodeType.TRIGGER) is False
        assert should_count_step(NodeType.CLOSE) is False
        assert should_count_step(NodeType.HUMAN_APPROVAL) is False

    def test_r24_approval_wait_not_active(self):
        t = ActiveTimeTracker()
        t.open_segment(0.0)
        t.close_segment(10.0)     # 10s active
        # 等待（审批），不累计
        t.open_segment(100.0)     # 100s 后才 resume
        t.close_segment(105.0)    # 5s active
        assert t.active_elapsed == 15.0  # 10 + 5，不含等待 90s


# ═══════════════════════════════════════════════════════════════════════════════
# Loop Guard
# ═══════════════════════════════════════════════════════════════════════════════


class TestLoopGuard:
    def test_r08_same_fingerprint_loop(self):
        g = LoopGuard()
        assert g.register_fingerprint("fp1") is False
        assert g.register_fingerprint("fp1") is True  # loop

    def test_canonical_signature_stable(self):
        s1 = canonical_action_signature("notify_wechat", {"a": 1, "timestamp": "x", "requestId": "y"})
        s2 = canonical_action_signature("notify_wechat", {"timestamp": "z", "a": 1})
        assert s1 == s2  # 瞬态 key 不影响


# ═══════════════════════════════════════════════════════════════════════════════
# Rejection / DENY
# ═══════════════════════════════════════════════════════════════════════════════


class TestRejection:
    def test_r13_policy_deny_alias_bypass(self):
        from backend.planning.rejection import PolicyDenyConstraint
        c = [PolicyDenyConstraint(toolName="notify_wechat", actionType="notify_wechat",
                                  intentFamily=ActionIntentFamily.NOTIFICATION).to_dict()]
        # 同 intent family 的 alias 也被约束
        assert is_intent_rejected(c, "notify_dingtalk") is True

    def test_r16_rejected_intent_alias_requires_approval(self):
        from backend.planning.rejection import RejectionConstraint
        c = [RejectionConstraint(actionType="notify_wechat",
                                 intentFamily=ActionIntentFamily.NOTIFICATION).to_dict()]
        assert is_intent_rejected(c, "notify_dingtalk") is True
        assert is_intent_rejected(c, "simulation_monitor") is False

    def test_intent_family_mapping(self):
        assert intent_family("notify_wechat") == ActionIntentFamily.NOTIFICATION
        assert intent_family("simulation_traffic_diversion") == ActionIntentFamily.TRAFFIC_DIVERSION
        assert intent_family("save_result") == ActionIntentFamily.PERSISTENCE


# ═══════════════════════════════════════════════════════════════════════════════
# Replanner / Carried-forward
# ═══════════════════════════════════════════════════════════════════════════════


def _linear_plan(steps=None, plan_id="plan_r2") -> Plan:
    steps = steps or [
        PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT),
        PlanStep(stepId="agent_x", stepType=NodeType.AGENT_TASK, agentType="CongestionAgent", dependsOn=["validate_event"]),
        PlanStep(stepId="action_notify", stepType=NodeType.ACTION, actionType="notify_wechat", toolName="notify_wechat", riskLevel="high_risk", approvalRequired=True, dependsOn=["agent_x"]),
        PlanStep(stepId="action_save", stepType=NodeType.ACTION, actionType="save_result", toolName="save_result", riskLevel="write", dependsOn=["action_notify"]),
        PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["action_save"]),
    ]
    return Plan(planId=plan_id, planFingerprint=compute_fingerprint(steps), goal="g",
                goalType=GoalType.GENERIC, definitionStatus=PlanDefinitionStatus.DRAFT, version=1, steps=steps)


class TestReplanner:
    def test_r07_revision_lineage_fingerprint(self):
        plan = _linear_plan()
        completed = {"validate_event": "r1:validate_event", "agent_x": "r1:agent_x"}
        v2 = build_revision(plan, completed, "r1")
        assert v2.planId == plan.planId
        assert v2.version == plan.version + 1
        assert v2.planFingerprint != plan.planFingerprint

    def test_r06_carried_steps_marked(self):
        plan = _linear_plan()
        completed = {"validate_event": "r1:validate_event"}
        v2 = build_revision(plan, completed, "r1")
        carried = [s for s in v2.steps if is_carried(s)]
        assert [s.stepId for s in carried] == ["validate_event"]
        assert carried[0].resultRef == "r1:validate_event"

    def test_r28_carried_absent_from_child_graph(self):
        plan = _linear_plan()
        completed = {"validate_event": "r1:v", "agent_x": "r1:a"}
        v2 = build_revision(plan, completed, "r1")
        child_def = plan_to_child_definition(v2)
        node_ids = {n.node_id for n in child_def.nodes}
        assert "validate_event" not in node_ids
        assert "agent_x" not in node_ids
        assert "action_notify" in node_ids  # 未完成 → 保留

    def test_r29_dependency_frontier(self):
        plan = _linear_plan()
        completed = {"validate_event": "r1:v", "agent_x": "r1:a"}
        v2 = build_revision(plan, completed, "r1")
        child_def = plan_to_child_definition(v2)
        node = {n.node_id: n for n in child_def.nodes}
        # frontier：trigger → action_notify（carried 依赖已满足）
        assert node["trigger"].next_nodes == ["action_notify"]
        assert node["action_notify"].next_nodes == ["action_save"]

    def test_r05_revised_high_risk_keeps_approval(self):
        plan = _linear_plan()
        completed = {"validate_event": "r1:v", "agent_x": "r1:a"}
        v2 = build_revision(plan, completed, "r1")
        notify = next(s for s in v2.steps if s.stepId == "action_notify")
        assert notify.approvalRequired is True


# ═══════════════════════════════════════════════════════════════════════════════
# Child Transaction / Idempotency / Persistence
# ═══════════════════════════════════════════════════════════════════════════════


class TestChildTransaction:
    def _repo(self):
        from backend.workflow.repository import SQLiteWorkflowRepository
        return SQLiteWorkflowRepository()

    def _parent_run(self, repo, run_id="parent_1", definition_id="plan_r2"):
        from backend.workflow.models import WorkflowRun, WorkflowRunStatus
        state = {"status": "failed", "currentNode": "", "currentEvent": {}}
        set_lineage(state, new_lineage(run_id))
        run = WorkflowRun(run_id=run_id, definition_id=definition_id, version=1,
                          status=WorkflowRunStatus.FAILED, state=state)
        repo.save_run(run)
        return run

    def test_r26_carried_missing_ref_fail_closed(self):
        repo = self._repo()
        plan = _linear_plan()
        # 手动构造一个 carried step 但 resultRef 为空
        plan.steps[0] = PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT,
                                 metadata={"carriedForward": True, "carriedForwardFromRunId": "", "carriedForwardFromVersion": 1})
        issues = validate_carried_refs(plan, repo)
        assert issues  # fail-closed

    def test_r36_version_allocation_no_collision(self):
        repo = self._repo()
        from backend.workflow.repository import SQLiteWorkflowRepository
        repo.save_definition(plan_to_child_definition(_linear_plan()))
        # 两次分配（不同 child）得到不同 version
        v1 = self._tx_version(repo, "child_1", "plan_r2", {})
        v2 = self._tx_version(repo, "child_2", "plan_r2", {})
        assert v1 != v2

    def _tx_version(self, repo, child_run_id, definition_id, child_state):
        from backend.workflow.models import WorkflowRun, WorkflowRunStatus
        child = WorkflowRun(run_id=child_run_id, definition_id=definition_id, version=0,
                            status=WorkflowRunStatus.PENDING, state=child_state)
        return repo.create_child_continuation_tx(
            child_run=child, parent_run_id="parent_1", parent_status="failed",
            parent_state={"status": "failed", "replannedToRunId": child_run_id},
            definition_json={"id": definition_id, "nodes": []},
        )

    def test_r39_rollback_no_orphan(self):
        repo = self._repo()
        from backend.workflow.models import WorkflowRun, WorkflowRunStatus
        parent = self._parent_run(repo, "parent_1", "plan_r2")
        # 预先创建一个占位 run 使 child run_id PK 冲突
        repo.save_run(WorkflowRun(run_id="child_dup", definition_id="x", version=1,
                                  status=WorkflowRunStatus.PENDING, state={}))
        child = WorkflowRun(run_id="child_dup", definition_id="plan_r2", version=0,
                            status=WorkflowRunStatus.PENDING, state={})
        with pytest.raises(Exception):
            repo.create_child_continuation_tx(
                child_run=child, parent_run_id="parent_1", parent_status="failed",
                parent_state={"status": "failed", "replannedToRunId": "child_dup"},
                definition_json={"id": "plan_r2", "nodes": []},
            )
        # parent 未被半写
        reloaded = repo.get_run("parent_1")
        assert reloaded.status.value == "failed"
        assert not reloaded.state.get("replannedToRunId")

    def test_r20_observation_durable_reload(self):
        repo = self._repo()
        from backend.workflow.models import WorkflowRun, WorkflowRunStatus, generate_run_id
        run_id = generate_run_id()
        repo.save_run(WorkflowRun(run_id=run_id, definition_id="d", version=1,
                                  status=WorkflowRunStatus.COMPLETED, state={}))
        from backend.planning.continuation import PlanningContinuationCoordinator
        coord = PlanningContinuationCoordinator(repo)
        obs = _obs(ObservationType.TOOL_FAILED, ObservationStatus.FAILURE)
        obs.runId = run_id
        coord.persist_observation(obs)
        # fresh repo reload
        from backend.workflow.repository import SQLiteWorkflowRepository
        fresh = SQLiteWorkflowRepository()
        events = fresh.list_observations(run_id)
        assert len(events) == 1
        assert events[0].event_type == "observation_recorded"
        assert events[0].payload.get("type") == "tool_failed"


# ═══════════════════════════════════════════════════════════════════════════════
# Budget enforcement (runtime)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBudgetEnforcement:
    def test_r38_reservation_before_dispatch(self, monkeypatch):
        from backend.planning.budget import get_lineage
        from backend.workflow.models import NodeConfig, NodeType, WorkflowRun, WorkflowRunStatus, generate_run_id
        from backend.workflow.nodes.action import execute_action
        from backend.workflow.repository import SQLiteWorkflowRepository
        from backend.workflow.state import TrafficWorkflowState

        repo = SQLiteWorkflowRepository()
        run_id = generate_run_id()
        state = {"status": "running"}
        set_lineage(state, new_lineage(run_id))
        repo.save_run(WorkflowRun(run_id=run_id, definition_id="d", version=1,
                                  status=WorkflowRunStatus.RUNNING, state=state))

        seen = {}
        async def fake_dispatch(action_type, params, st):
            db_run = repo.get_run(run_id)
            seen["toolCallsUsed"] = get_lineage(db_run.state).budgetUsage.toolCallsUsed
            return {"sent": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        st = TrafficWorkflowState(workflow_run_id=run_id)
        out = asyncio.run(execute_action(
            st, NodeConfig(node_id="a1", node_type=NodeType.ACTION, config={"action_type": "save_result"}),
            repository=repo,
        ))
        assert out.get("executed") is not False  # dispatch happened
        assert seen.get("toolCallsUsed") == 1  # dispatch 前已 durable reserve

    def test_r25_require_approval_no_tool_call(self):
        from backend.workflow.models import NodeConfig, NodeType, WorkflowRun, WorkflowRunStatus, generate_run_id
        from backend.workflow.nodes.action import execute_action
        from backend.workflow.repository import SQLiteWorkflowRepository
        from backend.workflow.state import TrafficWorkflowState

        repo = SQLiteWorkflowRepository()
        run_id = generate_run_id()
        state = {"status": "running"}
        set_lineage(state, new_lineage(run_id))
        repo.save_run(WorkflowRun(run_id=run_id, definition_id="d", version=1,
                                  status=WorkflowRunStatus.RUNNING, state=state))

        st = TrafficWorkflowState(workflow_run_id=run_id)
        out = asyncio.run(execute_action(
            st, NodeConfig(node_id="a1", node_type=NodeType.ACTION, config={"action_type": "notify_wechat"}),
            repository=repo,
        ))
        # 未批准 → approval_required，未 dispatch → 未 reserve tool call
        assert out.get("status") == "approval_required"
        assert out.get("executed") is False
        db_run = repo.get_run(run_id)
        assert get_lineage(db_run.state).budgetUsage.toolCallsUsed == 0
