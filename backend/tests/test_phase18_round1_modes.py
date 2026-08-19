"""
Phase 18 Round 1 — Planner Mode Orchestrator 单元测试

覆盖 P11-P14 / P26（orchestrator 级）+ backward compat：
  - deterministic 默认：零 LLM，与 build_plan 等价
  - llm：成功 → LLM_ASSISTED plan；失败 → raise PlannerFailure（不 fallback）
  - auto：成功 → LLM；失败 → deterministic fallback + fallbackReason + goalCoverage
  - P26：deterministic 模式绝不调用 LLM client
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.planning.context import build_planning_context
from backend.planning.models import PlanningMode
from backend.planning.planner import build_plan, build_plan_with_mode
from backend.planning.proposal import PlannerFailure, PlannerFailureCode, PlanProposal, PlanProposalStep


def _congestion_event():
    return {
        "eventId": "E_CONG", "eventType": "congestion", "roadName": "C路",
        "avgSpeed": 8, "queueLength": 200, "duration": 1200,
        "isMainRoad": True, "nearbySchool": False, "nearbyHospital": False,
        "weather": "clear", "timePeriod": "off_peak",
    }


def _accident_event():
    return {
        "eventId": "E_ACC", "eventType": "accident", "roadName": "A路",
        "avgSpeed": 8, "queueLength": 150, "duration": 600,
        "isMainRoad": True, "nearbySchool": False, "nearbyHospital": True,
    }


def _ctx(event, goal="分析"):
    return build_planning_context(event, user_goal=goal)


class FakeLLMClient:
    """mock LLM client：可返回 canned proposal 或 raise PlannerFailure。"""

    def __init__(self, steps=None, failure=None):
        self.steps = steps or [
            PlanProposalStep(proposalStepId="s1", intent="analyze",
                             requiredCapabilities=["congestion_analysis"], expectedOutcome="分析"),
        ]
        self.failure = failure
        self.calls = 0
        self.last_attempt_count = 1
        self.last_usage = {}

    async def generate_proposal(self, ctx, snapshot, user_goal):
        self.calls += 1
        if self.failure:
            raise self.failure
        return PlanProposal(
            proposalId="p1", goal=user_goal or "分析", goalSummary=user_goal or "分析",
            steps=self.steps, confidence=0.9, plannerModel="fake-model",
            plannerReasonSummary="test", capabilitySnapshotHash=snapshot.snapshotHash,
        )


class TestDeterministicMode:
    def test_p26_deterministic_zero_llm(self):
        client = FakeLLMClient()
        r = asyncio.run(build_plan_with_mode(_ctx(_congestion_event()), "deterministic", client))
        assert client.calls == 0  # 零 LLM 调用
        assert r.planner_audit.planningModeUsed == "deterministic"
        assert r.planner_audit.plannerModel is None
        assert r.planner_audit.proposalId is None

    def test_deterministic_equals_build_plan(self):
        # backward compat：deterministic 模式与 build_plan 语义等价
        ctx = _ctx(_congestion_event())
        r = asyncio.run(build_plan_with_mode(ctx, "deterministic"))
        direct = build_plan(ctx)
        assert r.plan.planFingerprint == direct.planFingerprint
        assert [s.stepId for s in r.plan.steps] == [s.stepId for s in direct.steps]


class TestLlmMode:
    def test_llm_success(self):
        client = FakeLLMClient()
        r = asyncio.run(build_plan_with_mode(_ctx(_congestion_event()), "llm", client))
        assert r.plan.planningMode == PlanningMode.LLM_ASSISTED
        assert r.planner_audit.planningModeUsed == "llm"
        assert r.planner_audit.plannerModel == "fake-model"
        assert r.planner_audit.proposalId == "p1"
        assert r.planner_audit.goalCoverage == "FULL"

    def test_p12_llm_failure_explicit(self):
        client = FakeLLMClient(failure=PlannerFailure(PlannerFailureCode.TIMEOUT, "超时", retryable=True))
        with pytest.raises(PlannerFailure) as ei:
            asyncio.run(build_plan_with_mode(_ctx(_congestion_event()), "llm", client))
        assert ei.value.code == PlannerFailureCode.TIMEOUT

    def test_p14_llm_schema_invalid_explicit(self):
        client = FakeLLMClient(failure=PlannerFailure(PlannerFailureCode.SCHEMA_INVALID, "schema", retryable=False))
        with pytest.raises(PlannerFailure) as ei:
            asyncio.run(build_plan_with_mode(_ctx(_congestion_event()), "llm", client))
        assert ei.value.code == PlannerFailureCode.SCHEMA_INVALID


class TestAutoMode:
    def test_auto_success_uses_llm(self):
        client = FakeLLMClient()
        r = asyncio.run(build_plan_with_mode(_ctx(_congestion_event()), "auto", client))
        assert r.plan.planningMode == PlanningMode.LLM_ASSISTED
        assert r.planner_audit.planningModeRequested == "auto"
        assert r.planner_audit.planningModeUsed == "llm"
        assert r.planner_audit.fallbackReason is None

    @pytest.mark.parametrize("code", [
        PlannerFailureCode.TIMEOUT,
        PlannerFailureCode.TRANSPORT_ERROR,
        PlannerFailureCode.INVALID_JSON,
        PlannerFailureCode.SCHEMA_INVALID,
        PlannerFailureCode.UNSUPPORTED_CAPABILITY,
        PlannerFailureCode.ATTEMPTS_EXHAUSTED,
    ])
    def test_p11_p13_p14_auto_fallback(self, code):
        client = FakeLLMClient(failure=PlannerFailure(code, "fail", retryable=True))
        r = asyncio.run(build_plan_with_mode(_ctx(_congestion_event()), "auto", client))
        assert r.plan.planningMode == PlanningMode.DETERMINISTIC
        assert r.planner_audit.planningModeRequested == "auto"
        assert r.planner_audit.planningModeUsed == "deterministic"
        assert r.planner_audit.fallbackReason == code
        assert r.planner_audit.goalCoverage == "UNKNOWN"  # 不虚报 FULL

    def test_auto_compile_error_fallback(self):
        # 返回 proposal 但 compiler 失败（hallucinated capability）
        client = FakeLLMClient(steps=[
            PlanProposalStep(proposalStepId="s1", intent="magic",
                             requiredCapabilities=["magic_capability"], expectedOutcome="x"),
        ])
        r = asyncio.run(build_plan_with_mode(_ctx(_congestion_event()), "auto", client))
        assert r.planner_audit.planningModeUsed == "deterministic"
        assert r.planner_audit.fallbackReason == PlannerFailureCode.UNSUPPORTED_CAPABILITY
