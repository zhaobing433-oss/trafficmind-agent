"""
DB-backed Planning RunDriver — Phase17 Round3

唯一 execution owner（对 planning driver-managed run）。
只 poll / claim / heartbeat / classification / invoke WorkflowExecutor / release。

禁止：执行 Node / 执行 Tool / 实现 approval / 实现 retry / 实现 replan decision。
Node runtime 唯一 = WorkflowExecutor。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from backend.workflow.repository import SQLiteWorkflowRepository


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _lease_until_iso(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class RunDriver:
    """DB-backed polling driver（复用 WaitScheduler claim pattern，扩展到 planning run）。"""

    def __init__(
        self,
        repository: Optional[SQLiteWorkflowRepository] = None,
        owner_id: str = "",
        poll_interval: float = 2.0,
        lease_seconds: float = 60.0,
        heartbeat_interval: float = 20.0,
    ):
        self._repo = repository or SQLiteWorkflowRepository()
        self._owner = owner_id or f"driver_{uuid.uuid4().hex[:8]}"
        self._poll_interval = poll_interval
        self._lease_seconds = lease_seconds
        self._heartbeat_interval = heartbeat_interval
        self._stop_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def owner(self) -> str:
        return self._owner

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._task = asyncio.create_task(self._poll_loop())
        print(f"[RunDriver] 启动，owner={self._owner}，poll={self._poll_interval}s")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        print("[RunDriver] 已停止")

    async def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._poll_once()
            except Exception as e:
                print(f"[RunDriver] poll error: {e}")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
                break
            except asyncio.TimeoutError:
                continue

    async def _poll_once(self) -> None:
        candidates = self._repo.list_driver_candidates(limit=10)
        for run in candidates:
            claim = self._repo.claim_driver_run(
                run.run_id, self._owner, _lease_until_iso(self._lease_seconds)
            )
            if not claim.get("claimed"):
                continue
            asyncio.create_task(self._drive(run.run_id, claim["generation"]))

    async def _drive(self, run_id: str, generation: int) -> None:
        hb = asyncio.create_task(self._heartbeat(run_id, generation))
        try:
            from backend.workflow.executor import get_executor
            executor = get_executor()
            executor.set_driver_context(self._owner, generation)
            fresh = self._repo.get_run(run_id)
            if fresh is None:
                return
            if fresh.status.value == "pending":
                async for _ in executor.execute_created_run(run_id):
                    pass
            elif fresh.status.value == "running":
                await self._recover_running(executor, fresh, generation)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[RunDriver] drive {run_id} error: {e}")
        finally:
            hb.cancel()
            try:
                await hb
            except asyncio.CancelledError:
                pass
            self._repo.release_driver_lease(run_id, self._owner, generation)

    async def _heartbeat(self, run_id: str, generation: int) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            ok = self._repo.heartbeat_driver_lease(
                run_id, self._owner, generation, _lease_until_iso(self._lease_seconds)
            )
            if not ok:
                return  # lease lost（被接管）

    async def _recover_running(self, executor, run, generation: int) -> None:
        """stale RUNNING recovery（lease 过期后由本 driver 接管）。"""
        from backend.workflow.recovery import (
            RecoverySafetyClass,
            RecoverySafetyClassifier,
            detect_unknown_outcome,
        )

        # 1. UNKNOWN_OUTCOME detection（HIGH_RISK dispatch started 无 final result）
        unknowns = detect_unknown_outcome(self._repo, run.run_id)
        if unknowns:
            self._record_unknown_outcome(run, unknowns[0])
            return

        # 2. 分类当前 stale node
        classifier = RecoverySafetyClassifier()
        state = run.state if isinstance(run.state, dict) else {}
        current_node = state.get("currentNode", "") or run.current_node_id
        node_type = self._resolve_node_type(run, current_node)
        action_type = self._resolve_action_type(run, current_node)
        cls = classifier.classify_node(node_type, action_type)

        if cls in (RecoverySafetyClass.READ_ONLY, RecoverySafetyClass.WRITE_IDEMPOTENT):
            # 安全重放：标 stale node failed → resume
            await self._safe_replay(executor, run, current_node, generation)
        else:
            # HIGH_RISK_NON_IDEMPOTENT / UNKNOWN → fail-closed，不 replay
            print(f"[RunDriver] run {run.run_id} node {current_node} 分类 {cls.value}，fail-closed")

    def _resolve_node_type(self, run, node_id: str) -> str:
        for nr in self._repo.get_node_runs(run.run_id):
            if nr.node_id == node_id:
                return nr.node_type.value
        return ""

    def _resolve_action_type(self, run, node_id: str) -> str:
        # 从 definition metadata 找 actionType
        try:
            definition = self._repo.get_definition(run.definition_id)
            if definition is not None:
                for n in definition.nodes:
                    if n.node_id == node_id:
                        return n.config.get("action_type", "")
        except Exception:
            pass
        return ""

    def _record_unknown_outcome(self, run, unknown: Dict[str, Any]) -> None:
        from backend.planning.observation import (
            Observation, ObservationScope, ObservationSource,
            ObservationStatus, ObservationType, generate_observation_id,
        )
        from backend.planning.continuation import PlanningContinuationCoordinator

        coord = PlanningContinuationCoordinator(self._repo)
        obs = Observation(
            observationId=generate_observation_id(run.run_id),
            planId=run.definition_id, planVersion=run.version, runId=run.run_id,
            type=ObservationType.UNKNOWN_OUTCOME, status=ObservationStatus.UNKNOWN,
            scope=ObservationScope.STEP, source=ObservationSource.TOOL,
            stepId=unknown.get("nodeId", ""),
            metadata={"actionType": unknown.get("actionType", ""),
                      "externalOutcomeKnown": False},
        )
        coord.persist_observation(obs)

    async def _safe_replay(self, executor, run, node_id: str, generation: int) -> None:
        """标 stale node failed → 复用 resume 从 current_node 重放。"""
        from backend.workflow.models import NodeStatus, WorkflowNodeRun, WorkflowRunStatus
        from backend.workflow.state import TrafficWorkflowState

        # 标旧 attempt failed（audit）
        node_runs = self._repo.get_node_runs(run.run_id)
        for nr in node_runs:
            if nr.node_id == node_id and nr.status == NodeStatus.RUNNING:
                nr.status = NodeStatus.FAILED
                nr.error = "stale_failed_recovery"
                self._repo.save_node_run(nr)

        # 过渡到 PAUSED 以复用 resume()
        state = TrafficWorkflowState.from_dict(run.state if isinstance(run.state, dict) else {})
        state.transition(WorkflowRunStatus.PAUSED)
        executor._persist_run(run, state)
        async for _ in executor.resume(run.run_id):
            pass


# ── 全局单例 ──────────────────────────────────────────────────────────────

_driver: Optional[RunDriver] = None


def get_run_driver() -> RunDriver:
    """获取 RunDriver 单例（测试可 reset）。间隔可由 env 注入（测试用短间隔）。"""
    import os
    global _driver
    if _driver is None:
        _driver = RunDriver(
            poll_interval=float(os.getenv("RUN_DRIVER_POLL_INTERVAL", "2.0")),
            heartbeat_interval=float(os.getenv("RUN_DRIVER_HEARTBEAT_INTERVAL", "20.0")),
            lease_seconds=float(os.getenv("RUN_DRIVER_LEASE_SECONDS", "60.0")),
        )
    return _driver


def reset_run_driver() -> None:
    """重置（测试用）。"""
    global _driver
    _driver = None
