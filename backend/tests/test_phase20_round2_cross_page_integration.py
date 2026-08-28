"""
Phase20 Round2 — Cross-Page Integration 后端契约测试

覆盖（验收口径 §Tests）：
  A. GET /workflow/runs?eventId= 只读过滤 0 / 1 / N（真实 list，绝不静默 latest）
  B. 无事件绑定的 run 被排除；exact match（非前缀匹配）
  C. decisionProvenance API 契约：仍只读、安全投影（白名单 key，不泄漏
     raw / 自由文本 / state 正文）
  D. Plan/run authority：run.definitionId == planId；非 Plan 定义诚实 404
  E. Evaluation summary PASS / FAIL / UNKNOWN（Phase19 R4 已覆盖回归语义，
     此处补充 Phase20 面向前端的三态契约 + null 元数据诚实）

全部测试使用 pytest tmp_path 临时数据库（monkeypatch backend.config.DB_PATH），
不触碰 trafficmind.db / rag_v2.db / vector_db。eventId 过滤本身只读。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.workflow.models import (
    DefinitionStatus,
    NodeType,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowRun,
    WorkflowRunStatus,
)
from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables

# ── 常量 ─────────────────────────────────────────────────────────────
EVENT_A = "evt-phase20-A"
EVENT_B = "evt-phase20-B"
EVENT_C = "evt-phase20-C"
PLAN_ID = "plan_phase20_r2"
ROOT = "p20_root_run"
RUN_ID = "p20_parent_run"
CHILD_ID = "p20_child_run"
VERSION = 1
OBS_TYPE = "tool_failed"
STEP_ID = "action_sim"

CRITIC_KEY = f"{ROOT}:{RUN_ID}:{VERSION}:{OBS_TYPE}:{STEP_ID}"
SEMANTIC_KEY = f"{ROOT}:{RUN_ID}:{VERSION}:{STEP_ID}:{OBS_TYPE}"
ASSESSMENT_KEY = f"{ROOT}:{RUN_ID}:{VERSION}"

# provenance 白名单（Phase19 R4 §12 + Phase20 R2 主层/技术层字段）
PROVENANCE_ALLOWED_KEYS = {
    "decisionType", "runId", "rootRunId", "planVersion", "boundaryKey",
    "decisionStatus", "groundedMode", "groundedPlanEnabled", "providerCall",
    "providerClaimed", "evidenceRefs", "runStatus",
    # critic
    "recommendation", "confidence",
    # semantic replan
    "criticBoundaryKey", "criticRecommendation", "resultStatus",
    "childRunId", "childVersion",
    # assessment
    "verdict", "goalResolved",
}

# 自由文本哨兵（seed 时写入 provider 产出物，断言绝不出现在投影中）
FREE_TEXT_SENTINELS = ("LLM_FREE_TEXT_REASON", "LLM_FREE_TEXT_TYPE",
                       "LLM_FREE_TEXT_ASSESS_REASON", "RAW_LLM_INTENT")


# ── fixtures ─────────────────────────────────────────────────────────

@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """每测试独立临时 DB（写隔离），复刻 Phase19 R4 模式。"""
    test_db = str(tmp_path / "test_phase20_r2.db")
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    init_workflow_tables()
    return SQLiteWorkflowRepository()


def _api_client(repo, monkeypatch):
    """workflow API 最小 TestClient（无 lifespan，repo 已打补丁）。"""
    import backend.workflow.api as workflow_api
    monkeypatch.setattr(workflow_api, "_repo", repo)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(workflow_api.router)
    return TestClient(app)


def _planning_api_client(repo, monkeypatch):
    import backend.planning.api as planning_api
    monkeypatch.setattr(planning_api, "_repo", repo)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(planning_api.router)
    return TestClient(app)


def _save_run(repo, run_id, event_id=None, definition_id="def_plain",
              status=WorkflowRunStatus.PENDING, state_extra=None):
    """按生产 binding 形状写入 run：state_json 内 $.currentEvent.eventId。"""
    state = dict(state_extra or {})
    if event_id is not None:
        state["currentEvent"] = {"eventId": event_id}
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=definition_id,
                              version=1, status=status, state=state))
    return run_id


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
        planId=PLAN_ID, planFingerprint="fp_p20r2", goal="R2 跨页集成目标",
        goalType=GoalType.SIMULATION_EVALUATION,
        definitionStatus=PlanDefinitionStatus.ACTIVE, version=VERSION, steps=steps,
    )
    plan.semanticReplanEnabled = True
    plan.groundedDecisionContextEnabled = flag
    return plan


def _save_plan_definition(repo, plan):
    from backend.workflow.definition import DefinitionManager
    definition = WorkflowDefinition(
        id=plan.planId, name=plan.goal, status=DefinitionStatus.ACTIVE,
        metadata={"plan": plan.to_dict()},
    )
    repo.save_definition(definition)
    DefinitionManager(repo).create_version(definition, changelog="seed")


def _seed_provenance_run(repo, plan):
    """critic COMPLETED + semantic COMPLETED + assessment COMPLETED 完整父 run。"""
    _save_plan_definition(repo, plan)
    from backend.planning.budget import new_lineage, set_lineage
    st = {}
    set_lineage(st, new_lineage(ROOT))
    repo.save_run(WorkflowRun(run_id=RUN_ID, definition_id=PLAN_ID, version=VERSION,
                              status=WorkflowRunStatus.FAILED, state=st))
    # critic（带自由文本 reasonSummary → 投影必须剥除）
    assert repo.claim_critic_invocation_tx(RUN_ID, CRITIC_KEY)["result"] == "claimed"
    repo.complete_critic_invocation_tx(RUN_ID, CRITIC_KEY, {
        "recommendation": "replan", "confidence": 0.85,
        "reasonSummary": "LLM_FREE_TEXT_REASON", "semanticFailureType": "LLM_FREE_TEXT_TYPE",
    })
    # semantic replan（raw provider 产出物 → 投影必须剥除）
    assert repo.claim_semantic_replan_tx(RUN_ID, SEMANTIC_KEY)["result"] == "claimed"
    repo.complete_semantic_replan_tx(RUN_ID, SEMANTIC_KEY, {
        "raw": {"suffixSteps": [{"proposalStepId": "s1", "intent": "RAW_LLM_INTENT"}]},
    })
    # assessment（自由文本 reason → 投影必须剥除）
    repo.complete_assessment_tx(RUN_ID, ASSESSMENT_KEY, {
        "assessmentStatus": "assessed", "goalAchievement": "achieved",
        "assessmentMode": "llm", "goalResolved": True, "confidence": 0.9,
        "assessmentReason": "LLM_FREE_TEXT_ASSESS_REASON", "assessmentModel": "deepseek-chat",
    })
    # child 指针 + observation 证据
    st = repo.get_run(RUN_ID).state
    st["replannedToRunId"] = CHILD_ID
    repo.save_run(WorkflowRun(run_id=RUN_ID, definition_id=PLAN_ID, version=VERSION,
                              status=WorkflowRunStatus.FAILED, state=st))
    repo.save_run(WorkflowRun(run_id=CHILD_ID, definition_id=PLAN_ID, version=2,
                              status=WorkflowRunStatus.PENDING,
                              state={"executionLineage": {"rootRunId": ROOT}}))
    repo.save_event(WorkflowEvent(
        event_id="wfevent_obs_p20", run_id=RUN_ID, event_type="observation_recorded",
        payload={"observationId": "obs_p20", "planId": PLAN_ID, "planVersion": VERSION,
                 "runId": RUN_ID, "type": OBS_TYPE, "status": "failure",
                 "scope": "run", "source": "system",
                 "timestamp": "2026-08-28T00:00:00Z", "stepId": STEP_ID,
                 "confidence": 0.5, "evidenceRefs": ["ref-1", "ref-2"],
                 "failureCode": "tool_error",
                 "failureReason": "LLM_FREE_TEXT_FAILURE", "metadata": {}},
        sequence=0))
    return repo.get_run(RUN_ID)


def _provenance(repo, run_id=RUN_ID):
    from backend.planning.decision_provenance import build_decision_provenance
    return build_decision_provenance(repo.get_run(run_id), repo)


# ═══════════════════════════════════════════════════════════════════════════════
# A. eventId 过滤 0 / 1 / N
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventIdFilter:
    def test_event_a_two_runs_b_one_c_zero(self, repo):
        """A→2 runs，B→1，C→0；返回真实 list（绝不静默 latest）。"""
        _save_run(repo, "a1", event_id=EVENT_A)
        _save_run(repo, "a2", event_id=EVENT_A)
        _save_run(repo, "b1", event_id=EVENT_B)

        res = repo.list_runs(event_id=EVENT_A, limit=200)
        assert sorted(r.run_id for r in res) == ["a1", "a2"]
        assert repo.count_runs(event_id=EVENT_A) == 2

        assert [r.run_id for r in repo.list_runs(event_id=EVENT_B, limit=200)] == ["b1"]
        assert repo.count_runs(event_id=EVENT_B) == 1

        assert repo.list_runs(event_id=EVENT_C, limit=200) == []
        assert repo.count_runs(event_id=EVENT_C) == 0

    def test_api_endpoint_accepts_event_id_param(self, repo, monkeypatch):
        """GET /workflow/runs?event_id= 端到端只读链路。"""
        _save_run(repo, "a1", event_id=EVENT_A)
        _save_run(repo, "a2", event_id=EVENT_A)
        _save_run(repo, "b1", event_id=EVENT_B)
        client = _api_client(repo, monkeypatch)
        resp = client.get(f"/workflow/runs?event_id={EVENT_A}&limit=200")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert sorted(r["runId"] for r in body["runs"]) == ["a1", "a2"]

    def test_empty_param_means_no_filter(self, repo):
        """event_id 为空字符串 → 不过滤（与现有 session_id/definition_id 语义一致）。"""
        _save_run(repo, "a1", event_id=EVENT_A)
        _save_run(repo, "plain1")  # 无事件绑定
        assert repo.count_runs(event_id="") == 2

    def test_malformed_state_json_ignored_by_event_id_filter(self, repo):
        """malformed state_json 不应让 event_id filter 500；仅命中合法绑定数据。"""
        _save_run(repo, "valid", event_id=EVENT_A)
        import backend.config as cfg
        conn = sqlite3.connect(cfg.DB_PATH)
        conn.execute(
            """INSERT INTO workflow_runs (
                run_id, definition_id, version, status, state_json,
                started_at, updated_at, completed_at, triggered_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("malformed", "def_plain", 1, "pending", "not json",
             "", "2099-01-01T00:00:00Z", "", "test"),
        )
        conn.commit()
        conn.close()

        assert [r.run_id for r in repo.list_runs(event_id=EVENT_A, limit=200)] == ["valid"]
        assert repo.count_runs(event_id=EVENT_A) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# B. 无绑定 run 排除 + exact match
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventBindingTruthfulness:
    def test_run_without_current_event_excluded(self, repo):
        """无 currentEvent / 有 currentEvent 但无 eventId 的 run 一律排除。"""
        _save_run(repo, "bound", event_id=EVENT_A)
        _save_run(repo, "no_state")  # state={}
        _save_run(repo, "no_event_id", state_extra={"currentEvent": {"roadName": "中山路"}})
        _save_run(repo, "null_event", state_extra={"currentEvent": None})

        assert repo.count_runs(event_id=EVENT_A) == 1
        ids = [r.run_id for r in repo.list_runs(event_id=EVENT_A, limit=200)]
        assert ids == ["bound"]

    def test_exact_match_not_prefix(self, repo):
        """"evt-A" 不得匹配 "evt-A-suffix"（exact match 语义）。"""
        _save_run(repo, "exact", event_id=EVENT_A)
        _save_run(repo, "suffix", event_id=EVENT_A + "-suffix")
        _save_run(repo, "prefix", event_id="x-" + EVENT_A)

        ids = [r.run_id for r in repo.list_runs(event_id=EVENT_A, limit=200)]
        assert ids == ["exact"]
        assert repo.count_runs(event_id=EVENT_A) == 1

    def test_filter_composes_with_status_and_definition(self, repo):
        """event_id 与 status / definition_id 组合过滤仍正确。"""
        _save_run(repo, "a_done", event_id=EVENT_A, definition_id="def1",
                  status=WorkflowRunStatus.COMPLETED)
        _save_run(repo, "a_pending", event_id=EVENT_A, definition_id="def1",
                  status=WorkflowRunStatus.PENDING)
        _save_run(repo, "a_other_def", event_id=EVENT_A, definition_id="def2",
                  status=WorkflowRunStatus.COMPLETED)

        res = repo.list_runs(event_id=EVENT_A, definition_id="def1",
                             status="completed", limit=200)
        assert [r.run_id for r in res] == ["a_done"]


