"""
Phase 17 Round 2 — Runtime Smoke

端到端：parent 失败 → explicit replan → child continuation（carried prefix 不重跑）。
全部 mock/fake 外部副作用。
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
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_r2_smoke.db"))


def _low_risk_event():
    return {"eventId": "E_SMOKE", "eventType": "congestion", "roadName": "验收路",
            "avgSpeed": 40, "queueLength": 20, "duration": 100, "isMainRoad": False}


def _noop_rag_memory(registry):
    async def _noop(state, config):
        return {}
    saved = {t: registry.get(t) for t in ("rag_retrieve", "memory_context")}
    for t in ("rag_retrieve", "memory_context"):
        registry.register(t, _noop)
    return saved


def _restore(registry, saved):
    for t, fn in saved.items():
        registry.register(t, fn)


class TestFullReplanFlow:
    def test_semantic_failure_replan_carried_not_rerun(self, monkeypatch):
        from backend.planning.context import build_planning_context
        from backend.planning.planner import build_plan
        from backend.planning.adapter import plan_to_definition
        from backend.planning.continuation import PlanningContinuationCoordinator
        from backend.workflow.executor import get_executor
        from backend.workflow.nodes.base import get_node_registry
        from backend.workflow.repository import SQLiteWorkflowRepository

        repo = SQLiteWorkflowRepository()
        plan = build_plan(build_planning_context(_low_risk_event()))
        repo.save_definition(plan_to_definition(plan))

        calls = []
        dispatch_mode = {"fail": True}

        async def fake_dispatch(action_type, params, state):
            calls.append(action_type)
            if dispatch_mode["fail"]:
                return {"saved": False, "error": "semantic failure"}
            return {"saved": True}

        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        # 父 run：低风险（只有 save_result action），save_result 失败 → run FAILED
        executor = get_executor()
        registry = get_node_registry()
        saved = _noop_rag_memory(registry)
        try:
            async def _run():
                out = []
                async for s in executor.start(definition_id=plan.planId, initial_event=_low_risk_event()):
                    out.append(s)
                return out
            asyncio.run(_run())
        finally:
            _restore(registry, saved)

        parent_runs = repo.list_runs(definition_id=plan.planId)
        parent = parent_runs[0]
        assert parent.status.value == "failed"
        assert calls == ["save_result"]  # 父 run 只 dispatch 一次（失败）

        # explicit replan（dispatch 改为成功）→ child PENDING + driver_managed（Round3 由 RunDriver 执行）
        dispatch_mode["fail"] = False
        coord = PlanningContinuationCoordinator(repo)
        result = coord.explicit_replan(parent.run_id)
        assert "error" not in result, result
        child_run_id = result["childRunId"]

        # RunDriver 拾取 child（execution owner = RunDriver）
        from backend.workflow.run_driver import RunDriver
        claim = repo.claim_driver_run(child_run_id, "smoke_driver", "2099-01-01T00:00:00Z")
        assert claim["claimed"] is True
        driver = RunDriver(repo, owner_id="smoke_driver")
        asyncio.run(driver._drive(child_run_id, claim["generation"]))

        # child 只重跑 unresolved suffix（save_result），carried prefix 不重跑
        assert calls == ["save_result", "save_result"]  # 父失败 + 子成功

        # 幂等：再次 replan → 同一 child
        result2 = coord.explicit_replan(parent.run_id)
        assert result2.get("childRunId") == child_run_id or result2.get("alreadyReplanned")

        # child run 状态
        child = repo.get_run(child_run_id)
        assert child is not None
        # 同一 lineage
        from backend.planning.budget import get_lineage
        assert get_lineage(child.state).rootRunId == get_lineage(parent.state).rootRunId

    def test_budget_inheritance_limits_dispatch(self, monkeypatch):
        from backend.planning.budget import ExecutionBudgetLimits, new_lineage, inherit_lineage, reserve_tool_call, get_lineage, set_lineage
        from backend.workflow.models import NodeConfig, NodeType, WorkflowRun, WorkflowRunStatus, generate_run_id
        from backend.workflow.nodes.action import execute_action
        from backend.workflow.repository import SQLiteWorkflowRepository
        from backend.workflow.state import TrafficWorkflowState

        repo = SQLiteWorkflowRepository()
        # 父 lineage 已用 1 个 tool call（maxToolCalls=1）
        parent_run_id = generate_run_id()
        parent_state = {"status": "running"}
        parent_lineage = new_lineage(parent_run_id, ExecutionBudgetLimits(maxToolCalls=1))
        reserve_tool_call(parent_lineage)  # 用掉唯一配额
        set_lineage(parent_state, parent_lineage)
        repo.save_run(WorkflowRun(run_id=parent_run_id, definition_id="d", version=1,
                                  status=WorkflowRunStatus.FAILED, state=parent_state))

        # child 继承（toolCallsUsed=1 = 配额满）
        child_run_id = generate_run_id()
        child_state = {"status": "running"}
        set_lineage(child_state, inherit_lineage(parent_lineage))
        repo.save_run(WorkflowRun(run_id=child_run_id, definition_id="d", version=1,
                                  status=WorkflowRunStatus.RUNNING, state=child_state))

        calls = []
        async def fake_dispatch(action_type, params, state):
            calls.append(action_type)
            return {"saved": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)

        st = TrafficWorkflowState(workflow_run_id=child_run_id)
        out = asyncio.run(execute_action(
            st, NodeConfig(node_id="a1", node_type=NodeType.ACTION, config={"action_type": "save_result"}),
            repository=repo,
        ))
        # 预算已满 → 不 dispatch
        assert out.get("status") == "budget_exhausted"
        assert out.get("executed") is False
        assert calls == []
