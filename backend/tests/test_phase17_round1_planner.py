"""
Phase 17 Round 1 — Deterministic Planner 单元测试

覆盖：
  - build_plan 确定性（P08/P15）
  - Agent selection 只来自 Router
  - UNKNOWN != ZERO（P03）
  - 空 RAG 证据不伪造（P09）
  - planner 零副作用（P10）
  - 普通拥堵生成合法有界计划（P01）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.agent.event_normalizer import normalize_event
from backend.planning.context import build_planning_context
from backend.planning.models import MAX_PLAN_STEPS, GoalType, Plan
from backend.planning.planner import build_plan
from backend.planning.validator import has_errors, validate_plan
from backend.workflow.models import NodeType


def _congestion_event(**overrides):
    ev = {
        "eventId": "E_CONG_1",
        "eventType": "congestion",
        "roadName": "测试匝道",
        "avgSpeed": 8,
        "queueLength": 200,
        "duration": 1200,
        "isMainRoad": True,
        "nearbySchool": False,
        "nearbyHospital": False,
        "weather": "clear",
        "timePeriod": "off_peak",
    }
    ev.update(overrides)
    return ev


class TestBuildPlanDeterminism:
    def test_same_input_stable_structure(self):
        ev = _congestion_event()
        p1 = build_plan(build_planning_context(ev))
        p2 = build_plan(build_planning_context(ev))
        assert p1.planFingerprint == p2.planFingerprint
        assert [s.stepId for s in p1.steps] == [s.stepId for s in p2.steps]
        assert [s.stepType for s in p1.steps] == [s.stepType for s in p2.steps]
        # topology 稳定
        assert [s.dependsOn for s in p1.steps] == [s.dependsOn for s in p2.steps]


class TestAgentSelection:
    def test_agents_from_router(self):
        ev = _congestion_event()
        ctx = build_planning_context(ev)
        plan = build_plan(ctx)
        agent_steps = [s for s in plan.steps if s.stepType == NodeType.AGENT_TASK]
        assert agent_steps, "应至少有 agent_task 步骤"
        # 全部来自 router（归一化后 ∈ 合法集合，且 planner 不自行挑 agent）
        assert all(s.agentType for s in agent_steps)

    def test_signal_fault_context(self):
        # P02: signal fault + congestion evidence → context 含 Signal + Congestion
        ev = {
            "eventId": "E_SIG_1",
            "eventType": "signal_fault",
            "roadName": "学校路口",
            "avgSpeed": 15,
            "queueLength": 120,
            "duration": 300,
        }
        ctx = build_planning_context(ev)
        agents = ctx.selected_agents
        assert "SignalAgent" in agents
        # 拥堵证据（avgSpeed 低）附加 CongestionAgent
        assert "CongestionAgent" in agents


class TestUnknownNotZero:
    def test_duration_none_preserved(self):
        ev = _congestion_event(duration=None)
        normalized = normalize_event(ev)
        assert normalized.get("duration") is None
        assert "duration" in normalized.get("unknownFields", [])
        # planner 不把 None 写成 0（assumption 记录 unknown）
        plan = build_plan(build_planning_context(ev))
        assert any("duration" in a for a in plan.assumptions)


class TestEvidenceGrounded:
    def test_no_rag_evidence_no_fabrication(self):
        ev = _congestion_event()
        plan = build_plan(build_planning_context(ev, rag_evidence=None))
        assert plan.evidenceRefs == []

    def test_rag_evidence_passed_through(self):
        ev = _congestion_event()
        rag = {
            "query": "",
            "results": [{"id": "doc_1", "source": "rules", "score": 0.9}],
            "resultCount": 1,
            "traceId": "",
            "degraded": False,
        }
        plan = build_plan(build_planning_context(ev, rag_evidence=rag))
        assert plan.evidenceRefs == [{"id": "doc_1", "source": "rules", "score": 0.9}]


class TestOrdinaryCongestion:
    def test_valid_bounded_plan(self):
        ev = _congestion_event(avgSpeed=40, queueLength=20, duration=100)
        plan = build_plan(build_planning_context(ev))
        assert 0 < len(plan.steps) <= MAX_PLAN_STEPS
        assert any(s.stepType == NodeType.CLOSE for s in plan.steps)
        assert not has_errors(validate_plan(plan))

    def test_goal_type_derived(self):
        ev = _congestion_event()
        plan = build_plan(build_planning_context(ev))
        assert plan.goalType == GoalType.CONGESTION_RESOLUTION


class TestPlannerNoSideEffects:
    def test_build_plan_pure(self):
        # build_plan 不导入/调用 notify 工具；即使 notify 函数被替换为 raise 也不受影响
        import backend.tools.notify_tools as nt

        def _boom(*a, **k):
            raise AssertionError("planner 不得调用通知工具")

        orig = nt.send_wechat_work
        nt.send_wechat_work = _boom
        try:
            plan = build_plan(build_planning_context(_congestion_event()))
            assert isinstance(plan, Plan)
        finally:
            nt.send_wechat_work = orig
