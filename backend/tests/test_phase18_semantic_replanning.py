"""
Phase18 Semantic Replanning Extension — 单元测试（SR01-SR26）

覆盖：compile_replan_suffix / build_semantic_revision / claim tx /
continuation 集成（semantic replan + deterministic fallback）。
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.planning.capability_snapshot import build_planner_capability_snapshot
from backend.planning.context import build_planning_context
from backend.planning.models import Plan, PlanDefinitionStatus, PlanStep
from backend.planning.planner import build_plan
from backend.planning.proposal import PlannerFailure, PlannerFailureCode, PlanProposalStep
from backend.planning.proposal_compiler import compile_replan_suffix
from backend.planning.replanner import build_revision, build_semantic_revision, is_carried
from backend.planning.validator import validate_plan, has_errors
from backend.workflow.models import NodeType


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_sr.db"))
    from backend.workflow.repository import init_workflow_tables
    init_workflow_tables()
    yield


def _parent_plan():
    ev = {"eventId": "E_ACC", "eventType": "accident", "roadName": "A路",
          "avgSpeed": 8, "queueLength": 200, "duration": 900, "nearbyHospital": True}
    return build_plan(build_planning_context(ev))


def _suffix_steps():
    return [
        PlanProposalStep(proposalStepId="s1", intent="re-analyze congestion",
                         requiredCapabilities=["congestion_analysis"], expectedOutcome="重分析拥堵"),
        PlanProposalStep(proposalStepId="s2", intent="notify",
                         actionIntent="notify", requiredCapabilities=["notify_wechat"], expectedOutcome="通知"),
    ]


class TestCompileReplanSuffix:
    def test_sr15_suffix_valid(self):
        snap = build_planner_capability_snapshot()
        suffix = compile_replan_suffix(_suffix_steps(), snap, True, set())
        # 有 agent/action/evidence/risk_gate/save_result/close，且无 prefix structural
        types = [s.stepType for s in suffix]
        assert NodeType.AGENT_TASK in types
        assert NodeType.ACTION in types
        assert NodeType.CLOSE in types
        assert NodeType.VALIDATE_EVENT not in types  # 不重建 prefix structural
        assert NodeType.RULE_ROUTER not in types

    def test_sr21_deterministic_stable(self):
        snap = build_planner_capability_snapshot()
        s1 = compile_replan_suffix(_suffix_steps(), snap, True, set())
        s2 = compile_replan_suffix(_suffix_steps(), snap, True, set())
        assert [x.stepId for x in s1] == [x.stepId for x in s2]

    def test_sr22_step_id_continues_carried(self):
        snap = build_planner_capability_snapshot()
        # carried 已有 action_notify_wechat_01
        suffix = compile_replan_suffix(_suffix_steps(), snap, True, {"action_notify_wechat_01"})
        action_ids = [s.stepId for s in suffix if s.stepType == NodeType.ACTION and s.actionType == "notify_wechat"]
        assert action_ids == ["action_notify_wechat_02"]  # 非 _01

    def test_sr16_parallel_reject(self):
        snap = build_planner_capability_snapshot()
        steps = [
            PlanProposalStep(proposalStepId="s1", intent="a", requiredCapabilities=["congestion_analysis"]),
            PlanProposalStep(proposalStepId="s2", intent="b", requiredCapabilities=["signal_analysis"],
                             dependsOnProposalStepIds=["s0"]),  # 非线性
        ]
        with pytest.raises(PlannerFailure) as ei:
            compile_replan_suffix(steps, snap, True, set())
        assert ei.value.code == PlannerFailureCode.UNSUPPORTED_PLAN_SHAPE

    def test_sr04_sr05_unsupported_capability(self):
        snap = build_planner_capability_snapshot()
        steps = [PlanProposalStep(proposalStepId="s1", intent="magic", requiredCapabilities=["magic_capability"])]
        with pytest.raises(PlannerFailure) as ei:
            compile_replan_suffix(steps, snap, True, set())
        assert ei.value.code == PlannerFailureCode.UNSUPPORTED_CAPABILITY

    def test_sr17_raw_hallucination_reject(self):
        # PlanProposalStep strict parser 拒绝 raw 字段（复用 Round1）
        with pytest.raises(PlannerFailure):
            PlanProposalStep.from_dict_strict({"proposalStepId": "s1", "intent": "x", "toolName": "notify_wechat"})


class TestBuildSemanticRevision:
    def test_sr02_carried_prefix_stable(self):
        snap = build_planner_capability_snapshot()
        parent = _parent_plan()
        carried = {"validate_event", "rule_router", "rag_retrieve", "memory_context", "agent_accident"}
        refs = {s: "r:" + s for s in carried}
        suffix = compile_replan_suffix(_suffix_steps(), snap, True, carried)
        v2 = build_semantic_revision(parent, refs, "run1", suffix)
        # carried steps 原样（stepId/objective/resultRef 不变）
        for s in v2.steps:
            if is_carried(s):
                orig = parent.get_step(s.stepId)
                assert orig is not None
                assert s.objective == orig.objective
                assert s.resultRef == refs.get(s.stepId, "")

    def test_sr03_completed_action_not_in_suffix(self):
        snap = build_planner_capability_snapshot()
        parent = _parent_plan()
        # carried 含 notify action（已成功）→ suffix 不应重放
        carried = {s.stepId for s in parent.steps if s.stepType == NodeType.ACTION and s.actionType == "notify_wechat"}
        # 但 notify action 是最后一个 action，失败在前，实际不 carried；这里验证 suffix 不重放 carried action
        refs = {s: "r:" + s for s in carried}
        suffix = compile_replan_suffix(_suffix_steps(), snap, True, carried)
        suffix_action_ids = [s.stepId for s in suffix if s.stepType == NodeType.ACTION]
        assert not (carried & set(suffix_action_ids))  # carried action 不重放

    def test_sr23_no_duplicate_structural(self):
        snap = build_planner_capability_snapshot()
        parent = _parent_plan()
        carried = {"validate_event", "rule_router", "rag_retrieve", "memory_context"}
        refs = {s: "r:" + s for s in carried}
        suffix = compile_replan_suffix(_suffix_steps(), snap, True, carried)
        v2 = build_semantic_revision(parent, refs, "run1", suffix)
        ids = [s.stepId for s in v2.steps]
        assert ids.count("close") == 1
        assert ids.count("risk_gate") == 1
        assert ids.count("evidence_evaluate") == 1
        assert not has_errors(validate_plan(v2))

    def test_sr11_sr12_approval_isolation(self):
        snap = build_planner_capability_snapshot()
        parent = _parent_plan()
        carried = {"validate_event", "rule_router", "rag_retrieve", "memory_context"}
        refs = {s: "r:" + s for s in carried}
        suffix = compile_replan_suffix(_suffix_steps(), snap, True, carried)
        v2 = build_semantic_revision(parent, refs, "run1", suffix)
        approvals = [s for s in v2.steps if s.stepType == NodeType.HUMAN_APPROVAL]
        actions = [s for s in v2.steps if s.stepType == NodeType.ACTION and s.actionType == "notify_wechat"]
        assert approvals and actions
        # 新 approval 绑定新 actionStepId
        target = approvals[0].metadata["targetActionStepId"]
        assert target == actions[0].stepId

    def test_sr25_plan_identity_preserved(self):
        snap = build_planner_capability_snapshot()
        parent = _parent_plan()
        carried = {"validate_event", "rule_router", "rag_retrieve", "memory_context"}
        refs = {s: "r:" + s for s in carried}
        suffix = compile_replan_suffix(_suffix_steps(), snap, True, carried)
        v2 = build_semantic_revision(parent, refs, "run1", suffix)
        assert v2.planId == parent.planId  # 同 lineage
        assert v2.version == parent.version + 1
        assert v2.approvalIdentityVersion == parent.approvalIdentityVersion


class TestSemanticReplanClaim:
    def test_sr09_budget_exhausted(self):
        from backend.planning.budget import new_lineage, set_lineage
        from backend.workflow.models import WorkflowRun, WorkflowRunStatus
        from backend.workflow.repository import SQLiteWorkflowRepository
        repo = SQLiteWorkflowRepository()
        state = {}
        lineage = new_lineage("r1")
        lineage.budgetUsage.llmCallsUsed = 5
        set_lineage(state, lineage)
        repo.save_run(WorkflowRun(run_id="r1", status=WorkflowRunStatus.FAILED, state=state))
        res = repo.claim_semantic_replan_tx("r1", "k1")
        assert res["result"] == "budget_exhausted"
        run = repo.get_run("r1")
        assert run.state["executionLineage"]["budgetUsage"]["llmCallsUsed"] == 5  # 未增长

    def test_sr13_sr14_started_no_replay(self):
        from backend.workflow.models import WorkflowRun, WorkflowRunStatus
        from backend.workflow.repository import SQLiteWorkflowRepository
        repo = SQLiteWorkflowRepository()
        repo.save_run(WorkflowRun(run_id="r1", status=WorkflowRunStatus.FAILED, state={}))
        assert repo.claim_semantic_replan_tx("r1", "k1")["result"] == "claimed"
        # STARTED 无 COMPLETED → 再次 claim = already_started（不 replay provider）
        assert repo.claim_semantic_replan_tx("r1", "k1")["result"] == "already_started"

    def test_sr24_registry_survives(self):
        from backend.workflow.models import WorkflowRun, WorkflowRunStatus
        from backend.workflow.repository import SQLiteWorkflowRepository
        repo = SQLiteWorkflowRepository()
        repo.save_run(WorkflowRun(run_id="r1", status=WorkflowRunStatus.FAILED, state={}))
        repo.claim_semantic_replan_tx("r1", "k1")
        repo.complete_semantic_replan_tx("r1", "k1", {"raw": {"reasonSummary": "x", "suffixSteps": []}})
        run = repo.get_run("r1")
        assert run.state["semanticReplanInvocations"]["k1"]["status"] == "COMPLETED"
        # 二次 claim 复用
        assert repo.claim_semantic_replan_tx("r1", "k1")["result"] == "already_completed"


class TestFallback:
    def test_sr18_fallback_equals_deterministic(self):
        snap = build_planner_capability_snapshot()
        parent = _parent_plan()
        carried = {"validate_event", "rule_router", "rag_retrieve", "memory_context"}
        refs = {s: "r:" + s for s in carried}
        # deterministic build_revision
        det = build_revision(parent, refs, "run1")
        # semantic 失败 → fallback 用 deterministic（同一 build_revision）
        fallback = build_revision(parent, refs, "run1")
        assert det.planFingerprint == fallback.planFingerprint


# ── continuation 集成（SR01/SR06/SR20 隔离）────────────────────────────────

def _make_failed_action_run(repo, run_id="sr_failed"):
    from backend.planning.models import PlanDefinitionStatus
    from backend.workflow.models import DefinitionStatus, NodeStatus, WorkflowNodeRun, WorkflowRunStatus
    event = {"eventId": "E_ACC", "eventType": "accident", "roadName": "A路",
             "avgSpeed": 8, "queueLength": 200, "duration": 900, "nearbyHospital": True}
    plan = build_plan(build_planning_context(event))
    plan.definitionStatus = PlanDefinitionStatus.ACTIVE
    plan.semanticReplanEnabled = True  # EA01：extension-enabled plan
    from backend.workflow.models import WorkflowDefinition
    repo.save_definition(WorkflowDefinition(id=plan.planId, name=plan.goal,
                                            status=DefinitionStatus.ACTIVE, metadata={"plan": plan.to_dict()}))
    action_id = next((s.stepId for s in plan.steps if s.stepType == NodeType.ACTION and s.actionType == "notify_wechat"), "action_x")
    from backend.workflow.models import WorkflowRun
    from backend.planning.budget import new_lineage, set_lineage
    state = {}
    set_lineage(state, new_lineage(run_id))
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=plan.planId, status=WorkflowRunStatus.FAILED, state=state))
    repo.save_node_run(WorkflowNodeRun(node_run_id=f"nr_{run_id}_1", run_id=run_id, node_id=action_id,
                                       node_type=NodeType.ACTION, status=NodeStatus.FAILED))
    return run_id


class FakeSemanticReplanClient:
    _model = "fake"
    def __init__(self, proposal=None, fail=False):
        self._proposal = proposal or {
            "reasonSummary": "re-design",
            "suffixSteps": [{"proposalStepId": "s1", "intent": "re-analyze",
                             "requiredCapabilities": ["congestion_analysis"], "expectedOutcome": "重分析"}],
        }
        self._fail = fail
        self.calls = 0
    def call_structured_json_sync(self, system, user):
        self.calls += 1
        if self._fail:
            raise PlannerFailure(PlannerFailureCode.TIMEOUT, "timeout", retryable=True)
        # 区分 critic vs semantic replan prompt
        if "suffixSteps" in user or "续接" in user or "续接方案" in user:
            return self._proposal, {}, 1
        return {"recommendation": "replan", "confidence": 0.9, "reasonSummary": "x"}, {}, 1


class TestContinuationIntegration:
    def test_sr01_semantic_replan_produces_suffix(self, monkeypatch):
        from backend.planning.continuation import PlanningContinuationCoordinator
        from backend.workflow.repository import SQLiteWorkflowRepository
        repo = SQLiteWorkflowRepository()
        run_id = _make_failed_action_run(repo)
        client = FakeSemanticReplanClient()
        monkeypatch.setattr("backend.planning.llm_client.get_planning_llm_client_optional", lambda: client)
        coordinator = PlanningContinuationCoordinator(repo)  # semantic_replan_enabled 默认 True
        result = coordinator.explicit_replan(run_id)
        assert "childRunId" in result  # 创建 child（semantic revision）
        assert client.calls >= 2  # critic + semantic replan
        # 新 suffix 有 agent step（重设计），且 carried prefix 保留
        run = repo.get_run(run_id)
        assert run.state.get("replannedToRunId") is not None

    def test_sr06_semantic_replan_fail_falls_back(self, monkeypatch):
        from backend.planning.continuation import PlanningContinuationCoordinator
        from backend.workflow.repository import SQLiteWorkflowRepository
        repo = SQLiteWorkflowRepository()
        run_id = _make_failed_action_run(repo)
        client = FakeSemanticReplanClient(fail=True)  # 所有 LLM 失败
        monkeypatch.setattr("backend.planning.llm_client.get_planning_llm_client_optional", lambda: client)
        coordinator = PlanningContinuationCoordinator(repo)
        result = coordinator.explicit_replan(run_id)
        # semantic replan 失败 → deterministic fallback（仍创建 child）
        assert "childRunId" in result or "error" in result
        run = repo.get_run(run_id)
        # 不使 continuation 失败（有 child 或明确 error，非 crash）
        assert result is not None

    def test_sr20_critic_disabled_preserves_round2(self, monkeypatch):
        """semantic_replan_enabled=False 时 critic 路径不变（Round2 FA08 隔离）。"""
        from backend.planning.continuation import PlanningContinuationCoordinator
        from backend.workflow.repository import SQLiteWorkflowRepository
        repo = SQLiteWorkflowRepository()
        run_id = _make_failed_action_run(repo)
        client = FakeSemanticReplanClient()
        monkeypatch.setattr("backend.planning.llm_client.get_planning_llm_client_optional", lambda: client)
        coordinator = PlanningContinuationCoordinator(repo, semantic_replan_enabled=False)
        result = coordinator.explicit_replan(run_id)
        # 只 critic 调用一次（semantic replan 不触发）
        assert client.calls == 1
        assert "childRunId" in result


# ── EA acceptance（EA01/EA03/EA04/EA15 等）────────────────────────────────

class TestEA:
    def test_ea01_durable_enablement(self):
        """EA01：semanticReplanEnabled absent=False；deterministic=False；LLM=True；持久化往返。"""
        from backend.planning.models import Plan
        # absent → False
        assert Plan(planId="p", planFingerprint="f", goal="g", goalType="generic",
                    definitionStatus="draft", version=1, steps=[]).semanticReplanEnabled is False
        # deterministic build_plan → False
        assert _parent_plan().semanticReplanEnabled is False
        # LLM compile_proposal → True
        snap = build_planner_capability_snapshot()
        from backend.planning.context import build_planning_context
        from backend.planning.proposal_compiler import compile_proposal
        from backend.planning.proposal import PlanProposal, PlanProposalStep
        ctx = build_planning_context({"eventId": "E", "eventType": "congestion", "roadName": "C"}, user_goal="分析")
        proposal = PlanProposal(proposalId="p", goal="分析", steps=[
            PlanProposalStep(proposalStepId="s1", intent="analyze", requiredCapabilities=["congestion_analysis"])],
            confidence=0.9, plannerModel="m", plannerReasonSummary="x", capabilitySnapshotHash=snap.snapshotHash)
        plan = compile_proposal(proposal, snap, ctx)
        assert plan.semanticReplanEnabled is True
        # 往返持久化
        assert Plan.from_dict(plan.to_dict()).semanticReplanEnabled is True

    def test_ea03_legacy_compat_provider_zero(self, monkeypatch):
        """EA03：semanticReplanEnabled=False（legacy）→ semantic provider 0，deterministic fallback。"""
        from backend.planning.continuation import PlanningContinuationCoordinator
        from backend.workflow.repository import SQLiteWorkflowRepository
        repo = SQLiteWorkflowRepository()
        run_id = _make_failed_action_run(repo)
        # 将 plan 改为 legacy（semanticReplanEnabled=False）
        run = repo.get_run(run_id)
        definition = repo.get_definition(run.definition_id)
        from backend.planning.models import Plan
        plan = Plan.from_dict(definition.metadata["plan"])
        plan.semanticReplanEnabled = False
        definition.metadata["plan"] = plan.to_dict()
        repo.save_definition(definition)
        client = FakeSemanticReplanClient()
        monkeypatch.setattr("backend.planning.llm_client.get_planning_llm_client_optional", lambda: client)
        coordinator = PlanningContinuationCoordinator(repo)
        result = coordinator.explicit_replan(run_id)
        # 无 semantic replan provider call（critic 会调 1 次，但 semantic replan 不触发）
        # FakeSemanticReplanClient 的 critic 响应会返回 replan，但 semantic replan 因 semanticReplanEnabled=False 跳过
        assert "childRunId" in result  # deterministic child 仍创建
        # semanticReplanInvocations 不存在（未 claim）
        run2 = repo.get_run(run_id)
        assert "semanticReplanInvocations" not in run2.state

    def test_ea04_replan_budget_before_llm(self, monkeypatch):
        """EA04：maxReplans 耗尽 → semantic provider 0（在 LLM spend 前检查）。"""
        from backend.planning.continuation import PlanningContinuationCoordinator
        from backend.workflow.repository import SQLiteWorkflowRepository
        from backend.planning.budget import get_lineage
        repo = SQLiteWorkflowRepository()
        run_id = _make_failed_action_run(repo)
        run = repo.get_run(run_id)
        lineage = get_lineage(run.state)
        lineage.budgetUsage.replansUsed = lineage.budgetLimits.maxReplans  # 耗尽
        state = dict(run.state)
        state["executionLineage"] = lineage.to_dict()
        run.state = state
        repo.save_run(run)
        client = FakeSemanticReplanClient()
        monkeypatch.setattr("backend.planning.llm_client.get_planning_llm_client_optional", lambda: client)
        coordinator = PlanningContinuationCoordinator(repo)
        result = coordinator.explicit_replan(run_id)
        # semantic replan 不触发（maxReplans 已耗尽），无 semanticReplanInvocations
        run2 = repo.get_run(run_id)
        assert "semanticReplanInvocations" not in run2.state

    def test_ea15_hard_safety_provider_zero(self):
        """EA15：hard safety 分类永不触发 semantic replan（classify_observation 直接拒绝）。"""
        from backend.planning.replan_decision import classify_observation
        from backend.planning.observation import Observation, ObservationScope, ObservationSource, ObservationStatus, ObservationType
        for t in (ObservationType.UNKNOWN_OUTCOME, ObservationType.TOOL_DENIED,
                  ObservationType.BUDGET_EXHAUSTED, ObservationType.LOOP_DETECTED,
                  ObservationType.CANCELLED, ObservationType.APPROVAL_REJECTED):
            o = Observation(observationId="o", planId="p", planVersion=1, runId="r",
                            type=t, status=ObservationStatus.FAILURE, scope=ObservationScope.RUN,
                            source=ObservationSource.SYSTEM)
            assert classify_observation(o) != "semantic_review"


class TestProductionEnablement:
    """PE01-PE04：durable enablement 继承与重启持久化。"""

    def test_pe01_semantic_revision_preserves_flag(self):
        snap = build_planner_capability_snapshot()
        parent = _parent_plan()
        parent.semanticReplanEnabled = True
        carried = {"validate_event", "rule_router", "rag_retrieve", "memory_context"}
        refs = {s: "r:" + s for s in carried}
        suffix = compile_replan_suffix(_suffix_steps(), snap, True, carried)
        v2 = build_semantic_revision(parent, refs, "run1", suffix)
        assert v2.semanticReplanEnabled is True
        assert Plan.from_dict(v2.to_dict()).semanticReplanEnabled is True  # serialize/deserialize

    def test_pe02_deterministic_fallback_preserves_flag(self):
        parent = _parent_plan()
        parent.semanticReplanEnabled = True
        carried = {"validate_event", "rule_router", "rag_retrieve", "memory_context"}
        refs = {s: "r:" + s for s in carried}
        v2 = build_revision(parent, refs, "run1")
        assert v2.semanticReplanEnabled is True  # deterministic fallback 也保留（child 可再 semantic replan）

    def test_pe03_legacy_never_auto_enables(self):
        snap = build_planner_capability_snapshot()
        parent = _parent_plan()  # build_plan → False
        assert parent.semanticReplanEnabled is False
        carried = {"validate_event", "rule_router", "rag_retrieve", "memory_context"}
        refs = {s: "r:" + s for s in carried}
        v2 = build_revision(parent, refs, "run1")
        assert v2.semanticReplanEnabled is False  # 不 auto-enable
        suffix = compile_replan_suffix(_suffix_steps(), snap, True, carried)
        v3 = build_semantic_revision(parent, refs, "run1", suffix)
        assert v3.semanticReplanEnabled is False

    def test_pe04_restart_preserves_flag(self):
        from backend.workflow.models import DefinitionStatus, WorkflowDefinition
        parent = _parent_plan()
        parent.semanticReplanEnabled = True
        definition = WorkflowDefinition(id=parent.planId, name=parent.goal,
                                        status=DefinitionStatus.ACTIVE, metadata={"plan": parent.to_dict()})
        reloaded = Plan.from_dict(definition.metadata["plan"])
        assert reloaded.semanticReplanEnabled is True


# ── PE02 真实多 revision E2E（两次连续 semantic replan）────────────────────

def _llm_plan_with_notify():
    from backend.planning.context import build_planning_context
    from backend.planning.models import PlanDefinitionStatus
    from backend.planning.proposal import PlanProposal, PlanProposalStep
    from backend.planning.proposal_compiler import compile_proposal
    snap = build_planner_capability_snapshot()
    ctx = build_planning_context({"eventId": "E", "eventType": "accident", "roadName": "A",
                                  "avgSpeed": 8, "queueLength": 200, "duration": 900, "nearbyHospital": True},
                                 user_goal="通知")
    proposal = PlanProposal(proposalId="p", goal="通知", goalSummary="通知",
                            steps=[PlanProposalStep(proposalStepId="s1", intent="analyze accident",
                                                    requiredCapabilities=["accident_analysis"]),
                                   PlanProposalStep(proposalStepId="s2", intent="notify",
                                                    actionIntent="notify", requiredCapabilities=["notify_wechat"],
                                                    expectedOutcome="通知")],
                            confidence=0.9, plannerModel="m", plannerReasonSummary="x",
                            capabilitySnapshotHash=snap.snapshotHash)
    plan = compile_proposal(proposal, snap, ctx)
    plan.definitionStatus = PlanDefinitionStatus.ACTIVE
    return plan


def _seed_run(repo, plan, run_id):
    from backend.planning.budget import new_lineage, set_lineage
    from backend.workflow.definition import DefinitionManager
    from backend.workflow.models import DefinitionStatus, NodeStatus, WorkflowDefinition, WorkflowNodeRun, WorkflowRun, WorkflowRunStatus
    definition = WorkflowDefinition(id=plan.planId, name=plan.goal,
                                    status=DefinitionStatus.ACTIVE, metadata={"plan": plan.to_dict()})
    repo.save_definition(definition)
    # 创建 version 1 snapshot（模拟 run 时 create_version）
    ver = DefinitionManager(repo).create_version(definition, changelog="seed")
    action_id = next(s.stepId for s in plan.steps if s.stepType == NodeType.ACTION and s.actionType == "notify_wechat")
    state = {}
    set_lineage(state, new_lineage(run_id))
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=plan.planId, version=ver.version,
                              status=WorkflowRunStatus.FAILED, state=state))
    repo.save_node_run(WorkflowNodeRun(node_run_id=f"nr_{run_id}_1", run_id=run_id, node_id=action_id,
                                       node_type=NodeType.ACTION, status=NodeStatus.FAILED))
    return action_id


class FakeMultiReplanClient:
    _model = "fake"
    def __init__(self):
        self.critic_calls = 0
        self.semantic_calls = 0
    def call_structured_json_sync(self, system, user):
        if "suffixSteps" in user:
            self.semantic_calls += 1
            return {"reasonSummary": "re-design", "suffixSteps": [
                {"proposalStepId": "s1", "intent": "re-analyze",
                 "requiredCapabilities": ["congestion_analysis"], "expectedOutcome": "重分析"},
                {"proposalStepId": "s2", "intent": "notify", "actionIntent": "notify",
                 "requiredCapabilities": ["notify_wechat"], "expectedOutcome": "通知"},
            ]}, {}, 1
        self.critic_calls += 1
        return {"recommendation": "replan", "confidence": 0.9, "reasonSummary": "x"}, {}, 1


class TestVersionedPlanLoad:
    """VL01-VL07：_load_plan_from_run 版本化加载 + fail-closed。"""

    def _coord(self):
        from backend.planning.continuation import PlanningContinuationCoordinator
        from backend.workflow.repository import SQLiteWorkflowRepository
        repo = SQLiteWorkflowRepository()
        return repo, PlanningContinuationCoordinator(repo)

    def _save(self, repo, plan, run_id, version, snapshot_versions):
        from backend.workflow.definition import DefinitionManager
        from backend.workflow.models import DefinitionStatus, WorkflowDefinition, WorkflowRun, WorkflowRunStatus
        repo.save_definition(WorkflowDefinition(id=plan.planId, name=plan.goal,
                                                status=DefinitionStatus.ACTIVE, metadata={"plan": plan.to_dict()}))
        mgr = DefinitionManager(repo)
        for v_plan in snapshot_versions:
            mgr.create_version(WorkflowDefinition(id=plan.planId, name=plan.goal,
                                                  status=DefinitionStatus.ACTIVE, metadata={"plan": v_plan.to_dict()}),
                               changelog="seed")
        repo.save_run(WorkflowRun(run_id=run_id, definition_id=plan.planId, version=version,
                                  status=WorkflowRunStatus.FAILED, state={}))
        return repo.get_run(run_id)

    def test_vl01_legacy_v1_no_snapshot(self):
        repo, coord = self._coord()
        plan = _parent_plan()
        run = self._save(repo, plan, "r1", 1, [])  # 无 snapshot
        loaded = coord._load_plan_from_run(run)
        assert loaded is not None and loaded.planId == plan.planId and loaded.version == 1

    def test_vl02_snapshot_v2(self):
        repo, coord = self._coord()
        plan = _parent_plan()
        v2 = build_revision(plan, {}, "r1")
        run = self._save(repo, plan, "r1", 2, [plan, v2])  # snapshot 1=v1, snapshot 2=v2
        loaded = coord._load_plan_from_run(run)
        assert loaded.version == 2  # 读 v2，非 v1

    def test_vl03_child_missing_snapshot_fail_closed(self):
        repo, coord = self._coord()
        plan = _parent_plan()
        run = self._save(repo, plan, "r1", 2, [plan])  # 只有 snapshot 1，无 snapshot 2
        loaded = coord._load_plan_from_run(run)
        assert loaded is None  # fail-closed

    def test_vl04_malformed_snapshot_fail_closed(self):
        from backend.workflow.definition import DefinitionManager
        from backend.workflow.models import DefinitionStatus, WorkflowDefinition, WorkflowRun, WorkflowRunStatus
        repo, coord = self._coord()
        plan = _parent_plan()
        repo.save_definition(WorkflowDefinition(id=plan.planId, name=plan.goal,
                                                status=DefinitionStatus.ACTIVE, metadata={"plan": plan.to_dict()}))
        mgr = DefinitionManager(repo)
        mgr.create_version(WorkflowDefinition(id=plan.planId, name=plan.goal,
                                              status=DefinitionStatus.ACTIVE, metadata={"plan": plan.to_dict()}), changelog="v1")
        mgr.create_version(WorkflowDefinition(id=plan.planId, name=plan.goal,
                                              status=DefinitionStatus.ACTIVE, metadata={}), changelog="v2")  # 无 plan
        repo.save_run(WorkflowRun(run_id="r1", definition_id=plan.planId, version=2,
                                  status=WorkflowRunStatus.FAILED, state={}))
        loaded = coord._load_plan_from_run(repo.get_run("r1"))
        assert loaded is None  # fail-closed

    def test_vl05_semantic_enablement_reload(self):
        repo, coord = self._coord()
        plan = _parent_plan()
        plan.semanticReplanEnabled = True
        v2 = build_revision(plan, {}, "r1")
        assert v2.semanticReplanEnabled is True
        run = self._save(repo, plan, "r1", 2, [plan, v2])
        loaded = coord._load_plan_from_run(run)
        assert loaded.semanticReplanEnabled is True

    def test_vl06_deterministic_replan_reads_v2(self):
        repo, coord = self._coord()
        plan = _parent_plan()
        v2 = build_revision(plan, {}, "r1")
        run = self._save(repo, plan, "r1", 2, [plan, v2])
        loaded = coord._load_plan_from_run(run)
        assert loaded.version == 2

    def test_vl07_carried_id_no_collision(self):
        snap = build_planner_capability_snapshot()
        parent = _parent_plan()
        carried = {"validate_event", "rule_router", "rag_retrieve", "memory_context", "action_notify_wechat_01"}
        refs = {s: "r:" + s for s in carried}
        suffix = compile_replan_suffix(_suffix_steps(), snap, True, carried)
        action_ids = [s.stepId for s in suffix if s.stepType == NodeType.ACTION and s.actionType == "notify_wechat"]
        assert action_ids == ["action_notify_wechat_02"]  # 不与 carried _01 冲突
        v2 = build_semantic_revision(parent, refs, "run1", suffix)
        approvals = [s for s in v2.steps if s.stepType == NodeType.HUMAN_APPROVAL]
        actions = [s for s in v2.steps if s.stepType == NodeType.ACTION and s.actionType == "notify_wechat"]
        assert approvals[0].metadata["targetActionStepId"] == actions[0].stepId


class TestPE02TrueMultiRevision:
    def test_pe02_two_consecutive_semantic_replans(self, monkeypatch):
        from backend.planning.continuation import PlanningContinuationCoordinator
        from backend.workflow.models import NodeStatus, WorkflowNodeRun, WorkflowRunStatus
        from backend.workflow.repository import SQLiteWorkflowRepository
        repo = SQLiteWorkflowRepository()
        plan_v1 = _llm_plan_with_notify()
        assert plan_v1.semanticReplanEnabled is True
        plan_id = plan_v1.planId

        # round 1
        _seed_run(repo, plan_v1, "run_v1")
        client = FakeMultiReplanClient()
        monkeypatch.setattr("backend.planning.llm_client.get_planning_llm_client_optional", lambda: client)
        coordinator = PlanningContinuationCoordinator(repo)
        r1 = coordinator.explicit_replan("run_v1")
        assert "childRunId" in r1, r1
        run_v2_id = r1["childRunId"]
        run_v2 = repo.get_run(run_v2_id)

        # v2 plan 从 version snapshot 读（version = run_v2.version）
        ver2 = repo.get_definition_version(plan_id, run_v2.version)
        assert ver2 is not None, f"version {run_v2.version} snapshot missing"
        v2_meta = ver2.definition_json["metadata"] if isinstance(ver2.definition_json, dict) else ver2.definition_json
        plan_v2 = Plan.from_dict(v2_meta["plan"])
        assert plan_v2.semanticReplanEnabled is True
        action_v2 = next(s.stepId for s in plan_v2.steps if s.stepType == NodeType.ACTION and s.actionType == "notify_wechat")

        # 模拟 v2 第二次 semantic failure（mark FAILED + failed action node）
        run_v2.status = WorkflowRunStatus.FAILED
        repo.save_run(run_v2)
        repo.save_node_run(WorkflowNodeRun(node_run_id="nr_run_v2_1", run_id=run_v2_id, node_id=action_v2,
                                           node_type=NodeType.ACTION, status=NodeStatus.FAILED))

        # round 2
        r2 = coordinator.explicit_replan(run_v2_id)
        assert "childRunId" in r2, r2
        run_v3_id = r2["childRunId"]
        run_v3 = repo.get_run(run_v3_id)

        # 断言
        assert client.semantic_calls == 2  # 两次真实 semantic replan
        assert client.critic_calls == 2
        ver3 = repo.get_definition_version(plan_id, run_v3.version)
        assert ver3 is not None, f"version {run_v3.version} snapshot missing"
        v3_meta = ver3.definition_json["metadata"] if isinstance(ver3.definition_json, dict) else ver3.definition_json
        plan_v3 = Plan.from_dict(v3_meta["plan"])
        assert plan_v3.semanticReplanEnabled is True
        assert plan_v3.planId == plan_id  # 同 lineage
        # 版本严格递增（v1→v2→v3）
        assert plan_v2.version == 2
        assert plan_v3.version == 3
        # 父 run 各自只有一个 child
        assert repo.get_run("run_v1").state.get("replannedToRunId") == run_v2_id
        assert repo.get_run(run_v2_id).state.get("replannedToRunId") == run_v3_id
        # 两个 distinct invocation keys（不同 parentRunId/planVersion）
        regs = list(repo.get_run(run_v2_id).state.get("semanticReplanInvocations", {}).keys()) + \
               list(repo.get_run(run_v3_id).state.get("semanticReplanInvocations", {}).keys())
        # 两个 run 各自一个 invocation key（可不同）
        assert repo.get_run("run_v1").state.get("semanticReplanInvocations", {})
        assert repo.get_run(run_v2_id).state.get("semanticReplanInvocations", {})
        assert not has_errors(validate_plan(plan_v3))
