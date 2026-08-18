"""
Phase 17 PR#9 Safety Closure — S01-S10 runtime safety tests
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
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_r3_safety.db"))


def _repo():
    from backend.workflow.repository import SQLiteWorkflowRepository
    return SQLiteWorkflowRepository()


def _minimal_definition(def_id="def_safe"):
    from backend.workflow.models import NodeConfig, NodeType, WorkflowDefinition, DefinitionStatus
    return WorkflowDefinition(id=def_id, name="safe", status=DefinitionStatus.ACTIVE,
        nodes=[NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER, next_nodes=["validate_event"]),
               NodeConfig(node_id="validate_event", node_type=NodeType.VALIDATE_EVENT, next_nodes=["close"]),
               NodeConfig(node_id="close", node_type=NodeType.CLOSE)],
        entry_node_id="trigger")


def _seed(repo, def_id="def_safe"):
    from backend.workflow.models import WorkflowDefinitionVersion
    from backend.workflow.definition import generate_version_id
    d = _minimal_definition(def_id)
    repo.save_definition(d)
    repo.save_definition_version(WorkflowDefinitionVersion(
        id=generate_version_id(), definition_id=def_id, version=1, definition_json=d.to_dict()))
    return d


def _pending_run(repo, run_id, def_id="def_safe"):
    from backend.workflow.models import WorkflowRun, WorkflowRunStatus
    from backend.planning.budget import new_lineage, set_lineage
    state = {"status": "pending", "currentEvent": {"eventId": "E", "eventType": "congestion", "roadName": "路"}}
    set_lineage(state, new_lineage(run_id))
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=def_id, version=1,
                              status=WorkflowRunStatus.PENDING, state=state))
    repo.mark_driver_managed(run_id)


class TestLeaseLossStop:
    def test_s01_lease_loss_stops_execution(self):
        from backend.workflow.models import generate_run_id
        from backend.workflow.executor import get_executor
        repo = _repo()
        _seed(repo)
        run_id = generate_run_id()
        _pending_run(repo, run_id)
        c1 = repo.claim_driver_run(run_id, "w1", "2000-01-01T00:00:00Z")  # 已过期 lease
        c2 = repo.claim_driver_run(run_id, "w2", "2099-01-01T00:00:00Z")  # takeover gen2
        assert c2["claimed"] is True

        executor = get_executor()
        executor.set_driver_context("w1", c1["generation"])  # stale gen1
        async def run():
            async for _ in executor.execute_created_run(run_id):
                pass
        asyncio.run(run())
        run = repo.get_run(run_id)
        # w1（stale）不得推进到 completed
        assert run.status.value != "completed"

    def test_s02_dispatch_fencing_after_lease_loss(self, monkeypatch):
        from backend.workflow.models import generate_run_id, NodeConfig, NodeType
        from backend.workflow.nodes.action import execute_action
        from backend.workflow.state import TrafficWorkflowState
        repo = _repo()
        _seed(repo)
        run_id = generate_run_id()
        _pending_run(repo, run_id)
        repo.claim_driver_run(run_id, "w1", "2000-01-01T00:00:00Z")
        repo.claim_driver_run(run_id, "w2", "2099-01-01T00:00:00Z")  # gen2 takeover

        calls = []
        async def fake_dispatch(at, p, st):
            calls.append(at)
            return {"saved": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        st = TrafficWorkflowState(workflow_run_id=run_id)
        # stale gen1 → fencing 失败，不 dispatch
        out = asyncio.run(execute_action(
            st, NodeConfig(node_id="a1", node_type=NodeType.ACTION, config={"action_type": "save_result"}),
            repository=repo, driver_owner="w1", driver_generation=1))
        assert out.get("status") == "lease_lost"
        assert out.get("executed") is False
        assert calls == []


class TestDispatchMarkerFailClosed:
    def test_s03_marker_persist_fail_no_dispatch(self, monkeypatch):
        from backend.workflow.models import generate_run_id, NodeConfig, NodeType
        from backend.workflow.nodes.action import execute_action
        from backend.workflow.state import TrafficWorkflowState
        repo = _repo()
        _seed(repo)
        run_id = generate_run_id()
        _pending_run(repo, run_id)
        c = repo.claim_driver_run(run_id, "w1", "2099-01-01T00:00:00Z")
        assert c["claimed"] is True
        # 但 marker persist 抛错
        calls = []
        async def fake_dispatch(at, p, st):
            calls.append(at)
            return {"saved": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        def _boom(record):
            raise RuntimeError("db down")
        monkeypatch.setattr(repo, "save_action_record", _boom)

        st = TrafficWorkflowState(workflow_run_id=run_id)
        out = asyncio.run(execute_action(
            st, NodeConfig(node_id="a1", node_type=NodeType.ACTION, config={"action_type": "save_result"}),
            repository=repo, driver_owner="w1", driver_generation=c["generation"]))
        assert out.get("status") == "marker_persist_failed"
        assert out.get("executed") is False
        assert calls == []

    def test_s04_existing_executing_fail_closed(self):
        from backend.workflow.models import generate_run_id, NodeConfig, NodeType, WorkflowActionRecord, ActionStatus, compute_action_idempotency_key
        from backend.workflow.nodes.action import execute_action
        from backend.workflow.state import TrafficWorkflowState
        repo = _repo()
        _seed(repo)
        run_id = generate_run_id()
        _pending_run(repo, run_id)
        repo.claim_driver_run(run_id, "w1", "2099-01-01T00:00:00Z")
        # 预置 EXECUTING record（同 idempotency_key）
        repo.save_action_record(WorkflowActionRecord(
            action_id="wfact_s04", run_id=run_id, node_id="a1", action_type="save_result",
            idempotency_key=compute_action_idempotency_key(run_id, "a1", "save_result"),
            status=ActionStatus.EXECUTING))

        st = TrafficWorkflowState(workflow_run_id=run_id)
        out = asyncio.run(execute_action(
            st, NodeConfig(node_id="a1", node_type=NodeType.ACTION, config={"action_type": "save_result"}),
            repository=repo, driver_owner="w1", driver_generation=1))
        assert out.get("status") == "in_flight"
        assert out.get("executed") is False


class TestTerminalResultFailSafe:
    def test_s05_terminal_result_fail_not_succeeded(self, monkeypatch):
        from backend.workflow.models import generate_run_id, NodeConfig, NodeType
        from backend.workflow.nodes.action import execute_action
        from backend.workflow.state import TrafficWorkflowState
        repo = _repo()
        _seed(repo)
        run_id = generate_run_id()
        _pending_run(repo, run_id)
        c = repo.claim_driver_run(run_id, "w1", "2099-01-01T00:00:00Z")
        calls = []
        async def fake_dispatch(at, p, st):
            calls.append(at)
            return {"saved": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        # marker save 成功，terminal save 失败（第二次调用抛错）
        real_save = repo.save_action_record
        cnt = {"n": 0}
        def flaky_save(record):
            cnt["n"] += 1
            if cnt["n"] >= 2:
                raise RuntimeError("terminal save db down")
            real_save(record)
        monkeypatch.setattr(repo, "save_action_record", flaky_save)

        st = TrafficWorkflowState(workflow_run_id=run_id)
        out = asyncio.run(execute_action(
            st, NodeConfig(node_id="a1", node_type=NodeType.ACTION, config={"action_type": "save_result"}),
            repository=repo, driver_owner="w1", driver_generation=c["generation"]))
        # external 已发生，但 terminal result 持久化失败 → 不标 SUCCEEDED
        assert calls == ["save_result"]
        assert out.get("status") == "result_persist_failed"


class TestFencedActiveSegment:
    def test_s06_stale_active_segment_no_overwrite(self):
        from backend.workflow.models import generate_run_id
        from backend.workflow.executor import get_executor
        repo = _repo()
        _seed(repo)
        run_id = generate_run_id()
        _pending_run(repo, run_id)
        c1 = repo.claim_driver_run(run_id, "w1", "2000-01-01T00:00:00Z")
        repo.claim_driver_run(run_id, "w2", "2099-01-01T00:00:00Z")  # gen2

        executor = get_executor()
        executor.set_driver_context("w1", c1["generation"])  # stale
        run = repo.get_run(run_id)
        executor._close_active_segment(run)
        # stale close 不得覆盖 w2 的 lease（is_driver_owner(w2) 仍 true）
        assert repo.is_driver_owner(run_id, "w2", 2) is True


class TestAtomicManagedCreation:
    def test_s07_child_driver_managed_in_tx(self):
        from backend.workflow.models import generate_run_id, WorkflowRun, WorkflowRunStatus
        from backend.planning.budget import new_lineage, set_lineage
        repo = _repo()
        _seed(repo)
        parent = generate_run_id()
        _pending_run(repo, parent)
        child_id = f"wfrun_cont_{generate_run_id()[:8]}"
        state = {"status": "pending"}
        set_lineage(state, new_lineage(parent))
        child = WorkflowRun(run_id=child_id, definition_id="def_safe", version=0,
                            status=WorkflowRunStatus.PENDING, state=state)
        repo.create_child_continuation_tx(
            child_run=child, parent_run_id=parent, parent_status="failed",
            parent_state={"status": "failed", "replannedToRunId": child_id},
            definition_json={"id": "def_safe", "nodes": []})
        # 无需 mark_driver_managed；tx 内已落库 driver_managed=1
        assert repo.is_driver_managed(child_id) is True
        assert child_id in [r.run_id for r in repo.list_driver_candidates()]

    def test_s08_root_managed_atomic(self):
        from backend.workflow.models import generate_run_id, WorkflowRun, WorkflowRunStatus
        from backend.planning.budget import new_lineage, set_lineage
        repo = _repo()
        run_id = generate_run_id()
        state = {"status": "pending", "currentEvent": {"eventId": "E"}}
        set_lineage(state, new_lineage(run_id))
        run = WorkflowRun(run_id=run_id, definition_id="def_safe", version=1,
                          status=WorkflowRunStatus.PENDING, state=state)
        repo.save_driver_managed_run(run)
        assert repo.is_driver_managed(run_id) is True


class TestConcurrentVersionAllocation:
    def test_s09_parent_replanned_version_matches_child(self):
        from backend.workflow.models import generate_run_id, WorkflowRun, WorkflowRunStatus
        from backend.planning.budget import new_lineage, set_lineage
        repo = _repo()
        _seed(repo)
        # rootA v1 + rootB v1
        rootA = generate_run_id(); rootB = generate_run_id()
        _pending_run(repo, rootA); _pending_run(repo, rootB)
        def _replan(root, child_id):
            state = {"status": "pending"}
            set_lineage(state, new_lineage(root))
            child = WorkflowRun(run_id=child_id, definition_id="def_safe", version=0,
                                status=WorkflowRunStatus.PENDING, state=state)
            parent_state = {"status": "failed", "replannedToRunId": child_id}
            v = repo.create_child_continuation_tx(
                child_run=child, parent_run_id=root, parent_status="failed",
                parent_state=parent_state, definition_json={"id": "def_safe", "nodes": []})
            return v
        childA = f"wfrun_cont_a{generate_run_id()[:6]}"
        childB = f"wfrun_cont_b{generate_run_id()[:6]}"
        vA = _replan(rootA, childA)
        vB = _replan(rootB, childB)
        assert vA != vB
        parentA = repo.get_run(rootA)
        parentB = repo.get_run(rootB)
        assert parentA.state["replannedToVersion"] == vA == repo.get_run(childA).version
        assert parentB.state["replannedToVersion"] == vB == repo.get_run(childB).version


class TestFilterPagination:
    def test_s10_filter_before_pagination(self):
        from backend.planning.models import Plan, PlanStep, GoalType, PlanDefinitionStatus, compute_fingerprint
        from backend.workflow.models import NodeType
        from backend.planning.adapter import plan_to_definition
        repo = _repo()
        # 创建 3 个 plan（2 个 congestion + 1 个 accident），只留 congestion 有 goalType
        for i in range(3):
            gt = GoalType.CONGESTION_RESOLUTION if i < 2 else GoalType.ACCIDENT_RESPONSE
            steps = [PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT),
                     PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["validate_event"])]
            p = Plan(planId=f"plan_s{i}", planFingerprint=compute_fingerprint(steps), goal=f"goal{i}",
                     goalType=gt, definitionStatus=PlanDefinitionStatus.ACTIVE, version=1, steps=steps)
            repo.save_definition(plan_to_definition(p))
        # 直接调 api list_plans（注入 repo）
        import backend.planning.api as api_mod
        orig = api_mod._repo
        api_mod._repo = repo
        try:
            r = asyncio.run(api_mod.list_plans(page=1, pageSize=1, goalType="congestion_resolution"))
        finally:
            api_mod._repo = orig
        assert r["total"] == 2  # filtered total
        assert len(r["plans"]) == 1  # page size 1
        assert r["plans"][0]["goalType"] == "congestion_resolution"
