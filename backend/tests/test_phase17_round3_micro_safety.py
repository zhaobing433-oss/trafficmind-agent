"""
Phase 17 PR#9 Final Micro Safety Closure — M01-M04 + P01-P03

M01: 迟到 node 完成 fencing（lease 在 node 执行期间被 takeover）
M02: marker 持久化失败 → 完整 run 不 dispatch / node != SUCCEEDED / run != COMPLETED
M03: 已有 EXECUTING → 完整 run 不 dispatch / node != SUCCEEDED / run != COMPLETED
M04: lease_lost sentinel 不被当普通 success node 持久化
P01-P03: plan 分页 >1000 无上限 + filter-before-pagination
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_r3_micro_safety.db"))


def _repo():
    from backend.workflow.repository import SQLiteWorkflowRepository
    return SQLiteWorkflowRepository()


def _action_definition(def_id="def_action"):
    from backend.workflow.models import NodeConfig, NodeType, WorkflowDefinition, DefinitionStatus
    return WorkflowDefinition(
        id=def_id, name="action_safe", status=DefinitionStatus.ACTIVE,
        nodes=[
            NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER, next_nodes=["a1"]),
            NodeConfig(node_id="a1", node_type=NodeType.ACTION, next_nodes=["close"],
                       config={"action_type": "save_result"}, max_attempts=1),
            NodeConfig(node_id="close", node_type=NodeType.CLOSE),
        ],
        entry_node_id="trigger",
    )


def _seed_def(repo, definition):
    from backend.workflow.models import WorkflowDefinitionVersion
    from backend.workflow.definition import generate_version_id
    repo.save_definition(definition)
    repo.save_definition_version(WorkflowDefinitionVersion(
        id=generate_version_id(), definition_id=definition.id, version=1,
        definition_json=definition.to_dict()))
    return definition


def _pending_run(repo, run_id, def_id="def_action"):
    from backend.workflow.models import WorkflowRun, WorkflowRunStatus
    from backend.planning.budget import new_lineage, set_lineage
    state = {"status": "pending", "currentEvent": {"eventId": "E", "eventType": "congestion", "roadName": "路"}}
    set_lineage(state, new_lineage(run_id))
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=def_id, version=1,
                              status=WorkflowRunStatus.PENDING, state=state))
    repo.mark_driver_managed(run_id)


def _drive(executor, run_id):
    async def _run():
        async for _ in executor.execute_created_run(run_id):
            pass
    asyncio.run(_run())


def _expire_lease(run_id):
    """手动将 run 的 lease 置为过期（用于模拟执行期间 lease 到期）。"""
    import sqlite3
    conn = sqlite3.connect(cfg.DB_PATH)
    conn.execute("UPDATE workflow_runs SET driver_lease_until='2000-01-01T00:00:00Z' WHERE run_id=?", (run_id,))
    conn.commit()
    conn.close()


class TestLateNodeCompletionFencing:
    def test_m01_late_node_completion_no_progression(self, monkeypatch):
        from backend.workflow.models import generate_run_id
        from backend.workflow.executor import WorkflowExecutor
        from backend.planning.budget import get_lineage

        repo = _repo()
        _seed_def(repo, _action_definition())
        run_id = generate_run_id()
        _pending_run(repo, run_id, "def_action")

        c1 = repo.claim_driver_run(run_id, "w1", "2099-01-01T00:00:00Z")  # gen1（valid lease，执行期间才过期）
        assert c1["claimed"] is True

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_dispatch(at, p, st):
            started.set()
            await release.wait()
            return {"saved": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", slow_dispatch)

        executor = WorkflowExecutor(repository=repo)
        executor.set_driver_context("w1", c1["generation"])

        async def main():
            async def drive():
                async for _ in executor.execute_created_run(run_id):
                    pass
            task = asyncio.create_task(drive())
            await asyncio.wait_for(started.wait(), timeout=10.0)  # action node 已开始 dispatch
            _expire_lease(run_id)  # 手动让 gen1 lease 过期
            c2 = repo.claim_driver_run(run_id, "w2", "2099-01-01T00:00:00Z")  # gen2 takeover
            assert c2["claimed"] is True
            release.set()
            await asyncio.wait_for(task, timeout=10.0)
            return c2

        c2 = asyncio.run(main())

        run = repo.get_run(run_id)
        # 旧 generation 不得推进 run 到 terminal / 覆盖 cursor
        assert run.status.value == "running"
        assert run.current_node_id == "a1"
        # 旧 generation 不得写 node terminal（SUCCEEDED/FAILED）
        node_runs = repo.get_node_runs(run_id)
        assert not any(nr.node_id == "a1" and nr.status.value in ("succeeded", "failed") for nr in node_runs)
        # 旧 generation 不得写 node_completed 事件
        events = repo.list_events(run_id)
        assert not any(e.event_type == "node_completed" and e.node_id == "a1" for e in events)
        # 迟到完成不得增量 stepsUsed
        lineage = get_lineage(run.state if isinstance(run.state, dict) else {})
        assert lineage.budgetUsage.stepsUsed == 0
        # B 仍是合法 owner
        assert repo.is_driver_owner(run_id, "w2", c2["generation"]) is True


class TestActionFailClosed:
    def test_m02_marker_persist_fail_no_dispatch_no_success(self, monkeypatch):
        from backend.workflow.models import generate_run_id
        from backend.workflow.executor import WorkflowExecutor

        repo = _repo()
        _seed_def(repo, _action_definition())
        run_id = generate_run_id()
        _pending_run(repo, run_id, "def_action")
        c = repo.claim_driver_run(run_id, "w1", "2099-01-01T00:00:00Z")
        assert c["claimed"] is True

        calls = []
        async def fake_dispatch(at, p, st):
            calls.append(at)
            return {"saved": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        def _boom(record):
            raise RuntimeError("db down")
        monkeypatch.setattr(repo, "save_action_record", _boom)

        executor = WorkflowExecutor(repository=repo)
        executor.set_driver_context("w1", c["generation"])
        _drive(executor, run_id)

        assert calls == []  # external call count == 0
        run = repo.get_run(run_id)
        assert run.status.value == "failed"  # 不 COMPLETED
        a1_runs = [nr for nr in repo.get_node_runs(run_id) if nr.node_id == "a1"]
        assert a1_runs and all(nr.status.value == "failed" for nr in a1_runs)  # node != SUCCEEDED

    def test_m03_existing_executing_no_dispatch_no_success(self, monkeypatch):
        from backend.workflow.models import (
            generate_run_id, WorkflowActionRecord, ActionStatus, compute_action_idempotency_key,
        )
        from backend.workflow.executor import WorkflowExecutor

        repo = _repo()
        _seed_def(repo, _action_definition())
        run_id = generate_run_id()
        _pending_run(repo, run_id, "def_action")
        c = repo.claim_driver_run(run_id, "w1", "2099-01-01T00:00:00Z")
        assert c["claimed"] is True

        # 预置同 idempotency_key 的 EXECUTING record
        repo.save_action_record(WorkflowActionRecord(
            action_id="wfact_m03", run_id=run_id, node_id="a1", action_type="save_result",
            idempotency_key=compute_action_idempotency_key(run_id, "a1", "save_result"),
            status=ActionStatus.EXECUTING))

        calls = []
        async def fake_dispatch(at, p, st):
            calls.append(at)
            return {"saved": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        executor = WorkflowExecutor(repository=repo)
        executor.set_driver_context("w1", c["generation"])
        _drive(executor, run_id)

        assert calls == []  # 强化旧 S04：真正 mock _dispatch_action 并断言 call count == 0
        run = repo.get_run(run_id)
        assert run.status.value == "failed"
        a1_runs = [nr for nr in repo.get_node_runs(run_id) if nr.node_id == "a1"]
        assert a1_runs and all(nr.status.value == "failed" for nr in a1_runs)

    def test_m04_lease_lost_not_node_success(self):
        from backend.workflow.models import generate_run_id
        from backend.workflow.executor import WorkflowExecutor
        from backend.workflow.nodes.base import get_node_registry

        repo = _repo()
        _seed_def(repo, _action_definition())
        run_id = generate_run_id()
        _pending_run(repo, run_id, "def_action")
        c = repo.claim_driver_run(run_id, "w1", "2099-01-01T00:00:00Z")
        assert c["claimed"] is True

        executor = WorkflowExecutor(repository=repo)
        executor.set_driver_context("w1", c["generation"])

        # 覆盖 action executor → 返回 lease_lost sentinel（模拟 action 检测到 lease loss）
        async def _lease_lost_action(state, config, repository=None, driver_owner="", driver_generation=0):
            return {"status": "lease_lost", "executed": False, "reason": "driver lease lost"}
        registry = get_node_registry()
        orig_action = registry.get("action")
        registry.register("action", _lease_lost_action)
        try:
            _drive(executor, run_id)
        finally:
            registry.register("action", orig_action)

        run = repo.get_run(run_id)
        # lease_lost sentinel 不得被当普通 success：run 不 COMPLETED、cursor 不推进、node 不 SUCCEEDED
        assert run.status.value != "completed"
        assert run.current_node_id == "a1"
        node_runs = repo.get_node_runs(run_id)
        assert not any(nr.node_id == "a1" and nr.status.value == "succeeded" for nr in node_runs)


class TestPlanPagination:
    def _make_plan(self, i, goal=None, goal_type=None):
        from backend.planning.models import Plan, PlanStep, GoalType, PlanDefinitionStatus, compute_fingerprint
        from backend.workflow.models import NodeType
        steps = [PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT),
                 PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["validate_event"])]
        return Plan(
            planId=f"plan_s{i:04d}",
            planFingerprint=compute_fingerprint(steps),
            goal=goal if goal is not None else f"goal_{i}",
            goalType=goal_type or GoalType.CONGESTION_RESOLUTION,
            definitionStatus=PlanDefinitionStatus.ACTIVE,
            version=1,
            steps=steps,
        )

    def _save_plans(self, repo, n, goal_type_fn=None, goal_fn=None):
        from backend.planning.adapter import plan_to_definition
        for i in range(n):
            gt = goal_type_fn(i) if goal_type_fn else None
            goal = goal_fn(i) if goal_fn else None
            repo.save_definition(plan_to_definition(self._make_plan(i, goal=goal, goal_type=gt)))

    def _list(self, repo, **kwargs):
        import backend.planning.api as api_mod
        orig = api_mod._repo
        api_mod._repo = repo
        try:
            return asyncio.run(api_mod.list_plans(**kwargs))
        finally:
            api_mod._repo = orig

    def test_p01_search_beyond_1000(self):
        from backend.planning.models import GoalType
        repo = _repo()
        target = "zzz_unique_target_goal"
        self._save_plans(repo, 1010, goal_fn=lambda i: target if i == 1009 else f"goal_{i}")
        r = self._list(repo, page=1, pageSize=100, search="zzz_unique_target")
        assert r["total"] == 1
        assert len(r["plans"]) == 1
        assert r["plans"][0]["goal"] == target

    def test_p02_goaltype_beyond_1000(self):
        from backend.planning.models import GoalType
        repo = _repo()
        # 5 个 accident 在最后（index 1000-1004）
        self._save_plans(repo, 1005, goal_type_fn=lambda i: GoalType.ACCIDENT_RESPONSE if i >= 1000 else GoalType.CONGESTION_RESOLUTION)
        r = self._list(repo, page=1, pageSize=100, goalType="accident_response")
        assert r["total"] == 5
        assert len(r["plans"]) == 5
        assert all(p["goalType"] == "accident_response" for p in r["plans"])

    def test_p03_status_filter_correct(self):
        from backend.workflow.models import generate_run_id, WorkflowRun, WorkflowRunStatus
        repo = _repo()
        self._save_plans(repo, 3)
        # latest run status：p0=failed, p1=completed, p2=failed
        for i, status in enumerate(["failed", "completed", "failed"]):
            repo.save_run(WorkflowRun(
                run_id=generate_run_id(), definition_id=f"plan_s{i:04d}", version=1,
                status=WorkflowRunStatus(status), state={}, updated_at="2026-01-01T00:00:00Z",
            ))
        r = self._list(repo, page=1, pageSize=100, status="failed")
        assert r["total"] == 2
        assert all(p["latestExecutionStatus"] == "failed" for p in r["plans"])
