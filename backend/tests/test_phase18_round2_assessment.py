"""
Phase18 Round2 — ExecutionAssessment 单元测试

覆盖 R13-R20 / R24 / R30-R33 / R38。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.planning.assessment import (
    ExecutionAssessment,
    assessment_eligible,
    assess_terminal_run,
    build_assessment_key,
    deterministic_assessment,
)
from backend.planning.budget import new_lineage, set_lineage
from backend.planning.observation import (
    Observation, ObservationScope, ObservationSource, ObservationStatus, ObservationType,
)
from backend.workflow.models import WorkflowEvent, WorkflowRun, WorkflowRunStatus
from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_round2_assess.db")
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    init_workflow_tables()
    yield test_db


def _make_run(repo, run_id, status, state_extra=None):
    state = {}
    lineage = new_lineage(run_id)
    set_lineage(state, lineage)
    if state_extra:
        state.update(state_extra)
    run = WorkflowRun(run_id=run_id, status=status, state=state)
    repo.save_run(run)
    return run


def _add_observation(repo, run_id, obs_type):
    obs = Observation(observationId="o1", planId="p", planVersion=1, runId=run_id,
                      type=obs_type, status=ObservationStatus.FAILURE,
                      scope=ObservationScope.STEP, source=ObservationSource.TOOL, stepId="s")
    evt = WorkflowEvent(event_id="e1", run_id=run_id, event_type="observation_recorded",
                        payload=obs.to_dict(), sequence=0)
    repo.save_event(evt)


class FakeAssessClient:
    _model = "fake-model"
    def __init__(self, achievement="achieved", fail=False):
        self._achievement = achievement
        self._fail = fail
        self.calls = 0
    async def call_structured_json(self, system, user):
        self.calls += 1
        if self._fail:
            raise RuntimeError("timeout")
        return {"goalAchievement": self._achievement, "confidence": 0.9,
                "reasonSummary": "clear success"}, {}, 1


class TestAssessmentEligible:
    def test_r30_replanned_parent_not_eligible(self, patch_db):
        repo = SQLiteWorkflowRepository()
        run = _make_run(repo, "parent", WorkflowRunStatus.FAILED,
                        state_extra={"replannedToRunId": "child", "terminationReason": "replanned"})
        assert not assessment_eligible(repo.get_run("parent"))

    def test_r31_final_leaf_eligible(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        assert assessment_eligible(repo.get_run("leaf"))

    def test_non_terminal_not_eligible(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "r", WorkflowRunStatus.RUNNING)
        assert not assessment_eligible(repo.get_run("r"))


class TestDeterministicAssessment:
    def test_r16_cancelled_not_assessed(self, patch_db):
        repo = SQLiteWorkflowRepository()
        run = _make_run(repo, "r", WorkflowRunStatus.CANCELLED)
        a = deterministic_assessment(repo, run)
        assert a.assessmentStatus == "not_assessed"
        assert a.goalAchievement == "unknown"

    def test_rejected_not_achieved(self, patch_db):
        repo = SQLiteWorkflowRepository()
        run = _make_run(repo, "r", WorkflowRunStatus.REJECTED)
        a = deterministic_assessment(repo, run)
        assert a.goalAchievement == "not_achieved"

    def test_failed_not_achieved(self, patch_db):
        repo = SQLiteWorkflowRepository()
        run = _make_run(repo, "r", WorkflowRunStatus.FAILED)
        a = deterministic_assessment(repo, run)
        assert a.goalAchievement == "not_achieved"

    def test_r15_unknown_outcome_blocks_achieved(self, patch_db):
        repo = SQLiteWorkflowRepository()
        run = _make_run(repo, "r", WorkflowRunStatus.COMPLETED)
        _add_observation(repo, "r", ObservationType.UNKNOWN_OUTCOME)
        a = deterministic_assessment(repo, run)
        assert a.goalAchievement != "achieved"
        assert a.goalAchievement == "unknown"


class TestAssessTerminalRun:
    def test_r13_completed_llm_achieved(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        client = FakeAssessClient("achieved")
        a = asyncio.run(assess_terminal_run(repo, "leaf", client=client))
        assert a.assessmentStatus == "assessed"
        assert a.goalAchievement == "achieved"
        assert client.calls == 1

    def test_r18_duplicate_assessment_once(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        client = FakeAssessClient("achieved")
        a1 = asyncio.run(assess_terminal_run(repo, "leaf", client=client))
        a2 = asyncio.run(assess_terminal_run(repo, "leaf", client=client))
        assert client.calls == 1  # 第二次复用，不再 LLM
        assert a1.goalAchievement == a2.goalAchievement

    def test_r33_cancelled_provider_0(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.CANCELLED)
        client = FakeAssessClient("achieved")
        a = asyncio.run(assess_terminal_run(repo, "leaf", client=client))
        assert a.assessmentStatus == "not_assessed"
        assert client.calls == 0  # 不调 LLM

    def test_r15_unknown_outcome_provider_0(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        _add_observation(repo, "leaf", ObservationType.UNKNOWN_OUTCOME)
        client = FakeAssessClient("achieved")
        a = asyncio.run(assess_terminal_run(repo, "leaf", client=client))
        assert a.goalAchievement != "achieved"
        assert client.calls == 0  # hard fact → 不调 LLM

    def test_r17_assessment_timeout_run_stays_terminal(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        client = FakeAssessClient("achieved", fail=True)
        a = asyncio.run(assess_terminal_run(repo, "leaf", client=client))
        assert a.assessmentStatus == "fallback"  # LLM 失败
        run = repo.get_run("leaf")
        assert run.status == WorkflowRunStatus.COMPLETED  # 状态不变

    def test_r19_assessment_consumes_budget(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        client = FakeAssessClient("achieved")
        asyncio.run(assess_terminal_run(repo, "leaf", client=client))
        run = repo.get_run("leaf")
        usage = run.state["executionLineage"]["budgetUsage"]
        assert usage["llmCallsUsed"] == 1
        assert usage["assessmentCallsUsed"] == 1

    def test_r24_budget_exhausted_fallback(self, patch_db):
        repo = SQLiteWorkflowRepository()
        run = _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        lineage = run.state["executionLineage"]
        lineage["budgetUsage"]["llmCallsUsed"] = 5  # 耗尽
        repo.save_run(WorkflowRun(run_id="leaf", status=WorkflowRunStatus.COMPLETED,
                                  state=run.state))
        client = FakeAssessClient("achieved")
        a = asyncio.run(assess_terminal_run(repo, "leaf", client=client))
        assert client.calls == 0
        assert a.assessmentStatus == "fallback"

    def test_r20_no_raw_prompt_persisted(self, patch_db):
        repo = SQLiteWorkflowRepository()
        _make_run(repo, "leaf", WorkflowRunStatus.COMPLETED)
        client = FakeAssessClient("achieved")
        asyncio.run(assess_terminal_run(repo, "leaf", client=client))
        run = repo.get_run("leaf")
        blob = json.dumps(run.state, ensure_ascii=False)
        for forbidden in ["rawPrompt", "rawResponse", "chainOfThought", "thinking", "systemPrompt"]:
            assert forbidden not in blob


class TestAssessmentKey:
    def test_key_stable(self):
        assert build_assessment_key("root", "leaf", 2) == "root:leaf:2"
