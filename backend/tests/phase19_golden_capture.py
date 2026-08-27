"""
Phase19 Round1 — Phase18 golden prompt 捕获器

用途：在**未修改的 master 代码**上，捕获 Critic / Semantic Replanner / Assessment
三个 legacy prompt 的精确 (system, user) UTF-8 字节，写入 golden fixture。

关键约束：
  - 必须调用真实 production builder（_build_critic_context / _build_replan_context /
    build_assessment_messages），**不得**重新实现一份 expected builder。
  - 使用临时 DB，绝不触碰 backend/data/trafficmind.db。

用法（仓库根目录）：
    backend/.venv/bin/python -m backend.tests.phase19_golden_capture

输出：backend/tests/fixtures/phase19_phase18_golden_prompts.json
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
FIXTURE_PATH = os.path.join(FIXTURE_DIR, "phase19_phase18_golden_prompts.json")


def _seed_plan(repo, run_id: str):
    """构建一个 ACTIVE plan + definition（确定性 planner，无 LLM）。"""
    from backend.planning.context import build_planning_context
    from backend.planning.models import PlanDefinitionStatus
    from backend.planning.planner import build_plan
    from backend.workflow.models import DefinitionStatus, WorkflowDefinition

    event = {
        "eventId": "E_GOLDEN", "eventType": "accident", "roadName": "A路",
        "avgSpeed": 8, "queueLength": 200, "duration": 900, "nearbyHospital": True,
    }
    plan = build_plan(build_planning_context(event))
    plan.definitionStatus = PlanDefinitionStatus.ACTIVE
    plan.semanticReplanEnabled = True
    repo.save_definition(WorkflowDefinition(
        id=plan.planId, name=plan.goal, status=DefinitionStatus.ACTIVE,
        metadata={"plan": plan.to_dict()},
    ))
    return plan


def _seed_run(repo, plan, run_id: str, scenario: str):
    """按 scenario 构造 parent run + node_runs（覆盖 legacy 场景矩阵）。"""
    from backend.planning.budget import new_lineage, set_lineage
    from backend.workflow.models import (
        NodeStatus, NodeType, WorkflowNodeRun, WorkflowRun, WorkflowRunStatus,
    )

    state: Dict[str, Any] = {}
    set_lineage(state, new_lineage(run_id))

    if scenario == "approval_rejected":
        status = WorkflowRunStatus.REJECTED
    elif scenario == "assessment_terminal":
        status = WorkflowRunStatus.COMPLETED
        state["nodeOutputs"] = {"validate_event": {"ok": True}, "rule_router": {"route": "main_road"}}
    else:
        status = WorkflowRunStatus.FAILED

    repo.save_run(WorkflowRun(run_id=run_id, definition_id=plan.planId, version=plan.version,
                              status=status, state=state))

    # 前缀成功节点（完成前缀 → completedStepIds / completedPrefixSummary 非空）
    for i, s in enumerate(plan.steps[:3]):
        repo.save_node_run(WorkflowNodeRun(
            node_run_id=f"nr_{run_id}_ok{i}", run_id=run_id, node_id=s.stepId,
            node_type=s.stepType, status=NodeStatus.SUCCEEDED,
        ))

    if scenario == "tool_failed":
        # action 节点失败 → ObservationType.TOOL_FAILED（唯一 semantic_review 入口）
        action_id = next((s.stepId for s in plan.steps if s.stepType == NodeType.ACTION), "action_x")
        repo.save_node_run(WorkflowNodeRun(
            node_run_id=f"nr_{run_id}_fail", run_id=run_id, node_id=action_id,
            node_type=NodeType.ACTION, status=NodeStatus.FAILED, error="simulated tool failure",
        ))
    elif scenario == "node_failed":
        # 非 action 节点失败 → ObservationType.NODE_FAILED
        agent_id = next((s.stepId for s in plan.steps if s.stepType == NodeType.AGENT_TASK), "agent_x")
        repo.save_node_run(WorkflowNodeRun(
            node_run_id=f"nr_{run_id}_fail", run_id=run_id, node_id=agent_id,
            node_type=NodeType.AGENT_TASK, status=NodeStatus.FAILED, error="simulated agent failure",
        ))
    return repo.get_run(run_id)


def capture() -> Dict[str, Any]:
    """在真实 production builder 上捕获 legacy prompt 字节。"""
    from backend.planning.assessment_prompts import build_assessment_messages
    from backend.planning.continuation import PlanningContinuationCoordinator
    from backend.planning.critic_prompts import build_critic_messages
    from backend.planning.replan_context import build_semantic_replan_messages
    from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables

    init_workflow_tables()
    repo = SQLiteWorkflowRepository()
    coordinator = PlanningContinuationCoordinator(repo)

    golden: Dict[str, Any] = {}

    for scenario in ("tool_failed", "node_failed", "approval_rejected"):
        run_id = f"golden_{scenario}"
        plan = _seed_plan(repo, run_id)
        run = _seed_run(repo, plan, run_id, scenario)
        lineage = coordinator._get_or_init_lineage(run)
        observation = coordinator._build_observation(run, plan, lineage)

        c_sys, c_user = build_critic_messages(
            coordinator._build_critic_context(observation, plan, run, lineage))
        r_sys, r_user = build_semantic_replan_messages(
            coordinator._build_replan_context(plan, run, lineage, observation))

        golden[f"critic::{scenario}"] = {"system": c_sys, "user": c_user}
        golden[f"replan::{scenario}"] = {"system": r_sys, "user": r_user}

    # assessment terminal fixture
    run_id = "golden_assessment_terminal"
    plan = _seed_plan(repo, run_id)
    run = _seed_run(repo, plan, run_id, "assessment_terminal")
    a_sys, a_user = build_assessment_messages(run, run_id)
    golden["assessment::terminal"] = {"system": a_sys, "user": a_user}

    return golden


def main() -> int:
    import backend.config as cfg

    tmpdir = tempfile.mkdtemp(prefix="phase19_golden_")
    original_db = cfg.DB_PATH
    try:
        # 隔离 DB：绝不触碰 backend/data/trafficmind.db
        cfg.DB_PATH = os.path.join(tmpdir, "golden.db")
        golden = capture()
    finally:
        cfg.DB_PATH = original_db
        shutil.rmtree(tmpdir, ignore_errors=True)

    # 每条记录附 sha256，便于人工核对 fixture 未被意外重写
    for key, payload in golden.items():
        raw = (payload["system"] + "\x00" + payload["user"]).encode("utf-8")
        payload["sha256"] = hashlib.sha256(raw).hexdigest()

    os.makedirs(FIXTURE_DIR, exist_ok=True)
    with open(FIXTURE_PATH, "w", encoding="utf-8") as f:
        json.dump({"capturedFromRef": "master", "scenarios": golden},
                  f, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"[golden] 写入 {FIXTURE_PATH}")
    for key in sorted(golden):
        p = golden[key]
        print(f"  {key:34s} sys={len(p['system']):5d}ch user={len(p['user']):6d}ch "
              f"sha256={p['sha256'][:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
