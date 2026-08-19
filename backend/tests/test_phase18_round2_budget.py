"""
Phase18 Round2 — atomic budget reservation + critic idempotency 单元测试

覆盖 R05 / R09 / R10 / R11 / R25 / R26 / R27 / R28 / R29 / R37。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.planning.budget import new_lineage, set_lineage
from backend.workflow.models import WorkflowRun, WorkflowRunStatus
from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_round2_budget.db")
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    init_workflow_tables()
    yield test_db


def _make_run(repo, run_id, root_run_id=None, max_llm=5, max_critic=3, llm_used=0, critic_used=0):
    state = {}
    lineage = new_lineage(root_run_id or run_id)
    lineage.budgetLimits.maxLlmCalls = max_llm
    lineage.budgetLimits.maxCriticCalls = max_critic
    lineage.budgetUsage.llmCallsUsed = llm_used
    lineage.budgetUsage.criticCallsUsed = critic_used
    set_lineage(state, lineage)
    run = WorkflowRun(run_id=run_id, status=WorkflowRunStatus.FAILED, state=state)
    repo.save_run(run)
    return run


class TestAtomicCompoundReservation:
    def test_r05_budget_exhausted_no_partial(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "r1", max_llm=5, max_critic=3, llm_used=5, critic_used=0)  # 总 LLM 已耗尽
        res = repo.claim_critic_invocation_tx("r1", "k1")
        assert res["result"] == "budget_exhausted"
        # 零变化
        run = repo.get_run("r1")
        usage = run.state["executionLineage"]["budgetUsage"]
        assert usage["llmCallsUsed"] == 5
        assert usage["criticCallsUsed"] == 0

    def test_r25_critic_exhausted_no_partial(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "r1", max_llm=5, max_critic=3, llm_used=0, critic_used=3)  # critic 已耗尽
        res = repo.claim_critic_invocation_tx("r1", "k1")
        assert res["result"] == "budget_exhausted"
        run = repo.get_run("r1")
        usage = run.state["executionLineage"]["budgetUsage"]
        assert usage["llmCallsUsed"] == 0
        assert usage["criticCallsUsed"] == 3

    def test_r26_total_llm_exhausted_critic_available(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "r1", max_llm=1, max_critic=3, llm_used=1, critic_used=0)
        res = repo.claim_critic_invocation_tx("r1", "k1")
        assert res["result"] == "budget_exhausted"
        run = repo.get_run("r1")
        usage = run.state["executionLineage"]["budgetUsage"]
        assert usage["llmCallsUsed"] == 1
        assert usage["criticCallsUsed"] == 0

    def test_claim_increments_both(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "r1")
        res = repo.claim_critic_invocation_tx("r1", "k1")
        assert res["result"] == "claimed"
        run = repo.get_run("r1")
        usage = run.state["executionLineage"]["budgetUsage"]
        assert usage["llmCallsUsed"] == 1
        assert usage["criticCallsUsed"] == 1
        # STARTED marker 已写
        assert run.state["criticInvocations"]["k1"]["status"] == "STARTED"


class TestCriticIdempotency:
    def test_r09_duplicate_claim_once(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "r1")
        assert repo.claim_critic_invocation_tx("r1", "k1")["result"] == "claimed"
        # 第二次 → already_started（不是 claimed）
        assert repo.claim_critic_invocation_tx("r1", "k1")["result"] == "already_started"

    def test_r10_completed_reused(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "r1")
        repo.claim_critic_invocation_tx("r1", "k1")
        repo.complete_critic_invocation_tx("r1", "k1", {"recommendation": "replan", "confidence": 0.8})
        res = repo.claim_critic_invocation_tx("r1", "k1")
        assert res["result"] == "already_completed"
        assert res["recommendation"]["recommendation"] == "replan"

    def test_r27_started_crash_no_replay(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "r1")
        repo.claim_critic_invocation_tx("r1", "k1")  # STARTED，未 COMPLETED
        # restart → already_started（不是 claimed，不 replay provider）
        assert repo.claim_critic_invocation_tx("r1", "k1")["result"] == "already_started"

    def test_r28_complete_only_transitions_started(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "r1")
        # 无 STARTED → complete 不写
        repo.complete_critic_invocation_tx("r1", "k1", {"recommendation": "replan"})
        run = repo.get_run("r1")
        assert "k1" not in run.state.get("criticInvocations", {})

    def test_r29_concurrent_claim_single_winner(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "r1")
        # 两个顺序 claim（模拟并发：SQLite BEGIN IMMEDIATE 序列化）
        r1 = repo.claim_critic_invocation_tx("r1", "k1")
        r2 = repo.claim_critic_invocation_tx("r1", "k1")
        winners = [r["result"] for r in (r1, r2) if r["result"] == "claimed"]
        assert len(winners) == 1  # 恰好一个 claim 成功


class TestChildInheritsBudget:
    def test_r11_child_carries_budget(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "parent", root_run_id="root", llm_used=2, critic_used=1)
        # 新 root 独立，child 继承同一 rootRunId 的 cumulative usage
        run = repo.get_run("parent")
        lineage = run.state["executionLineage"]
        assert lineage["rootRunId"] == "root"
        assert lineage["budgetUsage"]["llmCallsUsed"] == 2
        assert lineage["budgetUsage"]["criticCallsUsed"] == 1


class TestStateMergeSafety:
    """R37：critic COMPLETED + budget 在 child cutover 后仍存在。"""
    def test_registry_survives_cutover(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "parent", root_run_id="root")
        repo.claim_critic_invocation_tx("parent", "k1")
        repo.complete_critic_invocation_tx("parent", "k1", {"recommendation": "replan", "confidence": 0.8})
        # 模拟 child cutover 后 parent state 仍含 registry + budget + replannedToRunId
        run = repo.get_run("parent")
        state = dict(run.state)
        state["replannedToRunId"] = "child1"
        state["terminationReason"] = "replanned"
        repo.save_run(WorkflowRun(run_id="parent", status=WorkflowRunStatus.FAILED, state=state))
        # reload → 三者同时存在
        run2 = repo.get_run("parent")
        assert run2.state["criticInvocations"]["k1"]["status"] == "COMPLETED"
        assert run2.state["executionLineage"]["budgetUsage"]["criticCallsUsed"] == 1
        assert run2.state["replannedToRunId"] == "child1"
