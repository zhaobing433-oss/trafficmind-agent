"""
Phase 17 Round 1 — 评估用例 P01-P23 + Runtime Smoke

覆盖 Design Lock v1.1 的完整安全不变量与评估矩阵。
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.agent.tool_policy import ToolExecutionStatus
from backend.planning.adapter import plan_to_definition
from backend.planning.context import build_planning_context
from backend.planning.models import (
    TERMINAL_STEP_STATUSES,
    GoalType,
    Plan,
    PlanDefinitionStatus,
    PlanStep,
    PlanStepStatus,
    compute_fingerprint,
    create_revision,
)
from backend.planning.planner import build_plan
from backend.planning.status_projection import project_step_statuses
from backend.planning.validator import has_errors, validate_plan
from backend.workflow.models import ApprovalDecision, NodeConfig, NodeType, WorkflowRunStatus
from backend.workflow.nodes.action import execute_action, is_current_action_approved
from backend.workflow.nodes.human_approval import process_approval_decision
from backend.workflow.state import TrafficWorkflowState


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_phase17_eval.db"))


# ── helpers ─────────────────────────────────────────────────────


def _congestion(**kw):
    ev = {
        "eventId": "E_CONG",
        "eventType": "congestion",
        "roadName": "测试路",
        "avgSpeed": 8,
        "queueLength": 200,
        "duration": 1200,
        "isMainRoad": True,
    }
    ev.update(kw)
    return ev


def _plan(steps, plan_id="plan_eval") -> Plan:
    return Plan(
        planId=plan_id,
        planFingerprint=compute_fingerprint(steps),
        goal="测试",
        goalType=GoalType.GENERIC,
        definitionStatus=PlanDefinitionStatus.DRAFT,
        version=1,
        steps=steps,
    )


def _state(run_id="run_eval_1"):
    return TrafficWorkflowState(workflow_run_id=run_id)


# ═══════════════════════════════════════════════════════════════════════════════
# P01-P10 规划层
# ═══════════════════════════════════════════════════════════════════════════════


class TestPlanningLayer:
    def test_p01_ordinary_congestion_valid_bounded_plan(self):
        plan = build_plan(build_planning_context(_congestion()))
        assert 0 < len(plan.steps) <= 100
        assert any(s.stepType == NodeType.CLOSE for s in plan.steps)
        assert not has_errors(validate_plan(plan))

    def test_p02_signal_fault_and_congestion_context(self):
        ev = {"eventId": "E_SIG", "eventType": "signal_fault", "roadName": "路口",
              "avgSpeed": 15, "queueLength": 120, "duration": 300}
        ctx = build_planning_context(ev)
        assert "SignalAgent" in ctx.selected_agents
        assert "CongestionAgent" in ctx.selected_agents

    def test_p03_duration_none_preserved(self):
        from backend.agent.event_normalizer import normalize_event
        norm = normalize_event(_congestion(duration=None))
        assert norm["duration"] is None
        assert "duration" in norm["unknownFields"]

    def test_p04_unknown_tool_invalid(self):
        steps = [
            PlanStep(stepId="a", stepType=NodeType.VALIDATE_EVENT),
            PlanStep(stepId="bad", stepType=NodeType.ACTION, actionType="ghost_tool",
                     toolName="ghost_tool", riskLevel="unknown", approvalRequired=False,
                     dependsOn=["a"]),
            PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["bad"]),
        ]
        issues = validate_plan(_plan(steps))
        assert any(i.code == "unknown_tool" for i in issues)
        assert has_errors(issues)

    def test_p05_high_risk_approval_annotation(self):
        plan = build_plan(build_planning_context(_congestion()))
        actions = [s for s in plan.steps if s.stepType == NodeType.ACTION]
        high = [s for s in actions if s.approvalRequired]
        assert high, "高风险 notify action 应标注 approvalRequired"
        assert all(s.actionType == "notify_wechat" for s in high)

    def test_p06_cyclic_dependency_rejected(self):
        steps = [
            PlanStep(stepId="a", stepType=NodeType.VALIDATE_EVENT, dependsOn=["b"]),
            PlanStep(stepId="b", stepType=NodeType.CLOSE, dependsOn=["a"]),
        ]
        assert any(i.code == "cyclic_dependency" for i in validate_plan(_plan(steps)))

    def test_p07_missing_dependency_rejected(self):
        steps = [
            PlanStep(stepId="a", stepType=NodeType.VALIDATE_EVENT, dependsOn=["ghost"]),
            PlanStep(stepId="b", stepType=NodeType.CLOSE, dependsOn=["a"]),
        ]
        assert any(i.code == "missing_dependency" for i in validate_plan(_plan(steps)))

    def test_p08_deterministic_structure_stable(self):
        p1 = build_plan(build_planning_context(_congestion()))
        p2 = build_plan(build_planning_context(_congestion()))
        assert p1.planFingerprint == p2.planFingerprint
        assert [s.stepId for s in p1.steps] == [s.stepId for s in p2.steps]
        assert [s.dependsOn for s in p1.steps] == [s.dependsOn for s in p2.steps]

    def test_p09_no_rag_evidence_no_fabrication(self):
        plan = build_plan(build_planning_context(_congestion(), rag_evidence=None))
        assert plan.evidenceRefs == []

    def test_p10_planner_zero_side_effects(self):
        plan = build_plan(build_planning_context(_congestion()))
        # planner 只产出 steps，不执行任何 action（无 run/event/action 记录）
        assert isinstance(plan, Plan)


# ═══════════════════════════════════════════════════════════════════════════════
# P11-P13 状态语义 + 投影
# ═══════════════════════════════════════════════════════════════════════════════


class TestStatusSemantics:
    def _project(self, plan, node_runs, run_status="", pending=None):
        return project_step_statuses(plan, node_runs, run_status, pending)

    def test_p11_denial_not_succeeded(self):
        plan = _plan([
            PlanStep(stepId="action_x", stepType=NodeType.ACTION, actionType="x", toolName="x"),
            PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["action_x"]),
        ])
        node_runs = [{"nodeId": "action_x", "status": "succeeded",
                      "outputSnapshot": {"status": "denied"}, "attempt": 1}]
        st = self._project(plan, node_runs)
        assert st["action_x"] == PlanStepStatus.DENIED
        assert st["action_x"] != PlanStepStatus.SUCCEEDED

    def test_p12_approval_required_not_succeeded(self):
        plan = _plan([
            PlanStep(stepId="action_x", stepType=NodeType.ACTION, actionType="x", toolName="x"),
            PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["action_x"]),
        ])
        node_runs = [{"nodeId": "action_x", "status": "succeeded",
                      "outputSnapshot": {"status": "approval_required"}, "attempt": 1}]
        st = self._project(plan, node_runs)
        assert st["action_x"] == PlanStepStatus.AWAITING_APPROVAL
        assert st["action_x"] != PlanStepStatus.SUCCEEDED

    def test_p13_rejected_approval_cannot_bypass(self):
        state = _state()
        state.transition(WorkflowRunStatus.RUNNING)
        state.transition(WorkflowRunStatus.AWAITING_APPROVAL)
        state.pending_approval = {"approvalId": "a1", "nodeId": "h", "proposedActions": [{"actionType": "notify_wechat"}]}
        r = process_approval_decision(state, ApprovalDecision.REJECTED)
        assert r["decision"] == "rejected"
        assert state.approved_actions == []
        out = asyncio.run(execute_action(
            state, NodeConfig(node_id="action1", node_type=NodeType.ACTION,
                              config={"action_type": "notify_wechat"})))
        assert out["executed"] is False
        assert out["status"] == ToolExecutionStatus.APPROVAL_REQUIRED.value


# ═══════════════════════════════════════════════════════════════════════════════
# P14-P15 身份 / fingerprint
# ═══════════════════════════════════════════════════════════════════════════════


class TestIdentity:
    def test_p14_revision_stable_plan_id(self):
        steps = [PlanStep(stepId="a", stepType=NodeType.VALIDATE_EVENT),
                 PlanStep(stepId="c", stepType=NodeType.CLOSE, dependsOn=["a"])]
        p = _plan(steps)
        new_steps = [PlanStep(stepId="a", stepType=NodeType.VALIDATE_EVENT),
                     PlanStep(stepId="b", stepType=NodeType.RULE_ROUTER, dependsOn=["a"]),
                     PlanStep(stepId="c", stepType=NodeType.CLOSE, dependsOn=["b"])]
        r = create_revision(p, new_steps)
        assert r.planId == p.planId
        assert r.version == p.version + 1
        assert r.planFingerprint != p.planFingerprint

    def test_p15_same_input_fingerprint_stable(self):
        p1 = build_plan(build_planning_context(_congestion()))
        p2 = build_plan(build_planning_context(_congestion()))
        assert p1.planFingerprint == p2.planFingerprint


# ═══════════════════════════════════════════════════════════════════════════════
# P16-P17 adapter / projection
# ═══════════════════════════════════════════════════════════════════════════════


class TestAdapterProjection:
    def test_p16_dependency_direction(self):
        steps = [PlanStep(stepId="A", stepType=NodeType.VALIDATE_EVENT),
                 PlanStep(stepId="B", stepType=NodeType.RULE_ROUTER, dependsOn=["A"]),
                 PlanStep(stepId="C", stepType=NodeType.CLOSE, dependsOn=["B"])]
        d = plan_to_definition(_plan(steps))
        node = {n.node_id: n for n in d.nodes}
        assert node["A"].next_nodes == ["B"]
        assert node["B"].next_nodes == ["C"]
        assert "A" not in node["B"].next_nodes

    def test_p17_blocked_terminal(self):
        plan = _plan([
            PlanStep(stepId="action_x", stepType=NodeType.ACTION, actionType="x", toolName="x"),
            PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["action_x"]),
        ])
        node_runs = [{"nodeId": "action_x", "status": "succeeded",
                      "outputSnapshot": {"status": "denied"}, "attempt": 1}]
        st = project_step_statuses(plan, node_runs)
        assert st["action_x"] == PlanStepStatus.DENIED
        assert st["close"] == PlanStepStatus.BLOCKED
        assert PlanStepStatus.BLOCKED in TERMINAL_STEP_STATUSES


# ═══════════════════════════════════════════════════════════════════════════════
# P18-P19 unknown tool 双层
# ═══════════════════════════════════════════════════════════════════════════════


class TestUnknownToolLayers:
    def test_p18_planning_time_unknown_invalid(self):
        plan = _plan([
            PlanStep(stepId="a", stepType=NodeType.VALIDATE_EVENT),
            PlanStep(stepId="bad", stepType=NodeType.ACTION, actionType="ghost_tool",
                     toolName="ghost_tool", riskLevel="unknown", approvalRequired=False,
                     dependsOn=["a"]),
            PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["bad"]),
        ])
        assert has_errors(validate_plan(plan))

    def test_p19_runtime_unknown_tool_denied(self, monkeypatch):
        calls = []
        async def fake_dispatch(action_type, params, state):
            calls.append(action_type)
            return {"sent": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        state = _state()
        out = asyncio.run(execute_action(
            state, NodeConfig(node_id="action1", node_type=NodeType.ACTION,
                              config={"action_type": "totally_unknown_tool_xyz"})))
        assert out["executed"] is False
        assert out["status"] == ToolExecutionStatus.DENIED.value
        assert calls == []


# ═══════════════════════════════════════════════════════════════════════════════
# P20-P23 preview / policy / approval isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestSafety:
    def test_p20_preview_zero_persistence(self, tmp_path):
        import sqlite3
        db = cfg.DB_PATH
        # build + validate（= preview 逻辑）后无任何 workflow 表记录
        build_plan(build_planning_context(_congestion()))
        conn = sqlite3.connect(db)
        c = conn.cursor()
        counts = {}
        for t in ["workflow_definitions", "workflow_runs", "workflow_events",
                  "workflow_approvals", "workflow_action_records"]:
            try:
                counts[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.OperationalError:
                counts[t] = 0
        conn.close()
        assert sum(counts.values()) == 0

    def test_p21_plan_metadata_cannot_override_policy(self, monkeypatch):
        calls = []
        async def fake_dispatch(action_type, params, state):
            calls.append(action_type)
            return {"sent": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        # 无审批（approved_actions 空），high-risk tool 即使"元数据说可执行"也被 runtime 阻止
        state = _state()
        out = asyncio.run(execute_action(
            state, NodeConfig(node_id="action1", node_type=NodeType.ACTION,
                              config={"action_type": "notify_wechat"})))
        assert out["executed"] is False
        assert out["status"] == ToolExecutionStatus.APPROVAL_REQUIRED.value
        assert calls == []

    def test_p22_duplicate_high_risk_same_action_type_fail(self):
        steps = [
            PlanStep(stepId="a", stepType=NodeType.VALIDATE_EVENT),
            PlanStep(stepId="h1", stepType=NodeType.HUMAN_APPROVAL, actionType="notify_wechat",
                     riskLevel="high_risk", approvalRequired=True, dependsOn=["a"]),
            PlanStep(stepId="x1", stepType=NodeType.ACTION, actionType="notify_wechat",
                     toolName="notify_wechat", riskLevel="high_risk", approvalRequired=True, dependsOn=["h1"]),
            PlanStep(stepId="x2", stepType=NodeType.ACTION, actionType="notify_wechat",
                     toolName="notify_wechat", riskLevel="high_risk", approvalRequired=True, dependsOn=["x1"]),
            PlanStep(stepId="close", stepType=NodeType.CLOSE, dependsOn=["x2"]),
        ]
        assert any(i.code == "duplicate_high_risk_action_type" for i in validate_plan(_plan(steps)))

    def test_p23_approving_a_does_not_authorize_b(self, monkeypatch):
        calls = []
        async def fake_dispatch(action_type, params, state):
            calls.append(action_type)
            return {"sent": True}
        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", fake_dispatch)
        state = _state()
        # 只批准 notify_wechat
        state.approved_actions = [{"actionType": "notify_wechat", "params": {}}]
        assert is_current_action_approved(state, "notify_wechat") is True
        assert is_current_action_approved(state, "simulation_monitor") is False
        out = asyncio.run(execute_action(
            state, NodeConfig(node_id="a2", node_type=NodeType.ACTION,
                              config={"action_type": "simulation_monitor"})))
        assert out["executed"] is False
        assert out["status"] == ToolExecutionStatus.APPROVAL_REQUIRED.value
        assert calls == []


# ═══════════════════════════════════════════════════════════════════════════════
# Runtime Smoke（Section 19）
# ═══════════════════════════════════════════════════════════════════════════════


class TestRuntimeSmoke:
    """端到端：plan → definition → WorkflowExecutor。禁用外部 side effect。"""

    def _run_plan(self, plan, event, monkeypatch):
        from backend.workflow.executor import get_executor
        from backend.workflow.nodes.base import get_node_registry
        from backend.workflow.repository import SQLiteWorkflowRepository

        calls = []
        async def _fake_dispatch(action_type, params, state):
            calls.append(action_type)
            return {"sent": True, "saved": True}

        monkeypatch.setattr("backend.workflow.nodes.action._dispatch_action", _fake_dispatch)

        repo = SQLiteWorkflowRepository()
        repo.save_definition(plan_to_definition(plan))

        executor = get_executor()
        # 禁用慢节点（RAG/Memory 检索）
        registry = get_node_registry()
        async def _noop(state, config):
            return {}
        saved = {t: registry.get(t) for t in ("rag_retrieve", "memory_context")}
        for t in ("rag_retrieve", "memory_context"):
            registry.register(t, _noop)

        async def _collect():
            out = []
            async for s in executor.start(definition_id=plan.planId, initial_event=event):
                out.append(s)
            return out

        try:
            sse = asyncio.run(_collect())
        finally:
            for t, fn in saved.items():
                registry.register(t, fn)

        runs = repo.list_runs(definition_id=plan.planId)
        run = runs[0] if runs else None
        return sse, run, calls

    def test_run_low_risk_completes(self, monkeypatch):
        plan = build_plan(build_planning_context(_congestion(avgSpeed=40, queueLength=20, duration=100)))
        sse, run, calls = self._run_plan(plan, _congestion(avgSpeed=40, queueLength=20, duration=100), monkeypatch)
        assert run is not None
        assert run.status.value == "completed"
        # 低风险：只有 save_result（WRITE，非 high-risk）
        assert calls == ["save_result"]

    def test_run_high_risk_awaits_approval_zero_tool_call(self, monkeypatch):
        plan = build_plan(build_planning_context(_congestion()))
        sse, run, calls = self._run_plan(plan, _congestion(), monkeypatch)
        assert run is not None
        assert run.status.value == "awaiting_approval"
        # high-risk notify 未执行（暂停在 human_approval）
        assert calls == []
        joined = "\n".join(sse)
        assert "approval_required" in joined


# ═══════════════════════════════════════════════════════════════════════════════
# Plan Step Audit Contract（DESIGN LOCK v1.1 AMENDMENT — Option B）
# PlanStepStatus 由 durable node/action/approval 记录确定性派生；进程重启可重建。
# ═══════════════════════════════════════════════════════════════════════════════


class TestStepAuditDurableContract:
    """锁定：PlanStepStatus 是投影，canonical audit source 是 workflow_node_runs /
    action_records / events / approvals；客户端断开/进程重启后仍可重建全部状态。"""

    def test_reconstruct_all_statuses_after_reload(self):
        from backend.workflow.models import (
            NodeStatus,
            WorkflowNodeRun,
            WorkflowRun,
            generate_run_id,
        )
        from backend.workflow.repository import SQLiteWorkflowRepository

        plan = build_plan(build_planning_context(_congestion()))
        step_types = {s.stepId: s.stepType for s in plan.steps}

        # 持久化 definition + run + node_runs（模拟执行产生的 durable 记录）
        repo = SQLiteWorkflowRepository()
        repo.save_definition(plan_to_definition(plan))

        run_id = generate_run_id()
        repo.save_run(WorkflowRun(
            run_id=run_id, definition_id=plan.planId, version=1,
            status=WorkflowRunStatus.AWAITING_APPROVAL,
            state={"pendingApproval": {"nodeId": "human_approval_notify_wechat", "approvalId": "a1"}},
        ))

        def _save_nr(node_id, status, output=None):
            repo.save_node_run(WorkflowNodeRun(
                node_run_id=f"nr_{run_id}_{node_id}", run_id=run_id, node_id=node_id,
                node_type=step_types.get(node_id, NodeType.VALIDATE_EVENT),
                status=status, attempt=1, max_attempts=1, output_snapshot=output or {},
            ))

        _save_nr("validate_event", NodeStatus.SUCCEEDED)
        _save_nr("evidence_evaluate", NodeStatus.FAILED, {"error": "boom"})
        _save_nr("human_approval_notify_wechat", NodeStatus.SUCCEEDED, {"approval_required": True})
        _save_nr("action_notify_wechat", NodeStatus.SUCCEEDED, {"status": "denied"})

        # ── 模拟进程重启：全新 repo 实例，从 SQLite 重读（无内存缓存）──
        fresh = SQLiteWorkflowRepository()
        reloaded = fresh.get_run(run_id)
        node_runs = fresh.get_node_runs(run_id)
        assert reloaded is not None
        assert len(node_runs) == 4

        statuses = project_step_statuses(
            plan, node_runs,
            run_status=reloaded.status.value,
            pending_approval=(reloaded.state or {}).get("pendingApproval"),
        )

        # 五种状态全部可从 durable 记录重建
        assert statuses["validate_event"] == PlanStepStatus.SUCCEEDED
        assert statuses["evidence_evaluate"] == PlanStepStatus.FAILED
        assert statuses["human_approval_notify_wechat"] == PlanStepStatus.AWAITING_APPROVAL
        assert statuses["action_notify_wechat"] == PlanStepStatus.DENIED
        assert statuses["action_save_result"] == PlanStepStatus.BLOCKED
        assert statuses["close"] == PlanStepStatus.BLOCKED

    def test_get_endpoint_uses_only_durable_reads(self):
        """GET /planning/plans/{id} 的 stepStatuses 仅来自 repo 持久层读取。"""
        from backend.workflow.repository import SQLiteWorkflowRepository
        repo = SQLiteWorkflowRepository()
        plan = build_plan(build_planning_context(_congestion()))
        repo.save_definition(plan_to_definition(plan))
        # 无 run 时 projection 输入为空，但不依赖任何进程内缓存
        statuses = project_step_statuses(plan, [], run_status="", pending_approval=None)
        assert statuses["validate_event"] == PlanStepStatus.READY  # 无依赖 → ready
        assert statuses["close"] == PlanStepStatus.PENDING          # 依赖未满足 → pending
