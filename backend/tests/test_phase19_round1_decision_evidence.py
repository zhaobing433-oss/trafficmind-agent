"""
Phase19 Round1 — Decision Evidence Contract 验收（R1-01 … R1-32）

覆盖：
  契约模型 R1-01..R1-06 / 归一化与 allowlist R1-07..R1-14 /
  排名与预算 R1-15..R1-20 / digest 与 fingerprint R1-21..R1-26 /
  Observation 富化与 legacy 冻结 R1-27..R1-30 / flag 与安全性 R1-31..R1-32

本轮**不**验证 grounded Critic / Assessment / Replanner 行为（属 R2/R3）。
"""

from __future__ import annotations

import json
import os
import random
import sys
from typing import Any, Dict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.planning import evidence_refs as ev
from backend.planning.context import build_planning_context
from backend.planning.context_assembler import (
    ALL_SOURCE_TYPES,
    EXCLUDED_FIELDS,
    SOURCE_ACTION,
    SOURCE_APPROVAL,
    SOURCE_MEMORY,
    SOURCE_NODE_RUN,
    SOURCE_POLICY_AUDIT,
    SOURCE_RAG_TRACE,
    assemble_decision_context,
    assemble_or_empty,
    collect_source_projections,
    pack_evidence,
    rank_projections,
)
from backend.planning.decision_context import (
    ContextBudget,
    DECISION_BUDGET_CHARS,
    DecisionType,
    EvidenceRef,
    FreeText,
    SourceProjection,
    TRUST_ORDINAL,
    TrustClass,
    UNTRUSTED_TRUST_CLASSES,
    canonical_json,
    compute_context_fingerprint,
    compute_source_snapshot_digest,
    content_hash,
    empty_decision_context,
    fingerprint_projection,
    prompt_projection,
)
from backend.planning.models import Plan, PlanDefinitionStatus
from backend.planning.planner import build_plan
from backend.planning.observation import (
    Observation,
    ObservationScope,
    ObservationSource,
    ObservationStatus,
    ObservationType,
)
from backend.workflow.models import (
    ActionStatus,
    ApprovalDecision,
    DefinitionStatus,
    NodeStatus,
    NodeType,
    WorkflowActionRecord,
    WorkflowApproval,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowRunStatus,
)

FIXTURE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "fixtures", "phase19_phase18_golden_prompts.json")

#: 用于验证「正文绝不入 prompt」的 RAG 大正文哨兵
RAG_BODY_SENTINEL = "RAG_BODY_SENTINEL_" + ("x" * 4000)
#: 用于验证「secret 绝不入 prompt」的动作参数哨兵
SECRET_SENTINEL = "SECRET_WEBHOOK_TOKEN_SENTINEL"
#: 用于验证「memory 原文绝不入 prompt」的哨兵
MEMORY_SENTINEL = "MEMORY_BODY_SENTINEL_" + ("y" * 600)


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "DB_PATH", str(tmp_path / "test_p19r1.db"))
    from backend.workflow.repository import init_workflow_tables
    init_workflow_tables()
    yield


@pytest.fixture()
def repo():
    from backend.workflow.repository import SQLiteWorkflowRepository
    return SQLiteWorkflowRepository()


def _plan(repo, grounded: bool = False) -> Plan:
    ev_payload = {"eventId": "E_R1", "eventType": "accident", "roadName": "A路",
                  "avgSpeed": 8, "queueLength": 200, "duration": 900, "nearbyHospital": True}
    plan = build_plan(build_planning_context(ev_payload))
    plan.definitionStatus = PlanDefinitionStatus.ACTIVE
    plan.semanticReplanEnabled = True
    plan.groundedDecisionContextEnabled = grounded
    repo.save_definition(WorkflowDefinition(id=plan.planId, name=plan.goal,
                                            status=DefinitionStatus.ACTIVE,
                                            metadata={"plan": plan.to_dict()}))
    return plan