# ═══════════════════════════════════════════════════════════════════════════════
# C. decisionProvenance 契约：只读 + 安全投影
# ═══════════════════════════════════════════════════════════════════════════════

class TestDecisionProvenanceContract:
    def test_unseeded_run_honest_empty(self, repo):
        plan = _make_plan()
        _save_plan_definition(repo, plan)
        _save_run(repo, "fresh", definition_id=PLAN_ID)
        assert _provenance(repo, "fresh") == []

    def test_full_seed_stable_order_and_whitelist(self, repo):
        plan = _make_plan(flag=True)
        _seed_provenance_run(repo, plan)
        entries = _provenance(repo)
        assert [e["decisionType"] for e in entries] == [
            "critic", "semantic_replan", "assessment"]
        for e in entries:
            assert set(e.keys()) <= PROVENANCE_ALLOWED_KEYS, \
                f"非法投影字段: {set(e.keys()) - PROVENANCE_ALLOWED_KEYS}"

    def test_no_free_text_no_raw_leak(self, repo):
        """provider 自由文本 / raw 产出物 / failureReason 绝不进入投影。"""
        plan = _make_plan(flag=True)
        _seed_provenance_run(repo, plan)
        dump = json.dumps(_provenance(repo), ensure_ascii=False)
        for sentinel in FREE_TEXT_SENTINELS:
            assert sentinel not in dump, f"泄漏自由文本: {sentinel}"
        assert "LLM_FREE_TEXT_FAILURE" not in dump  # failureReason 正文
        # state 正文绝不内嵌（投影是逐字段白名单构造，无嵌套 dict 自由文本）
        for e in _provenance(repo):
            for v in e.values():
                if isinstance(v, dict):
                    raise AssertionError(f"投影含嵌套 dict: {v}")

    def test_read_twice_stable_no_persistence_write(self, repo):
        """读取侧两次调用字节一致，且 run 状态/state 不被读取改动。"""
        plan = _make_plan(flag=True)
        _seed_provenance_run(repo, plan)
        before = repo.get_run(RUN_ID)
        e1 = _provenance(repo)
        e2 = _provenance(repo)
        assert json.dumps(e1, sort_keys=True) == json.dumps(e2, sort_keys=True)
        after = repo.get_run(RUN_ID)
        assert before.status == after.status
        assert before.state == after.state
        assert before.updated_at == after.updated_at

    def test_api_endpoint_projection_safe(self, repo, monkeypatch):
        """GET /workflow/runs/{id} → decisionProvenance 为安全投影。"""
        plan = _make_plan(flag=True)
        _seed_provenance_run(repo, plan)
        client = _api_client(repo, monkeypatch)
        resp = client.get(f"/workflow/runs/{RUN_ID}")
        assert resp.status_code == 200
        prov = resp.json()["decisionProvenance"]
        assert [e["decisionType"] for e in prov] == [
            "critic", "semantic_replan", "assessment"]
        prov_dump = json.dumps(prov, ensure_ascii=False)
        for sentinel in FREE_TEXT_SENTINELS:
            assert sentinel not in prov_dump
        for e in prov:
            assert set(e.keys()) <= PROVENANCE_ALLOWED_KEYS


