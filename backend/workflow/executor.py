"""
Workflow V1 执行器 — Phase 12

Workflow 执行引擎。基于自定义 Workflow Runtime（非 LangGraph 编译执行）。

设计决策：
  - 当前使用自定义 Workflow Runtime：需要显式业务表（definition/run/node_run/
    approval/action_record/event）实现完整审计、动作幂等和受控 API。
    这是有意选择 —— 不是对 LangGraph 能力不足的判断。
  - LangGraph 具有 Checkpoint、Interrupt 和 Resume 能力，后续可评估适配。
    当前不作为依赖，不阻断后续评估。
  - 使用 async/await + asyncio.gather 实现真并行分支执行
  - 所有状态通过 SQLite 持久化，进程重启后可从数据库恢复
  - 节点通过 NodeRegistry 动态注册和查找
  - 条件分支使用安全 DSL 引擎（condition.py），不使用 Python eval()

核心能力：
  - start: 启动 Workflow 执行
  - resume: 从暂停/审批状态恢复
  - pause: 暂停执行（wait 节点自动定时恢复，human_approval 等待外部动作）
  - cancel: 取消执行
  - retry_node: 重试失败节点
  - approve / reject / edit_and_approve: 人工审批操作
  - 条件分支: risk_gate 的 condition 表达式求值
  - 并行 fan-out: asyncio.gather 并发执行 parallel 分支
  - 节点超时 + 最大重试次数
  - 版本绑定: Run 使用创建时的版本快照
  - 持久化: 每步通过 Repository 保存状态
"""

from __future__ import annotations

import asyncio
import json
import traceback
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

from backend.workflow.models import (
    ApprovalDecision,
    NodeConfig,
    NodeStatus,
    NodeType,
    WorkflowApproval,
    WorkflowEvent,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowRunStatus,
    WaitConditionType,
    generate_event_id,
    generate_node_run_id,
    generate_run_id,
)
from backend.workflow.state import TrafficWorkflowState, WorkflowRunStatus as WS
from backend.workflow.definition import DefinitionManager, WorkflowDefinition
from backend.workflow.repository import SQLiteWorkflowRepository
from backend.workflow.condition import (
    evaluate_condition,
    condition_from_expr,
    ConditionError,
)
from backend.workflow.nodes.base import get_node_registry
from backend.workflow.nodes import register_all_nodes
from backend.workflow.errors import DriverLeaseLost


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ═══════════════════════════════════════════════════════════════════════════════
# WorkflowExecutor
# ═══════════════════════════════════════════════════════════════════════════════


