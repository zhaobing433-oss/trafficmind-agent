"""DAG 任务图 — Phase 9.2"""

from typing import Any, Dict, List, Set
from backend.agent.collaboration.roles import is_registered_agent

TASK_STATUSES = {"pending", "ready", "running", "succeeded", "retrying", "skipped", "failed", "timed_out", "blocked"}


class AgentTaskNode:
    def __init__(self, task_id: str, run_id: str, agent_name: str, task_type: str = "analyze",
                 depends_on: List[str] = None, priority: int = 5,
                 max_retries: int = 1, timeout_seconds: int = 30):
        self.task_id = task_id
        self.run_id = run_id
        self.agent_name = agent_name
        self.task_type = task_type
        self.depends_on: List[str] = depends_on or []
        self.status: str = "pending"
        self.priority = priority
        self.attempt: int = 0
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.input_refs: List[str] = []
        self.output_ref: str = ""
        self.started_at: str = ""
        self.completed_at: str = ""
        self.error: str = ""
        self.input_snapshot: Dict[str, Any] = {}
        self.output_snapshot: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {"task_id": self.task_id, "agent_name": self.agent_name, "status": self.status,
                "depends_on": self.depends_on, "attempt": self.attempt, "error": self.error,
                "input_snapshot": self.input_snapshot or {},
                "output_snapshot": self.output_snapshot or {}}


class CollaborationTaskGraph:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.tasks: Dict[str, AgentTaskNode] = {}

    def add_task(self, task: AgentTaskNode):
        if task.task_id in self.tasks:
            raise ValueError(f"重复 task_id: {task.task_id}")
        if not is_registered_agent(task.agent_name):
            raise ValueError(f"Agent 未注册: {task.agent_name}")
        self.tasks[task.task_id] = task

    def validate_dependencies(self):
        for tid, task in self.tasks.items():
            for dep in task.depends_on:
                if dep not in self.tasks:
                    raise ValueError(f"Task '{tid}' 依赖不存在的 '{dep}'")
        self._check_cycles()

    def _check_cycles(self):
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        def dfs(tid):
            visited.add(tid); rec_stack.add(tid)
            for dep in self.tasks[tid].depends_on:
                if dep not in visited:
                    if dfs(dep): return True
                elif dep in rec_stack: return True
            rec_stack.discard(tid); return False
        for tid in self.tasks:
            if tid not in visited:
                if dfs(tid): raise ValueError(f"检测到循环依赖，涉及 task: {tid}")

    def get_ready_tasks(self) -> List[AgentTaskNode]:
        """返回所有依赖已满足且状态为 pending 的任务。"""
        ready = []
        for task in self.tasks.values():
            if task.status != "pending": continue
            if all(self.tasks[dep].status == "succeeded" for dep in task.depends_on):
                ready.append(task)
        return ready

    def mark_running(self, task_id: str):
        t = self._get(task_id)
        if t.status not in ("pending", "retrying"):
            raise ValueError(f"Task {task_id} status={t.status}, cannot mark running")
        t.status = "running"; t.attempt += 1

    def mark_succeeded(self, task_id: str):
        t = self._get(task_id); t.status = "succeeded"

    def mark_failed(self, task_id: str, error: str = ""):
        t = self._get(task_id); t.error = error
        if t.attempt < t.max_retries:
            t.status = "retrying"
        else:
            t.status = "failed"
            self._block_dependents(task_id)

    def mark_skipped(self, task_id: str):
        self._get(task_id).status = "skipped"
        self._block_dependents(task_id)

    def _block_dependents(self, failed_id: str):
        for task in self.tasks.values():
            if failed_id in task.depends_on and task.status == "pending":
                task.status = "blocked"

    def is_completed(self) -> bool:
        return all(t.status in ("succeeded", "skipped") for t in self.tasks.values())

    def has_failed_tasks(self) -> bool:
        return any(t.status == "failed" for t in self.tasks.values())

    def has_blocked_tasks(self) -> bool:
        return any(t.status == "blocked" for t in self.tasks.values())

    def topological_order(self) -> List[str]:
        order: List[str] = []
        visited: Set[str] = set()
        def dfs(tid):
            if tid in visited: return
            visited.add(tid)
            for dep in self.tasks[tid].depends_on:
                if dep in self.tasks: dfs(dep)
            order.append(tid)
        for tid in self.tasks:
            if tid not in visited: dfs(tid)
        return order

    def _get(self, task_id: str) -> AgentTaskNode:
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")
        return self.tasks[task_id]