# ═══════════════════════════════════════════════════════════════════════════════
# D. Plan/run authority：run.definitionId == planId
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlanRunAuthority:
    def test_plan_definition_metadata_is_authority(self, repo):
        """definition.metadata.plan 可反序列化且 planId == definition id。"""
        plan = _make_plan()
        _save_plan_definition(repo, plan)
        from backend.planning.api import _load_plan_from_metadata
        loaded = _load_plan_from_metadata(repo.get_definition(PLAN_ID).metadata)
        assert loaded is not None
        assert loaded.planId == PLAN_ID

    def test_non_plan_definition_honest_not_plan(self, repo):
        """无 plan 元数据的 definition → 不是 Plan（前端「该定义不是 Plan」路径）。"""
        repo.save_definition(WorkflowDefinition(
            id="def_plain", name="普通定义", status=DefinitionStatus.ACTIVE,
            metadata={}))
        from backend.planning.api import _load_plan_from_metadata
        assert _load_plan_from_metadata(
            repo.get_definition("def_plain").metadata) is None

    def test_run_definition_id_binds_to_plan_id(self, repo):
        """run.definitionId == planId 是唯一 authority；list_runs 按此绑定。"""
        plan = _make_plan()
        _save_plan_definition(repo, plan)
        _save_run(repo, "p_run", definition_id=PLAN_ID,
                  status=WorkflowRunStatus.RUNNING)
        run = repo.get_run("p_run")
        assert run.definition_id == PLAN_ID
        res = repo.list_runs(definition_id=PLAN_ID, limit=200)
        assert [r.run_id for r in res] == ["p_run"]

    def test_api_plan_404_for_non_plan_definition(self, repo, monkeypatch):
        """GET /planning/plans/{id}：plan 定义 200；普通定义 400（存在但无 plan
        元数据，不 fallback 猜 Plan）；完全不存在 404。"""
        plan = _make_plan()
        _save_plan_definition(repo, plan)
        repo.save_definition(WorkflowDefinition(
            id="def_plain", name="普通定义", status=DefinitionStatus.ACTIVE,
            metadata={}))
        client = _planning_api_client(repo, monkeypatch)
        assert client.get(f"/planning/plans/{PLAN_ID}").status_code == 200
        resp = client.get("/planning/plans/def_plain")
        assert resp.status_code == 400  # 存在但不是 Plan（缺 plan 元数据）
        assert client.get("/planning/plans/not_exists_at_all").status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# E. Evaluation summary PASS / FAIL / UNKNOWN（Phase20 面向前端契约）
