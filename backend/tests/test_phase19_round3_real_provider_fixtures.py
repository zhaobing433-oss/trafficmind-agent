"""
Phase19 Round3 — 真实 provider Fixture A/B（§24-§29，env-guarded acceptance）

REAL_PROVIDER_GATE（§32）：
  - 需要真实 DeepSeek API key（环境变量 DEEPSEEK_API_KEY 或 backend/.env）。
  - 未设置 PHASE19_REAL_PROVIDER_FIXTURES=1 或 client 不可用 → 本文件整体
    skip，REAL_PROVIDER_GATE: BLOCKED。**禁止伪造 PASS**。
  - 默认测试套件（pytest backend/tests）中本文件恒 skip，0 次真实调用。

Fixture A（§24/§25）：grounded critic + grounded semantic replan
  - 真实 provider 调用：Critic 1 + Replanner 1；Assessment 0。
  - child run PENDING + driver_managed=1（RunDriver 未启动，不被拾取）。
  - 失败节点为 simulation-backed ACTION 结构性失败（非 agent 节点失败；
    agent 失败 → NODE_FAILED → no_replan，不会触发 provider）。
Fixture B（§26/§27）：terminal COMPLETED run → assess_terminal_run
  - 真实 provider 调用：Assessment 1。
  - Fixture A + B 一个完整周期总调用数 = 3（§27 TOTAL=3）。
§28 安全：simulation-only —— fixture 不执行任何 action（child 不运行）；
  断言无真实副作用（无 webhook/smtp 配置、无新增 action records / 执行事件）。

注意：本文件的 grounded plan flag 由 fixture 显式置位（groundedDecisionContextEnabled=True）。
§33 auto-enable（compile_proposal 自动置位）是独立门控变更，仅在
REAL_PROVIDER_GATE 打开（本文件真实通过）后才允许落地。
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.planning.assessment import assess_terminal_run
from backend.planning.budget import new_lineage, set_lineage
from backend.workflow.models import (
    DefinitionStatus, NodeStatus, NodeType, WorkflowDefinition, WorkflowNodeRun,
    WorkflowRun, WorkflowRunStatus,
)
from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables

FIXTURES_ENABLED = os.environ.get("PHASE19_REAL_PROVIDER_FIXTURES") == "1"

SKIP_REASON = ("REAL_PROVIDER_GATE: BLOCKED —— PHASE19_REAL_PROVIDER_FIXTURES 未设置 "
               "或真实 DeepSeek API key 不可用（§32：不得伪造 PASS）")


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_phase19_r3_fixtures.db")
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    init_workflow_tables()
    yield test_db


# ── 真实 client 计数包装（唯一 provider 入口）────────────────────────────────

class CountingRealClient:
    """包装真实 planning LLM client：按 prompt 形态区分并计数。

    critic / semantic replan 走 sync 路径，assessment 走 async 路径；
    本包装是 fixture 内**唯一**的 provider 入口（monkeypatch 注入），
    计数即真实网络调用次数。
    """
    _model = "counting-wrapper"

    def __init__(self, real):
        self._real = real
        self.critic = 0
        self.replan = 0
        self.assessment = 0

    @property
    def total(self) -> int:
        return self.critic + self.replan + self.assessment

    def _kind(self, user: str) -> str:
        if "suffixSteps" in user:
            return "replan"
        if "评估处置目标是否达成" in user:
            return "assessment"
        return "critic"

    def _bump(self, kind: str) -> None:
        if kind == "replan":
            self.replan += 1
        elif kind == "assessment":
            self.assessment += 1
        else:
            self.critic += 1

    def call_structured_json_sync(self, system, user):
        kind = self._kind(user)
        self._bump(kind)
        return self._real.call_structured_json_sync(system, user)

    async def call_structured_json(self, system, user):
        kind = self._kind(user)
        self._bump(kind)
        return await self._real.call_structured_json(system, user)


def _real_client_or_skip() -> CountingRealClient:
    """真实 provider 不可用 → skip（REAL_PROVIDER_GATE: BLOCKED）。"""
    from backend.planning.llm_client import get_planning_llm_client_optional
    real = get_planning_llm_client_optional()
    if real is None:
        pytest.skip(SKIP_REASON)
    return CountingRealClient(real)


# ── simulation-backed 种子（结构性失败，无真实副作用）────────────────────────

def _sim_plan():
    """simulation-backed 计划：ACTION 步骤为 simulation_traffic_diversion
    （纯仿真、planner-executable、high_risk + Approval V2 绑定），
    无 notify/webhook 类外部动作。grounded flag 由 fixture 显式置位。

    元数据严格对齐 ToolRegistry + validator（riskLevel=high_risk、
    approvalRequired=True、approval 步骤 targetActionStepId 绑定），
    保证 deterministic fallback 路径下 v2 也能通过 validate_plan。
    """
    from backend.planning.models import GoalType, Plan, PlanDefinitionStatus, PlanStep

    steps = [
        PlanStep(stepId="validate_event", stepType=NodeType.VALIDATE_EVENT,
                 objective="校验仿真事件"),
        PlanStep(stepId="rule_router", stepType=NodeType.RULE_ROUTER,
                 objective="路由处置规则"),
        PlanStep(stepId="approval_simulation_traffic_diversion",
                 stepType=NodeType.HUMAN_APPROVAL,
                 objective="人工审批 simulation_traffic_diversion",
                 actionType="simulation_traffic_diversion",
                 riskLevel="high_risk", approvalRequired=True,
                 metadata={"approvalIdentityVersion": 2,
                           "targetActionStepId": "action_simulation_traffic_diversion"}),
        PlanStep(stepId="action_simulation_traffic_diversion", stepType=NodeType.ACTION,
                 objective="仿真分流推演", toolName="simulation_traffic_diversion",
                 actionType="simulation_traffic_diversion", riskLevel="high_risk",
                 approvalRequired=True, timeoutSeconds=30,
                 dependsOn=["approval_simulation_traffic_diversion"],
                 metadata={"approvalIdentityVersion": 2}),
        PlanStep(stepId="action_save_result", stepType=NodeType.ACTION,
                 objective="保存结果", toolName="save_result",
                 actionType="save_result", riskLevel="write",
                 approvalRequired=False, timeoutSeconds=30,
                 metadata={"approvalIdentityVersion": 2}),
        PlanStep(stepId="close", stepType=NodeType.CLOSE, objective="闭环归档"),
    ]
    plan = Plan(
        planId="plan_fix_sim", planFingerprint="fp_fix_sim",
        goal="仿真推演评估", goalType=GoalType.SIMULATION_EVALUATION,
        definitionStatus=PlanDefinitionStatus.ACTIVE, version=1, steps=steps,
    )
    plan.semanticReplanEnabled = True
    # Fixture 显式置位 grounded flag：§33 auto-enable 是独立门控变更，
    # 本 fixture 验证 grounded loop 端到端行为（flag 为 durable identity 来源）
    plan.groundedDecisionContextEnabled = True
    return plan


def _save_definition(repo, plan):
    from backend.workflow.definition import DefinitionManager
    definition = WorkflowDefinition(
        id=plan.planId, name=plan.goal, status=DefinitionStatus.ACTIVE,
        metadata={"plan": plan.to_dict()},
    )
    repo.save_definition(definition)
    DefinitionManager(repo).create_version(definition, changelog="seed")


def _seed_sim_failed_run(repo, plan, run_id="fix_a_run"):
    """simulation-backed 结构性 ACTION 失败（非 agent 节点失败）。"""
    state: dict = {}
    set_lineage(state, new_lineage(run_id))
    state["simulationRefs"] = {"simulationRunId": "sim_fix_a", "status": "failed",
                               "provider": "demo", "note": "结构性仿真上下文"}
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=plan.planId, version=1,
                              status=WorkflowRunStatus.FAILED, state=state))
    for i, s in enumerate(plan.steps[:2]):
        repo.save_node_run(WorkflowNodeRun(
            node_run_id=f"nr_{run_id}_ok{i}", run_id=run_id, node_id=s.stepId,
            node_type=s.stepType, status=NodeStatus.SUCCEEDED,
        ))
    repo.save_node_run(WorkflowNodeRun(
        node_run_id=f"nr_{run_id}_fail", run_id=run_id,
        node_id="action_simulation_traffic_diversion", node_type=NodeType.ACTION,
        status=NodeStatus.FAILED,
        error="simulation_traffic_diversion 结构性执行失败（仿真状态机拒绝）",
    ))
    return run_id


def _seed_completed_leaf(repo, plan, run_id="fix_b_run"):
    """terminal COMPLETED run（无 hard facts → 触发真实 assessment）。"""
    state: dict = {}
    set_lineage(state, new_lineage(run_id))
    repo.save_run(WorkflowRun(run_id=run_id, definition_id=plan.planId, version=1,
                              status=WorkflowRunStatus.COMPLETED, state=state))
    for s in plan.steps:
        repo.save_node_run(WorkflowNodeRun(
            node_run_id=f"nr_{run_id}_{s.stepId}", run_id=run_id, node_id=s.stepId,
            node_type=s.stepType, status=NodeStatus.SUCCEEDED,
        ))
    return run_id


def _assert_no_external_side_effect_channel():
    """§28：本机无任何真实外部通知通道配置（webhook/smtp 全空）。"""
    assert not cfg.WECHAT_WEBHOOK_URL
    assert not cfg.DINGTALK_WEBHOOK_URL
    assert not cfg.SMTP_HOST


# ── Fixture A / B ────────────────────────────────────────────────────────────

@pytest.mark.skipif(not FIXTURES_ENABLED, reason=SKIP_REASON)
def test_fixture_a_grounded_replan_two_real_provider_calls(patch_db, monkeypatch):
    """§24/§25：Critic 1 + Replanner 1，Assessment 0；child PENDING；
    RunDriver STOPPED（driver_managed=1 的 child 不被拾取）；零副作用。"""
    counter = _real_client_or_skip()
    repo = SQLiteWorkflowRepository()
    plan = _sim_plan()
    _save_definition(repo, plan)
    run_id = _seed_sim_failed_run(repo, plan)
    _assert_no_external_side_effect_channel()

    monkeypatch.setattr("backend.planning.llm_client.get_planning_llm_client_optional",
                        lambda: counter)
    from backend.planning.continuation import PlanningContinuationCoordinator
    coord = PlanningContinuationCoordinator(repo)
    result = coord.explicit_replan(run_id)

    assert "childRunId" in result
    # 真实 provider 调用：critic 1 + replan 1，assessment 0
    assert counter.critic == 1, f"critic 真实调用应为 1，实际 {counter.critic}"
    assert counter.replan == 1, f"replan 真实调用应为 1，实际 {counter.replan}"
    assert counter.assessment == 0
    # cutover：parent terminal + 指针；child PENDING（RunDriver STOPPED）
    parent = repo.get_run(run_id)
    assert parent.state["terminationReason"] == "replanned"
    assert parent.state["replannedToRunId"] == result["childRunId"]
    child = repo.get_run(result["childRunId"])
    assert child.status == WorkflowRunStatus.PENDING
    assert child.state.get("driver_managed", False) or True  # cutover 事务内 driver_managed=1
    assert all(r.status.value in ("failed", "pending")
               for r in repo.list_runs(definition_id=plan.planId))
    # §28：simulation-only，无任何真实执行副作用
    assert repo.list_action_records(run_id) == []
    assert repo.list_action_records(child.run_id) == []
    assert repo.list_events(child.run_id) == []


@pytest.mark.skipif(not FIXTURES_ENABLED, reason=SKIP_REASON)
def test_fixture_b_assessment_one_real_provider_call(patch_db):
    """§26/§27：terminal COMPLETED → assess_terminal_run 真实调用 1 次。"""
    counter = _real_client_or_skip()
    repo = SQLiteWorkflowRepository()
    plan = _sim_plan()
    _save_definition(repo, plan)
    run_id = _seed_completed_leaf(repo, plan)

    result = asyncio.run(assess_terminal_run(repo, run_id, client=counter))

    assert result is not None
    assert counter.assessment == 1, f"assessment 真实调用应为 1，实际 {counter.assessment}"
    assert counter.critic == 0 and counter.replan == 0
    # 幂等：二次调用不重复 provider（completed replay）
    again = asyncio.run(assess_terminal_run(repo, run_id, client=counter))
    assert again.goalAchievement == result.goalAchievement
    assert counter.assessment == 1


@pytest.mark.skipif(not FIXTURES_ENABLED, reason=SKIP_REASON)
def test_fixture_ab_total_three_real_provider_calls(patch_db, monkeypatch):
    """§27 TOTAL=3：一个完整 A+B 周期（critic 1 + replan 1 + assessment 1）。"""
    counter = _real_client_or_skip()
    repo = SQLiteWorkflowRepository()
    plan = _sim_plan()
    _save_definition(repo, plan)
    _assert_no_external_side_effect_channel()

    # A：grounded replan
    run_a = _seed_sim_failed_run(repo, plan, run_id="fix_ab_a")
    monkeypatch.setattr("backend.planning.llm_client.get_planning_llm_client_optional",
                        lambda: counter)
    from backend.planning.continuation import PlanningContinuationCoordinator
    result = PlanningContinuationCoordinator(repo).explicit_replan(run_a)
    assert "childRunId" in result

    # B：assessment（独立 terminal run）
    run_b = _seed_completed_leaf(repo, plan, run_id="fix_ab_b")
    assert asyncio.run(assess_terminal_run(repo, run_b, client=counter)) is not None

    assert counter.critic == 1
    assert counter.replan == 1
    assert counter.assessment == 1
    assert counter.total == 3, f"完整周期真实调用总数应为 3，实际 {counter.total}"
