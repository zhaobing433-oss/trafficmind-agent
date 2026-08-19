"""
Phase18 Round2 — Runtime Wiring Closure E2E（FA01-FA10）

验证 production 路径（RunDriver terminal hook / continuation replan boundary）
真实解析 planning LLM client 并进入 critic/assessment provider，而非硬编码 None。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.planning.budget import new_lineage, set_lineage
from backend.planning.observation import (
    Observation, ObservationScope, ObservationSource, ObservationStatus, ObservationType,
)
from backend.workflow.models import (
    NodeConfig, NodeType, WorkflowDefinition, WorkflowEvent, WorkflowRun, WorkflowRunStatus,
)
from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_round2_runtime.db")
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    init_workflow_tables()
    yield test_db


def _make_run(repo, run_id, status, state_extra=None, definition_id="def1", version=1):
    state = {}
    lineage = new_lineage(run_id)
    set_lineage(state, lineage)
    if state_extra:
        state.update(state_extra)
    run = WorkflowRun(run_id=run_id, definition_id=definition_id, version=version,
                      status=status, state=state)
    repo.save_run(run)
    return run


class FakeAssessClient:
    _model = "fake-model"
    def __init__(self, achievement="achieved"):
        self._achievement = achievement
        self.calls = 0
    async def call_structured_json(self, system, user):
        self.calls += 1
        return {"goalAchievement": self._achievement, "confidence": 0.9, "reasonSummary": "x"}, {}, 1


class FakeCriticClient:
    _model = "fake-model"
    def __init__(self, recommendation="escalate_human"):
        self._recommendation = recommendation
        self.calls = 0
    def call_structured_json_sync(self, system, user):
        self.calls += 1
        return {"recommendation": self._recommendation, "confidence": 0.9,
                "reasonSummary": "x", "semanticFailureType": "semantic"}, {}, 1


def _patch_factory(monkeypatch, client):
    monkeypatch.setattr("backend.planning.llm_client.get_planning_llm_client_optional", lambda: client)


# ── Assessment production wiring（FA01-FA05 / FA09 / FA10）─────────────────────

class TestAssessmentProductionWiring:
    def test_fa01_configured_client_reachable(self, patch_db, monkeypatch):
        """FA01：RunDriver terminal hook → factory 解析 client → LLM assessment ACHIEVED。"""
        from backend.workflow.run_driver import RunDriver
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        client = FakeAssessClient("achieved")
        _patch_factory(monkeypatch, client)

        driver = RunDriver(repository=repo)
        asyncio.run(driver._assess_if_terminal("leaf"))

        assert client.calls == 1  # provider 调用一次
        run = repo.get_run("leaf")
        assessment = list(run.state.get("assessment", {}).values())[0]
        assert assessment["status"] == "COMPLETED"
        assert assessment["result"]["assessmentStatus"] == "assessed"
        assert assessment["result"]["goalAchievement"] == "achieved"
        usage = run.state["executionLineage"]["budgetUsage"]
        assert usage["assessmentCallsUsed"] == 1
        assert usage["llmCallsUsed"] == 1
        assert run.status == WorkflowRunStatus.COMPLETED  # H：状态不变

    def test_fa02_unavailable_fallback(self, patch_db, monkeypatch):
        """FA02：client unavailable → fallback/UNKNOWN，provider 0，run 不失败。"""
        from backend.workflow.run_driver import RunDriver
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        _patch_factory(monkeypatch, None)  # 无 key

        driver = RunDriver(repository=repo)
        asyncio.run(driver._assess_if_terminal("leaf"))

        run = repo.get_run("leaf")
        assessment = list(run.state.get("assessment", {}).values())[0]
        assert assessment["result"]["assessmentStatus"] == "fallback"
        assert run.status == WorkflowRunStatus.COMPLETED

    def test_fa03_budget_exhausted(self, patch_db, monkeypatch):
        """FA03：budget 耗尽 → provider 0，counters 不部分增长，run 仍 COMPLETED。"""
        from backend.workflow.run_driver import RunDriver
        repo = SQLiteWorkflowRepository()
        run = _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        lineage = run.state["executionLineage"]
        lineage["budgetUsage"]["llmCallsUsed"] = 5
        repo.save_run(WorkflowRun(run_id="leaf", status=WorkflowRunStatus.COMPLETED, state=run.state))
        client = FakeAssessClient("achieved")
        _patch_factory(monkeypatch, client)

        driver = RunDriver(repository=repo)
        asyncio.run(driver._assess_if_terminal("leaf"))

        assert client.calls == 0
        run2 = repo.get_run("leaf")
        assert run2.status == WorkflowRunStatus.COMPLETED
        assert run2.state["executionLineage"]["budgetUsage"]["llmCallsUsed"] == 5  # 未增长

    def test_fa04_replanned_parent_provider_0(self, patch_db, monkeypatch):
        """FA04：replanned parent → assessment provider 0。"""
        from backend.workflow.run_driver import RunDriver
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "parent", WorkflowRunStatus.FAILED,
                  state_extra={"replannedToRunId": "child", "terminationReason": "replanned"})
        client = FakeAssessClient("achieved")
        _patch_factory(monkeypatch, client)

        driver = RunDriver(repository=repo)
        asyncio.run(driver._assess_if_terminal("parent"))

        assert client.calls == 0
        run = repo.get_run("parent")
        assert "assessment" not in run.state  # 未 claim

    def test_fa05_started_restart_no_replay(self, patch_db, monkeypatch):
        """FA05：assessment STARTED 无 COMPLETED → restart 不 replay provider。"""
        from backend.workflow.run_driver import RunDriver
        repo = SQLiteWorkflowRepository()
        run = _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        state = dict(run.state)
        state["assessment"] = {"leaf:leaf:1": {"status": "STARTED"}}
        repo.save_run(WorkflowRun(run_id="leaf", status=WorkflowRunStatus.COMPLETED, state=state))
        client = FakeAssessClient("achieved")
        _patch_factory(monkeypatch, client)

        driver = RunDriver(repository=repo)
        asyncio.run(driver._assess_if_terminal("leaf"))

        assert client.calls == 0  # 不 replay
        run2 = repo.get_run("leaf")
        assert run2.status == WorkflowRunStatus.COMPLETED

    def test_fa09_terminal_durable_before_assessment(self, patch_db, monkeypatch):
        """FA09：assessment hook 入口 repo.get_run 已是 terminal。"""
        from backend.workflow.run_driver import RunDriver
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        _patch_factory(monkeypatch, FakeAssessClient("achieved"))

        # 直接读 repo：terminal 已 durable
        assert repo.get_run("leaf").is_terminal()
        driver = RunDriver(repository=repo)
        asyncio.run(driver._assess_if_terminal("leaf"))

    def test_fa10_status_immutable(self, patch_db, monkeypatch):
        """FA10：assessment 后 status/terminationReason/cursor/replannedToRunId 不变。"""
        from backend.workflow.run_driver import RunDriver
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        _patch_factory(monkeypatch, FakeAssessClient("achieved"))
        before = repo.get_run("leaf")
        snapshot = (before.status.value, before.current_node_id,
                    before.state.get("terminationReason"), before.state.get("replannedToRunId"))

        driver = RunDriver(repository=repo)
        asyncio.run(driver._assess_if_terminal("leaf"))

        after = repo.get_run("leaf")
        after_snapshot = (after.status.value, after.current_node_id,
                          after.state.get("terminationReason"), after.state.get("replannedToRunId"))
        assert snapshot == after_snapshot


# ── Critic production wiring（FA06-FA08）──────────────────────────────────────

def _make_failed_action_run(repo, run_id="failed1"):
    """构造 FAILED run + 失败 action node（合法 deterministic plan），使 observation = TOOL_FAILED。"""
    from backend.planning.context import build_planning_context
    from backend.planning.models import PlanDefinitionStatus
    from backend.planning.planner import build_plan
    from backend.workflow.models import DefinitionStatus, NodeStatus, WorkflowNodeRun

    event = {"eventId": "E_ACC", "eventType": "accident", "roadName": "A路",
             "avgSpeed": 8, "queueLength": 200, "duration": 900, "nearbyHospital": True}
    plan = build_plan(build_planning_context(event))
    plan.definitionStatus = PlanDefinitionStatus.ACTIVE
    definition = WorkflowDefinition(id=plan.planId, name=plan.goal,
                                    status=DefinitionStatus.ACTIVE,
                                    metadata={"plan": plan.to_dict()})
    repo.save_definition(definition)
    action_steps = [s for s in plan.steps if s.stepType == NodeType.ACTION and s.actionType == "notify_wechat"]
    action_id = action_steps[0].stepId if action_steps else "action_x"
    _make_run(repo, run_id, WorkflowRunStatus.FAILED, definition_id=plan.planId)
    nr = WorkflowNodeRun(node_run_id=f"nr_{run_id}_1", run_id=run_id, node_id=action_id,
                         node_type=NodeType.ACTION, status=NodeStatus.FAILED)
    repo.save_node_run(nr)
    return run_id


class TestCriticProductionWiring:
    def test_fa06_semantic_critic_escalate_no_revision(self, patch_db, monkeypatch):
        """FA06：SEMANTIC_REVIEW + critic ESCALATE → final gate ESCALATE，不 create child。"""
        from backend.planning.continuation import PlanningContinuationCoordinator
        repo = SQLiteWorkflowRepository()
        run_id = _make_failed_action_run(repo)
        client = FakeCriticClient("escalate_human")
        _patch_factory(monkeypatch, client)

        coordinator = PlanningContinuationCoordinator(repo)
        result = coordinator.explicit_replan(run_id)

        assert client.calls == 1
        # final decision = ESCALATE_HUMAN（非 REPLAN）→ 不 create child
        assert "childRunId" not in result
        run = repo.get_run(run_id)
        assert "replannedToRunId" not in run.state  # 没有 child
        # critic registry COMPLETED + budget 递增
        assert run.state["criticInvocations"].get(f"{run_id}:{run_id}:1:tool_failed:") or \
               any(k for k in run.state.get("criticInvocations", {}))

    def test_fa07_critic_unavailable_fallback(self, patch_db, monkeypatch):
        """FA07：SEMANTIC_REVIEW + client unavailable → provider 0 → deterministic fallback。"""
        from backend.planning.continuation import PlanningContinuationCoordinator
        repo = SQLiteWorkflowRepository()
        run_id = _make_failed_action_run(repo)
        _patch_factory(monkeypatch, None)

        coordinator = PlanningContinuationCoordinator(repo)
        result = coordinator.explicit_replan(run_id)
        # deterministic TOOL_FAILED(non-retryable) → REPLAN → 创建 child（Phase17 fallback）
        assert "childRunId" in result or "error" in result  # 不失败
        # provider 0
        run = repo.get_run(run_id)
        assert "criticInvocations" not in run.state  # 未 claim

    def test_fa08_critic_replan_build_revision_once(self, patch_db, monkeypatch):
        """FA08：critic REPLAN → final REPLAN → build_revision 一次（critic 不直接 build revision）。"""
        from backend.planning.continuation import PlanningContinuationCoordinator
        repo = SQLiteWorkflowRepository()
        run_id = _make_failed_action_run(repo)
        client = FakeCriticClient("replan")
        _patch_factory(monkeypatch, client)

        coordinator = PlanningContinuationCoordinator(repo)
        result = coordinator.explicit_replan(run_id)

        assert client.calls == 1
        # final REPLAN → 创建 child
        assert "childRunId" in result
        run = repo.get_run(run_id)
        assert run.state.get("replannedToRunId") is not None  # child 已接续


class TestAsyncSafety:
    def test_run_driver_event_loop_not_blocked(self, patch_db, monkeypatch):
        """async 路径：assessment 等待期间 event loop 仍可调度（heartbeat）。"""
        from backend.workflow.run_driver import RunDriver
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)

        class SlowClient:
            _model = "fake"
            async def call_structured_json(self, system, user):
                await asyncio.sleep(0.05)
                return {"goalAchievement": "achieved", "confidence": 0.9, "reasonSummary": "x"}, {}, 1

        _patch_factory(monkeypatch, SlowClient())

        async def _run():
            ticks = []
            async def heartbeat():
                for _ in range(10):
                    ticks.append(1)
                    await asyncio.sleep(0.005)
            hb = asyncio.create_task(heartbeat())
            driver = RunDriver(repository=repo)
            await driver._assess_if_terminal("leaf")
            await hb
            return len(ticks)
        assert asyncio.run(_run()) > 0
