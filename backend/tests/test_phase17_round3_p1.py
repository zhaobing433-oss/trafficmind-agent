"""
Phase 17 Round 3 P1 — backend tests（F26-F37, F46, F47）
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_r3_p1.db"))


def _repo():
    from backend.workflow.repository import SQLiteWorkflowRepository
    return SQLiteWorkflowRepository()


def _plan(plan_id="plan_p1"):
    from backend.planning.models import Plan, PlanStep, GoalType, PlanDefinitionStatus, compute_fingerprint
    from backend.workflow.models import NodeType
    steps = [
        PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT),
        PlanStep(stepId="action_save", stepType=NodeType.ACTION, actionType="save_result",
                 toolName="save_result", riskLevel="write", dependsOn=["validate_event"]),
        PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["action_save"]),
    ]
    return Plan(planId=plan_id, planFingerprint=compute_fingerprint(steps), goal="验收计划",
                goalType=GoalType.GENERIC, definitionStatus=PlanDefinitionStatus.ACTIVE, version=1, steps=steps)


def _seed_definition(repo, plan=None):
    from backend.planning.adapter import plan_to_definition
    from backend.workflow.models import WorkflowDefinitionVersion
    from backend.workflow.definition import generate_version_id
    p = plan or _plan()
    d = plan_to_definition(p)
    repo.save_definition(d)
    repo.save_definition_version(WorkflowDefinitionVersion(
        id=generate_version_id(), definition_id=p.planId, version=1, definition_json=d.to_dict()))
    return p


def _run(repo, run_id, definition_id="plan_p1", status="pending", version=1, extra_state=None):
    from backend.workflow.models import WorkflowRun, WorkflowRunStatus
    from backend.planning.budget import new_lineage, set_lineage
    state = {"status": status, "currentEvent": {"eventId": "E", "eventType": "congestion", "roadName": "路"}}
    set_lineage(state, new_lineage(run_id))
    if extra_state:
        state.update(extra_state)
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=definition_id, version=version,
                              status=WorkflowRunStatus(status), state=state))
    repo.mark_driver_managed(run_id)
    return run_id


class TestDiscovery:
    def test_f26_plan_discovery_pagination(self):
        from backend.planning.api import list_plans
        repo = _repo()
        _seed_definition(repo, _plan("plan_a"))
        _seed_definition(repo, _plan("plan_b"))
        _run(repo, "run_a1", "plan_a", status="completed")
        _run(repo, "run_a2", "plan_a", status="failed", extra_state={"replannedFromRunId": "run_a1"})
        # 直接调用 endpoint 函数（复用同一 _repo）
        import asyncio
        result = asyncio.run(_invoke_list_plans(repo, page=1, pageSize=10))
        ids = [p["planId"] for p in result["plans"]]
        assert "plan_a" in ids and "plan_b" in ids


async def _invoke_list_plans(repo, page, pageSize):
    # 复用 api 的 _repo（模块级），这里直接测试 repository 层发现
    from backend.planning.api import _repo as api_repo
    import backend.planning.api as api_mod
    api_mod._repo = repo
    try:
        return await api_mod.list_plans(page=page, pageSize=pageSize)
    finally:
        api_mod._repo = api_repo


class TestDiff:
    def test_f31_version_diff(self):
        from backend.planning.diff import compute_diff
        from backend.planning.models import PlanStep
        from backend.workflow.models import NodeType
        a = _plan()
        b_steps = [
            PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT, objective="changed"),
            PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["validate_event"]),
        ]
        b = _plan()
        b.steps = b_steps
        diff = compute_diff(a, b)
        assert diff["removedSteps"] == ["action_save"]
        # validate_event objective 变了；close 的 dependsOn 也变了（action_save 移除）
        assert diff["changedSteps"] == ["validate_event", "close"]


class TestTrajectory:
    def _lineage(self, repo, root_id="root1"):
        """root → child lineage。"""
        _seed_definition(repo, _plan())
        _run(repo, root_id, status="failed", version=1,
             extra_state={"terminationReason": "replanned", "replannedToRunId": "child1"})
        _run(repo, "child1", status="completed", version=2,
             extra_state={"replannedFromRunId": root_id})
        # child 同 rootRunId（继承）
        from backend.planning.budget import get_lineage, set_lineage
        child = repo.get_run("child1")
        lin = get_lineage(child.state)
        lin.rootRunId = root_id
        set_lineage(child.state, lin)
        child.state = child.state
        repo.save_run(child)

    def test_f28_root_isolation(self):
        repo = _repo()
        _seed_definition(repo, _plan())
        _run(repo, "rootA", status="completed", extra_state={"replannedToRunId": "childA"})
        _run(repo, "childA", status="completed", extra_state={"replannedFromRunId": "rootA"})
        _run(repo, "rootB", status="completed")  # 独立 root
        from backend.planning.trajectory import resolve_root_run_id, build_lineage_runs
        assert resolve_root_run_id(repo, "childA") == "rootA"
        assert resolve_root_run_id(repo, "rootB") == "rootB"
        # rootA lineage 只含 rootA + childA
        runs = build_lineage_runs(repo, "rootA")
        assert [r.run_id for r in runs] == ["rootA", "childA"]

    def test_f32_revision_replan_count(self):
        repo = _repo()
        self._lineage(repo)
        from backend.planning.trajectory import compute_trajectory
        t = compute_trajectory(repo, "root1")
        assert t["metrics"]["revisionCount"] == 2  # version 1 + 2
        assert t["metrics"]["replanCount"] == 1  # child1

    def test_f33_recovery_metrics(self):
        repo = _repo()
        self._lineage(repo)
        # emit recovery events
        from backend.workflow.run_driver import RunDriver
        drv = RunDriver(repo, owner_id="t")
        drv._emit_recovery_event("child1", "recovery_started", {
            "recoveryAttemptId": "rec1", "rootRunId": "root1", "runId": "child1",
            "kind": "child_pickup", "startedAt": "2026-08-18T00:00:00Z"})
        drv._emit_recovery_event("child1", "recovery_completed", {
            "recoveryAttemptId": "rec1", "rootRunId": "root1", "runId": "child1",
            "kind": "child_pickup", "outcome": "completed", "completedAt": "2026-08-18T00:00:10Z"})
        from backend.planning.trajectory import compute_trajectory
        t = compute_trajectory(repo, "child1")
        assert t["metrics"]["recoveryAttempts"] == 1
        assert t["metrics"]["recoverySuccess"] == 1
        assert t["metrics"]["recoveryRate"] == 1.0
        assert t["metrics"]["averageTimeToRecoverySeconds"] == 10.0

    def test_f33_recovery_rate_null_when_zero(self):
        repo = _repo()
        self._lineage(repo)
        from backend.planning.trajectory import compute_trajectory
        t = compute_trajectory(repo, "root1")
        assert t["metrics"]["recoveryAttempts"] == 0
        assert t["metrics"]["recoveryRate"] is None

    def test_f34_tool_denial_no_double_count(self):
        repo = _repo()
        self._lineage(repo)
        # 一个 TOOL_DENIED observation
        from backend.planning.observation import Observation, ObservationType, ObservationStatus, ObservationScope, ObservationSource
        from backend.planning.continuation import PlanningContinuationCoordinator
        obs = Observation(observationId="obs1", planId="plan_p1", planVersion=1, runId="root1",
                          type=ObservationType.TOOL_DENIED, status=ObservationStatus.DENIED,
                          scope=ObservationScope.STEP, source=ObservationSource.TOOL, stepId="action_save")
        PlanningContinuationCoordinator(repo).persist_observation(obs)
        from backend.planning.trajectory import compute_trajectory
        t = compute_trajectory(repo, "root1")
        assert t["metrics"]["toolDenials"] == 1  # 只算 observation，不双加 event

    def test_f35_human_interventions(self):
        repo = _repo()
        self._lineage(repo)
        from backend.workflow.models import WorkflowApproval, ApprovalDecision
        repo.save_approval(WorkflowApproval(approval_id="a1", run_id="root1", node_id="h",
                                            proposed_actions=[], decision=ApprovalDecision.APPROVED))
        repo.save_approval(WorkflowApproval(approval_id="a2", run_id="root1", node_id="h",
                                            proposed_actions=[], decision=ApprovalDecision.PENDING))
        from backend.planning.trajectory import compute_trajectory
        t = compute_trajectory(repo, "root1")
        assert t["metrics"]["humanInterventions"] == 1  # 只数 APPROVED，不数 PENDING

    def test_f36_duplicate_side_effect(self):
        repo = _repo()
        self._lineage(repo)
        from backend.workflow.models import WorkflowActionRecord, ActionStatus, compute_action_idempotency_key
        # 两个 SUCCEEDED notify（HIGH_RISK_NON_IDEMPOTENT）同签名（不同 node → 不同 idempotency_key）→ duplicate 1
        for i, nid in [(1, "action_notify_1"), (2, "action_notify_2")]:
            repo.save_action_record(WorkflowActionRecord(
                action_id=f"wfact_{i}", run_id="root1", node_id=nid,
                action_type="notify_wechat",
                idempotency_key=compute_action_idempotency_key("root1", nid, "notify_wechat"),
                status=ActionStatus.SUCCEEDED, result={"sent": True}))
        from backend.planning.trajectory import compute_trajectory
        t = compute_trajectory(repo, "root1")
        assert t["metrics"]["duplicateSideEffectCount"] == 1

    def test_f37_trajectory_length_no_structural(self):
        repo = _repo()
        self._lineage(repo)
        from backend.workflow.models import WorkflowNodeRun, NodeStatus, NodeType
        # 结构节点（trigger/close）不计；semantic（validate/action）计
        for nid, ntype in [("trigger", NodeType.TRIGGER), ("validate_event", NodeType.VALIDATE_EVENT),
                           ("action_save", NodeType.ACTION), ("close", NodeType.CLOSE)]:
            repo.save_node_run(WorkflowNodeRun(node_run_id=f"nr_{nid}", run_id="root1", node_id=nid,
                                               node_type=ntype, status=NodeStatus.SUCCEEDED, attempt=1))
        from backend.planning.trajectory import compute_trajectory
        t = compute_trajectory(repo, "root1")
        assert t["metrics"]["trajectoryLength"] == 2  # validate + action（trigger/close 不计）


class TestRecoveryMarkers:
    def test_b01_latest_version_canonical(self):
        """latestVersion 应来自 workflow_definition_versions 的 MAX(version)。"""
        repo = _repo()
        _seed_definition(repo, _plan("plan_v"))  # version 1
        from backend.workflow.definition import DefinitionManager
        from backend.planning.adapter import plan_to_definition
        p2 = _plan("plan_v"); p2.version = 2
        DefinitionManager(repo).create_version(plan_to_definition(p2), changelog='v2')
        assert repo.get_latest_version_number("plan_v") == 2

    def test_b03_observation_payload_shape(self):
        """observation payload 含 type/status/stepId/failureReason（非 event 包装）。"""
        repo = _repo()
        _seed_definition(repo, _plan())
        _run(repo, "root_obs", status="completed")
        from backend.planning.observation import Observation, ObservationType, ObservationStatus, ObservationScope, ObservationSource
        from backend.planning.continuation import PlanningContinuationCoordinator
        obs = Observation(observationId="o1", planId="plan_p1", planVersion=1, runId="root_obs",
                          type=ObservationType.TOOL_DENIED, status=ObservationStatus.DENIED,
                          scope=ObservationScope.STEP, source=ObservationSource.TOOL,
                          stepId="action_save", failureReason="策略拒绝")
        PlanningContinuationCoordinator(repo).persist_observation(obs)
        events = repo.list_observations("root_obs")
        assert events[0].payload["type"] == "tool_denied"
        assert events[0].payload["stepId"] == "action_save"
        assert events[0].payload["failureReason"] == "策略拒绝"

    def test_f46_normal_child_not_recovery(self):
        """fresh child pickup 不产生 recovery marker。"""
        repo = _repo()
        _seed_definition(repo, _plan())
        _run(repo, "root1", status="failed", extra_state={"terminationReason": "replanned", "replannedToRunId": "child1"})
        # child 是 fresh（createdAt 现在），driver 稍后启动（startup 早于 child 创建）
        _run(repo, "child1", status="pending", version=2,
             extra_state={"replannedFromRunId": "root1", "_continuationCreatedAtUnix": time.time() + 5})

        from backend.workflow.run_driver import RunDriver
        from backend.workflow.executor import get_executor
        drv = RunDriver(repo, owner_id="t")  # startup 现在是 now
        claim = repo.claim_driver_run("child1", "t", "2099-01-01T00:00:00Z")
        exec_ = get_executor()
        exec_.set_driver_context("t", claim["generation"])
        async def go():
            await drv._drive_pending(exec_, repo.get_run("child1"), claim["generation"])
        asyncio.run(go())
        # 无 recovery_started 事件
        events = [e.event_type for e in repo.list_events("child1")]
        assert "recovery_started" not in events

    def test_f47_recovery_attempt_pairing(self):
        repo = _repo()
        _seed_definition(repo, _plan())
        _run(repo, "root1", status="completed")
        from backend.workflow.run_driver import RunDriver
        from backend.planning.trajectory import compute_trajectory, _collect_recoveries
        drv = RunDriver(repo, owner_id="t")
        # 两次 recovery attempt
        for aid, ok in [("rec1", "completed"), ("rec2", "failed")]:
            drv._emit_recovery_event("root1", "recovery_started", {
                "recoveryAttemptId": aid, "rootRunId": "root1", "runId": "root1",
                "kind": "stale_replay", "startedAt": "2026-08-18T00:00:00Z"})
            drv._emit_recovery_event("root1", "recovery_completed", {
                "recoveryAttemptId": aid, "rootRunId": "root1", "runId": "root1",
                "kind": "stale_replay", "outcome": ok, "completedAt": "2026-08-18T00:00:05Z"})
        attempts = _collect_recoveries(repo, ["root1"])
        assert len(attempts) == 2
        t = compute_trajectory(repo, "root1")
        assert t["metrics"]["recoveryAttempts"] == 2
        assert t["metrics"]["recoverySuccess"] == 1  # 只有 rec1 completed
        assert t["metrics"]["recoveryRate"] == 0.5
