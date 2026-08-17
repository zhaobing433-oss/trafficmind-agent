"""
Planning Continuation Coordinator — Phase 17 Round 2

thin control-plane：
  safe-boundary result → Observation → Decision → existing retry OR revision transaction
  → after commit → WorkflowExecutor execute child

禁止：执行 node / 调用 Tool / 实现 approval / 实现 retry runtime。不是第二 runtime。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.planning.budget import (
    ExecutionLineage,
    get_lineage,
    inherit_lineage,
    new_lineage,
    reserve_replan,
    set_lineage,
)
from backend.planning.models import Plan
from backend.planning.observation import (
    Observation,
    ObservationScope,
    ObservationSource,
    ObservationStatus,
    ObservationType,
    generate_observation_id,
)
from backend.planning.replan_decision import (
    DecisionResult,
    ReplanDecision,
    ReplanDecisionEngine,
)
from backend.planning.replanner import build_revision
from backend.planning.revision import (
    build_child_state,
    compute_continuation_key,
    deterministic_child_run_id,
    plan_to_child_definition,
    validate_carried_refs,
)
from backend.planning.validator import has_errors, validate_plan
from backend.workflow.models import WorkflowEvent, WorkflowRun, WorkflowRunStatus, generate_event_id
from backend.workflow.repository import SQLiteWorkflowRepository


class PlanningContinuationCoordinator:
    """control plane：串 Observation → Decision → Replanner → child。"""

    def __init__(self, repository: Optional[SQLiteWorkflowRepository] = None):
        self._repo = repository or SQLiteWorkflowRepository()
        self._engine = ReplanDecisionEngine()

    @property
    def repo(self) -> SQLiteWorkflowRepository:
        return self._repo

    # ── observation 持久化 ───────────────────────────────────────────

    def persist_observation(self, observation: Observation) -> None:
        """写 observation_recorded workflow_event（durable audit log）。"""
        events = self._repo.list_events(observation.runId)
        seq = len(events)
        evt = WorkflowEvent(
            event_id=generate_event_id(observation.runId, seq),
            run_id=observation.runId,
            event_type="observation_recorded",
            payload=observation.to_dict(),
            sequence=seq,
        )
        self._repo.save_event(evt)

    # ── 幂等 / lineage 辅助 ─────────────────────────────────────────

    def _load_plan_from_run(self, run: WorkflowRun) -> Optional[Plan]:
        definition = self._repo.get_definition(run.definition_id)
        if definition is None:
            return None
        plan_raw = definition.metadata.get("plan")
        if not plan_raw:
            return None
        if isinstance(plan_raw, str):
            import json
            try:
                plan_raw = json.loads(plan_raw)
            except Exception:
                return None
        try:
            return Plan.from_dict(plan_raw)
        except Exception:
            return None

    def _completed_result_refs(self, run_id: str) -> Dict[str, str]:
        """从 node_runs 提取 completed step 的 {stepId: resultRef}。"""
        refs: Dict[str, str] = {}
        for nr in self._repo.get_node_runs(run_id):
            if nr.status.value == "succeeded":
                refs[nr.node_id] = f"{run_id}:{nr.node_id}"
        return refs

    def _get_or_init_lineage(self, run: WorkflowRun) -> ExecutionLineage:
        state = run.state if isinstance(run.state, dict) else {}
        lineage = get_lineage(state)
        if not lineage.rootRunId:
            lineage = new_lineage(run.run_id)
            set_lineage(state, lineage)
            run.state = state
            self._repo.save_run(run)
        return lineage

    # ── explicit replan ─────────────────────────────────────────────

    def explicit_replan(self, run_id: str, user_goal: str = "") -> Dict[str, Any]:
        """显式 deterministic replan。幂等（parent.replannedToRunId 为第一道防线）。"""
        parent = self._repo.get_run(run_id)
        if parent is None:
            return {"error": f"Run '{run_id}' 不存在"}
        parent_state = parent.state if isinstance(parent.state, dict) else {}

        # 幂等第一道防线：已 replan → 返回既有 child
        if parent_state.get("replannedToRunId"):
            return {"childRunId": parent_state["replannedToRunId"], "alreadyReplanned": True}

        plan = self._load_plan_from_run(parent)
        if plan is None:
            return {"error": "无法从 definition 加载 Plan"}

        lineage = self._get_or_init_lineage(parent)

        # 构建 observation（从 parent 状态）
        observation = self._build_observation(parent, plan, lineage)

        # decision
        decision = self._engine.decide(observation, lineage)
        if decision.decision != ReplanDecision.REPLAN:
            self.persist_observation(observation)
            return {"error": f"decision={decision.decision.value}, 不 replan"}

        return self._perform_replan(parent, plan, lineage, observation)

    def auto_continue(self, run_id: str) -> Dict[str, Any]:
        """自动 continuation（machine failure 在 safe terminal boundary）。"""
        run = self._repo.get_run(run_id)
        if run is None:
            return {"decision": "no_replan", "reason": "run not found"}
        # 审批拒绝 → 不自动（显式 /replan）
        if run.status == WorkflowRunStatus.REJECTED:
            return {"decision": "no_replan", "reason": "approval_rejected"}
        # 仅 machine failure（FAILED）触发
        if run.status != WorkflowRunStatus.FAILED:
            return {"decision": "no_replan", "reason": f"status={run.status.value}"}

        plan = self._load_plan_from_run(run)
        if plan is None:
            return {"decision": "no_replan", "reason": "no plan"}

        lineage = self._get_or_init_lineage(run)
        observation = self._build_observation(run, plan, lineage)
        decision = self._engine.decide(observation, lineage)

        if decision.decision == ReplanDecision.REPLAN:
            return self._perform_replan(run, plan, lineage, observation)

        # 非 REPLAN 决策（DENY/ABORT/ESCALATE/NO_REPLAN）→ 只记录，不自动 replan
        self.persist_observation(observation)
        return {"decision": decision.decision.value, "reason": decision.reason}

    def _build_observation(self, parent: WorkflowRun, plan: Plan, lineage: ExecutionLineage) -> Observation:
        """根据 parent 状态构造 observation。"""
        parent_state = parent.state if isinstance(parent.state, dict) else {}
        if parent.status == WorkflowRunStatus.REJECTED:
            typ = ObservationType.APPROVAL_REJECTED
            status = ObservationStatus.APPROVAL_REJECTED
        else:
            # 找失败 node
            typ, status = ObservationType.NODE_FAILED, ObservationStatus.FAILURE
            for nr in self._repo.get_node_runs(parent.run_id):
                if nr.status.value in ("failed", "timed_out"):
                    typ = ObservationType.TOOL_FAILED if nr.node_type.value == "action" else ObservationType.NODE_FAILED
                    status = ObservationStatus.FAILURE
                    break
        return Observation(
            observationId=generate_observation_id(parent.run_id),
            planId=plan.planId,
            planVersion=plan.version,
            runId=parent.run_id,
            type=typ,
            status=status,
            scope=ObservationScope.RUN,
            source=ObservationSource.SYSTEM,
        )

    def _perform_replan(
        self,
        parent: WorkflowRun,
        plan: Plan,
        lineage: ExecutionLineage,
        observation: Observation,
    ) -> Dict[str, Any]:
        """执行 revision transaction（build → validate → child cutover → execute）。"""
        completed_refs = self._completed_result_refs(parent.run_id)

        # 构建 v2（carried prefix + suffix）
        v2 = build_revision(plan, completed_refs, parent.run_id)

        # validate
        issues = validate_plan(v2)
        if has_errors(issues):
            self.persist_observation(observation)
            return {"error": "v2 validation failed", "validationIssues": [i.to_dict() for i in issues]}

        # carried result 校验（fail-closed）
        carried_issues = validate_carried_refs(v2, self._repo)
        if carried_issues:
            return {"error": "carried validation failed", "carriedIssues": carried_issues}

        # maxReplans enforcement（execution lineage）
        if not reserve_replan(lineage):
            budget_obs = Observation(
                observationId=generate_observation_id(parent.run_id),
                planId=plan.planId, planVersion=plan.version, runId=parent.run_id,
                type=ObservationType.BUDGET_EXHAUSTED, status=ObservationStatus.BLOCKED,
                scope=ObservationScope.RUN, source=ObservationSource.BUDGET,
            )
            self.persist_observation(budget_obs)
            return {"error": "maxReplans exhausted", "decision": "abort"}

        # 持久化 observation
        self.persist_observation(observation)

        # child lineage 继承（含 replansUsed+1，与 cutover 事务原子提交）
        child_lineage = inherit_lineage(lineage)
        return self._create_and_execute_child(parent, v2, child_lineage, observation)

    def _create_and_execute_child(
        self,
        parent: WorkflowRun,
        v2: Plan,
        child_lineage: ExecutionLineage,
        observation: Observation,
    ) -> Dict[str, Any]:
        """child cutover + execute。"""
        child_run_id = deterministic_child_run_id(child_lineage.rootRunId, observation.observationId)
        child_definition = plan_to_child_definition(v2)

        parent_state = parent.state if isinstance(parent.state, dict) else {}
        carried_refs = {s.stepId: s.resultRef for s in v2.steps if s.metadata.get("carriedForward")}
        child_state = build_child_state(
            parent_state, child_lineage, parent.run_id, parent.version, carried_refs,
        )

        child_run = WorkflowRun(
            run_id=child_run_id, definition_id=v2.planId,
            version=parent.version + 1,  # placeholder，事务内重新分配
            session_id=parent.session_id, event_thread_id=parent.event_thread_id,
            status=WorkflowRunStatus.PENDING, state=child_state,
            triggered_by="replan",
        )

        # 更新 parent state：lineage 指针 + termination metadata
        new_parent_state = dict(parent_state)
        new_parent_state["replannedToRunId"] = child_run_id
        new_parent_state["replannedToVersion"] = parent.version + 1
        new_parent_state["terminationReason"] = "replanned"
        new_parent_state["executionLineage"] = child_lineage.to_dict()
        parent_status = WorkflowRunStatus.REJECTED if parent.status == WorkflowRunStatus.REJECTED else WorkflowRunStatus.FAILED

        try:
            new_version = self._repo.create_child_continuation_tx(
                child_run=child_run,
                parent_run_id=parent.run_id,
                parent_status=parent_status.value,
                parent_state=new_parent_state,
                definition_json=child_definition.to_dict(),
            )
        except Exception as e:
            # 幂等（确定性 run_id PK 冲突）→ 返回既有 child
            existing = self._repo.get_run(child_run_id)
            if existing is not None:
                return {"childRunId": child_run_id, "alreadyReplanned": True}
            return {"error": f"child cutover failed: {e}"}

        # cutover commit 后执行 child
        return self._execute_child(child_run_id, new_version)

    def _execute_child(self, child_run_id: str, version: int) -> Dict[str, Any]:
        from backend.workflow.executor import get_executor
        import asyncio
        executor = get_executor()
        sse = asyncio.run(self._collect(executor.execute_created_run(child_run_id)))
        return {"childRunId": child_run_id, "version": version, "started": True}

    async def _collect(self, agen):
        out = []
        async for s in agen:
            out.append(s)
        return out
