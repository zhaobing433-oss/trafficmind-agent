"""
Phase 17 Round 3 P0 — FINAL E2E acceptance（F01/F06/F07/F08/F13/F14/F16/F17）

真实 runtime：FastAPI lifespan + RunDriver + WaitScheduler + WorkflowExecutor control flow。
external side effects 全部 mock。
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
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_r3_e2e.db"))


def _repo():
    from backend.workflow.repository import SQLiteWorkflowRepository
    return SQLiteWorkflowRepository()


def _make_driver(repo, poll=0.02, heartbeat=0.05, lease=1.0):
    from backend.workflow.run_driver import RunDriver
    return RunDriver(repo, owner_id=f"e2e_{int(time.time()*1000)}", poll_interval=poll,
                     heartbeat_interval=heartbeat, lease_seconds=lease)


def _minimal_definition():
    from backend.workflow.models import NodeConfig, NodeType, WorkflowDefinition, DefinitionStatus
    nodes = [
        NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER, next_nodes=["validate_event"]),
        NodeConfig(node_id="validate_event", node_type=NodeType.VALIDATE_EVENT, next_nodes=["close"]),
        NodeConfig(node_id="close", node_type=NodeType.CLOSE),
    ]
    return WorkflowDefinition(id="def_e2e", name="e2e", status=DefinitionStatus.ACTIVE,
                              nodes=nodes, entry_node_id="trigger")


def _seed_definition(repo, d=None):
    from backend.workflow.models import WorkflowDefinitionVersion
    from backend.workflow.definition import generate_version_id
    d = d or _minimal_definition()
    repo.save_definition(d)
    repo.save_definition_version(WorkflowDefinitionVersion(
        id=generate_version_id(), definition_id=d.id, version=1, definition_json=d.to_dict()))


def _create_pending_run(repo, run_id, definition_id="def_e2e"):
    from backend.workflow.models import WorkflowRun, WorkflowRunStatus
    from backend.planning.budget import new_lineage, set_lineage
    state = {"status": "pending", "currentEvent": {"eventId": "E", "eventType": "congestion", "roadName": "路"}}
    set_lineage(state, new_lineage(run_id))
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=definition_id, version=1,
                              status=WorkflowRunStatus.PENDING, state=state))
    repo.mark_driver_managed(run_id)


async def _wait_for_status(repo, run_id, statuses, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = repo.get_run(run_id)
        if run is not None and run.status.value in statuses:
            return run
        await asyncio.sleep(0.02)
    run = repo.get_run(run_id)
    raise AssertionError(f"run {run_id} status={run.status.value if run else None}, expected {statuses}")


# ═══════════════════════════════════════════════════════════════════════════════


class TestExecutionOwnership:
    def test_f01_create_then_driver_executes(self, monkeypatch):
        """POST /run 语义：create PENDING → RunDriver claim → execute → terminal。"""
        repo = _repo()
        _seed_definition(repo)
        from backend.workflow.models import generate_run_id
        from backend.planning.api import _create_planning_run_record

        class _Body:
            sessionId = ""; eventThreadId = ""; event = {"eventId": "E", "eventType": "congestion", "roadName": "路"}; triggeredBy = "api"

        run_id = _create_planning_run_record("def_e2e", _Body())
        assert run_id is not None
        # 创建后仍是 PENDING（HTTP request 不执行）
        assert repo.get_run(run_id).status.value == "pending"

        async def _drive():
            driver = _make_driver(repo)
            await driver.start()
            try:
                run = await _wait_for_status(repo, run_id, ["completed"])
                return run
            finally:
                await driver.stop()
        run = asyncio.run(_drive())
        assert run.status.value == "completed"
        # driver 已释放 lease（owner cleared）
        assert repo.is_driver_owner(run_id, "", 0) is False


class TestRestartE2E:
    def _run_to_failed(self, monkeypatch):
        """构造一个 machine-failure 的 planning run（instance A）。"""
        from backend.planning.context import build_planning_context
        from backend.planning.planner import build_plan
        from backend.planning.adapter import plan_to_definition
        repo = _repo()
        plan = build_plan(build_planning_context(
            {"eventId": "E", "eventType": "congestion", "roadName": "路",
             "avgSpeed": 40, "queueLength": 20, "duration": 100}))
        repo.save_definition(plan_to_definition(plan))

        async def fake_dispatch(at, p, st):
            return {"saved": False, "error": "semantic failure"}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        async def _run_a():
            from backend.workflow.executor import get_executor
            from backend.workflow.nodes.base import get_node_registry
            executor = get_executor()
            reg = get_node_registry()
            saved = {}
            async def noop(s, c): return {}
            for t in ("rag_retrieve", "memory_context"):
                saved[t] = reg.get(t); reg.register(t, noop)
            try:
                async for _ in executor.start(definition_id=plan.planId,
                                              initial_event={"eventId": "E", "eventType": "congestion", "roadName": "路", "avgSpeed": 40, "queueLength": 20, "duration": 100}):
                    pass
            finally:
                for t, fn in saved.items(): reg.register(t, fn)
        asyncio.run(_run_a())
        parent = repo.list_runs(definition_id=plan.planId)[0]
        assert parent.status.value == "failed"
        return repo, parent

    def test_f08_lineage_restart(self, monkeypatch):
        """parent FAILED + child PENDING（instance A）→ 新 instance B pickup child。"""
        repo, parent = self._run_to_failed(monkeypatch)
        from backend.planning.continuation import PlanningContinuationCoordinator
        async def fake_dispatch(at, p, st):
            return {"saved": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        coord = PlanningContinuationCoordinator(repo)
        result = coord.explicit_replan(parent.run_id)  # 创建 child（driver_managed），不执行
        child_run_id = result["childRunId"]
        child = repo.get_run(child_run_id)
        assert child.status.value == "pending"
        assert repo.is_driver_managed(child_run_id) is True
        parent2 = repo.get_run(parent.run_id)
        assert parent2.state.get("terminationReason") == "replanned"

        # ── 新 instance B（同 DB）pickup child ──
        repo_b = _repo()  # 全新 repository 实例
        async def _drive_b():
            driver_b = _make_driver(repo_b)
            await driver_b.start()
            try:
                return await _wait_for_status(repo_b, child_run_id, ["completed"])
            finally:
                await driver_b.stop()
        final_child = asyncio.run(_drive_b())
        assert final_child.status.value == "completed"
        # lineage 保持
        from backend.planning.budget import get_lineage
        assert get_lineage(final_child.state).rootRunId == get_lineage(parent2.state).rootRunId


class TestWaitSchedulerWake:
    def test_f13_f16_wake_only_then_driver(self):
        """PAUSED planning run → WaitScheduler wake（PENDING）→ RunDriver execute。"""
        repo = _repo()
        _seed_definition(repo)
        from backend.workflow.models import generate_run_id, WorkflowRun, WorkflowRunStatus
        from backend.planning.budget import new_lineage, set_lineage
        run_id = generate_run_id()
        state = {"status": "paused", "currentNode": "close",
                 "currentEvent": {"eventId": "E", "eventType": "congestion", "roadName": "路"}}
        set_lineage(state, new_lineage(run_id))
        repo.save_run(WorkflowRun(run_id=run_id, definition_id="def_e2e", version=1,
                                  status=WorkflowRunStatus.PAUSED, state=state))
        repo.mark_driver_managed(run_id)

        # WaitScheduler wake（direct wake path）
        from backend.workflow.wait_scheduler import WaitScheduler
        async def _wake():
            ws = WaitScheduler()
            await ws._resume_waiting_run(run_id)
        asyncio.run(_wake())
        assert repo.get_run(run_id).status.value == "pending"  # wake-only，不 resume

        async def _drive():
            driver = _make_driver(repo)
            await driver.start()
            try:
                return await _wait_for_status(repo, run_id, ["completed"])
            finally:
                await driver.stop()
        assert asyncio.run(_drive()).status.value == "completed"


class TestApprovalWake:
    def test_f14_f17_approve_then_driver(self, monkeypatch):
        """AWAITING_APPROVAL planning run → approve（PENDING）→ RunDriver execute。"""
        repo = _repo()
        _seed_definition(repo)
        from backend.workflow.models import generate_run_id, WorkflowRun, WorkflowRunStatus, NodeConfig, NodeType
        from backend.workflow.definition import generate_version_id, DefinitionManager
        from backend.workflow.models import WorkflowDefinitionVersion
        from backend.planning.budget import new_lineage, set_lineage

        # 含 human_approval 的 definition
        d = _minimal_definition()
        d.nodes = [
            NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER, next_nodes=["human_approval"]),
            NodeConfig(node_id="human_approval", node_type=NodeType.HUMAN_APPROVAL, next_nodes=["close"],
                       config={"action_types": ["notify_wechat"]}),
            NodeConfig(node_id="close", node_type=NodeType.CLOSE),
        ]
        repo.save_definition(d)
        repo.save_definition_version(WorkflowDefinitionVersion(
            id=generate_version_id(), definition_id=d.id, version=1, definition_json=d.to_dict()))

        run_id = generate_run_id()
        state = {"status": "awaiting_approval", "currentNode": "human_approval",
                 "pendingApproval": {"approvalId": "a1", "nodeId": "human_approval",
                                     "proposedActions": [{"actionType": "notify_wechat"}]},
                 "currentEvent": {"eventId": "E", "eventType": "congestion", "roadName": "路"}}
        set_lineage(state, new_lineage(run_id))
        repo.save_run(WorkflowRun(run_id=run_id, definition_id="def_e2e", version=1,
                                  status=WorkflowRunStatus.AWAITING_APPROVAL, state=state))
        repo.mark_driver_managed(run_id)

        # approve（wake-only）
        from backend.workflow.executor import WorkflowExecutor
        async def _approve():
            executor = WorkflowExecutor(repo)
            return await executor.approve(run_id, reviewer="t", comment="ok")
        result = asyncio.run(_approve())
        assert "error" not in result, result
        assert repo.get_run(run_id).status.value == "pending"  # approve 后 PENDING，不 resume

        async def _drive():
            driver = _make_driver(repo)
            await driver.start()
            try:
                return await _wait_for_status(repo, run_id, ["completed"])
            finally:
                await driver.stop()
        assert asyncio.run(_drive()).status.value == "completed"


class TestApprovalRestartE2E:
    def test_f06_approval_restart(self):
        """AWAITING_APPROVAL 持久化 → 新 instance 读取 + approve → driver 继续。"""
        from backend.workflow.models import generate_run_id, WorkflowRun, WorkflowRunStatus, NodeConfig, NodeType, WorkflowDefinitionVersion, WorkflowApproval, ApprovalDecision
        from backend.workflow.definition import generate_version_id
        from backend.planning.budget import new_lineage, set_lineage

        repo_a = _repo()
        d = _minimal_definition()
        d.nodes = [
            NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER, next_nodes=["human_approval"]),
            NodeConfig(node_id="human_approval", node_type=NodeType.HUMAN_APPROVAL, next_nodes=["close"],
                       config={"action_types": ["notify_wechat"]}),
            NodeConfig(node_id="close", node_type=NodeType.CLOSE),
        ]
        repo_a.save_definition(d)
        repo_a.save_definition_version(WorkflowDefinitionVersion(
            id=generate_version_id(), definition_id=d.id, version=1, definition_json=d.to_dict()))

        run_id = generate_run_id()
        state = {"status": "awaiting_approval", "currentNode": "human_approval",
                 "pendingApproval": {"approvalId": "a1", "nodeId": "human_approval",
                                     "proposedActions": [{"actionType": "notify_wechat"}]},
                 "currentEvent": {"eventId": "E", "eventType": "congestion", "roadName": "路"}}
        set_lineage(state, new_lineage(run_id))
        repo_a.save_run(WorkflowRun(run_id=run_id, definition_id="def_e2e", version=1,
                                    status=WorkflowRunStatus.AWAITING_APPROVAL, state=state))
        repo_a.mark_driver_managed(run_id)
        repo_a.save_approval(WorkflowApproval(approval_id="a1", run_id=run_id, node_id="human_approval",
                                              proposed_actions=[{"actionType": "notify_wechat"}],
                                              decision=ApprovalDecision.PENDING))

        # ── 新 instance B（同 DB）──
        repo_b = _repo()
        assert repo_b.get_run(run_id).status.value == "awaiting_approval"
        assert repo_b.get_pending_approval(run_id, "human_approval") is not None

        from backend.workflow.executor import WorkflowExecutor
        async def _approve_b():
            return await WorkflowExecutor(repo_b).approve(run_id, reviewer="b", comment="ok")
        assert "error" not in asyncio.run(_approve_b())
        assert repo_b.get_run(run_id).status.value == "pending"

        async def _drive_b():
            driver_b = _make_driver(repo_b)
            await driver_b.start()
            try:
                return await _wait_for_status(repo_b, run_id, ["completed"])
            finally:
                await driver_b.stop()
        assert asyncio.run(_drive_b()).status.value == "completed"


class TestBudgetRestartE2E:
    def test_f07_budget_restart(self):
        """instance A 消费 budget → 新 instance B 读取：usage 不 reset。"""
        from backend.workflow.models import generate_run_id, WorkflowRun, WorkflowRunStatus
        from backend.planning.budget import new_lineage, set_lineage, get_lineage, reserve_tool_call, reserve_step, ExecutionBudgetLimits

        repo_a = _repo()
        run_id = generate_run_id()
        state = {"status": "pending", "currentEvent": {"eventId": "E", "eventType": "congestion", "roadName": "路"}}
        lin = new_lineage(run_id, ExecutionBudgetLimits(maxToolCalls=2))
        reserve_tool_call(lin)
        reserve_step(lin); reserve_step(lin)
        set_lineage(state, lin)
        repo_a.save_run(WorkflowRun(run_id=run_id, definition_id="def_e2e", version=1,
                                    status=WorkflowRunStatus.PENDING, state=state))
        repo_a.mark_driver_managed(run_id)

        repo_b = _repo()
        lin_b = get_lineage(repo_b.get_run(run_id).state)
        assert lin_b.budgetUsage.toolCallsUsed == 1
        assert lin_b.budgetUsage.stepsUsed == 2
        assert reserve_tool_call(lin_b) is True
        assert reserve_tool_call(lin_b) is False


class TestCursorRecoveryE2E:
    def test_f04_f09_cursor_recovery_no_prefix_rerun(self, monkeypatch):
        """A/B SUCCEEDED，C（action）RUNNING stale → 从 C 恢复，A/B 不重跑。"""
        from backend.workflow.models import NodeConfig, NodeType, WorkflowDefinition, DefinitionStatus, WorkflowDefinitionVersion, WorkflowRun, WorkflowRunStatus, WorkflowNodeRun, NodeStatus, generate_run_id
        from backend.workflow.definition import generate_version_id
        from backend.planning.budget import new_lineage, set_lineage

        repo = _repo()
        d = WorkflowDefinition(id="def_cur", name="cur", status=DefinitionStatus.ACTIVE,
            nodes=[
                NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER, next_nodes=["validate_event"]),
                NodeConfig(node_id="validate_event", node_type=NodeType.VALIDATE_EVENT, next_nodes=["agent_task"]),
                NodeConfig(node_id="agent_task", node_type=NodeType.AGENT_TASK, next_nodes=["action_save"],
                           config={"agent_name": "CongestionAgent"}),
                NodeConfig(node_id="action_save", node_type=NodeType.ACTION, next_nodes=["close"],
                           config={"action_type": "save_result", "action_params": {}}),
                NodeConfig(node_id="close", node_type=NodeType.CLOSE),
            ], entry_node_id="trigger")
        repo.save_definition(d)
        repo.save_definition_version(WorkflowDefinitionVersion(
            id=generate_version_id(), definition_id="def_cur", version=1, definition_json=d.to_dict()))

        run_id = generate_run_id()
        state = {"status": "running", "currentNode": "action_save",
                 "currentEvent": {"eventId": "E", "eventType": "congestion", "roadName": "路"}}
        set_lineage(state, new_lineage(run_id))
        repo.save_run(WorkflowRun(run_id=run_id, definition_id="def_cur", version=1,
                                  status=WorkflowRunStatus.RUNNING, state=state))
        repo.mark_driver_managed(run_id)
        # node_runs: trigger/validate/agent succeeded，action RUNNING（stale）
        def _nr(node_id, status):
            repo.save_node_run(WorkflowNodeRun(node_run_id=f"nr_{run_id}_{node_id}", run_id=run_id, node_id=node_id,
                                               node_type=NodeType.ACTION if node_id == "action_save" else NodeType.VALIDATE_EVENT,
                                               status=status, attempt=1))
        _nr("trigger", NodeStatus.SUCCEEDED)
        _nr("validate_event", NodeStatus.SUCCEEDED)
        _nr("agent_task", NodeStatus.SUCCEEDED)
        _nr("action_save", NodeStatus.RUNNING)

        calls = []
        async def fake_dispatch(at, p, st):
            calls.append(at)
            return {"saved": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        claim = repo.claim_driver_run(run_id, "driver_cur", "2099-01-01T00:00:00Z")
        assert claim["claimed"] is True

        async def _drive():
            from backend.workflow.run_driver import RunDriver
            driver = RunDriver(repo, owner_id="driver_cur")  # 与 claim owner 一致
            await driver._drive(run_id, claim["generation"])
        asyncio.run(_drive())

        run = repo.get_run(run_id)
        assert run.status.value == "completed"
        # save_result 只 dispatch 一次（C 恢复），A/B 无 side effect
        assert calls == ["save_result"]
        # A/B 不重跑：node_runs 中 trigger/validate/agent 仍只有 1 条 succeeded
        node_ids = [nr.node_id for nr in repo.get_node_runs(run_id)]
        assert node_ids.count("trigger") == 1
        assert node_ids.count("validate_event") == 1