def _rich_state(failed_node: str) -> Dict[str, Any]:
    """覆盖全部 12 类 source 的 state_json（含 secret / 大正文哨兵）。"""
    from backend.planning.budget import new_lineage, set_lineage
    state: Dict[str, Any] = {
        # nodeOutputs 保存的是节点 handler 的**原始返回值**（executor.py:860），
        # 因此这里必须复刻真实形状，而不是玩具值 —— 否则 allowlist 测不出来。
        "nodeOutputs": {
            "validate_event": {"ok": True},
            "rag_retrieve": {"rag_context": {
                "query": "事故 A路 处置预案", "resultCount": 1, "traceId": "trace_abc",
                "degraded": False,
                "results": [{"chunk_id": "chunk_1", "document_id": "doc_1",
                             "content": RAG_BODY_SENTINEL}]}},
            "memory_context": {"memory_context": {
                "recallCount": 2, "sessionGoal": MEMORY_SENTINEL,
                "stableFacts": [{"memoryKey": "k", "value": MEMORY_SENTINEL}]}},
            # 通用 action 分支会把整个 params 回填进 result（action.py:547-552）
            failed_node: {"action_id": "act_1", "action_type": "adjust_signal",
                          "status": "failed", "params": {"webhook": SECRET_SENTINEL},
                          "result": {"params": {"webhook": SECRET_SENTINEL}},
                          "error": "post to https://qyapi.weixin.qq.com/send?key=" + SECRET_SENTINEL},
        },
        "agentOutputs": {"CongestionAgent": {"summary": "主干道拥堵加剧",
                                             "evidenceRefs": [], "recordedAt": "2026-01-01T00:00:01Z"}},
        "riskAssessment": {"riskScore": 88, "riskLevel": "重大风险",
                           "riskReasons": ["医院邻近", "队列超长"]},
        "auditEvents": [
            {"eventType": "tool_denied", "nodeId": failed_node,
             "payload": {"decision": "deny", "riskLevel": "高", "actionType": "adjust_signal",
                         "reason": "自由文本原因不应进入 T0"},
             "timestamp": "2026-01-01T00:00:02Z"},
            {"eventType": "node_started", "nodeId": "validate_event", "payload": {},
             "timestamp": "2026-01-01T00:00:00Z"},
        ],
        "ragContext": {"query": "事故处置", "results": [
            {"chunk_id": "chunk_1", "document_id": "doc_1", "content": RAG_BODY_SENTINEL}]},
        "ragTraceIds": ["trace_abc"],
        "memoryContext": {"provenance": [
            {"memoryId": "m1", "memoryType": "constraint", "summary": "长" * 900}]},
        "simulationRefs": {"simulationRunId": "sim_1", "trafficEventId": "E_R1",
                           "latestSnapshotId": "snap_1"},
        "errors": [{"nodeId": failed_node, "attempt": 1, "error": "tool timeout",
                    "timestamp": "2026-01-01T00:00:03Z"}],
        "currentNode": failed_node,
    }
    set_lineage(state, new_lineage("r1_run"))
    return state


def _seed(repo, plan: Plan, run_id: str = "r1_run",
          status: WorkflowRunStatus = WorkflowRunStatus.FAILED) -> WorkflowRun:
    """构造覆盖 12 类 source 的完整 run。"""
    failed = next(s.stepId for s in plan.steps if s.stepType == NodeType.ACTION)
    state = _rich_state(failed)
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=plan.planId,
                              version=plan.version, status=status, state=state))
    for i, s in enumerate(plan.steps[:3]):
        repo.save_node_run(WorkflowNodeRun(node_run_id=f"nr_ok{i}", run_id=run_id,
                                           node_id=s.stepId, node_type=s.stepType,
                                           status=NodeStatus.SUCCEEDED,
                                           completed_at=f"2026-01-01T00:00:0{i}Z"))
    repo.save_node_run(WorkflowNodeRun(node_run_id="nr_fail", run_id=run_id, node_id=failed,
                                       node_type=NodeType.ACTION, status=NodeStatus.FAILED,
                                       error="tool timeout", attempt=2,
                                       completed_at="2026-01-01T00:00:09Z"))
    repo.save_event(WorkflowEvent(event_id="evt_1", run_id=run_id, node_id=failed,
                                  event_type="node_failed", payload={"x": 1}, sequence=1))
    repo.save_approval(WorkflowApproval(approval_id="ap_1", run_id=run_id, node_id=failed,
                                        decision=ApprovalDecision.REJECTED,
                                        reviewer="张三", comment="审批人自由文本不应外泄",
                                        decided_at="2026-01-01T00:00:05Z"))
    repo.save_action_record(WorkflowActionRecord(
        action_id="act_1", run_id=run_id, node_id=failed, action_type="adjust_signal",
        idempotency_key="idem_1", params={"webhook": SECRET_SENTINEL},
        result={"ok": False}, status=ActionStatus.FAILED, error="tool timeout"))
    return repo.get_run(run_id)


def _ctx(repo, plan, run, decision=DecisionType.CRITIC, observation=None):
    return assemble_decision_context(repo, run, plan, observation, decision)


