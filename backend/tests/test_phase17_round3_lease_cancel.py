"""
Phase 17 PR#9 Final Lease & Cancellation Closure — LC01-LC08

L1-L4: temporal lease validity（identity vs execution-valid）
C1-C4: cancellation dispatch/progression gates
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
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_r3_lease_cancel.db"))


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


class TestLeaseValidity:
    def test_lc01_expired_lease_not_execution_valid(self):
        from backend.workflow.models import generate_run_id
        repo = _repo()
        run_id = generate_run_id()
        _pending_run(repo, run_id, "def_action")
        c = repo.claim_driver_run(run_id, "w1", "2000-01-01T00:00:00Z")  # 已过期 lease，无 takeover
        assert c["claimed"] is True
        # identity（owner/gen）仍匹配
        assert repo.is_driver_owner(run_id, "w1", c["generation"]) is True
        # execution-valid（含 lease 未过期）→ False
        assert repo.is_driver_execution_valid(run_id, "w1", c["generation"]) is False

    def test_lc02_expired_lease_no_dispatch(self, monkeypatch):
        from backend.workflow.models import generate_run_id, NodeConfig, NodeType
        from backend.workflow.nodes.action import execute_action
        from backend.workflow.state import TrafficWorkflowState
        repo = _repo()
        _seed_def(repo, _action_definition())
        run_id = generate_run_id()
        _pending_run(repo, run_id, "def_action")
        c = repo.claim_driver_run(run_id, "w1", "2000-01-01T00:00:00Z")  # 已过期 lease，无 takeover
        assert c["claimed"] is True

        calls = []
        async def fake_dispatch(at, p, st):
            calls.append(at)
            return {"saved": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        st = TrafficWorkflowState(workflow_run_id=run_id)
        out = asyncio.run(execute_action(
            st, NodeConfig(node_id="a1", node_type=NodeType.ACTION, config={"action_type": "save_result"}),
            repository=repo, driver_owner="w1", driver_generation=c["generation"]))
        assert out.get("status") == "lease_lost"
        assert out.get("executed") is False
        assert calls == []

    def test_lc03_expired_lease_fenced_false(self):
        from backend.workflow.models import generate_run_id
        repo = _repo()
        run_id = generate_run_id()
        _pending_run(repo, run_id, "def_action")
        c = repo.claim_driver_run(run_id, "w1", "2000-01-01T00:00:00Z")  # 已过期 lease
        assert c["claimed"] is True
        ok = repo.fenced_update_run(run_id, "w1", c["generation"], "running", "trigger", {"status": "running"})
        assert ok is False  # lease 过期 → 不得写 control state

    def test_lc04_expired_lease_heartbeat_false(self):
        from backend.workflow.models import generate_run_id
        repo = _repo()
        run_id = generate_run_id()
        _pending_run(repo, run_id, "def_action")
        c = repo.claim_driver_run(run_id, "w1", "2000-01-01T00:00:00Z")  # 已过期 lease
        assert c["claimed"] is True
        ok = repo.heartbeat_driver_lease(run_id, "w1", c["generation"], "2099-01-01T00:00:00Z")
        assert ok is False  # 不能复活过期 lease


class TestCancellationBeforeDispatch:
    def test_lc05_cancel_before_action_no_dispatch(self, monkeypatch):
        from backend.workflow.models import generate_run_id, NodeConfig, NodeType
        from backend.workflow.nodes.action import execute_action
        from backend.workflow.state import TrafficWorkflowState
        from backend.planning.budget import get_lineage
        repo = _repo()
        _seed_def(repo, _action_definition())
        run_id = generate_run_id()
        _pending_run(repo, run_id, "def_action")
        c = repo.claim_driver_run(run_id, "w1", "2099-01-01T00:00:00Z")
        assert c["claimed"] is True
        repo.set_run_status_managed(run_id, "cancelled")  # 在 action 前 cancel

        calls = []
        async def fake_dispatch(at, p, st):
            calls.append(at)
            return {"saved": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        st = TrafficWorkflowState(workflow_run_id=run_id)
        out = asyncio.run(execute_action(
            st, NodeConfig(node_id="a1", node_type=NodeType.ACTION, config={"action_type": "save_result"}),
            repository=repo, driver_owner="w1", driver_generation=c["generation"]))
        assert out.get("status") == "cancelled"
        assert calls == []
        # budget 不新增（toolCallsUsed 仍 0）
        run = repo.get_run(run_id)
        lineage = get_lineage(run.state if isinstance(run.state, dict) else {})
        assert lineage.budgetUsage.toolCallsUsed == 0
        # marker 不新增
        assert repo.list_action_records(run_id) == []

    def test_lc06_cancel_after_marker_before_dispatch(self, monkeypatch):
        from backend.workflow.models import generate_run_id, NodeConfig, NodeType
        from backend.workflow.nodes.action import execute_action
        from backend.workflow.state import TrafficWorkflowState
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

        # marker（EXECUTING）保存成功后立即 cancel，模拟 marker 与真正 dispatch 之间的 cancel
        real_save = repo.save_action_record
        counter = {"n": 0}
        def save_and_cancel(record):
            counter["n"] += 1
            real_save(record)
            if counter["n"] == 1:
                repo.set_run_status_managed(run_id, "cancelled")
        monkeypatch.setattr(repo, "save_action_record", save_and_cancel)

        st = TrafficWorkflowState(workflow_run_id=run_id)
        out = asyncio.run(execute_action(
            st, NodeConfig(node_id="a1", node_type=NodeType.ACTION, config={"action_type": "save_result"}),
            repository=repo, driver_owner="w1", driver_generation=c["generation"]))
        assert calls == []  # 绝不 dispatch
        assert out.get("status") == "cancelled"
        # marker 终结为 known-not-dispatched（FAILED/cancelled_before_dispatch），避免 UNKNOWN_OUTCOME false positive
        records = repo.list_action_records(run_id)
        assert len(records) == 1
        assert records[0].status.value == "failed"
        assert records[0].error == "cancelled_before_dispatch"


class TestCancellationDuringInFlight:
    def test_lc07_cancel_during_external_call(self, monkeypatch):
        from backend.workflow.models import generate_run_id
        from backend.workflow.executor import WorkflowExecutor
        from backend.planning.budget import get_lineage
        repo = _repo()
        _seed_def(repo, _action_definition())
        run_id = generate_run_id()
        _pending_run(repo, run_id, "def_action")
        c = repo.claim_driver_run(run_id, "w1", "2099-01-01T00:00:00Z")
        assert c["claimed"] is True

        started = asyncio.Event()
        release = asyncio.Event()
        async def slow_dispatch(at, p, st):
            started.set()
            await release.wait()
            return {"saved": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", slow_dispatch)

        executor = WorkflowExecutor(repository=repo)
        executor.set_driver_context("w1", c["generation"])

        async def main():
            async def drive():
                async for _ in executor.execute_created_run(run_id):
                    pass
            task = asyncio.create_task(drive())
            await asyncio.wait_for(started.wait(), timeout=10.0)  # external call 已开始
            repo.set_run_status_managed(run_id, "cancelled")
            release.set()
            await asyncio.wait_for(task, timeout=10.0)

        asyncio.run(main())

        run = repo.get_run(run_id)
        assert run.status.value == "cancelled"  # run 保持 CANCELLED
        assert run.current_node_id == "a1"  # cursor 未推进
        # node terminal 不推进
        node_runs = repo.get_node_runs(run_id)
        assert not any(nr.node_id == "a1" and nr.status.value in ("succeeded", "failed") for nr in node_runs)
        # stepsUsed 不变
        lineage = get_lineage(run.state if isinstance(run.state, dict) else {})
        assert lineage.budgetUsage.stepsUsed == 0
        # already-started external call factual result 允许保留
        records = repo.list_action_records(run_id)
        assert len(records) == 1 and records[0].status.value == "succeeded"

    def test_lc08_cancel_during_non_action_node(self, monkeypatch):
        from backend.workflow.models import generate_run_id, NodeConfig, NodeType, WorkflowDefinition, DefinitionStatus
        from backend.workflow.executor import WorkflowExecutor
        from backend.workflow.nodes.base import get_node_registry
        from backend.planning.budget import get_lineage

        started = asyncio.Event()
        release = asyncio.Event()
        async def slow_validate(state, config):
            started.set()
            await release.wait()
            return {"validated": True}

        repo = _repo()
        definition = WorkflowDefinition(
            id="def_v", name="v", status=DefinitionStatus.ACTIVE,
            nodes=[
                NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER, next_nodes=["validate_event"]),
                NodeConfig(node_id="validate_event", node_type=NodeType.VALIDATE_EVENT, next_nodes=["close"]),
                NodeConfig(node_id="close", node_type=NodeType.CLOSE),
            ],
            entry_node_id="trigger",
        )
        _seed_def(repo, definition)
        run_id = generate_run_id()
        _pending_run(repo, run_id, "def_v")
        c = repo.claim_driver_run(run_id, "w1", "2099-01-01T00:00:00Z")
        assert c["claimed"] is True

        executor = WorkflowExecutor(repository=repo)
        executor.set_driver_context("w1", c["generation"])

        registry = get_node_registry()
        orig = registry.get("validate_event")
        registry.register("validate_event", slow_validate)
        try:
            async def main():
                async def drive():
                    async for _ in executor.execute_created_run(run_id):
                        pass
                task = asyncio.create_task(drive())
                await asyncio.wait_for(started.wait(), timeout=10.0)  # slow non-action node 已开始
                repo.set_run_status_managed(run_id, "cancelled")
                release.set()
                await asyncio.wait_for(task, timeout=10.0)
            asyncio.run(main())
        finally:
            registry.register("validate_event", orig)

        run = repo.get_run(run_id)
        assert run.status.value == "cancelled"  # run 保持 CANCELLED
        assert run.current_node_id == "validate_event"  # cursor 未推进
        node_runs = repo.get_node_runs(run_id)
        assert not any(nr.node_id == "validate_event" and nr.status.value in ("succeeded", "failed") for nr in node_runs)
        lineage = get_lineage(run.state if isinstance(run.state, dict) else {})
        assert lineage.budgetUsage.stepsUsed == 0  # 迟到完成不增量 stepsUsed
