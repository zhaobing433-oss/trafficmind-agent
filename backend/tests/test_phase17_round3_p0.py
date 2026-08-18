"""
Phase 17 Round 3 P0 — Runtime Reliability tests（F01-F25 核心 contract）
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
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_r3.db"))


def _repo():
    from backend.workflow.repository import SQLiteWorkflowRepository
    return SQLiteWorkflowRepository()


def _minimal_definition():
    from backend.workflow.models import NodeConfig, NodeType, WorkflowDefinition, DefinitionStatus
    nodes = [
        NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER, next_nodes=["validate_event"]),
        NodeConfig(node_id="validate_event", node_type=NodeType.VALIDATE_EVENT, next_nodes=["close"]),
        NodeConfig(node_id="close", node_type=NodeType.CLOSE),
    ]
    return WorkflowDefinition(id="def_min", name="min", status=DefinitionStatus.ACTIVE,
                              nodes=nodes, entry_node_id="trigger")


def _pending_run(repo, run_id, definition_id="def_min", version=1, status="pending"):
    from backend.workflow.models import WorkflowRun, WorkflowRunStatus
    from backend.planning.budget import new_lineage, set_lineage
    state = {"status": status, "currentEvent": {"eventId": "E", "eventType": "congestion", "roadName": "路"}}
    set_lineage(state, new_lineage(run_id))
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=definition_id, version=version,
                              status=WorkflowRunStatus(status), state=state))
    repo.mark_driver_managed(run_id)
    return run_id


class TestClaim:
    def test_f03_exactly_one_claim(self):
        from backend.workflow.models import generate_run_id
        repo = _repo()
        run_id = _pending_run(repo, generate_run_id())
        c1 = repo.claim_driver_run(run_id, "worker1", "2099-01-01T00:00:00Z")
        c2 = repo.claim_driver_run(run_id, "worker2", "2099-01-01T00:00:00Z")
        assert c1["claimed"] is True
        assert c2["claimed"] is False  # 已被 worker1 持有

    def test_f21_fenced_write_generation_changed(self):
        from backend.workflow.models import generate_run_id
        repo = _repo()
        run_id = _pending_run(repo, generate_run_id())
        c1 = repo.claim_driver_run(run_id, "worker1", "2000-01-01T00:00:00Z")  # 已过期 lease
        # worker2 接管（lease 过期）
        c2 = repo.claim_driver_run(run_id, "worker2", "2099-01-01T00:00:00Z")
        assert c2["claimed"] is True
        assert c2["generation"] != c1["generation"]
        # 旧 worker（gen1）fenced write → rowcount 0
        ok = repo.fenced_update_run(run_id, "worker1", c1["generation"], "completed", "close", {"status": "completed"})
        assert ok is False
        # 新 worker 仍是 owner
        assert repo.is_driver_owner(run_id, "worker2", c2["generation"]) is True

    def test_f10_cancelled_not_claimed(self):
        from backend.workflow.models import generate_run_id, WorkflowRun, WorkflowRunStatus
        repo = _repo()
        run_id = generate_run_id()
        repo.save_run(WorkflowRun(run_id=run_id, definition_id="def_min", version=1,
                                  status=WorkflowRunStatus.CANCELLED, state={"status": "cancelled"}))
        repo.mark_driver_managed(run_id)
        c = repo.claim_driver_run(run_id, "worker1", "2099-01-01T00:00:00Z")
        assert c["claimed"] is False  # cancelled 不可 claim


class TestDriverPickup:
    def test_f02_pending_run_picked_up(self):
        from backend.workflow.models import generate_run_id, WorkflowDefinitionVersion
        from backend.workflow.definition import generate_version_id
        from backend.workflow.repository import SQLiteWorkflowRepository
        from backend.workflow.run_driver import RunDriver

        repo = SQLiteWorkflowRepository()
        # definition + version snapshot
        d = _minimal_definition()
        repo.save_definition(d)
        repo.save_definition_version(WorkflowDefinitionVersion(
            id=generate_version_id(), definition_id="def_min", version=1, definition_json=d.to_dict()))
        run_id = _pending_run(repo, generate_run_id())

        # claim 先（设置 driver_owner/generation），再 drive
        claim = repo.claim_driver_run(run_id, "driver_test", "2099-01-01T00:00:00Z")
        assert claim["claimed"] is True
        driver = RunDriver(repo, owner_id="driver_test")
        asyncio.run(driver._drive(run_id, claim["generation"]))
        run = repo.get_run(run_id)
        assert run.status.value == "completed"


class TestRecoveryClassifier:
    def test_f25_non_action_allowlist(self):
        from backend.workflow.recovery import RecoverySafetyClass, RecoverySafetyClassifier
        c = RecoverySafetyClassifier()
        assert c.classify_node("validate_event") == RecoverySafetyClass.READ_ONLY
        assert c.classify_node("agent_task") == RecoverySafetyClass.READ_ONLY
        # 未知 node type → UNKNOWN（fail closed）
        assert c.classify_node("totally_unknown_node_type") == RecoverySafetyClass.UNKNOWN

    def test_action_classification(self):
        from backend.workflow.recovery import RecoverySafetyClass, RecoverySafetyClassifier
        c = RecoverySafetyClassifier()
        assert c.classify_node("action", "get_stats") == RecoverySafetyClass.READ_ONLY
        assert c.classify_node("action", "notify_wechat") == RecoverySafetyClass.HIGH_RISK_NON_IDEMPOTENT
        assert c.classify_node("action", "save_result") == RecoverySafetyClass.WRITE_IDEMPOTENT
        assert c.classify_node("action", "totally_unknown_tool") == RecoverySafetyClass.UNKNOWN

    def test_f05_unknown_outcome_detection(self):
        from backend.workflow.models import generate_run_id, WorkflowActionRecord, ActionStatus, compute_action_idempotency_key
        from backend.workflow.recovery import detect_unknown_outcome
        repo = _repo()
        run_id = generate_run_id()
        _pending_run(repo, run_id)
        # HIGH_RISK action record EXECUTING（started 无 final result）
        repo.save_action_record(WorkflowActionRecord(
            action_id="wfact_unknown1", run_id=run_id, node_id="action_notify",
            action_type="notify_wechat", idempotency_key=compute_action_idempotency_key(run_id, "action_notify", "notify_wechat"),
            status=ActionStatus.EXECUTING,
        ))
        unknowns = detect_unknown_outcome(repo, run_id)
        assert len(unknowns) == 1
        assert unknowns[0]["actionType"] == "notify_wechat"

    def test_known_outcome_not_unknown(self):
        from backend.workflow.models import generate_run_id, WorkflowActionRecord, ActionStatus, compute_action_idempotency_key
        from backend.workflow.recovery import detect_unknown_outcome
        repo = _repo()
        run_id = generate_run_id()
        _pending_run(repo, run_id)
        # HIGH_RISK action record SUCCEEDED（有 final result）→ 非 UNKNOWN
        repo.save_action_record(WorkflowActionRecord(
            action_id="wfact_done1", run_id=run_id, node_id="action_notify",
            action_type="notify_wechat", idempotency_key=compute_action_idempotency_key(run_id, "action_notify", "notify_wechat"),
            status=ActionStatus.SUCCEEDED, result={"sent": True},
        ))
        assert detect_unknown_outcome(repo, run_id) == []