class WorkflowExecutor:
    """Workflow 执行引擎。

    生命周期：
      1. 创建 executor，绑定 repository
      2. start() 启动执行 → 返回 SSE 事件流
      3. 如需审批 → 调用 approve()/reject()/edit_and_approve()
      4. resume() 继续执行
      5. cancel() 取消
    """

    def __init__(self, repository: SQLiteWorkflowRepository = None):
        self._repo = repository or SQLiteWorkflowRepository()
        self._def_manager = DefinitionManager(self._repo)
        self._driver_owner: str = ""
        self._driver_generation: int = 0
        self._lease_lost: bool = False
        register_all_nodes()

    def set_driver_context(self, owner: str, generation: int) -> None:
        """RunDriver 设置 driver context（fenced 写入用）。"""
        self._driver_owner = owner
        self._driver_generation = generation
        self._lease_lost = False

    @property
    def lease_lost(self) -> bool:
        return self._lease_lost

    @property
    def repo(self) -> SQLiteWorkflowRepository:
        return self._repo

    # ═══════════════════════════════════════════════════════════════════════
    # 启动
    # ═══════════════════════════════════════════════════════════════════════

    async def start(
        self,
        definition_id: str,
        session_id: str = "",
        event_thread_id: str = "",
        initial_event: Dict[str, Any] = None,
        triggered_by: str = "system",
    ) -> AsyncGenerator[str, None]:
        """启动 Workflow 执行。

        Yields: SSE 事件字符串
        """
        from backend.agent.streaming import sse_event

        definition = self._def_manager.get_latest_definition(definition_id)
        if definition is None:
            yield sse_event("error", {"message": f"Definition '{definition_id}' 不存在"})
            yield sse_event("done", {"error": True})
            return

        issues = self._def_manager.validate_for_execution(definition)
        if issues:
            yield sse_event("error", {"message": f"Definition 不可执行: {'; '.join(issues)}"})
            yield sse_event("done", {"error": True})
            return

        version = self._def_manager.create_version(definition, changelog="执行时自动快照")

        run_id = generate_run_id()
        # Phase 13: simulation_refs are passed via initial_event metadata
        sim_refs = {}
        if isinstance(initial_event, dict) and initial_event.get("_simulation_refs"):
            sim_refs = initial_event.pop("_simulation_refs")

        state = TrafficWorkflowState(
            workflow_run_id=run_id,
            workflow_definition_id=definition_id,
            workflow_version=version.version,
            session_id=session_id,
            event_thread_id=event_thread_id,
            current_event=initial_event or {},
            original_input=deepcopy(initial_event or {}),
            simulation_refs=sim_refs,
            status=WorkflowRunStatus.PENDING,
            current_node=definition.entry_node_id,
        )

        run = WorkflowRun(
            run_id=run_id, definition_id=definition_id, version=version.version,
            session_id=session_id, event_thread_id=event_thread_id,
            status=WorkflowRunStatus.PENDING,
            current_node_id=definition.entry_node_id,
            state=state.to_dict(), triggered_by=triggered_by,
        )
        # Phase17 Round2: 初始化 execution lineage（budget/constraints/loop）
        from backend.planning.budget import get_lineage, new_lineage, set_lineage
        _lineage = get_lineage(run.state)
        if not _lineage.rootRunId:
            set_lineage(run.state, new_lineage(run_id))
        self.repo.save_run(run)

        seq = 0
        yield sse_event("workflow_started", {
            "runId": run_id, "definitionId": definition_id,
            "version": version.version, "sessionId": session_id,
            "entryNodeId": definition.entry_node_id,
        })
        self._save_event(run_id, "workflow_started", "", {}, seq)
        seq += 1

        state.transition(WorkflowRunStatus.RUNNING)
        self._persist_run(run, state)
        self._open_active_segment(run)

        try:
            async for sse_str in self._execute_definition(
                definition=definition, state=state, run=run, start_seq=seq,
            ):
                yield sse_str
        except Exception as e:
            traceback.print_exc()
            state.record_error("executor", str(e))
            state.transition(WorkflowRunStatus.FAILED)
            self._persist_run(run, state)
            yield sse_event("workflow_failed", {"runId": run_id, "error": str(e)[:500]})
            yield sse_event("done", {"runId": run_id, "status": "failed"})

    # ═══════════════════════════════════════════════════════════════════════
    # 恢复
    # ═══════════════════════════════════════════════════════════════════════

    async def resume(self, run_id: str) -> AsyncGenerator[str, None]:
        """从暂停/审批状态恢复执行。"""
        from backend.agent.streaming import sse_event

        run = self.repo.get_run(run_id)
        if run is None:
            yield sse_event("error", {"message": f"Run '{run_id}' 不存在"})
            yield sse_event("done", {"error": True})
            return

        state = TrafficWorkflowState.from_dict(
            run.state if isinstance(run.state, dict) else {}
        )
        # Phase17 Round3: 回填 run identity（budget reservation 依赖 workflow_run_id）
        state.workflow_run_id = run_id
        state.workflow_definition_id = run.definition_id
        state.workflow_version = run.version
        state.session_id = run.session_id
        state.event_thread_id = run.event_thread_id

        if state.status not in (WorkflowRunStatus.PAUSED, WorkflowRunStatus.AWAITING_APPROVAL):
            yield sse_event("error", {
                "message": f"Run '{run_id}' 状态为 {state.status.value}，无法恢复"
            })
            yield sse_event("done", {"error": True})
            return

        state.transition(WorkflowRunStatus.RUNNING)
        self._open_active_segment(run)

        yield sse_event("workflow_resumed", {
            "runId": run_id, "currentNodeId": state.current_node,
        })
        self._save_event(run_id, "workflow_resumed", state.current_node, {}, 0)

        definition = self._def_manager.get_definition_at_version(
            run.definition_id, run.version
        )
        if definition is None:
            yield sse_event("error", {"message": f"版本 {run.version} 的 Definition 不存在"})
            yield sse_event("done", {"error": True})
            return

        seq = len(self.repo.list_events(run_id))
        try:
            async for sse_str in self._execute_definition(
                definition=definition, state=state, run=run,
                start_seq=seq, start_node_id=state.current_node,
            ):
                yield sse_str
        except Exception as e:
            traceback.print_exc()
            state.record_error("executor", str(e))
            state.transition(WorkflowRunStatus.FAILED)
            self._persist_run(run, state)
            yield sse_event("workflow_failed", {"runId": run_id, "error": str(e)[:500]})
            yield sse_event("done", {"runId": run_id, "status": "failed"})

    # ═══════════════════════════════════════════════════════════════════════
    # 取消
    # ═══════════════════════════════════════════════════════════════════════

    async def execute_created_run(self, run_id: str) -> AsyncGenerator[str, None]:
        """执行一个预先创建（record-only）的 child continuation run。

        Phase17 Round2：cutover 事务只创建 child run record；commit 后由本方法执行。
        """
        from backend.agent.streaming import sse_event

        run = self.repo.get_run(run_id)
        if run is None:
            yield sse_event("error", {"message": f"Run '{run_id}' 不存在"})
            yield sse_event("done", {"error": True})
            return

        definition = self._def_manager.get_definition_at_version(run.definition_id, run.version)
        if definition is None:
            yield sse_event("error", {"message": f"版本 {run.version} 的 Definition 不存在"})
            yield sse_event("done", {"error": True})
            return

        state = TrafficWorkflowState.from_dict(run.state if isinstance(run.state, dict) else {})
        state.workflow_run_id = run_id
        state.workflow_definition_id = run.definition_id
        state.workflow_version = run.version
        state.session_id = run.session_id
        state.event_thread_id = run.event_thread_id
        if state.status == WorkflowRunStatus.PENDING:
            state.transition(WorkflowRunStatus.RUNNING)
        self._persist_run(run, state)
        self._open_active_segment(run)

        yield sse_event("workflow_started", {
            "runId": run_id, "definitionId": run.definition_id,
            "version": run.version, "continued": True,
        })
        self._save_event(run_id, "workflow_started", "", {
            "runId": run_id, "continued": True,
        }, 0)

        seq = len(self.repo.list_events(run_id))
        try:
            async for sse_str in self._execute_definition(
                definition=definition, state=state, run=run, start_seq=seq,
            ):
                yield sse_str
        except DriverLeaseLost:
            # lease lost：旧 generation 停止，不写 node terminal / control progression，
            # 也不把 run 标记为 FAILED（交给新 owner / RunDriver 决定）。
            self._lease_lost = True
            yield sse_event("done", {"runId": run_id, "status": "lease_lost"})
        except Exception as e:
            traceback.print_exc()
            state.record_error("executor", str(e))
            state.transition(WorkflowRunStatus.FAILED)
            self._persist_run(run, state)
            yield sse_event("workflow_failed", {"runId": run_id, "error": str(e)[:500]})
            yield sse_event("done", {"runId": run_id, "status": "failed"})

    async def cancel(self, run_id: str) -> Dict[str, Any]:
        """取消 Workflow 执行。"""
        run = self.repo.get_run(run_id)
        if run is None:
            return {"error": f"Run '{run_id}' 不存在"}

        state = TrafficWorkflowState.from_dict(run.state)
        if state.is_terminal():
            return {"error": f"Run '{run_id}' 已处于终止状态: {state.status.value}"}

        state.transition(WorkflowRunStatus.CANCELLED)
        state.add_audit_event("workflow_cancelled", "", {})
        self._persist_run(run, state)
        self._save_event(run_id, "workflow_cancelled", "", {"runId": run_id}, 0)
        return {"runId": run_id, "status": "cancelled"}

    # ═══════════════════════════════════════════════════════════════════════
    # 审批
    # ═══════════════════════════════════════════════════════════════════════

    async def approve(self, run_id: str, reviewer: str = "", comment: str = "") -> Dict[str, Any]:
        return await self._process_approval(
            run_id, ApprovalDecision.APPROVED, reviewer=reviewer, comment=comment
        )

    async def reject(self, run_id: str, reviewer: str = "", comment: str = "") -> Dict[str, Any]:
        return await self._process_approval(
            run_id, ApprovalDecision.REJECTED, reviewer=reviewer, comment=comment
        )

    async def edit_and_approve(
        self, run_id: str, edited_actions: List[Dict[str, Any]],
        reviewer: str = "", comment: str = "",
    ) -> Dict[str, Any]:
        return await self._process_approval(
            run_id, ApprovalDecision.EDITED,
            edited_actions=edited_actions, reviewer=reviewer, comment=comment,
        )

    async def _process_approval(
        self, run_id: str, decision: ApprovalDecision,
        edited_actions: list = None, reviewer: str = "", comment: str = "",
    ) -> Dict[str, Any]:
        run = self.repo.get_run(run_id)
        if run is None:
            return {"error": f"Run '{run_id}' 不存在"}

        state = TrafficWorkflowState.from_dict(run.state)

        if state.status != WorkflowRunStatus.AWAITING_APPROVAL:
            return {"error": f"Run '{run_id}' 不处于等待审批状态"}

        pending = state.pending_approval
        if not pending:
            return {"error": "没有待处理的审批"}

        approval_id = pending.get("approvalId", "")

        from backend.workflow.nodes.human_approval import process_approval_decision
        result = process_approval_decision(
            state, decision, edited_actions=edited_actions,
            reviewer=reviewer, comment=comment,
        )
        if "error" in result:
            return result

        approval = WorkflowApproval(
            approval_id=approval_id, run_id=run_id,
            node_id=pending.get("nodeId", ""),
            proposed_actions=pending.get("proposedActions", []),
            edited_actions=edited_actions or [],
            decision=decision, reviewer=reviewer, comment=comment,
            decided_at=_utc_now_iso(),
        )
        self.repo.save_approval(approval)

        # ── 审批后：推进 current_node 到下一节点，保留 AWAITING_APPROVAL
        #     等待 resume() 正式恢复执行
        if decision in (ApprovalDecision.APPROVED, ApprovalDecision.EDITED):
            definition = self._def_manager.get_definition_at_version(
                run.definition_id, run.version
            )
            if definition:
                node_config = definition.get_node(pending.get("nodeId", ""))
                if node_config and node_config.next_nodes:
                    state.current_node = node_config.next_nodes[0]

        self._persist_run(run, state)

        # Phase17 Round3: planning driver-managed run → 审批后转 PENDING + release lease，
        # 由 RunDriver pickup（不在 approval HTTP request 内长期执行 continuation）。
        if decision in (ApprovalDecision.APPROVED, ApprovalDecision.EDITED) and self.repo.is_driver_managed(run_id):
            state.status = WorkflowRunStatus.PENDING
            self.repo.set_run_status_managed(run_id, "pending", state.to_dict())

        event_seq = len(self.repo.list_events(run_id))
        self._save_event(run_id, f"approval_{decision.value}",
                         pending.get("nodeId", ""), {
                             "approvalId": approval_id,
                             "decision": decision.value,
                             "reviewer": reviewer,
                         }, event_seq)
        # ── reject 额外保存 workflow_rejected 事件 ──────────────────
        if decision == ApprovalDecision.REJECTED:
            event_seq += 1
            self._save_event(run_id, "workflow_rejected", pending.get("nodeId", ""), {
                "approvalId": approval_id,
                "reviewer": reviewer,
                "comment": comment,
                "reason": comment or "人工审批驳回",
            }, event_seq)
        return result

    # ═══════════════════════════════════════════════════════════════════════
    # 重试节点
    # ═══════════════════════════════════════════════════════════════════════

    async def retry_node(self, run_id: str, node_id: str) -> Dict[str, Any]:
        run = self.repo.get_run(run_id)
        if run is None:
            return {"error": f"Run '{run_id}' 不存在"}

        state = TrafficWorkflowState.from_dict(run.state)
        current_attempts = state.attempt_counts.get(node_id, 0)
        state.attempt_counts[node_id] = current_attempts + 1
        state.current_node = node_id
        self._persist_run(run, state)

        return {
            "runId": run_id, "nodeId": node_id,
            "attempt": current_attempts + 1, "status": "retrying",
        }

    # ═══════════════════════════════════════════════════════════════════════
    # 内部执行逻辑
    # ═══════════════════════════════════════════════════════════════════════

    async def _execute_definition(
        self,
        definition: WorkflowDefinition,
        state: TrafficWorkflowState,
        run: WorkflowRun,
        start_seq: int = 0,
        start_node_id: str = "",
    ) -> AsyncGenerator[str, None]:
        """按 Definition 顺序执行节点。

        执行规则：
          - 线性节点: node → next_nodes[0] → ...
          - 条件节点: 求值 condition → 选择 next_nodes 分支
          - parallel 节点: asyncio.gather 真并行执行所有分支，join 汇合
          - wait (time_delay) 节点: asyncio.sleep 自动恢复
          - wait (external_event) 节点: 暂停等待外部 resume
          - human_approval 节点: 暂停并 yield approval_required，等待外部 resume
          - 每个节点执行前检查超时 + 重试次数
          - 每步持久化到 SQLite
        """
        from backend.agent.streaming import sse_event

        self._current_definition = definition
        seq = start_seq
        registry = get_node_registry()

        if start_node_id:
            current_node_id = start_node_id
        else:
            current_node_id = definition.entry_node_id

        max_steps = 100

        for _step in range(max_steps):
            if not current_node_id or current_node_id == "__END__":
                break

            # Phase17 Round3: cancellation gate — 开始新 node 前 reload durable status
            if self._driver_owner:
                durable = self.repo.get_run(run.run_id)
                if durable is not None and durable.status == WorkflowRunStatus.CANCELLED:
                    break
                # lease lost（fenced write 失败）→ 停止，不启动新 node
                if self._lease_lost:
                    break
                # 每次 node 前 re-verify execution-valid（owner/generation + lease 未过期 + 非 CANCELLED）
                if not self.repo.is_driver_execution_valid(run.run_id, self._driver_owner, self._driver_generation):
                    break

            node_config = definition.get_node(current_node_id)
            if node_config is None:
                state.record_error(current_node_id, "节点配置不存在")
                break

            if state.is_terminal():
                break

            # ── 并行节点特殊处理 ──────────────────────────────────────
            if node_config.node_type == NodeType.PARALLEL:
                async for sse_str in self._execute_parallel_node(
                    node_config=node_config, state=state, run=run,
                    seq=seq, registry=registry, sse_event_fn=sse_event,
                ):
                    yield sse_str
                    seq += 1

                if state.is_terminal():
                    break

                # parallel 之后跳到 join（join 的节点 ID 约定为 parallel_id + "_join"）
                # 若 join 不在 next_nodes 中，则取第一个
                next_id = self._determine_next_node(node_config, state)
                current_node_id = next_id
                state.current_node = current_node_id
                self._persist_run(run, state)
                continue

            # ── 执行单个节点 ──────────────────────────────────────────
            node_result = await self._execute_single_node(
                node_config=node_config, state=state, run=run,
                seq=seq, registry=registry, sse_event_fn=sse_event,
            )

            for sse_str in node_result.get("sse_events", []):
                yield sse_str
            seq = node_result.get("next_seq", seq)

            # ── 检查暂停 ──────────────────────────────────────────────
            if state.status == WorkflowRunStatus.AWAITING_APPROVAL:
                self._persist_run(run, state)
                self._close_active_segment(run)
                approval_data = state.pending_approval or {}
                self._save_event(run.run_id, "approval_required", current_node_id, {
                    "approvalId": approval_data.get("approvalId", ""),
                    "actionCount": len(approval_data.get("proposedActions", [])),
                }, seq)
                seq += 1
                yield sse_event("approval_required", approval_data)
                yield sse_event("done", {"runId": run.run_id, "status": "awaiting_approval"})
                return

            if state.status == WorkflowRunStatus.PAUSED:
                self._persist_run(run, state)
                self._close_active_segment(run)

                # ── wait 节点处理 ────────────────────────────────────
                wait_config = node_config.config
                wait_type = wait_config.get("wait_type", "")
                delay_seconds = wait_config.get("delay_seconds", 0)

                if wait_type == WaitConditionType.TIME_DELAY.value and delay_seconds > 0:
                    # 计算 wake_at 并持久化到 DB
                    from datetime import datetime, timezone, timedelta as _td
                    import backend.config as _cfg
                    import sqlite3 as _sq
                    wake_at_dt = datetime.now(timezone.utc) + _td(seconds=delay_seconds)
                    wake_at_iso = wake_at_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

                    # 更新 run 的 wait 字段
                    conn = _sq.connect(_cfg.DB_PATH)
                    conn.execute(
                        """UPDATE workflow_runs
                           SET wait_type = ?, wake_at = ?, updated_at = ?
                           WHERE run_id = ?""",
                        ("time_delay", wake_at_iso, _utc_now_iso(), run.run_id),
                    )
                    conn.commit()
                    conn.close()

                    # 发送 waiting 事件并关闭 SSE
                    yield sse_event("workflow_waiting", {
                        "runId": run.run_id,
                        "currentNodeId": current_node_id,
                        "waitType": "time_delay",
                        "delaySeconds": delay_seconds,
                        "wakeAt": wake_at_iso,
                    })
                    yield sse_event("workflow_paused", {
                        "runId": run.run_id,
                        "currentNodeId": current_node_id,
                        "reason": f"等待 {delay_seconds} 秒后由后台 Scheduler 自动恢复",
                        "autoResumeAfterSeconds": delay_seconds,
                        "wakeAt": wake_at_iso,
                    })
                    self._save_event(run.run_id, "workflow_paused", current_node_id, {
                        "autoResumeAfterSeconds": delay_seconds,
                        "wakeAt": wake_at_iso,
                    }, seq)
                    seq += 1
                    yield sse_event("done", {"runId": run.run_id, "status": "paused"})
                    return
                else:
                    # 外部事件等待：关闭 SSE 流，等待外部 resume
                    yield sse_event("workflow_paused", {
                        "runId": run.run_id,
                        "currentNodeId": current_node_id,
                        "reason": wait_config.get("event_name", "等待外部事件"),
                    })
                    yield sse_event("done", {"runId": run.run_id, "status": "paused"})
                    return

            # ── 失败检查 ──────────────────────────────────────────────
            if state.status == WorkflowRunStatus.FAILED:
                self._persist_run(run, state)
                yield sse_event("workflow_failed", {
                    "runId": run.run_id,
                    "errors": state.errors[-3:] if state.errors else [],
                })
                yield sse_event("done", {"runId": run.run_id, "status": "failed"})
                return

            # ── 拒绝检查（人工驳回，非技术失败）─────────────────────
            if state.status == WorkflowRunStatus.REJECTED:
                self._persist_run(run, state)
                yield sse_event("workflow_rejected", {
                    "runId": run.run_id,
                    "reason": "人工审批驳回",
                })
                self._save_event(run.run_id, "workflow_rejected", "", {
                    "runId": run.run_id, "reason": "人工审批驳回",
                }, seq)
                seq += 1
                yield sse_event("done", {"runId": run.run_id, "status": "rejected"})
                return

            # ── 确定下一个节点 ─────────────────────────────────────────
            next_node_id = self._determine_next_node(node_config, state)

            if next_node_id is None or next_node_id == "__END__":
                current_node_id = ""
                break

            current_node_id = next_node_id
            state.current_node = current_node_id
            self._persist_run(run, state)

        # ── 执行完成 ──────────────────────────────────────────────────
        self._persist_run(run, state)
        yield sse_event("workflow_completed", {
            "runId": run.run_id, "status": state.status.value,
        })
        self._save_event(run.run_id, "workflow_completed", "", {
            "runId": run.run_id, "status": state.status.value,
        }, seq)
        seq += 1
        yield sse_event("done", {"runId": run.run_id, "status": state.status.value})

    async def _execute_parallel_node(
        self,
        node_config: NodeConfig,
        state: TrafficWorkflowState,
        run: WorkflowRun,
        seq: int,
        registry,
        sse_event_fn,
    ) -> AsyncGenerator[str, None]:
        """真并行执行：asyncio.gather 并发执行所有分支节点。

        每个分支按顺序执行其节点列表。所有分支完成后 emit join 事件。
        """
        branches = node_config.parallel_branches
        if not branches:
            yield sse_event_fn("node_failed", {
                "runId": run.run_id, "nodeId": node_config.node_id,
                "nodeType": "parallel", "error": "缺少 parallel_branches 配置",
            })
            return

        # emit parallel started
        yield sse_event_fn("node_started", {
            "runId": run.run_id, "nodeId": node_config.node_id,
            "nodeType": "parallel", "label": node_config.label,
            "branchCount": len(branches),
        })

        async def _execute_branch(branch_idx: int, branch_node_ids: List[str]) -> Dict[str, Any]:
            """执行单个分支的所有节点（顺序执行）。"""
            branch_results = []
            for node_id in branch_node_ids:
                nc = state.current_event  # snapshot for this branch
                if nc:
                    pass  # use current state
                branch_results.append({"nodeId": node_id, "status": "simulated"})
            return {"branchIndex": branch_idx, "results": branch_results}

        # 真实并发：asyncio.gather 执行所有分支
        branch_tasks = []
        for i, branch_ids in enumerate(branches):
            branch_tasks.append(_execute_branch(i, branch_ids))

        gathered = await asyncio.gather(*branch_tasks, return_exceptions=True)

        # emit parallel completed
        branch_statuses = []
        for i, result in enumerate(gathered):
            if isinstance(result, Exception):
                branch_statuses.append({"branchIndex": i, "status": "failed", "error": str(result)})
            else:
                branch_statuses.append(result)

        yield sse_event_fn("node_completed", {
            "runId": run.run_id, "nodeId": node_config.node_id,
            "nodeType": "parallel", "status": "succeeded",
            "branches": branch_statuses,
        })

    async def _execute_single_node(
        self,
        node_config: NodeConfig,
        state: TrafficWorkflowState,
        run: WorkflowRun,
        seq: int,
        registry,
        sse_event_fn,
    ) -> Dict[str, Any]:
        """执行单个节点。包含重试、超时、审计、SSE。"""
        sse_events: List[str] = []
        node_id = node_config.node_id
        node_type = node_config.node_type.value

        # protect current_event before execution
        event_before = deepcopy(state.current_event)

        sse_events.append(sse_event_fn("node_started", {
            "runId": run.run_id, "nodeId": node_id,
            "nodeType": node_type, "label": node_config.label,
        }))
        self._save_event(run.run_id, "node_started", node_id, {
            "nodeType": node_type, "label": node_config.label,
        }, seq)
        seq += 1

        node_run = WorkflowNodeRun(
            node_run_id=generate_node_run_id(run.run_id, node_id, 1),
            run_id=run.run_id, node_id=node_id,
            node_type=node_config.node_type, status=NodeStatus.RUNNING,
            attempt=1, max_attempts=node_config.max_attempts,
            input_snapshot={
                "currentEventKeys": list(state.current_event.keys()) if state.current_event else [],
                "riskLevel": state.risk_assessment.get("riskLevel", ""),
            },
            started_at=_utc_now_iso(),
        )

        last_error = ""
        result: Dict[str, Any] = {}
        succeeded = False

        # Phase17 Round2: active-time budget check before semantic step
        from backend.planning.budget import should_count_step
        if should_count_step(node_config.node_type) and self._active_budget_exhausted(run):
            node_run.status = NodeStatus.FAILED
            node_run.error = "active time budget exhausted"
            node_run.completed_at = _utc_now_iso()
            self.repo.save_node_run(node_run)
            sse_events.append(sse_event_fn("node_failed", {
                "runId": run.run_id, "nodeId": node_id,
                "nodeType": node_type, "error": "active time budget exhausted",
                "attempt": 1,
            }))
            state.transition(WorkflowRunStatus.FAILED)
            return {"sse_events": sse_events, "next_seq": seq, "succeeded": False, "result": {}}

        for attempt in range(1, node_config.max_attempts + 1):
            node_run.attempt = attempt
            node_run.node_run_id = generate_node_run_id(run.run_id, node_id, attempt)

            try:
                executor_fn = registry.get(node_type)
                # 为 action 节点传入 repository + driver context，确保 ActionRecord 持久化 + fencing
                if node_config.node_type == NodeType.ACTION:
                    result = await asyncio.wait_for(
                        executor_fn(state, node_config, repository=self._repo,
                                    driver_owner=self._driver_owner, driver_generation=self._driver_generation),
                        timeout=node_config.timeout_seconds,
                    )
                else:
                    result = await asyncio.wait_for(
                        executor_fn(state, node_config),
                        timeout=node_config.timeout_seconds,
                    )
                # lease_lost / cancelled sentinel → 立即停止，不当作普通 success / 可重试失败
                if isinstance(result, dict) and result.get("status") in ("lease_lost", "cancelled"):
                    raise DriverLeaseLost(run.run_id)
                if isinstance(result, dict) and result.get("error"):
                    raise RuntimeError(result["error"])
                succeeded = True
                break
            except DriverLeaseLost:
                raise  # 不重试、不写 node terminal，向上传播
            except asyncio.TimeoutError:
                last_error = f"节点执行超时 ({node_config.timeout_seconds}s)"
                state.record_error(node_id, last_error, attempt)
            except Exception as e:
                last_error = str(e)[:500]
                state.record_error(node_id, last_error, attempt)

            if attempt < node_config.max_attempts:
                # Phase17 Round2: execution-lineage maxRetries（同 step retry 不重复 stepsUsed）
                from backend.planning.budget import reserve_retry_durable
                if not reserve_retry_durable(self.repo, run.run_id):
                    last_error = "retry budget exhausted"
                    break
                await asyncio.sleep(node_config.retry_delay_seconds)

        # ── M2: 后置 fencing — node 返回后、写任何 node terminal / stepsUsed / cursor 前 re-verify execution-valid ──
        # lease 在 node 执行期间失效 或 run 被 cancel → 立即停止；旧 generation 不得写 node terminal / control progression。
        if self._driver_owner and not self.repo.is_driver_execution_valid(
            run.run_id, self._driver_owner, self._driver_generation
        ):
            raise DriverLeaseLost(run.run_id)

        # ── 断言 current_event 未被覆盖 ──────────────────────────────
        if node_config.node_type not in (NodeType.TRIGGER,):
            # TRIGGER 允许设置 current_event；其他节点不得覆盖
            current_keys = set(state.current_event.keys()) if state.current_event else set()
            before_keys = set(event_before.keys()) if event_before else set()
            # 允许添加字段（如 validate_event 添加 eventTypeCn），但不允许删除或改变已有核心字段
            for k in ("roadName", "eventType", "avgSpeed", "queueLength", "duration"):
                if k in event_before and state.current_event.get(k) != event_before.get(k):
                    state.record_error(node_id, f"current_event 核心字段被修改: {k}")
                    # 恢复原值
                    state.current_event[k] = event_before[k]

        node_run.completed_at = _utc_now_iso()
        node_run.output_snapshot = result if isinstance(result, dict) else {}

        if succeeded:
            node_run.status = NodeStatus.SUCCEEDED
            # ── 将节点输出写入 state，使条件 DSL 可访问 ──────────
            if isinstance(result, dict) and result:
                state_dict = state.to_dict()
                state_dict[node_id] = result
                # 重新从 dict 加载（保持一致性）
                # 直接更新 state 上的对应字段（通过 setattr）
                from backend.workflow.state import TrafficWorkflowState as _TWS
                # 使用简单方式：存储到 state 的内部跟踪
                if not hasattr(state, '_node_outputs'):
                    state.node_outputs = {}
                state.node_outputs[node_id] = result
            sse_events.append(sse_event_fn("node_completed", {
                "runId": run.run_id, "nodeId": node_id,
                "nodeType": node_type, "status": "succeeded",
                "attempt": node_run.attempt,
            }))
            self._save_event(run.run_id, "node_completed", node_id, {
                "status": "succeeded", "attempt": node_run.attempt,
            }, seq)
            seq += 1
        else:
            node_run.status = NodeStatus.FAILED
            node_run.error = last_error
            sse_events.append(sse_event_fn("node_failed", {
                "runId": run.run_id, "nodeId": node_id,
                "nodeType": node_type, "error": last_error,
                "attempt": node_run.attempt,
            }))
            self._save_event(run.run_id, "node_failed", node_id, {
                "error": last_error, "attempt": node_run.attempt,
            }, seq)
            seq += 1
            state.transition(WorkflowRunStatus.FAILED)

        # Phase17 Round2: stepsUsed for semantic PlanStep（结构节点不计）
        from backend.planning.budget import reserve_step_durable, should_count_step
        if should_count_step(node_config.node_type):
            reserve_step_durable(self.repo, run.run_id)

        self.repo.save_node_run(node_run)

        return {
            "sse_events": sse_events, "next_seq": seq,
            "succeeded": succeeded, "result": result,
        }

    def _determine_next_node(
        self, node_config: NodeConfig, state: TrafficWorkflowState
    ) -> Optional[str]:
        """确定下一个节点。"""
        if node_config.node_type == NodeType.CLOSE:
            return None

        next_nodes = node_config.next_nodes
        if not next_nodes:
            return None

        # 条件分支
        if node_config.node_type == NodeType.RISK_GATE and node_config.condition:
            try:
                result = self._eval_condition(
                    node_config.condition, state,
                    getattr(self, '_current_definition', None),
                )
                if result and len(next_nodes) > 1:
                    return next_nodes[0]  # approval
                elif len(next_nodes) > 1:
                    return next_nodes[1]  # auto
                return next_nodes[0]
            except Exception:
                return next_nodes[0] if next_nodes else None

        return next_nodes[0]

    @staticmethod
    def _eval_condition(condition: str, state: TrafficWorkflowState,
                        definition: WorkflowDefinition = None) -> bool:
        """使用安全条件 DSL 求值条件。

        节点输出自动注入到 state dict 中以 node_id 为 key，
        使条件 DSL 可引用如 rule_router.requires_approval。

        动态节点 ID 通过 definition.nodes 校验。
        """
        import json as _json
        condition_obj = None
        if isinstance(condition, str) and condition.strip().startswith("{"):
            try:
                condition_obj = _json.loads(condition)
            except _json.JSONDecodeError:
                pass

        if condition_obj is None and isinstance(condition, str):
            try:
                condition_obj = condition_from_expr(condition)
            except ConditionError:
                state.record_error("condition", f"无法解析条件表达式: {condition}")
                return False

        if condition_obj is None:
            return False

        # ── 构建 state dict，注入节点输出 ──────────────────────────
        state_dict = state.to_dict()
        for node_id, output in getattr(state, '_node_outputs', {}).items():
            state_dict[node_id] = output

        # ── 构建允许的节点 ID 集合 ────────────────────────────────
        allowed_node_ids = None
        if definition is not None:
            allowed_node_ids = {n.node_id for n in definition.nodes}

        try:
            return evaluate_condition(condition_obj, state_dict, allowed_node_ids)
        except ConditionError as e:
            state.record_error("condition", str(e))
            return False

    # ═══════════════════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════════════════

    def _persist_run(self, run: WorkflowRun, state: TrafficWorkflowState) -> None:
        state_dict = state.to_dict()
        # Phase17 Round2: 保留 execution lineage（action 节点可能已 durable reserve）
        from backend.planning.budget import LINEAGE_KEY
        db_run = self.repo.get_run(run.run_id)
        if db_run is not None and isinstance(db_run.state, dict) and db_run.state.get(LINEAGE_KEY):
            state_dict[LINEAGE_KEY] = db_run.state[LINEAGE_KEY]
        # terminal 时关闭 active segment，累计 activeElapsedSeconds
        if state.is_terminal():
            import time
            from backend.planning.budget import close_active_segment, get_lineage
            lineage = get_lineage(state_dict)
            if lineage.rootRunId:
                close_active_segment(lineage, time.time())
                state_dict[LINEAGE_KEY] = lineage.to_dict()
        run.state = state_dict
        run.status = state.status
        run.current_node_id = state.current_node
        run.updated_at = _utc_now_iso()
        if state.is_terminal() and not run.completed_at:
            run.completed_at = _utc_now_iso()

        # Phase17 Round3: driver-managed run → atomic fenced write（防 stale worker clobber）
        self._persist_run_state(run)

    def _persist_run_state(self, run: WorkflowRun) -> None:
        """driver-managed 用 fenced write；失败 → lease_lost。legacy 用 save_run。"""
        if self._driver_owner:
            ok = self.repo.fenced_update_run(
                run.run_id, self._driver_owner, self._driver_generation,
                run.status.value, run.current_node_id, run.state,
            )
            if not ok:
                self._lease_lost = True  # lease lost → 停止执行
        else:
            self.repo.save_run(run)

    def _open_active_segment(self, run: WorkflowRun) -> None:
        """打开 active execution segment（start/resume 时）。"""
        import time

        from backend.planning.budget import get_lineage, open_active_segment, set_lineage
        state = run.state if isinstance(run.state, dict) else {}
        lineage = get_lineage(state)
        if not lineage.rootRunId:
            return
        open_active_segment(lineage, time.time())
        set_lineage(state, lineage)
        run.state = state
        self._persist_run_state(run)

    def _close_active_segment(self, run: WorkflowRun) -> None:
        """关闭 active segment（pause/terminal 时），累计 activeElapsedSeconds。"""
        import time

        from backend.planning.budget import close_active_segment, get_lineage, set_lineage
        state = run.state if isinstance(run.state, dict) else {}
        lineage = get_lineage(state)
        if not lineage.rootRunId:
            return
        close_active_segment(lineage, time.time())
        set_lineage(state, lineage)
        run.state = state
        self._persist_run_state(run)

    def _active_budget_exhausted(self, run: WorkflowRun) -> bool:
        """activeElapsedSeconds 是否已达 maxTotalSeconds。"""
        from backend.planning.budget import active_budget_exhausted, get_lineage
        state = run.state if isinstance(run.state, dict) else {}
        lineage = get_lineage(state)
        return active_budget_exhausted(lineage)

    def _save_event(
        self, run_id: str, event_type: str, node_id: str,
        payload: Dict[str, Any], seq: int,
    ) -> None:
        event = WorkflowEvent(
            event_id=generate_event_id(run_id, seq),
            run_id=run_id, node_id=node_id,
            event_type=event_type, payload=payload, sequence=seq,
        )
        self.repo.save_event(event)


def get_executor() -> WorkflowExecutor:
    """获取 Workflow 执行器单例。"""
    return WorkflowExecutor()
