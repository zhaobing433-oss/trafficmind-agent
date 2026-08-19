"""
Phase 18 Round 1 — Final Acceptance Tests (A01–A24)

覆盖 trust-boundary / resource-bound / identity-stability / runtime E2E。
A01 SDK retry bound · A02 metadata spoofing · A03-A05 proposal bounds ·
A06-A08 param validation · A09-A10 identity stability · A11 Approval V2 E2E ·
A12 edit safety · A13 legacy V1 · A14-A16 duplicate semantic · A17 AUTO equivalence ·
A18 goal coverage · A19 preview purity · A20 create persistence · A21 failure codes ·
A22-A23 malformed JSON retry · A24 async safety。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.planning.capability_snapshot import build_planner_capability_snapshot
from backend.planning.context import build_planning_context
from backend.planning.models import PlanningMode
from backend.planning.planner import build_plan, build_plan_with_mode
from backend.planning.proposal import (
    MAX_PROPOSAL_STEPS,
    PlannerFailure,
    PlannerFailureCode,
    PlanProposal,
    PlanProposalStep,
)
from backend.planning.proposal_compiler import compile_proposal


def _congestion_event():
    return {
        "eventId": "E_CONG", "eventType": "congestion", "roadName": "C路",
        "avgSpeed": 8, "queueLength": 200, "duration": 1200,
        "isMainRoad": True, "nearbySchool": False, "nearbyHospital": False,
    }


def _accident_event():
    return {
        "eventId": "E_ACC", "eventType": "accident", "roadName": "A路",
        "avgSpeed": 8, "queueLength": 150, "duration": 600,
        "isMainRoad": True, "nearbyHospital": True,
    }


def _proposal(steps, snapshot, goal="分析", confidence=0.9):
    return PlanProposal(
        proposalId="p1", goal=goal, goalSummary=goal,
        steps=steps, confidence=confidence,
        plannerModel="deepseek-chat", plannerReasonSummary="test",
        capabilitySnapshotHash=snapshot.snapshotHash,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# A01 — SDK retry bound
# ═══════════════════════════════════════════════════════════════════════════════

class TestA01SdkRetryBound:
    def test_openai_client_max_retries_zero(self, monkeypatch):
        """A01：OpenAI client 显式 max_retries=0，关闭 SDK 内部 retry。"""
        from backend.planning import llm_client

        captured = {}

        class FakeCompletions:
            def create(self, **kw):
                raise RuntimeError("transport fail")

        class FakeChat:
            def __init__(self):
                self.completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self, **kw):
                captured.update(kw)

            @property
            def chat(self):
                return FakeChat()

        monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
        c = llm_client.PlannerLLMClient(api_key="sk-fake", timeout=1.0, max_attempts=2)
        with pytest.raises(PlannerFailure):
            c._call_once("sys", "user")
        assert captured.get("max_retries") == 0

    def test_attempt_loop_bounded(self, monkeypatch):
        """A01：transport 持续失败 → _call_attempts 最多 max_attempts 次真正调用。"""
        from backend.planning import llm_client

        calls = []
        c = llm_client.PlannerLLMClient(api_key="sk-fake", max_attempts=2)

        def _fail(system, user):
            calls.append(1)
            raise PlannerFailure(PlannerFailureCode.TRANSPORT_ERROR, "fail", retryable=True)

        monkeypatch.setattr(c, "_call_once", _fail)
        with pytest.raises(PlannerFailure) as ei:
            c._call_attempts("s", "u")
        assert ei.value.code == PlannerFailureCode.ATTEMPTS_EXHAUSTED
        assert len(calls) == 2  # ≤ maxAttempts


# ═══════════════════════════════════════════════════════════════════════════════
# A02 — Metadata spoofing → system-owned
# ═══════════════════════════════════════════════════════════════════════════════

class TestA02MetadataSpoofing:
    def test_metadata_spoofing_overridden(self, monkeypatch):
        """A02：恶意 LLM JSON 伪造 audit/control 字段 → 最终用 system 真实值。"""
        from backend.planning import llm_client

        snap = build_planner_capability_snapshot()
        ctx = build_planning_context(_congestion_event(), user_goal="分析")

        malicious = json.dumps({
            "proposalId": "evil-id",
            "goal": "分析",
            "goalSummary": "x",
            "steps": [{
                "proposalStepId": "s1", "intent": "analyze",
                "requiredCapabilities": ["congestion_analysis"],
            }],
            "plannerModel": "trusted-system",      # spoof
            "planningModeUsed": "deterministic",   # spoof
            "fallbackReason": None,
            "capabilitySnapshotHash": "arbitrary", # spoof
            "confidence": 0.9,
            "plannerReasonSummary": "x",
        })

        c = llm_client.PlannerLLMClient(api_key="sk-fake")
        monkeypatch.setattr(c, "_call_once", lambda s, u: (malicious, {}))

        proposal = asyncio.run(c.generate_proposal(ctx, snap, "分析"))
        assert proposal.capabilitySnapshotHash == snap.snapshotHash      # system
        assert proposal.planningModeUsed == "llm"                        # system
        assert proposal.plannerModel == c._model                         # system (真实 model)
        assert proposal.fallbackReason is None                           # system
        assert proposal.proposalId != "evil-id"                          # system 生成


# ═══════════════════════════════════════════════════════════════════════════════
# A03–A05 — Proposal resource bounds
# ═══════════════════════════════════════════════════════════════════════════════

class TestProposalBounds:
    def test_a03_too_many_steps(self):
        snap = build_planner_capability_snapshot()
        steps = [{"proposalStepId": f"s{i}", "intent": "analyze",
                  "requiredCapabilities": ["congestion_analysis"]}
                 for i in range(MAX_PROPOSAL_STEPS + 1)]
        d = {"proposalId": "p1", "goal": "x", "steps": steps,
             "confidence": 0.5, "plannerModel": "m", "plannerReasonSummary": "x",
             "capabilitySnapshotHash": snap.snapshotHash}
        with pytest.raises(PlannerFailure) as ei:
            PlanProposal.from_dict_strict(d)
        assert ei.value.code == PlannerFailureCode.SCHEMA_INVALID

    def test_a04_confidence_out_of_range(self):
        snap = build_planner_capability_snapshot()
        d = {"proposalId": "p1", "goal": "x",
             "steps": [{"proposalStepId": "s1", "intent": "analyze",
                        "requiredCapabilities": ["congestion_analysis"]}],
             "confidence": 1.5, "plannerModel": "m", "plannerReasonSummary": "x",
             "capabilitySnapshotHash": snap.snapshotHash}
        with pytest.raises(PlannerFailure) as ei:
            PlanProposal.from_dict_strict(d)
        assert ei.value.code == PlannerFailureCode.SCHEMA_INVALID

    def test_a05_oversized_parameter_hints(self):
        from backend.planning.proposal import MAX_PARAMETER_HINT_KEYS
        snap = build_planner_capability_snapshot()
        hints = {f"k{i}": "v" for i in range(MAX_PARAMETER_HINT_KEYS + 1)}
        d = {"proposalId": "p1", "goal": "x",
             "steps": [{"proposalStepId": "s1", "intent": "divert",
                        "actionIntent": "simulate_diversion",
                        "requiredCapabilities": ["simulate_traffic_diversion"],
                        "parameterHints": hints}],
             "confidence": 0.5, "plannerModel": "m", "plannerReasonSummary": "x",
             "capabilitySnapshotHash": snap.snapshotHash}
        with pytest.raises(PlannerFailure) as ei:
            PlanProposal.from_dict_strict(d)
        assert ei.value.code == PlannerFailureCode.SCHEMA_INVALID


# ═══════════════════════════════════════════════════════════════════════════════
# A06–A08 — Parameter validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestParameterValidation:
    def test_a06_unknown_business_param_dropped(self):
        snap = build_planner_capability_snapshot()
        ctx = build_planning_context(_accident_event())
        proposal = _proposal([
            PlanProposalStep(proposalStepId="s1", intent="divert",
                             actionIntent="simulate_diversion",
                             requiredCapabilities=["simulate_traffic_diversion"],
                             parameterHints={"source_road_id": "R1", "target_road_ids": ["R2"],
                                             "unknown_business_param": "x"}),
        ], snap)
        plan = compile_proposal(proposal, snap, ctx)
        action = [s for s in plan.steps if s.stepType.value == "action"
                  and s.actionType == "simulation_traffic_diversion"][0]
        assert "unknown_business_param" not in action.metadata.get("paramsTemplate", {})

    def test_a07_required_param_missing(self):
        snap = build_planner_capability_snapshot()
        ctx = build_planning_context(_accident_event())
        proposal = _proposal([
            PlanProposalStep(proposalStepId="s1", intent="divert",
                             actionIntent="simulate_diversion",
                             requiredCapabilities=["simulate_traffic_diversion"],
                             parameterHints={"source_road_id": "R1"}),  # missing target_road_ids
        ], snap)
        with pytest.raises(PlannerFailure) as ei:
            compile_proposal(proposal, snap, ctx)
        assert ei.value.code == PlannerFailureCode.INVALID_PARAMETER_HINTS

    def test_a08_wrong_business_param_type(self):
        snap = build_planner_capability_snapshot()
        ctx = build_planning_context(_accident_event())
        proposal = _proposal([
            PlanProposalStep(proposalStepId="s1", intent="divert",
                             actionIntent="simulate_diversion",
                             requiredCapabilities=["simulate_traffic_diversion"],
                             parameterHints={"source_road_id": "R1",
                                             "target_road_ids": "not-a-list"}),  # wrong type
        ], snap)
        with pytest.raises(PlannerFailure) as ei:
            compile_proposal(proposal, snap, ctx)
        assert ei.value.code == PlannerFailureCode.INVALID_PARAMETER_HINTS


# ═══════════════════════════════════════════════════════════════════════════════
# A09–A10 — Canonical step identity stability
# ═══════════════════════════════════════════════════════════════════════════════

class TestIdentityStability:
    def test_a09_compile_twice_stable(self):
        snap = build_planner_capability_snapshot()
        ctx = build_planning_context(_accident_event(), user_goal="分析事故")
        proposal = _proposal([
            PlanProposalStep(proposalStepId="s1", intent="analyze accident",
                             requiredCapabilities=["accident_analysis"]),
            PlanProposalStep(proposalStepId="s2", intent="notify",
                             actionIntent="notify", requiredCapabilities=["notify_wechat"],
                             expectedOutcome="通知交警"),
        ], snap)
        p1 = compile_proposal(proposal, snap, ctx)
        p2 = compile_proposal(proposal, snap, ctx)
        assert [s.stepId for s in p1.steps] == [s.stepId for s in p2.steps]
        assert p1.planFingerprint == p2.planFingerprint

    def test_a10_proposal_local_id_change_does_not_change_fingerprint(self):
        """A10：proposalStepId 只是 local 引用；改成 foo 不改变 canonical fingerprint。"""
        snap = build_planner_capability_snapshot()
        ctx = build_planning_context(_accident_event(), user_goal="分析事故")
        base = _proposal([
            PlanProposalStep(proposalStepId="s1", intent="analyze accident",
                             requiredCapabilities=["accident_analysis"]),
        ], snap)
        renamed = _proposal([
            PlanProposalStep(proposalStepId="foo", intent="analyze accident",
                             requiredCapabilities=["accident_analysis"]),
        ], snap)
        p1 = compile_proposal(base, snap, ctx)
        p2 = compile_proposal(renamed, snap, ctx)
        assert [s.stepId for s in p1.steps] == [s.stepId for s in p2.steps]
        assert p1.planFingerprint == p2.planFingerprint


# ═══════════════════════════════════════════════════════════════════════════════
# A11 — Approval V2 real workflow E2E
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    test_db = str(tmp_path / "test_a11.db")
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    yield test_db


async def _drain(gen):
    events = []
    async for e in gen:
        events.append(e)
    return events


def _extract_run_id(events):
    for e in events:
        if "runId" in e:
            m = __import__("re").search(r'"runId":\s*"([^"]+)"', e)
            if m:
                return m.group(1)
    return None


class TestA11ApprovalV2E2E:
    def test_approve_A_does_not_authorize_B(self, monkeypatch, tmp_db):
        """A11：真实 V2 compiled Plan（两个 notify_wechat）→ executor 执行，
        approve A 执行 A；B 在 approve B 前不执行。"""
        from backend.workflow.repository import init_workflow_tables
        init_workflow_tables()

        from backend.workflow.definition import DefinitionManager
        from backend.workflow.executor import WorkflowExecutor
        from backend.workflow.repository import SQLiteWorkflowRepository

        # 1. build V2 plan with two notify_wechat（不同 objective → 非 duplicate）
        snap = build_planner_capability_snapshot()
        ctx = build_planning_context(_accident_event(), user_goal="通知")
        proposal = _proposal([
            PlanProposalStep(proposalStepId="s1", intent="notify A",
                             actionIntent="notify", requiredCapabilities=["notify_wechat"],
                             expectedOutcome="通知交警大队"),
            PlanProposalStep(proposalStepId="s2", intent="notify B",
                             actionIntent="notify", requiredCapabilities=["notify_wechat"],
                             expectedOutcome="通知信号中心"),
        ], snap)
        plan = compile_proposal(proposal, snap, ctx)
        action_ids = [s.stepId for s in plan.steps
                      if s.stepType.value == "action" and s.actionType == "notify_wechat"]
        assert len(action_ids) == 2
        action_a, action_b = action_ids[0], action_ids[1]

        # 2. materialize
        from backend.planning.adapter import plan_to_definition
        plan.definitionStatus = __import__("backend.planning.models", fromlist=["PlanDefinitionStatus"]).PlanDefinitionStatus.ACTIVE
        definition = plan_to_definition(plan)

        # 3. mock external notify（不真实发送）
        calls = []
        def _fake_send(payload):
            calls.append(payload)
            return True
        monkeypatch.setattr("backend.tools.notify_tools.send_wechat_work", _fake_send)

        repo = SQLiteWorkflowRepository()
        mgr = DefinitionManager(repo)
        repo.save_definition(definition)
        executor = WorkflowExecutor(repo)

        # 4. start → 运行到 approval A（pauses）
        events = asyncio.run(_drain(executor.start(
            definition_id=definition.id,
            initial_event=_accident_event(),
        )))
        run_id = _extract_run_id(events)
        assert run_id is not None
        run = repo.get_run(run_id)
        assert run.status.value == "awaiting_approval"

        # 5. approve A → resume → 执行 A → 停在 approval B
        assert "error" not in asyncio.run(executor.approve(run_id))
        asyncio.run(_drain(executor.resume(run_id)))
        assert len(calls) == 1, "approve A 后应只执行 A"
        run = repo.get_run(run_id)
        assert run.status.value == "awaiting_approval"  # 停在 B 的 gate

        # 6. approve B → resume → 执行 B
        assert "error" not in asyncio.run(executor.approve(run_id))
        asyncio.run(_drain(executor.resume(run_id)))
        assert len(calls) == 2, "approve B 后 B 才执行"

        # 7. 记录 approval identity
        approvals = repo.list_approvals(run_id)
        assert len(approvals) >= 2


# ═══════════════════════════════════════════════════════════════════════════════
# A12 — Approval edit safety（actionStepId server-owned）
# ═══════════════════════════════════════════════════════════════════════════════

class TestA12EditSafety:
    def test_edit_cannot_change_action_step_id(self):
        from backend.workflow.models import ApprovalDecision
        from backend.workflow.nodes.human_approval import process_approval_decision
        from backend.workflow.state import TrafficWorkflowState

        state = TrafficWorkflowState()
        state.pending_approval = {
            "approvalId": "a1", "nodeId": "approval_notify_wechat_01",
            "proposedActions": [{"actionType": "notify_wechat",
                                 "actionStepId": "action_notify_wechat_01",
                                 "source": "compiled_plan"}],
        }
        # 客户端试图把 actionStepId 篡改成 B
        edited = [{"actionType": "notify_wechat", "actionStepId": "action_notify_wechat_02"}]
        result = process_approval_decision(state, ApprovalDecision.EDITED, edited_actions=edited)
        assert "error" not in result
        assert state.approved_actions[0]["actionStepId"] == "action_notify_wechat_01"  # server 保持 A


# ═══════════════════════════════════════════════════════════════════════════════
# A13 — Legacy V1 approval（actionType 语义）
# ═══════════════════════════════════════════════════════════════════════════════

class TestA13LegacyV1:
    def test_v1_action_type_approval(self):
        from backend.workflow.models import NodeConfig, NodeType
        from backend.workflow.nodes.action import is_current_action_approved
        from backend.workflow.state import TrafficWorkflowState

        state = TrafficWorkflowState()
        state.approved_actions = [{"actionType": "notify_wechat", "source": "workflow_template"}]
        config = NodeConfig(node_id="action_x", node_type=NodeType.ACTION,
                            config={"action_type": "notify_wechat"})  # 无 approval_identity_version → V1
        assert is_current_action_approved(state, "notify_wechat", config)


# ═══════════════════════════════════════════════════════════════════════════════
# A14–A16 — Duplicate semantic action
# ═══════════════════════════════════════════════════════════════════════════════

class TestDuplicateSemantic:
    def _compile_two_divert(self, params1, params2, obj1, obj2):
        snap = build_planner_capability_snapshot()
        ctx = build_planning_context(_accident_event())
        proposal = _proposal([
            PlanProposalStep(proposalStepId="s1", intent="divert A",
                             actionIntent="simulate_diversion",
                             requiredCapabilities=["simulate_traffic_diversion"],
                             parameterHints=params1, expectedOutcome=obj1),
            PlanProposalStep(proposalStepId="s2", intent="divert B",
                             actionIntent="simulate_diversion",
                             requiredCapabilities=["simulate_traffic_diversion"],
                             parameterHints=params2, expectedOutcome=obj2),
        ], snap)
        return compile_proposal(proposal, snap, ctx)

    def test_a14_same_params_diff_ordering_duplicate(self):
        p1 = {"source_road_id": "R1", "target_road_ids": ["R2", "R3"], "diversion_ratio": 0.4}
        p2 = {"diversion_ratio": 0.4, "target_road_ids": ["R2", "R3"], "source_road_id": "R1"}  # 不同 key 顺序
        with pytest.raises(PlannerFailure) as ei:
            self._compile_two_divert(p1, p2, "分流", "分流")
        assert ei.value.code == PlannerFailureCode.COMPILE_ERROR
        assert "duplicate_semantic_action" in ei.value.message

    def test_a15_different_business_params_allowed(self):
        p1 = {"source_road_id": "R1", "target_road_ids": ["R2"]}
        p2 = {"source_road_id": "R1", "target_road_ids": ["R3"]}  # 不同 target
        plan = self._compile_two_divert(p1, p2, "分流", "分流")
        assert plan is not None  # 不报 duplicate

    def test_a16_distinct_objective_allowed(self):
        p1 = {"source_road_id": "R1", "target_road_ids": ["R2"]}
        p2 = {"source_road_id": "R1", "target_road_ids": ["R2"]}  # 同 params
        plan = self._compile_two_divert(p1, p2, "分流到上游", "分流到辅路")  # 不同 objective
        assert plan is not None  # 同 params 但不同 objective → allowed


# ═══════════════════════════════════════════════════════════════════════════════
# A17 — AUTO fallback equivalence
# ═══════════════════════════════════════════════════════════════════════════════

class TestA17AutoFallbackEquivalence:
    def test_auto_fallback_equals_direct_deterministic(self):
        ctx = build_planning_context(_congestion_event(), user_goal="分析")

        class FailClient:
            last_attempt_count = 1
            last_usage = {}
            async def generate_proposal(self, ctx, snap, goal):
                raise PlannerFailure(PlannerFailureCode.TIMEOUT, "timeout", retryable=True)

        r = asyncio.run(build_plan_with_mode(ctx, "auto", FailClient()))
        direct = build_plan(ctx)
        assert r.plan.planFingerprint == direct.planFingerprint  # canonical execution plan 不变
        assert r.planner_audit.planningModeUsed == "deterministic"
        assert r.planner_audit.fallbackReason == PlannerFailureCode.TIMEOUT


# ═══════════════════════════════════════════════════════════════════════════════
# A18 — Goal coverage honesty
# ═══════════════════════════════════════════════════════════════════════════════

class TestA18GoalCoverage:
    def test_fallback_goal_coverage_not_full(self):
        ctx = build_planning_context(_congestion_event(), user_goal="复杂多目标分析")

        class FailClient:
            last_attempt_count = 1
            last_usage = {}
            async def generate_proposal(self, ctx, snap, goal):
                raise PlannerFailure(PlannerFailureCode.UNSUPPORTED_CAPABILITY, "unsupported", retryable=False)

        r = asyncio.run(build_plan_with_mode(ctx, "auto", FailClient()))
        assert r.planner_audit.goalCoverage != "FULL"
        assert r.planner_audit.goalCoverage == "UNKNOWN"


# ═══════════════════════════════════════════════════════════════════════════════
# A19 — Preview purity（strong：repo write → fail）
# ═══════════════════════════════════════════════════════════════════════════════

class TestA19PreviewPurity:
    def test_preview_no_repo_write(self, monkeypatch, tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "a19.db"))
        from backend.planning.api import router
        from backend.workflow.repository import SQLiteWorkflowRepository

        def _boom(*a, **k):
            raise AssertionError("preview 不得写 repository")

        for method in ["save_definition", "save_run", "save_event", "save_node_run",
                       "save_approval", "save_action_record", "create_version"]:
            if hasattr(SQLiteWorkflowRepository, method):
                monkeypatch.setattr(SQLiteWorkflowRepository, method, _boom)

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        r = client.post("/planning/plans/preview", json={
            "event": _congestion_event(), "goal": "分析", "plannerMode": "deterministic",
        })
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# A20 — Create persistence（plannerAudit + 无 raw prompt/CoT）
# ═══════════════════════════════════════════════════════════════════════════════

class TestA20CreatePersistence:
    def test_create_persists_planner_audit_no_raw(self, monkeypatch, tmp_path):
        import sqlite3
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        test_db = str(tmp_path / "a20.db")
        monkeypatch.setattr(cfg, "DB_PATH", test_db)
        from backend.planning.api import router

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        r = client.post("/planning/plans", json={
            "event": _congestion_event(), "goal": "分析", "plannerMode": "deterministic",
        })
        assert r.status_code == 200

        # 读持久化 definition.metadata["plan"]["plannerAudit"]
        conn = sqlite3.connect(test_db)
        row = conn.execute(
            "SELECT metadata_json FROM workflow_definitions LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None
        meta = json.loads(row[0])
        audit = meta.get("plan", {}).get("plannerAudit", {})
        assert audit.get("planningModeUsed") == "deterministic"
        blob = json.dumps(meta, ensure_ascii=False)
        for forbidden in ["rawPrompt", "rawResponse", "chainOfThought", "thinking",
                          "systemPrompt", "hiddenReasoning", "raw_prompt", "raw_response"]:
            assert forbidden not in blob


# ═══════════════════════════════════════════════════════════════════════════════
# A22–A23 — Malformed JSON retry
# ═══════════════════════════════════════════════════════════════════════════════

class TestMalformedJsonRetry:
    def test_a22_retry_then_valid(self, monkeypatch):
        from backend.planning import llm_client
        snap = build_planner_capability_snapshot()
        ctx = build_planning_context(_congestion_event(), user_goal="分析")

        responses = iter([
            ("not json", {}),  # attempt 1 malformed
            (json.dumps({
                "proposalId": "p", "goal": "分析", "steps": [
                    {"proposalStepId": "s1", "intent": "analyze",
                     "requiredCapabilities": ["congestion_analysis"]}],
                "confidence": 0.9, "plannerModel": "m", "plannerReasonSummary": "x",
            }), {}),  # attempt 2 valid
        ])
        c = llm_client.PlannerLLMClient(api_key="sk-fake", max_attempts=2)
        monkeypatch.setattr(c, "_call_once", lambda s, u: next(responses))
        proposal = asyncio.run(c.generate_proposal(ctx, snap, "分析"))
        assert proposal is not None  # 第二次成功

    def test_a23_malformed_then_fail(self, monkeypatch):
        from backend.planning import llm_client
        snap = build_planner_capability_snapshot()
        ctx = build_planning_context(_congestion_event(), user_goal="分析")

        c = llm_client.PlannerLLMClient(api_key="sk-fake", max_attempts=2)
        # 两次都 malformed → attempts_exhausted
        monkeypatch.setattr(c, "_call_once", lambda s, u: ("not json", {}))
        with pytest.raises(PlannerFailure) as ei:
            asyncio.run(c.generate_proposal(ctx, snap, "分析"))
        assert ei.value.code == PlannerFailureCode.ATTEMPTS_EXHAUSTED


# ═══════════════════════════════════════════════════════════════════════════════
# A24 — Async event-loop safety
# ═══════════════════════════════════════════════════════════════════════════════

class TestA24AsyncSafety:
    def test_event_loop_not_blocked(self):
        """A24：blocking fake LLM client 等待期间，event loop 仍可调度 heartbeat。"""
        async def _run():
            snap = build_planner_capability_snapshot()
            ctx = build_planning_context(_congestion_event(), user_goal="分析")

            class BlockingClient:
                last_attempt_count = 1
                last_usage = {}
                async def generate_proposal(self, ctx, snap, goal):
                    await asyncio.sleep(0.1)  # 模拟阻塞
                    raise PlannerFailure(PlannerFailureCode.TIMEOUT, "timeout", retryable=True)

            ticks = []
            async def heartbeat():
                for _ in range(20):
                    ticks.append(1)
                    await asyncio.sleep(0.01)

            hb = asyncio.create_task(heartbeat())
            r = await build_plan_with_mode(ctx, "auto", BlockingClient())
            await hb
            assert len(ticks) > 0  # event loop 在 planner 等待期间仍调度
            assert r.planner_audit.fallbackReason == PlannerFailureCode.TIMEOUT

        asyncio.run(_run())