def _rendered(ctx) -> str:
    """模型实际可见内容（prompt_projection 的序列化形式）。"""
    return json.dumps(prompt_projection(ctx), ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════════════════════
# 契约模型 R1-01 … R1-06
# ═══════════════════════════════════════════════════════════════════════════════


class TestContractModel:
    def test_r1_01_trust_ordering_and_untrusted_set(self):
        """T0 是唯一 trusted；T1-T4 全部 untrusted，序数单调。"""
        assert TrustClass.T0_SYSTEM not in UNTRUSTED_TRUST_CLASSES
        assert set(UNTRUSTED_TRUST_CLASSES) == {
            TrustClass.T1_TOOL, TrustClass.T2_AGENT,
            TrustClass.T3_KNOWLEDGE, TrustClass.T4_EXTERNAL}
        ordinals = [TRUST_ORDINAL[t] for t in (
            TrustClass.T0_SYSTEM, TrustClass.T1_TOOL, TrustClass.T2_AGENT,
            TrustClass.T3_KNOWLEDGE, TrustClass.T4_EXTERNAL)]
        assert ordinals == sorted(ordinals) == [0, 1, 2, 3, 4]

    def test_r1_02_ref_roundtrip_and_validation(self):
        """namespaced ref 可解析、可往返；非法 namespace 被拒。"""
        ref = ev.node_ref("run1", "step_3")
        assert ev.parse_ref(ref) == (ev.NS_NODE, "run1:step_3")
        assert ev.ref_namespace(ref) == ev.NS_NODE
        assert ev.is_valid_ref(ref) and not ev.is_valid_ref("bogus:x")
        assert not ev.is_valid_ref("noNamespace")
        with pytest.raises(ValueError):
            ev.make_ref("not_a_namespace", "k")
        with pytest.raises(ValueError):
            ev.make_ref(ev.NS_NODE)

    def test_r1_03_error_ref_keyed_on_node_attempt_not_index(self):
        """errors 重排不改变 ref —— 不得使用 list index。"""
        a = ev.error_ref("run1", "step_a", 1)
        b = ev.error_ref("run1", "step_b", 1)
        assert a != b
        assert a == ev.error_ref("run1", "step_a", 1)
        assert ev.error_ref("run1", "step_a", 2) != a

    def test_r1_04_canonical_json_key_order_independent(self):
        """canonical_json 与 dict 插入序无关；content_hash 随之稳定。"""
        assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
        assert content_hash({"b": 1, "a": 2}) == content_hash({"a": 2, "b": 1})
        assert content_hash({"a": 1}) != content_hash({"a": 2})
        assert "中文" in canonical_json({"k": "中文"})  # ensure_ascii=False

    def test_r1_05_budget_totals_and_subcaps(self):
        """每决策点总预算固定；T1-T4 有子预算，T0 不受限。"""
        for dt, total in DECISION_BUDGET_CHARS.items():
            b = ContextBudget.for_decision(dt)
            assert b.totalChars == total
            assert b.cap_for(TrustClass.T0_SYSTEM) == total
            for t in UNTRUSTED_TRUST_CLASSES:
                assert 0 < b.cap_for(t) < total
        b = ContextBudget.for_decision(DecisionType.CRITIC)
        assert b.cap_for(TrustClass.T1_TOOL) > b.cap_for(TrustClass.T3_KNOWLEDGE)

    def test_r1_06_empty_context_is_degraded_not_error(self):
        """空上下文等价 Phase18 行为，且可安全 project。"""
        ctx = empty_decision_context(DecisionType.CRITIC, run_id="r", plan_id="p")
        assert ctx.isEmpty and ctx.executionEvidence == () and ctx.observation is None
        assert ctx.sourceSnapshotDigest == ""
        assert prompt_projection(ctx)["executionEvidence"] == []
        assert compute_context_fingerprint(ctx)  # 不抛异常


# ═══════════════════════════════════════════════════════════════════════════════
# 归一化与 allowlist R1-07 … R1-14
# ═══════════════════════════════════════════════════════════════════════════════


class TestNormalizers:
    def test_r1_07_all_twelve_sources_declared_in_provenance(self, repo):
        """12 类 source 全部出现在 contextProvenance（可归因）。"""
        plan = _plan(repo)
        ctx = _ctx(repo, plan, _seed(repo, plan))
        declared = {p["sourceType"] for p in ctx.contextProvenance if "sourceType" in p}
        assert declared == set(ALL_SOURCE_TYPES)
        assert len(ALL_SOURCE_TYPES) == 12
        collected = {p.sourceType for p in collect_source_projections(repo, _seed(repo, plan))}
        # 本 fixture 覆盖到的实际 source 类型（error/policy/rag/memory/sim 均已 seed）
        assert collected >= {SOURCE_NODE_RUN, SOURCE_ACTION, SOURCE_APPROVAL,
                             SOURCE_POLICY_AUDIT, SOURCE_RAG_TRACE, SOURCE_MEMORY}

    def test_r1_08_action_params_never_normalized(self, repo):
        """action 归一化绝不读取 params_json（secret 边界）。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        for p in collect_source_projections(repo, run):
            assert SECRET_SENTINEL not in canonical_json(dict(p.normalizedFields))
        assert SECRET_SENTINEL not in _rendered(_ctx(repo, plan, run))

    def test_r1_09_rag_body_never_enters_context(self, repo):
        """RAG 正文永不进入 normalizedFields / prompt。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        projections = collect_source_projections(repo, run)
        rag = [p for p in projections if p.sourceType == SOURCE_RAG_TRACE]
        assert rag, "fixture 应包含 rag trace"
        for p in rag:
            assert "RAG_BODY_SENTINEL" not in canonical_json(dict(p.normalizedFields))
        assert "RAG_BODY_SENTINEL" not in _rendered(_ctx(repo, plan, run))

    def test_r1_10_approval_reviewer_and_comment_excluded(self, repo):
        """审批人姓名与意见不进入决策上下文。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        approvals = [p for p in collect_source_projections(repo, run)
                     if p.sourceType == SOURCE_APPROVAL]
        assert approvals
        for p in approvals:
            assert p.trustClass == TrustClass.T0_SYSTEM
            assert set(p.normalizedFields) == {"approvalId", "decision", "decidedAt"}
        rendered = _rendered(_ctx(repo, plan, run))
        assert "张三" not in rendered and "审批人自由文本" not in rendered

    def test_r1_11_policy_audit_is_t0_without_free_text(self, repo):
        """ToolPolicy 痕迹为 T0，且丢弃自由文本 reason。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        pol = [p for p in collect_source_projections(repo, run)
               if p.sourceType == SOURCE_POLICY_AUDIT]
        assert len(pol) == 1, "只应收录 policy 类 auditEvent"
        assert pol[0].trustClass == TrustClass.T0_SYSTEM
        assert pol[0].normalizedFields["decision"] == "deny"
        assert "自由文本原因" not in canonical_json(dict(pol[0].normalizedFields))

    def test_r1_12_node_run_trust_splits_on_error(self, repo):
        """无 error 的 node_run 为 T0；含 error 文本者降为 T1。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        nrs = [p for p in collect_source_projections(repo, run) if p.sourceType == SOURCE_NODE_RUN]
        ok = [p for p in nrs if "error" not in p.normalizedFields]
        bad = [p for p in nrs if "error" in p.normalizedFields]
        assert ok and bad
        assert all(p.trustClass == TrustClass.T0_SYSTEM for p in ok)
        assert all(p.trustClass == TrustClass.T1_TOOL for p in bad)

    def test_r1_13_memory_projection_is_bounded(self, repo):
        """Memory 只保留短投影（≤200 字符），不搬运原文。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        mem = [p for p in collect_source_projections(repo, run) if p.sourceType == SOURCE_MEMORY]
        assert mem
        for p in mem:
            assert len(p.normalizedFields["textProjection"]) <= 200
            assert p.trustClass == TrustClass.T3_KNOWLEDGE

    def test_r1_09b_node_output_shape_allowlist(self, repo):
        """CR 回归：nodeOutputs 承载 handler 原始返回值，必须按形状 allowlist 投影。

        修复前：整体 json.dumps + 截断 400 字 → RAG 正文 / memory 原文 / 回填的
        action params 全部以 T1_TOOL 进入上下文，绕过 T3 子预算与 params 排除。
        """
        from backend.planning.context_assembler import SOURCE_NODE_OUTPUT, project_node_output

        plan = _plan(repo)
        run = _seed(repo, plan)
        outs = {p.normalizedFields["nodeId"]: p
                for p in collect_source_projections(repo, run)
                if p.sourceType == SOURCE_NODE_OUTPUT}

        rag = outs["rag_retrieve"]
        assert rag.trustClass == TrustClass.T3_KNOWLEDGE, "RAG 输出必须归为 T3"
        assert rag.normalizedFields == {"nodeId": "rag_retrieve", "kind": "rag",
                                        "resultCount": 1, "traceId": "trace_abc",
                                        "degraded": False}

        mem = outs["memory_context"]
        assert mem.normalizedFields == {"nodeId": "memory_context", "kind": "memory",
                                        "recallCount": 2}

        # 未知形状 → 只保留键名，不搬运取值
        fields, trust = project_node_output("weird", {"secret_blob": SECRET_SENTINEL})
        assert fields == {"nodeId": "weird", "kind": "opaque", "outputKeys": ["secret_blob"]}
        assert SECRET_SENTINEL not in canonical_json(fields)

        # 1000 个未知键 → 固定上限、词典序、确定性、只保留键名
        many = {f"k{i:04d}": {"v": SECRET_SENTINEL} for i in range(1000)}
        f1, _ = project_node_output("weird", many)
        f2, _ = project_node_output("weird", dict(reversed(list(many.items()))))
        assert f1["keysTruncated"] is True
        assert len(f1["outputKeys"]) == 32
        assert f1["outputKeys"] == f2["outputKeys"] == sorted(f1["outputKeys"])
        assert f1["outputKeys"] == [f"k{i:04d}" for i in range(32)]
        assert SECRET_SENTINEL not in canonical_json(f1)

        # 端到端：三类哨兵均不出现在模型可见内容中
        rendered = _rendered(_ctx(repo, plan, run))
        for sentinel in ("RAG_BODY_SENTINEL", "MEMORY_BODY_SENTINEL", SECRET_SENTINEL):
            assert sentinel not in rendered, f"{sentinel} 泄漏进 prompt"

    def test_r1_09c_action_result_field_allowlist(self, repo):
        """CR 回归：action result 必须字段 allowlist —— 通用分支会回填整个 params。"""
        from backend.workflow.models import ActionStatus, WorkflowActionRecord
        plan = _plan(repo)
        run = _seed(repo, plan)
        repo.save_action_record(WorkflowActionRecord(
            action_id="act_generic", run_id=run.run_id, node_id="n1",
            action_type="generic", idempotency_key="idem_generic",
            params={"webhook": SECRET_SENTINEL},
            # action.py:547-552 的通用分支形状
            result={"action_type": "generic", "status": "executed", "note": "通用动作已记录",
                    "params": {"webhook": SECRET_SENTINEL}},
            status=ActionStatus.SUCCEEDED))
        acts = [p for p in collect_source_projections(repo, repo.get_run(run.run_id))
                if p.sourceType == SOURCE_ACTION and p.normalizedFields["actionId"] == "act_generic"]
        assert len(acts) == 1
        result = acts[0].normalizedFields["result"]
        assert result["status"] == "executed" and result["note"] == "通用动作已记录"
        assert "params" not in result, "params 不得携带取值"
        assert result["otherKeys"] == ["action_type", "params"], "越界键只保留键名"
        assert SECRET_SENTINEL not in canonical_json(acts[0].normalizedFields)

        # allowlist 内的嵌套 dict/list 不得整体透传 —— 只记录形状
        from backend.planning.context_assembler import _allowlist
        nested = _allowlist({"sent": {"ok": True, "raw": SECRET_SENTINEL},
                             "channel": "wechat", "unknown_1": 1, "unknown_2": 2},
                            ("sent", "channel", "status"))
        assert nested["sent"] == {"_shape": ["ok", "raw"], "_keysTruncated": False}
        assert nested["channel"] == "wechat"
        assert nested["otherKeys"] == ["unknown_1", "unknown_2"]
        assert SECRET_SENTINEL not in canonical_json(nested)

    def test_r1_09d_credentials_scrubbed_from_free_text(self, repo):
        """CR 回归：异常文本内嵌的 webhook URL / token 必须脱敏。"""
        from backend.planning.context_assembler import _free_text, _scrub_credentials
        raw = "POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=" + SECRET_SENTINEL
        assert SECRET_SENTINEL not in _scrub_credentials(raw)
        assert SECRET_SENTINEL not in _free_text(raw, 400)
        assert "[REDACTED]" in _scrub_credentials(raw)
        assert SECRET_SENTINEL not in _scrub_credentials("https://x/y?token=" + SECRET_SENTINEL)
        assert SECRET_SENTINEL not in _scrub_credentials("http://user:" + SECRET_SENTINEL + "@h/p")
        # 普通错误文本不被破坏
        assert _scrub_credentials("tool timeout") == "tool timeout"

    def test_r1_14_excluded_fields_absent_everywhere(self, repo):
        """EXCLUDED_FIELDS 中的字段名不出现在任何 normalizedFields。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        for p in collect_source_projections(repo, run):
            for banned in EXCLUDED_FIELDS:
                assert banned not in p.normalizedFields, f"{p.sourceType} 泄漏 {banned}"


# ═══════════════════════════════════════════════════════════════════════════════
# 排名与预算 R1-15 … R1-20
# ═══════════════════════════════════════════════════════════════════════════════


class TestRankingAndBudget:
    def test_r1_15_ranking_is_input_order_independent(self, repo):
        """打乱输入顺序不改变排名结果（全序 tie-break 可判）。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        projections = collect_source_projections(repo, run)
        base = [p.sourceRef for p in rank_projections(projections, "", "", [])]
        for seed in (1, 7, 99):
            shuffled = list(projections)
            random.Random(seed).shuffle(shuffled)
            assert [p.sourceRef for p in rank_projections(shuffled, "", "", [])] == base

    def test_r1_16_explicit_refs_rank_first(self, repo):
        """observation 显式 evidenceRef 排在最前。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        projections = collect_source_projections(repo, run)
        target = projections[-1].sourceRef
        ordered = rank_projections(projections, "", "", [target])
        assert ordered[0].sourceRef == target

    def test_r1_17_step_locality_boost(self, repo):
        """与当前失败 step 同 nodeId 的证据排名提升（可压过字典序 tie-break）。"""
        from backend.planning.context_assembler import SOURCE_NODE_OUTPUT, _relevance

        # 构造字典序与 locality 相反的一对，确保断言真正检验 locality 而非 tie-break
        far = SourceProjection(sourceRef="nodeout:r:aaa", sourceType=SOURCE_NODE_OUTPUT,
                               trustClass=TrustClass.T1_TOOL,
                               normalizedFields={"nodeId": "aaa"}, nodeId="aaa")
        near = SourceProjection(sourceRef="nodeout:r:zzz", sourceType=SOURCE_NODE_OUTPUT,
                                trustClass=TrustClass.T1_TOOL,
                                normalizedFields={"nodeId": "zzz"}, nodeId="zzz")
        assert [p.sourceRef for p in rank_projections([far, near], "", "", [])] == \
               ["nodeout:r:aaa", "nodeout:r:zzz"]
        assert [p.sourceRef for p in rank_projections([far, near], "zzz", "zzz", [])] == \
               ["nodeout:r:zzz", "nodeout:r:aaa"]

        # 真实 run 上：locality 严格提高相关度分数
        plan = _plan(repo)
        run = _seed(repo, plan)
        failed = next(s.stepId for s in plan.steps if s.stepType == NodeType.ACTION)
        local = next(p for p in collect_source_projections(repo, run)
                     if p.sourceRef == ev.node_ref(run.run_id, failed))
        assert _relevance(local, failed, failed, []) > _relevance(local, "", "", [])

    def test_r1_18_source_diversity_before_repeats(self, repo):
        """先每类取一条，再补齐同类 —— 单一 source 不得垄断头部。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        ordered = rank_projections(collect_source_projections(repo, run), "", "", [])
        distinct = {p.sourceType for p in ordered}
        head = [p.sourceType for p in ordered[:len(distinct)]]
        assert len(set(head)) == len(head) == len(distinct)

    def test_r1_19_total_budget_enforced_and_truncated_flag(self, repo):
        """超预算时丢弃并置 truncated；总量不超上限。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        ordered = rank_projections(collect_source_projections(repo, run), "", "", [])
        tiny = ContextBudget(totalChars=120, perEvidenceChars=60, t3ProjectionChars=40)
        packed, truncated, prov = pack_evidence(ordered, tiny, "", "", [])
        assert sum(len(e.summary) for e in packed) <= tiny.totalChars
        assert truncated is True
        assert any("dropped" in p and p["dropped"] > 0 for p in prov)

    def test_r1_20_trust_subcap_enforced_t0_uncapped(self, repo):
        """T3 受子预算约束；T0 不受子预算约束。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        ordered = rank_projections(collect_source_projections(repo, run), "", "", [])
        budget = ContextBudget.for_decision(DecisionType.SEMANTIC_REPLAN)
        packed, _t, _p = pack_evidence(ordered, budget, "", "", [])
        by_trust: Dict[TrustClass, int] = {}
        for e in packed:
            by_trust[e.trustClass] = by_trust.get(e.trustClass, 0) + len(e.summary)
        for trust, used in by_trust.items():
            if trust == TrustClass.T0_SYSTEM:
                continue
            assert used <= budget.cap_for(trust), f"{trust} 超子预算"


# ═══════════════════════════════════════════════════════════════════════════════
# digest 与 fingerprint R1-21 … R1-26
# ═══════════════════════════════════════════════════════════════════════════════


class TestDigestAndFingerprint:
    def test_r1_21_same_snapshot_same_digest_and_context(self, repo):
        """同一 durable snapshot 重复装配 → digest 与选择完全一致。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        a, b = _ctx(repo, plan, run), _ctx(repo, plan, run)
        assert a.sourceSnapshotDigest == b.sourceSnapshotDigest
        assert [e.evidenceId for e in a.executionEvidence] == \
               [e.evidenceId for e in b.executionEvidence]

    def test_r1_22_content_change_changes_digest(self, repo):
        """证据内容变化 → digest 变化。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        before = _ctx(repo, plan, run).sourceSnapshotDigest
        repo.save_node_run(WorkflowNodeRun(node_run_id="nr_fail", run_id=run.run_id,
                                           node_id=run.state["currentNode"],
                                           node_type=NodeType.ACTION, status=NodeStatus.FAILED,
                                           error="完全不同的错误", attempt=2,
                                           completed_at="2026-01-01T00:00:09Z"))
        assert _ctx(repo, plan, repo.get_run(run.run_id)).sourceSnapshotDigest != before

    def test_r1_23_ranking_only_input_changes_digest_not_fingerprint(self):
        """timestamp 是 ranking 输入而非 render 内容 → 改 digest，不改 fingerprint。"""
        base = SourceProjection(sourceRef="node:r:s1", sourceType=SOURCE_NODE_RUN,
                                trustClass=TrustClass.T0_SYSTEM,
                                normalizedFields={"nodeId": "s1"}, timestamp="T1")
        later = SourceProjection(sourceRef="node:r:s1", sourceType=SOURCE_NODE_RUN,
                                 trustClass=TrustClass.T0_SYSTEM,
                                 normalizedFields={"nodeId": "s1"}, timestamp="T2")
        assert compute_source_snapshot_digest([base], {}) != \
               compute_source_snapshot_digest([later], {})

        def ctx_with(ts: str):
            return empty_decision_context(DecisionType.CRITIC, run_id="r").__class__(
                decisionType=DecisionType.CRITIC, rootRunId="r", runId="r",
                planId="p", planVersion=1,
                executionEvidence=(EvidenceRef(
                    evidenceId="node:r:s1", sourceType=SOURCE_NODE_RUN, sourceRef="node:r:s1",
                    trustClass=TrustClass.T0_SYSTEM, summary="same", timestamp=ts,
                    relevance=1.0 if ts == "T1" else 9.0),))
        # timestamp / relevance 均不 render → fingerprint 相同
        assert compute_context_fingerprint(ctx_with("T1")) == compute_context_fingerprint(ctx_with("T2"))

    def test_r1_24_fingerprint_hashes_free_text_keeps_enums(self):
        """FreeText 被哈希；枚举/整数保持字面值。"""
        out = fingerprint_projection({"code": "tool_error", "n": 3, "ok": True,
                                      "text": FreeText("敏感自由文本"),
                                      "nested": [FreeText("x"), "y"]})
        assert out["code"] == "tool_error" and out["n"] == 3 and out["ok"] is True
        assert out["text"] == "h:" + content_hash("敏感自由文本")
        assert out["nested"] == ["h:" + content_hash("x"), "y"]
        assert "敏感自由文本" not in canonical_json(out)

    def test_r1_25_fingerprint_stable_across_reassembly(self, repo):
        """同一 source snapshot 内 assembler 为纯函数（Option B 契约）。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        f1 = compute_context_fingerprint(_ctx(repo, plan, run))
        f2 = compute_context_fingerprint(_ctx(repo, plan, repo.get_run(run.run_id)))
        assert f1 == f2

    def test_r1_26_digest_covers_ranking_visible_fields(self):
        """nodeId（ranking 可见）变化必须改变 digest，否则会 digest 同而选择异。"""
        a = SourceProjection(sourceRef="node:r:s1", sourceType=SOURCE_NODE_RUN,
                             trustClass=TrustClass.T0_SYSTEM,
                             normalizedFields={"k": 1}, nodeId="s1")
        b = SourceProjection(sourceRef="node:r:s1", sourceType=SOURCE_NODE_RUN,
                             trustClass=TrustClass.T0_SYSTEM,
                             normalizedFields={"k": 1}, nodeId="s2")
        assert compute_source_snapshot_digest([a], {}) != compute_source_snapshot_digest([b], {})
        # systemState 也必须参与
        assert compute_source_snapshot_digest([a], {"runStatus": "failed"}) != \
               compute_source_snapshot_digest([a], {"runStatus": "completed"})


# ═══════════════════════════════════════════════════════════════════════════════
# Observation 富化与 legacy 冻结 R1-27 … R1-30
# ═══════════════════════════════════════════════════════════════════════════════


def _coordinator(repo):
    from backend.planning.continuation import PlanningContinuationCoordinator
    return PlanningContinuationCoordinator(repo)


class TestObservationEnrichment:
    def test_r1_27_observation_now_carries_durable_evidence(self, repo):
        """RC1 修复：失败 node 的 stepId / error / refs 不再被丢弃。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        coord = _coordinator(repo)
        obs = coord._build_observation(run, plan, coord._get_or_init_lineage(run))
        failed = next(s.stepId for s in plan.steps if s.stepType == NodeType.ACTION)
        assert obs.stepId == failed
        assert obs.failureReason == "tool timeout"
        assert obs.failureCode == "tool_error"
        assert obs.metadata["nodeId"] == failed and obs.metadata["attempt"] == 2
        got = {r["ref"] for r in obs.evidenceRefs}
        assert ev.node_ref(run.run_id, failed) in got
        assert ev.error_ref(run.run_id, failed, 1) in got
        assert all(ev.is_valid_ref(r["ref"]) for r in obs.evidenceRefs)

    def test_r1_28_phase18_view_frozen_regardless_of_enrichment(self, repo):
        """flag=off 投影为冻结字面值，与富化内容无关。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        coord = _coordinator(repo)
        obs = coord._build_observation(run, plan, coord._get_or_init_lineage(run))
        legacy = obs.to_phase18_prompt_view()
        assert legacy == {"stepId": "", "type": obs.type.value, "status": obs.status.value,
                          "failureReason": None, "failureCode": None, "evidenceRefs": []}
        grounded = obs.to_grounded_prompt_view()
        assert grounded["stepId"] and grounded["failureReason"] and grounded["evidenceRefs"]
        assert set(legacy) == set(grounded)  # 同 key 集合，仅值不同
        assert coord._observation_prompt_view(obs, plan) == legacy
        plan.groundedDecisionContextEnabled = True
        assert coord._observation_prompt_view(obs, plan) == grounded

    def test_r1_29_phase18_golden_prompts_byte_identical(self):
        """在 master 上捕获的 7 条 legacy prompt 必须逐字节复现。"""
        import shutil
        import tempfile
        from backend.tests.phase19_golden_capture import capture

        with open(FIXTURE_PATH, encoding="utf-8") as f:
            golden = json.load(f)["scenarios"]
        assert len(golden) == 7, "golden fixture 应覆盖 7 个场景"

        tmpdir = tempfile.mkdtemp(prefix="p19r1_golden_")
        original = cfg.DB_PATH
        try:
            cfg.DB_PATH = os.path.join(tmpdir, "golden.db")
            current = capture()
        finally:
            cfg.DB_PATH = original
            shutil.rmtree(tmpdir, ignore_errors=True)

        assert set(current) == set(golden)
        for key in sorted(golden):
            assert current[key]["system"] == golden[key]["system"], f"{key} system prompt 漂移"
            assert current[key]["user"] == golden[key]["user"], f"{key} user prompt 漂移"

    def test_r1_29b_routing_and_retry_semantics_unchanged(self, repo):
        """CR 回归：富化只加 payload，不得改变 Phase18 路由与 retry 语义。

        走真实 classify_observation + 真实 retryable property，覆盖全部 17 种
        ObservationType，并对每种都注入 R1 可能产生的 failureCode。
        """
        from backend.planning.budget import new_lineage
        from backend.planning.replan_decision import classify_observation

        assert len(list(ObservationType)) == 17
        # R1 只会产生这三种 failureCode，且都不得触发 retryable 白名单
        r1_codes = ("tool_error", "node_error", "timeout")
        for code in r1_codes:
            assert not code.startswith("transient") and not code.startswith("network")

        lineage = new_lineage("root")
        for obs_type in ObservationType:
            baseline = None
            for code in (None,) + r1_codes:
                obs = Observation(
                    observationId="o1", planId="p", planVersion=1, runId="r",
                    type=obs_type, status=ObservationStatus.FAILURE,
                    scope=ObservationScope.RUN, source=ObservationSource.SYSTEM,
                    # 富化后的字段全部就位
                    stepId="step_x", failureCode=code, failureReason="tool timeout",
                    evidenceRefs=[{"ref": "node:r:step_x"}], metadata={"nodeId": "step_x"},
                )
                decision = classify_observation(obs, lineage)
                if baseline is None:
                    baseline = (decision, obs.retryable)
                assert (decision, obs.retryable) == baseline, \
                    f"{obs_type.value}: failureCode={code} 改变了路由/retry"

    def test_r1_29c_failed_agent_node_stays_node_failed(self, repo):
        """CR 回归：失败的 agent 节点仍映射 NODE_FAILED，不得偷偷变 AGENT_FAILED。"""
        plan = _plan(repo)
        run_id = "r1_agent_fail"
        repo.save_run(WorkflowRun(run_id=run_id, definition_id=plan.planId,
                                  version=plan.version, status=WorkflowRunStatus.FAILED,
                                  state=_rich_state("agent_x")))
        agent_step = next(s.stepId for s in plan.steps if s.stepType == NodeType.AGENT_TASK)
        repo.save_node_run(WorkflowNodeRun(node_run_id="nr_a", run_id=run_id,
                                           node_id=agent_step, node_type=NodeType.AGENT_TASK,
                                           status=NodeStatus.FAILED, error="agent boom"))
        run = repo.get_run(run_id)
        coord = _coordinator(repo)
        obs = coord._build_observation(run, plan, coord._get_or_init_lineage(run))
        assert obs.type == ObservationType.NODE_FAILED
        assert obs.type != ObservationType.AGENT_FAILED
        assert obs.failureCode == "node_error"
        assert obs.retryable is False

    def test_r1_30_idempotency_key_namespace_unchanged(self, repo):
        """flag=off 时 critic / semantic replan 幂等键与 Phase18 完全一致。"""
        from backend.planning.critic import build_critic_invocation_key
        plan = _plan(repo)
        run = _seed(repo, plan)
        coord = _coordinator(repo)
        lineage = coord._get_or_init_lineage(run)
        obs = coord._build_observation(run, plan, lineage)

        step_off = coord._observation_prompt_view(obs, plan)["stepId"]
        assert step_off == ""  # Phase18 命名空间
        root = lineage.rootRunId or run.run_id
        assert build_critic_invocation_key(root, run.run_id, plan.version,
                                           obs.type.value, step_off) == \
               build_critic_invocation_key(root, run.run_id, plan.version, obs.type.value, "")
        assert f"{step_off or 'unknown'}" == "unknown"

        plan.groundedDecisionContextEnabled = True
        assert coord._observation_prompt_view(obs, plan)["stepId"] == obs.stepId


# ═══════════════════════════════════════════════════════════════════════════════
# flag 与安全性 R1-31 … R1-32
# ═══════════════════════════════════════════════════════════════════════════════


class TestFlagAndSafety:
    def test_r1_31_flag_defaults_off_roundtrips_and_inherits(self, repo):
        """默认关闭 / 字段缺失⇒False / 往返保真 / 子计划继承 / 编译器不自动开启。"""
        from backend.planning.proposal_compiler import compile_proposal
        from backend.planning.replanner import build_revision, build_semantic_revision

        assert Plan.__dataclass_fields__["groundedDecisionContextEnabled"].default is False

        plan = _plan(repo)
        assert plan.groundedDecisionContextEnabled is False
        d = plan.to_dict()
        assert d["groundedDecisionContextEnabled"] is False
        d.pop("groundedDecisionContextEnabled")
        assert Plan.from_dict(d).groundedDecisionContextEnabled is False  # 缺失 ⇒ False

        plan.groundedDecisionContextEnabled = True
        assert Plan.from_dict(plan.to_dict()).groundedDecisionContextEnabled is True
        # 两条 revision 路径（deterministic / semantic）都必须继承
        assert build_revision(plan, {}, "run_p").groundedDecisionContextEnabled is True
        assert build_semantic_revision(plan, {}, "run_p", []).groundedDecisionContextEnabled is True
        plan.groundedDecisionContextEnabled = False
        assert build_revision(plan, {}, "run_p").groundedDecisionContextEnabled is False
        assert build_semantic_revision(plan, {}, "run_p", []).groundedDecisionContextEnabled is False

        # LLM 计划编译路径（compile_proposal）不得自动开启 grounded
        src_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "planning", "proposal_compiler.py")
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        assert "semanticReplanEnabled=True" in src, "前提：编译器确实会自动开启语义重规划"
        assert "groundedDecisionContextEnabled" not in src, "编译器不得自动开启 grounded"
        assert compile_proposal is not None

    def test_r1_32_assembler_is_pure_and_degrades_safely(self, repo):
        """装配不写库、不改状态；异常时退化为空上下文而非失败。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        before_events = len(repo.list_events(run.run_id))
        before_status = repo.get_run(run.run_id).status
        before_state = canonical_json(repo.get_run(run.run_id).state)

        ctx = _ctx(repo, plan, run)
        assert ctx.executionEvidence  # 确实做了事
        after = repo.get_run(run.run_id)
        assert len(repo.list_events(run.run_id)) == before_events
        assert after.status == before_status
        assert canonical_json(after.state) == before_state

        class Broken:
            def __getattr__(self, name):
                raise RuntimeError("repo 故障")

        degraded = assemble_or_empty(Broken(), run, plan, None, DecisionType.CRITIC)
        assert degraded.isEmpty and degraded.decisionType == DecisionType.CRITIC


# ═══════════════════════════════════════════════════════════════════════════════
# 交叉断言：untrusted 内容不得进入 trusted 区
# ═══════════════════════════════════════════════════════════════════════════════


class TestTrustBoundary:
    def test_observation_view_splits_trust(self, repo):
        """ObservationView：枚举/ID 可信，失败文本不可信。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        coord = _coordinator(repo)
        obs = coord._build_observation(run, plan, coord._get_or_init_lineage(run))
        ctx = _ctx(repo, plan, run, observation=obs)
        view = ctx.observation
        assert view is not None
        assert set(view.trusted_fields()) == {"type", "status", "stepId", "nodeId", "failureCode"}
        assert set(view.untrusted_fields()) == {"failureReason", "outputSummary"}
        assert view.failureReason == "tool timeout"
        # 自由文本在 fingerprint 中被哈希，不以明文出现
        fp = canonical_json(fingerprint_projection(prompt_projection(ctx)))
        assert "tool timeout" not in fp

    def test_every_packed_evidence_declares_trust(self, repo):
        """每条打包证据都必须带 trustClass 与 contentHash（可归因）。"""
        plan = _plan(repo)
        run = _seed(repo, plan)
        for e in _ctx(repo, plan, run).executionEvidence:
            assert isinstance(e.trustClass, TrustClass)
            assert e.contentHash and len(e.contentHash) == 64
            assert ev.is_valid_ref(e.sourceRef)