# ═══════════════════════════════════════════════════════════════════════════════

class TestEvalSummaryFacingContract:
    def _summary(self, report, report_id="r2"):
        from backend.evaluation.summary import build_eval_summary
        return build_eval_summary(report, report_id=report_id)

    def test_pass_report(self):
        s = self._summary({
            "metrics": {"totalCases": 4, "passedCases": 4, "failedCases": 0,
                        "overallScore": 0.95},
            "regressionGate": {"passed": True,
                               "thresholds": {"overallScore": 0.9},
                               "failures": []},
        })
        assert s["overallStatus"] == "PASS"
        assert s["metricsStatus"] == "PASS"
        assert s["gateStatus"] == "PASS"

    def test_fail_report_fail_closed(self):
        """gate FAIL → overall FAIL（fail-closed，即使 metrics 全过）。"""
        s = self._summary({
            "metrics": {"totalCases": 4, "passedCases": 4, "failedCases": 0},
            "regressionGate": {"passed": False,
                               "thresholds": {"overallScore": 0.9},
                               "failures": [{"gate": "overallScore",
                                             "threshold": 0.9, "actual": 0.82}]},
        })
        assert s["gateStatus"] == "FAIL"
        assert s["overallStatus"] == "FAIL"

    def test_failed_cases_force_fail(self):
        s = self._summary({
            "metrics": {"totalCases": 4, "passedCases": 3, "failedCases": 1},
            "regressionGate": {"passed": True,
                               "thresholds": {"overallScore": 0.9},
                               "failures": []},
        })
        assert s["metricsStatus"] == "FAIL"
        assert s["overallStatus"] == "FAIL"

    def test_unknown_report(self):
        """空 report → UNKNOWN（绝不默认 PASS）。"""
        s = self._summary({})
        assert s["overallStatus"] == "UNKNOWN"
        assert s["metricsStatus"] == "UNKNOWN"
        assert s["gateStatus"] == "UNKNOWN"
        assert s["gates"] == []

    def test_null_metadata_honest_no_hardcode(self):
        """generatedAt/commitSha/provider/model 缺失 → None（前端显示 未记录）。"""
        s = self._summary({
            "metrics": {"totalCases": 2, "passedCases": 2, "failedCases": 0},
            "regressionGate": {"passed": True, "thresholds": {}, "failures": []},
        })
        assert s["generatedAt"] is None
        assert s["commitSha"] is None
        assert s["provider"] is None
        assert s["model"] is None

    def test_summary_key_order_stable(self):
        """SUMMARY_KEYS 固定键序（Phase20 前端契约）。"""
        from backend.evaluation.summary import SUMMARY_KEYS
        assert list(self._summary({}).keys()) == list(SUMMARY_KEYS)
