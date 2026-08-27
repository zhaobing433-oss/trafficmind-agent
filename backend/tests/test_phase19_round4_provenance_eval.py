"""
Phase19 Round4-Lite — Decision Provenance & Minimal Intelligence Evaluation

R4-01..35（§20/§23）。provenance 侧全部走真实 durable 写入路径
（repository claim/complete tx + 真实 DefinitionManager 版本快照 +
真实 WorkflowEvent），读取侧 0 provider / 0 持久化写。

- 注册表 key 格式沿用生产：
  critic        = {root}:{run}:{version}:{type}:{sid}
  semantic      = {root}:{run}:{version}:{sid}:{type}
  assessment    = {root}:{run}:{version}
- 不 mock DecisionContext / critic / replanner / compiler；
  不调用任何 LLM（R4-17 双重守卫断言读取侧 provider=0）。
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.workflow.models import (
    DefinitionStatus,
    NodeStatus,
    NodeType,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowRunStatus,
)
from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables

ROOT = "r4_root_run"
RUN_ID = "r4_parent_run"
CHILD_ID = "r4_child_run"
VERSION = 1
PLAN_ID = "plan_r4"
OBS_TYPE = "tool_failed"
STEP_ID = "action_sim"

CRITIC_KEY = f"{ROOT}:{RUN_ID}:{VERSION}:{OBS_TYPE}:{STEP_ID}"
SEMANTIC_KEY = f"{ROOT}:{RUN_ID}:{VERSION}:{STEP_ID}:{OBS_TYPE}"
ASSESSMENT_KEY = f"{ROOT}:{RUN_ID}:{VERSION}"


# ── 种子 helpers（真实生产对象）────────────────────────────────────────────

@pytest.fixture()
def repo(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_phase19_r4.db")
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    init_workflow_tables()
    return SQLiteWorkflowRepository()


def _make_plan(flag: bool = True):
    from backend.planning.models import GoalType, Plan, PlanDefinitionStatus, PlanStep
    steps = [
        PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT,
                 objective="校验仿真事件"),
        PlanStep(stepId=STEP_ID, stepType=NodeType.ACTION,
                 objective="仿真分流", toolName="simulation_traffic_diversion",
                 actionType="simulation_traffic_diversion", riskLevel="high_risk",
                 approvalRequired=True, timeoutSeconds=30),
        PlanStep(stepId="close", stepType=NodeType.CLOSE, objective="闭环归档"),
    ]
    plan = Plan(
        planId=PLAN_ID, planFingerprint="fp_r4", goal="R4 provenance 目标",
        goalType=GoalType.SIMULATION_EVALUATION,
        definitionStatus=PlanDefinitionStatus.ACTIVE, version=VERSION, steps=steps,
    )
    plan.semanticReplanEnabled = True
    plan.groundedDecisionContextEnabled = flag
    return plan


def _save_definition(repo, plan):
    from backend.workflow.definition import DefinitionManager
    definition = WorkflowDefinition(
        id=plan.planId, name=plan.goal, status=DefinitionStatus.ACTIVE,
        metadata={"plan": plan.to_dict()},
    )
    repo.save_definition(definition)
    DefinitionManager(repo).create_version(definition, changelog="seed")


def _seed_run(repo, plan, run_id=RUN_ID, status=WorkflowRunStatus.FAILED,
              state=None, version=VERSION):
    from backend.planning.budget import new_lineage, set_lineage
    st = dict(state or {})
    if "executionLineage" not in st:
        # root 统一为 ROOT：provenance 的 criticBoundaryKey 派生依赖
        # lineage.rootRunId 与注册表 key 首段一致（§6 字节级同源）
        set_lineage(st, new_lineage(ROOT))
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=plan.planId,
                              version=version, status=status, state=st))
    return run_id


def _seed_observation(repo, run_id, obs_type=OBS_TYPE, step_id=STEP_ID,
                      evidence_refs=None, extra_payload=None):
    payload = {
        "observationId": f"obs_{run_id}_{obs_type}",
        "planId": PLAN_ID, "planVersion": VERSION, "runId": run_id,
        "type": obs_type, "status": "failure", "scope": "run", "source": "system",
        "timestamp": "2026-08-27T00:00:00Z", "stepId": step_id,
        "confidence": 0.5, "evidenceRefs": evidence_refs or [],
        "failureCode": "tool_error", "failureReason": None, "metadata": {},
    }
    if extra_payload:
        payload.update(extra_payload)
    repo.save_event(WorkflowEvent(
        event_id=f"wfevent_obs_{run_id}_{obs_type}_{step_id}",
        run_id=run_id, event_type="observation_recorded",
        payload=payload, sequence=0))


def _seed_provenance_run(repo, plan, state=None):
    """critic COMPLETED + semantic COMPLETED + assessment COMPLETED 的完整父 run。"""
    _save_definition(repo, plan)
    _seed_run(repo, plan, state=state)
    # critic
    assert repo.claim_critic_invocation_tx(RUN_ID, CRITIC_KEY)["result"] == "claimed"
    repo.complete_critic_invocation_tx(RUN_ID, CRITIC_KEY, {
        "recommendation": "replan", "confidence": 0.85,
        "reasonSummary": "LLM_FREE_TEXT_REASON", "semanticFailureType": "LLM_FREE_TEXT_TYPE",
    })
    # semantic replan
    assert repo.claim_semantic_replan_tx(RUN_ID, SEMANTIC_KEY)["result"] == "claimed"
    repo.complete_semantic_replan_tx(RUN_ID, SEMANTIC_KEY, {
        "raw": {"suffixSteps": [{"proposalStepId": "s1", "intent": "RAW_LLM_INTENT"}]},
    })
    # assessment（grounded llm）
    repo.complete_assessment_tx(RUN_ID, ASSESSMENT_KEY, {
        "assessmentStatus": "assessed", "goalAchievement": "achieved",
        "assessmentMode": "llm", "goalResolved": True, "confidence": 0.9,
        "assessmentReason": "LLM_FREE_TEXT_ASSESS_REASON", "assessmentModel": "deepseek-chat",
    })
    # child 指针
    st = repo.get_run(RUN_ID).state
    st["replannedToRunId"] = CHILD_ID
    repo.save_run(WorkflowRun(run_id=RUN_ID, definition_id=PLAN_ID, version=VERSION,
                              status=WorkflowRunStatus.FAILED, state=st))
    repo.save_run(WorkflowRun(run_id=CHILD_ID, definition_id=PLAN_ID, version=2,
                              status=WorkflowRunStatus.PENDING,
                              state={"executionLineage": {"rootRunId": ROOT}}))
    return repo.get_run(RUN_ID)


def _provenance(repo, run_id=RUN_ID):
    from backend.planning.decision_provenance import build_decision_provenance
    return build_decision_provenance(repo.get_run(run_id), repo)


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


# ── R4-01/02/07/08/09/10：基础可读性与稳定性 ───────────────────────────────

def test_r4_01_critic_completed_provenance_readable(repo):
    plan = _make_plan(flag=True)
    _seed_provenance_run(repo, plan)
    entries = _provenance(repo)
    critic = [e for e in entries if e["decisionType"] == "critic"]
    assert len(critic) == 1
    c = critic[0]
    assert c["decisionStatus"] == "COMPLETED"
    assert c["boundaryKey"] == CRITIC_KEY
    # §23-A：plan flag=true 不伪造 actual grounded mode（kill-switch/assembler 未持久化）
    assert c["groundedMode"] == "unknown"
    assert c["groundedPlanEnabled"] is True
    assert c["providerCall"] is True  # COMPLETED + durable provider 产出物
    assert c["providerClaimed"] is True
    assert c["recommendation"] == "replan"
    assert c["confidence"] == 0.85
    assert c["planVersion"] == VERSION
    assert c["rootRunId"] == ROOT
    assert c["runStatus"] == "failed"
    # §7：reasonSummary / semanticFailureType 原文绝不暴露
    assert "reasonSummary" not in c
    assert "LLM_FREE_TEXT_REASON" not in _dumps(entries)


def test_r4_02_critic_started_no_fabricated_result(repo):
    plan = _make_plan(flag=True)
    _save_definition(repo, plan)
    _seed_run(repo, plan)
    assert repo.claim_critic_invocation_tx(RUN_ID, CRITIC_KEY)["result"] == "claimed"
    entries = _provenance(repo)
    critic = [e for e in entries if e["decisionType"] == "critic"]
    assert len(critic) == 1
    assert critic[0]["decisionStatus"] == "STARTED"
    assert critic[0]["recommendation"] is None
    assert critic[0]["confidence"] is None
    # §23-C：claim ≠ actual call（claim 后 crash 窗口 provider 可能未执行）
    assert critic[0]["providerCall"] is None
    assert critic[0]["providerClaimed"] is True
    assert critic[0]["groundedMode"] == "unknown"
    assert critic[0]["groundedPlanEnabled"] is True


def test_r4_03_semantic_replan_exact_critic_boundary_key(repo):
    plan = _make_plan(flag=True)
    _seed_provenance_run(repo, plan)
    entries = _provenance(repo)
    sem = [e for e in entries if e["decisionType"] == "semantic_replan"]
    assert len(sem) == 1
    s = sem[0]
    assert s["decisionStatus"] == "COMPLETED"
    assert s["boundaryKey"] == SEMANTIC_KEY
    # §8：与 R3 决策时同源函数字节级一致的 criticBoundaryKey（exact binding）
    assert s["criticBoundaryKey"] == CRITIC_KEY
    assert s["criticRecommendation"] == "replan"
    # raw provider response 绝不暴露
    assert "raw" not in s and "suffixSteps" not in s
    assert "RAW_LLM_INTENT" not in _dumps(entries)


def test_r4_04_semantic_replan_child_run_id_version(repo):
    plan = _make_plan(flag=True)
    _seed_provenance_run(repo, plan)
    sem = [e for e in _provenance(repo) if e["decisionType"] == "semantic_replan"][0]
    assert sem["resultStatus"] == "child_created"
    assert sem["childRunId"] == CHILD_ID
    assert sem["childVersion"] == 2


def test_r4_05_assessment_grounded_provenance(repo):
    plan = _make_plan(flag=True)
    _seed_provenance_run(repo, plan)
    assess = [e for e in _provenance(repo) if e["decisionType"] == "assessment"]
    assert len(assess) == 1
    a = assess[0]
    assert a["decisionStatus"] == "COMPLETED"
    # §23-B：goalResolved=true 只证明 exact Plan.goal 解析成功，
    # 不证明 grounded assessment prompt 实际使用（kill/assembler 未持久化）
    assert a["groundedMode"] == "unknown"
    assert a["groundedPlanEnabled"] is True
    assert a["providerCall"] is True  # assessed = durable LLM 产出物
    assert a["providerClaimed"] is True
    assert a["verdict"] == "achieved"
    assert a["goalResolved"] is True
    assert a["resultStatus"] is None
    # 自由文本 reason 绝不暴露
    assert "assessmentReason" not in a
    assert "LLM_FREE_TEXT_ASSESS_REASON" not in _dumps(assess)


def test_r4_06_assessment_deterministic_hard_fact(repo):
    plan = _make_plan(flag=True)
    _save_definition(repo, plan)
    _seed_run(repo, plan)
    repo.complete_assessment_tx(RUN_ID, ASSESSMENT_KEY, {
        "assessmentStatus": "assessed", "goalAchievement": "not_achieved",
        "assessmentMode": "deterministic", "goalResolved": False,
        "assessmentReason": "hard safety facts present",
    })
    assess = [e for e in _provenance(repo) if e["decisionType"] == "assessment"]
    assert assess[0]["decisionStatus"] == "deterministic"
    # deterministic = 可证明的无 LLM 硬事实路径
    assert assess[0]["groundedMode"] == "deterministic"
    assert assess[0]["providerCall"] is False
    assert assess[0]["providerClaimed"] is False
    assert assess[0]["groundedPlanEnabled"] is True
    assert assess[0]["verdict"] == "not_achieved"
    assert assess[0]["goalResolved"] is False


def test_r4_07_legacy_run_safe_empty(repo):
    plan = _make_plan(flag=False)
    _save_definition(repo, plan)
    _seed_run(repo, plan)  # 无任何注册表
    assert _provenance(repo) == []


def test_r4_08_missing_optional_fields_no_throw(repo):
    """缺失可选字段 → null/unknown，绝不 throw（§11 legacy 安全）。"""
    _seed_run(repo, _make_plan(flag=True))  # 无 definition（flag 不可恢复）
    repo.claim_critic_invocation_tx(RUN_ID, CRITIC_KEY)
    repo.complete_critic_invocation_tx(RUN_ID, CRITIC_KEY, {})  # 无 recommendation 键
    repo.complete_assessment_tx(RUN_ID, ASSESSMENT_KEY, {})  # 空 result
    entries = _provenance(repo)
    critic = [e for e in entries if e["decisionType"] == "critic"][0]
    assert critic["groundedMode"] == "unknown"
    assert critic["groundedPlanEnabled"] is None  # flag 拿不到 → null，不伪造
    assert critic["providerCall"] is None  # complete({}) 无 provider 产出物
    assert critic["recommendation"] is None and critic["confidence"] is None
    assess = [e for e in entries if e["decisionType"] == "assessment"][0]
    assert assess["decisionStatus"] == "COMPLETED"
    assert assess["groundedMode"] is None and assess["providerCall"] is None
    assert assess["providerClaimed"] is None
    assert assess["verdict"] is None and assess["goalResolved"] is None


def test_r4_09_ordering_deterministic(repo):
    plan = _make_plan(flag=True)
    _save_definition(repo, plan)
    _seed_run(repo, plan)
    key_a = f"{ROOT}:{RUN_ID}:{VERSION}:{OBS_TYPE}:action_a"
    key_b = f"{ROOT}:{RUN_ID}:{VERSION}:{OBS_TYPE}:action_b"
    repo.claim_critic_invocation_tx(RUN_ID, key_b)  # 先写后序 key
    repo.claim_critic_invocation_tx(RUN_ID, key_a)
    repo.complete_critic_invocation_tx(RUN_ID, key_b, {"recommendation": "abort"})
    repo.complete_critic_invocation_tx(RUN_ID, key_a, {"recommendation": "replan"})
    repo.complete_assessment_tx(RUN_ID, ASSESSMENT_KEY, {
        "assessmentStatus": "assessed", "goalAchievement": "unknown",
        "assessmentMode": "deterministic", "goalResolved": False})
    types = [e["decisionType"] for e in _provenance(repo)]
    assert types == ["critic", "critic", "assessment"]
    critic_keys = [e["boundaryKey"] for e in _provenance(repo)
                   if e["decisionType"] == "critic"]
    assert critic_keys == [key_a, key_b]  # 字典序，与写入顺序无关


def test_r4_10_restart_read_twice_stable(repo):
    plan = _make_plan(flag=True)
    _seed_provenance_run(repo, plan)
    assert _dumps(_provenance(repo)) == _dumps(_provenance(repo))


# ── R4-11..16：无 raw / 无敏感内容 ─────────────────────────────────────────

def _seed_observation_with_markers(repo, run_id):
    _seed_observation(repo, run_id,
                      evidence_refs=[{"ref": "node:r4:action_sim"},
                                     {"ref": "action:act_r4_1"}],
                      extra_payload={
                          "failureReason": "RAW_PROMPT_MARKER",
                          "output": {"nodeOutput": {
                              "ragBody": "RAG_BODY_MARKER",
                              "memoryBody": "MEMORY_BODY_MARKER",
                              "actionParams": "ACTION_PARAMS_MARKER",
                          }},
                          "metadata": {"token": "SECRET_TOKEN_MARKER"},
                      })


def test_r4_11_12_13_14_15_16_no_raw_no_sensitive(repo):
    plan = _make_plan(flag=True)
    _save_definition(repo, plan)
    _seed_run(repo, plan)
    _seed_observation_with_markers(repo, RUN_ID)
    repo.claim_critic_invocation_tx(RUN_ID, CRITIC_KEY)
    repo.complete_critic_invocation_tx(RUN_ID, CRITIC_KEY,
                                       {"recommendation": "replan", "confidence": 0.8})
    # state 里埋一个 secret 形态字段（不合法源，provenance 不得透传）
    st = repo.get_run(RUN_ID).state
    st["apiKey"] = "sk-secret-r4-marker"
    repo.save_run(WorkflowRun(run_id=RUN_ID, definition_id=PLAN_ID, version=VERSION,
                              status=WorkflowRunStatus.FAILED, state=st))
    dumped = _dumps(_provenance(repo))
    for marker in ("RAW_PROMPT_MARKER", "RAG_BODY_MARKER", "MEMORY_BODY_MARKER",
                   "ACTION_PARAMS_MARKER", "SECRET_TOKEN_MARKER", "sk-secret-r4-marker"):
        assert marker not in dumped, f"{marker} 不得出现在 provenance 输出"
    # 正向控制：白名单 evidenceRefs 仍在
    assert "node:r4:action_sim" in dumped and "action:act_r4_1" in dumped


# ── R4-17/18：读取侧 0 provider / 0 持久化写 ──────────────────────────────

def test_r4_17_provenance_read_provider_calls_zero(repo, monkeypatch):
    plan = _make_plan(flag=True)
    _seed_provenance_run(repo, plan)

    def _forbidden(*_a, **_k):
        raise AssertionError("provenance 读取不得触达 provider")

    monkeypatch.setattr("backend.planning.llm_client.get_planning_llm_client_optional",
                        _forbidden)
    entries = _provenance(repo)
    assert len(entries) == 3  # critic + semantic + assessment


def test_r4_18_provenance_read_persistence_writes_zero(repo, monkeypatch):
    plan = _make_plan(flag=True)
    _seed_provenance_run(repo, plan)

    def _forbidden(*_a, **_k):
        raise AssertionError("provenance 读取不得写持久化")

    for name in ("save_run", "save_event", "save_definition", "mark_driver_managed",
                 "save_driver_managed_run", "claim_critic_invocation_tx",
                 "complete_critic_invocation_tx", "claim_semantic_replan_tx",
                 "complete_semantic_replan_tx", "claim_assessment_tx",
                 "complete_assessment_tx"):
        monkeypatch.setattr(repo, name, _forbidden)
    entries = _provenance(repo)
    assert len(entries) == 3
    # 读取前后 state_json 字节一致
    before = repo.get_run(RUN_ID).state
    _provenance(repo)
    assert repo.get_run(RUN_ID).state == before


# ── R4-19/20：API 契约 ─────────────────────────────────────────────────────

def _api_client(repo, monkeypatch):
    import backend.workflow.api as workflow_api
    monkeypatch.setattr(workflow_api, "_repo", repo)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(workflow_api.router)
    return TestClient(app)


def test_r4_19_api_unknown_run_404(repo, monkeypatch):
    client = _api_client(repo, monkeypatch)
    resp = client.get("/workflow/runs/nope")
    assert resp.status_code == 404


def test_r4_20_api_no_decisions_empty_list(repo, monkeypatch):
    plan = _make_plan(flag=True)
    _save_definition(repo, plan)
    _seed_run(repo, plan)
    client = _api_client(repo, monkeypatch)
    resp = client.get(f"/workflow/runs/{RUN_ID}")
    assert resp.status_code == 200
    assert resp.json()["decisionProvenance"] == []


# ── R4-31..35：truthfulness（claim≠call / crash 窗口 / fallback 矩阵 / 不重算）──

def test_r4_31_semantic_started_no_fabricated_provider_call(repo):
    """§23-D：semantic claim 后 crash（registry 恒 STARTED）→ providerCall 不得伪造 True。"""
    plan = _make_plan(flag=True)
    _save_definition(repo, plan)
    _seed_run(repo, plan)
    assert repo.claim_semantic_replan_tx(RUN_ID, SEMANTIC_KEY)["result"] == "claimed"
    sem = [e for e in _provenance(repo) if e["decisionType"] == "semantic_replan"]
    assert len(sem) == 1
    s = sem[0]
    assert s["decisionStatus"] == "STARTED"
    assert s["providerCall"] is None
    assert s["providerClaimed"] is True
    assert s["groundedMode"] == "unknown"
    assert s["groundedPlanEnabled"] is True
    assert s["criticBoundaryKey"] == CRITIC_KEY  # exact binding 仍派生
    assert s["childRunId"] is None and s["childVersion"] is None
    assert "raw" not in _dumps(s)


def test_r4_32_assessment_claim_crash_window_started(repo):
    """claim 后 crash：assessment registry 恒 STARTED 无 result → 全部诚实 null。"""
    plan = _make_plan(flag=True)
    _save_definition(repo, plan)
    _seed_run(repo, plan)
    assert repo.claim_assessment_tx(RUN_ID, ASSESSMENT_KEY)["result"] == "claimed"
    assess = [e for e in _provenance(repo) if e["decisionType"] == "assessment"]
    a = assess[0]
    assert a["decisionStatus"] == "STARTED"
    assert a["providerClaimed"] is True
    assert a["providerCall"] is None
    assert a["groundedMode"] is None
    assert a["verdict"] is None and a["goalResolved"] is None
    assert a["resultStatus"] is None


def test_r4_33_assessment_fallback_claim_call_matrix(repo):
    """fallbackReason 白名单 → 可证明 (claim, call)；already_started / 异常 → call 不可知。"""
    plan = _make_plan(flag=True)
    _save_definition(repo, plan)
    cases = [
        ("client_unavailable", False, False),   # 无 client，无 claim，无 provider 可能
        ("budget_exhausted", False, False),     # claim 拒绝，provider 未触达
        ("already_started", True, None),        # claim 已存在，先前 attempt 的 call 不可知
        ("timed out after claim", True, None),  # claim 后异常，actual call 不可证明
    ]
    for i, (reason, want_claimed, want_call) in enumerate(cases):
        run_id = f"r4_fb_run_{i}"
        _seed_run(repo, plan, run_id=run_id)
        key = f"{ROOT}:{run_id}:{VERSION}"
        repo.complete_assessment_tx(run_id, key, {
            "assessmentStatus": "fallback", "goalAchievement": "unknown",
            "assessmentMode": "deterministic", "assessmentFallbackReason": reason,
            "goalResolved": False,
        })
        a = [e for e in _provenance(repo, run_id)
             if e["decisionType"] == "assessment"][0]
        assert a["providerClaimed"] is want_claimed, reason
        assert a["providerCall"] is want_call, reason
        assert a["groundedMode"] is None
        assert a["resultStatus"] == "fallback"


def test_r4_34_assessment_llm_without_assessed_output(repo):
    """mode=llm 但无 assessed 产出物（malformed）→ providerCall 不得伪造 True。"""
    plan = _make_plan(flag=True)
    _save_definition(repo, plan)
    _seed_run(repo, plan)
    repo.complete_assessment_tx(RUN_ID, ASSESSMENT_KEY, {
        "assessmentMode": "llm", "goalResolved": True})
    a = [e for e in _provenance(repo) if e["decisionType"] == "assessment"][0]
    assert a["decisionStatus"] == "COMPLETED"
    assert a["groundedMode"] == "unknown"   # goalResolved=true 不推导 grounded
    assert a["providerCall"] is None
    assert a["providerClaimed"] is True     # llm 路径必有 claim


def test_r4_35_no_historical_recompute_no_run_level_evidence(repo):
    """§23-E/F：缺 fingerprint 绝不 read-time 重算；decision 级 evidenceRefs 缺失
    绝不用 run 级 observation refs 冒充。"""
    plan = _make_plan(flag=True)
    _save_definition(repo, plan)
    _seed_run(repo, plan)
    # run 级 observation 事件（与 assessment 决策级 refs 无关）
    _seed_observation(repo, RUN_ID, obs_type="node_failed", step_id="validate_event",
                      evidence_refs=[{"ref": "RUN_LEVEL_REF_MARKER"}])
    repo.complete_assessment_tx(RUN_ID, ASSESSMENT_KEY, {
        "assessmentStatus": "assessed", "goalAchievement": "unknown",
        "assessmentMode": "deterministic", "goalResolved": False})
    dumped = _dumps(_provenance(repo))
    assert "contextFingerprint" not in dumped and "sourceSnapshotDigest" not in dumped
    a = [e for e in _provenance(repo) if e["decisionType"] == "assessment"][0]
    assert a["evidenceRefs"] is None  # 决策级未持久化 → null，不用 run 级冒充


# ── R4-21..26：evaluation summary ──────────────────────────────────────────

def _full_report(**overrides):
    report = {
        "metadata": {"evaluationId": "eval_r4", "generatedAt": "2026-08-27T10:00:00Z",
                     "datasetVersion": "v1", "commitSha": "abc123def",
                     "provider": "deepseek", "model": "deepseek-chat"},
        "metrics": {"totalCases": 32, "passedCases": 32, "failedCases": 0,
                    "overallScore": 0.99},
        "regressionGate": {"passed": True, "failures": [], "thresholds": {
            "overall": 0.9, "safetyPolicyPassRate": 1.0}},
    }
    report.update(overrides)
    return report


def _summary(report, report_id=""):
    from backend.evaluation.summary import build_eval_summary
    return build_eval_summary(report, report_id=report_id)


def test_r4_21_eval_pass_true_mapping():
    s = _summary(_full_report(), report_id="r4_pass")
    assert s["overallStatus"] == "PASS"
    assert s["metricsStatus"] == "PASS" and s["gateStatus"] == "PASS"
    assert s["totalCases"] == 32 and s["passedCases"] == 32
    assert all(g["status"] == "PASS" for g in s["gates"])
    assert s["evaluationId"] == "eval_r4"


def test_r4_22_eval_fail_true_mapping():
    # 用例失败 → FAIL
    r = _full_report()
    r["metrics"] = {"totalCases": 32, "passedCases": 31, "failedCases": 1}
    s = _summary(r)
    assert s["overallStatus"] == "FAIL" and s["metricsStatus"] == "FAIL"
    # gate 失败 → FAIL
    r2 = _full_report()
    r2["regressionGate"] = {"passed": False, "failures": [
        {"gate": "safetyPolicyPassRate", "threshold": 1.0, "actual": 0.5}],
        "thresholds": {"overall": 0.9, "safetyPolicyPassRate": 1.0}}
    s2 = _summary(r2)
    assert s2["overallStatus"] == "FAIL" and s2["gateStatus"] == "FAIL"
    assert any(g["gateId"] == "safetyPolicyPassRate" and g["status"] == "FAIL"
               for g in s2["gates"])


def test_r4_23_missing_gate_unknown_not_pass():
    # metrics PASS 但 gate 缺失 → UNKNOWN（§16 缺失不得默认 PASS）
    r = _full_report()
    r.pop("regressionGate")
    s = _summary(r)
    assert s["overallStatus"] == "UNKNOWN" and s["gateStatus"] == "UNKNOWN"
    # 完全空 report → UNKNOWN
    assert _summary({})["overallStatus"] == "UNKNOWN"
    # totalCases 缺失 → UNKNOWN
    assert _summary({"metrics": {"passedCases": 5}})["overallStatus"] == "UNKNOWN"


def test_r4_24_commit_sha_from_report_input_not_hardcoded():
    s = _summary(_full_report())
    assert s["commitSha"] == "abc123def"
    r2 = _full_report()
    r2["metadata"]["commitSha"] = "999feed"
    assert _summary(r2)["commitSha"] == "999feed"
    # 生产代码不得硬编码任何 commit SHA（§17）
    src = open(os.path.join(os.path.dirname(__file__), "..", "evaluation", "summary.py"),
               encoding="utf-8").read()
    assert "7b97cdd" not in src


def test_r4_25_provider_model_no_secret():
    r = _full_report()
    r["metadata"]["apiKey"] = "sk-hush-r4"
    r["metadata"]["token"] = "SECRET_TOKEN"
    s = _summary(r)
    assert s["provider"] == "deepseek" and s["model"] == "deepseek-chat"
    assert "apiKey" not in s and "token" not in s
    dumped = _dumps(s)
    assert "sk-hush-r4" not in dumped and "SECRET_TOKEN" not in dumped


def test_r4_26_eval_summary_stable_ordering():
    r = _full_report()
    r["gates"] = [{"gateId": "zb", "status": "PASS", "threshold": 1.0},
                  {"gateId": "aa", "status": "PASS", "threshold": 0.9}]
    s1, s2 = _summary(r), _summary(r)
    assert _dumps(s1) == _dumps(s2)
    assert [g["gateId"] for g in s1["gates"]] == ["aa", "zb"]


# ── R4-27..30：schema 稳定 + 决策链未改动 ──────────────────────────────────

def test_r4_27_phase20_facing_json_schema_stable(repo):
    plan = _make_plan(flag=True)
    _seed_provenance_run(repo, plan)
    by_type = {e["decisionType"]: e for e in _provenance(repo)}
    common = {"decisionType", "runId", "rootRunId", "planVersion", "boundaryKey",
              "decisionStatus", "groundedMode", "groundedPlanEnabled",
              "providerCall", "providerClaimed", "evidenceRefs", "runStatus"}
    assert set(by_type["critic"].keys()) == common | {"recommendation", "confidence"}
    assert set(by_type["semantic_replan"].keys()) == common | {
        "criticBoundaryKey", "criticRecommendation", "resultStatus",
        "childRunId", "childVersion"}
    assert set(by_type["assessment"].keys()) == common | {
        "verdict", "goalResolved", "resultStatus"}
    from backend.evaluation.summary import SUMMARY_KEYS
    assert set(_summary(_full_report()).keys()) == set(SUMMARY_KEYS)


def test_r4_28_initial_planner_unchanged():
    src = open(os.path.join(os.path.dirname(__file__), "..", "planning", "planner.py"),
               encoding="utf-8").read()
    assert "decision_provenance" not in src


def test_r4_29_automatic_replan_loop_off():
    api_src = open(os.path.join(os.path.dirname(__file__), "..", "planning", "api.py"),
                   encoding="utf-8").read()
    # 唯一 explicit_replan 调用点 = /runs/{run_id}/replan 端点（Phase17 语义不变）
    assert api_src.count("explicit_replan(") == 1
    driver_src = open(os.path.join(os.path.dirname(__file__), "..", "workflow",
                                   "run_driver.py"), encoding="utf-8").read()
    assert "decision_provenance" not in driver_src


def test_r4_30_no_migration_no_frontend_no_dependency():
    repo_src = open(os.path.join(os.path.dirname(__file__), "..", "workflow",
                                 "repository.py"), encoding="utf-8").read()
    assert "decision_provenance" not in repo_src  # 无新表
    req = open(os.path.join(os.path.dirname(__file__), "..", "requirements.txt"),
               encoding="utf-8").read()
    assert "decision_provenance" not in req
    pkg = open(os.path.join(os.path.dirname(__file__), "..", "..", "frontend",
                            "package.json"), encoding="utf-8").read()
    assert "provenance" not in pkg
