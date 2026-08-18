"""
Phase 17 Round 3 P0 — runtime/recovery/integration tests（F04/F09/F11/F12/F15/F18/F19/F22/F23）
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
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_r3_runtime.db"))


def _repo():
    from backend.workflow.repository import SQLiteWorkflowRepository
    return SQLiteWorkflowRepository()


def _run(repo, run_id, status="running", definition_id="d", state=None):
    from backend.workflow.models import WorkflowRun, WorkflowRunStatus
    from backend.planning.budget import new_lineage, set_lineage
    st = state or {"status": status, "currentEvent": {}}
    set_lineage(st, new_lineage(run_id))
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=definition_id, version=1,
                              status=WorkflowRunStatus(status), state=st))
    return run_id


class TestLegacyIsolation:
    def test_f12_legacy_not_claimed(self):
        from backend.workflow.models import generate_run_id
        repo = _repo()
        legacy = generate_run_id()
        _run(repo, legacy, status="pending")  # driver_managed=0（默认）
        # planning run
        plan_run = generate_run_id()
        _run(repo, plan_run, status="pending")
        repo.mark_driver_managed(plan_run)
        candidates = repo.list_driver_candidates()
        ids = [r.run_id for r in candidates]
        assert plan_run in ids
        assert legacy not in ids


class TestChildDriverManaged:
    def test_f23_child_marked_managed(self):
        from backend.workflow.models import generate_run_id, WorkflowRun, WorkflowRunStatus, WorkflowDefinitionVersion
        from backend.workflow.definition import generate_version_id
        from backend.planning.budget import new_lineage, set_lineage
        repo = _repo()
        parent = generate_run_id()
        _run(repo, parent, status="failed")
        child_run_id = f"wfrun_cont_{generate_run_id()[:8]}"
        # child cutover tx（最小）
        state = {"status": "pending"}
        set_lineage(state, new_lineage(parent))
        child = WorkflowRun(run_id=child_run_id, definition_id="d", version=0,
                            status=WorkflowRunStatus.PENDING, state=state)
        v = repo.create_child_continuation_tx(
            child_run=child, parent_run_id=parent, parent_status="failed",
            parent_state={"status": "failed", "replannedToRunId": child_run_id},
            definition_json={"id": "d", "nodes": []},
        )
        repo.mark_driver_managed(child_run_id)
        candidates = repo.list_driver_candidates()
        assert child_run_id in [r.run_id for r in candidates]
        assert repo.is_driver_managed(child_run_id) is True


class TestCancellationWriteProtection:
    def test_f19_late_write_preserves_cancelled(self):
        from backend.workflow.models import generate_run_id
        repo = _repo()
        run_id = generate_run_id()
        _run(repo, run_id, status="running")
        repo.mark_driver_managed(run_id)
        c = repo.claim_driver_run(run_id, "w1", "2099-01-01T00:00:00Z")
        # 另请求 cancel（terminal-preserving 之外，直接设 CANCELLED）
        repo.set_run_status_managed(run_id, "cancelled")
        # 旧 worker late fenced write（status=completed）→ 不覆盖 CANCELLED
        ok = repo.fenced_update_run(run_id, "w1", c["generation"], "completed", "close", {"status": "completed"})
        assert ok is False
        run = repo.get_run(run_id)
        assert run.status.value == "cancelled"


class TestAttemptIdentity:
    def _action_record(self, repo, run_id, action_id, status, action_type="notify_wechat", node_id="action_notify"):
        from backend.workflow.models import WorkflowActionRecord, ActionStatus, compute_action_idempotency_key
        repo.save_action_record(WorkflowActionRecord(
            action_id=action_id, run_id=run_id, node_id=node_id, action_type=action_type,
            idempotency_key=compute_action_idempotency_key(run_id, node_id, action_type),
            status=status, result=({"sent": True} if status == ActionStatus.SUCCEEDED else {}),
        ))

    def test_f22_attempt2_unknown_not_misjudged_by_attempt1(self):
        from backend.workflow.models import ActionStatus, generate_run_id
        from backend.workflow.recovery import detect_unknown_outcome
        repo = _repo()
        run_id = generate_run_id()
        _run(repo, run_id)
        # attempt1 FAILED，attempt2 EXECUTING（同 node/actionType）
        self._action_record(repo, run_id, "wfact_a1", ActionStatus.FAILED)
        self._action_record(repo, run_id, "wfact_a2", ActionStatus.EXECUTING)
        unknowns = detect_unknown_outcome(repo, run_id)
        assert [u["actionId"] for u in unknowns] == ["wfact_a2"]  # 只分析 attempt2

    def test_f15_attempt2_known_result_not_unknown(self):
        from backend.workflow.models import ActionStatus, generate_run_id
        from backend.workflow.recovery import detect_unknown_outcome
        repo = _repo()
        run_id = generate_run_id()
        _run(repo, run_id)
        self._action_record(repo, run_id, "wfact_a1", ActionStatus.FAILED)
        self._action_record(repo, run_id, "wfact_a2", ActionStatus.SUCCEEDED)  # 有 durable result
        assert detect_unknown_outcome(repo, run_id) == []


class TestRecoveryRetryBudget:
    def test_f18_retry_exhausted(self):
        from backend.planning.budget import ExecutionBudgetLimits, new_lineage, reserve_retry
        lin = new_lineage("root", ExecutionBudgetLimits(maxRetries=2))
        assert reserve_retry(lin) is True
        assert reserve_retry(lin) is True
        assert reserve_retry(lin) is False  # 第3次阻止 → 无无限 recovery


class TestCursorRecovery:
    def test_f04_classifier_safe_replay(self):
        from backend.workflow.recovery import RecoverySafetyClass, RecoverySafetyClassifier
        c = RecoverySafetyClassifier()
        # C = save_result（WRITE idempotent）→ safe replay
        assert c.classify_node("action", "save_result") == RecoverySafetyClass.WRITE_IDEMPOTENT
        # A/B = 非 ACTION allowlist → READ_ONLY
        assert c.classify_node("validate_event") == RecoverySafetyClass.READ_ONLY
        assert c.classify_node("agent_task") == RecoverySafetyClass.READ_ONLY
        # notify → HIGH_RISK_NON_IDEMPOTENT → 不 auto replay
        assert c.classify_node("action", "notify_wechat") == RecoverySafetyClass.HIGH_RISK_NON_IDEMPOTENT


class TestHeartbeatBlockingPath:
    def test_f24_blocking_tool_offloaded(self):
        # action.py 的 notify 已用 asyncio.to_thread，验证 import 与标记
        import inspect
        from backend.workflow.nodes import action as action_mod
        src = inspect.getsource(action_mod._dispatch_action)
        assert "asyncio.to_thread" in src  # 阻塞 external call 已 offload
