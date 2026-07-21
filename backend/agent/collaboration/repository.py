"""运行状态存储 — Phase 9.2 InMemory 实现"""

from typing import Any, Dict, List, Optional


class InMemoryCollaborationRepository:
    def __init__(self):
        self._runs: Dict[str, Any] = {}
        self._messages: Dict[str, List[Dict]] = {}  # run_id -> messages
        self._tasks: Dict[str, Dict[str, Any]] = {}  # run_id -> {task_id: task}

    def save_run(self, state: Any):
        self._runs[state.run_id] = state.to_dict()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        return self._runs.get(run_id)

    def update_run(self, state: Any):
        self._runs[state.run_id] = state.to_dict()

    def save_message(self, run_id: str, message: Dict[str, Any]):
        if run_id not in self._messages:
            self._messages[run_id] = []
        self._messages[run_id].append(message)

    def list_messages(self, run_id: str) -> List[Dict[str, Any]]:
        return self._messages.get(run_id, [])

    def save_task(self, run_id: str, task: Any):
        if run_id not in self._tasks:
            self._tasks[run_id] = {}
        self._tasks[run_id][task.task_id] = task.to_dict()

    def update_task(self, run_id: str, task: Any):
        if run_id not in self._tasks:
            self._tasks[run_id] = {}
        self._tasks[run_id][task.task_id] = task.to_dict()

    def clear(self):
        self._runs.clear(); self._messages.clear(); self._tasks.clear()
