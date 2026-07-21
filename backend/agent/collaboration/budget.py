"""执行预算控制 — Phase 9.2"""

from datetime import datetime
from typing import Dict, Any


class ExecutionBudget:
    def __init__(self, max_agents: int = 6, max_total_tasks: int = 12,
                 max_agent_calls: int = 2, max_tool_calls: int = 0,
                 max_retries: int = 2, max_total_seconds: int = 120, max_llm_calls: int = 5):
        self.max_agents = max_agents
        self.max_total_tasks = max_total_tasks
        self.max_agent_calls = max_agent_calls
        self.max_tool_calls = max_tool_calls
        self.max_retries = max_retries
        self.max_total_seconds = max_total_seconds
        self.max_llm_calls = max_llm_calls

        self.used_agent_calls: Dict[str, int] = {}
        self.used_tool_calls: int = 0
        self.used_retries: Dict[str, int] = {}
        self.used_llm_calls: int = 0
        self.started_at: str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    def can_call_agent(self, agent_name: str) -> bool:
        return self.used_agent_calls.get(agent_name, 0) < self.max_agent_calls

    def record_agent_call(self, agent_name: str):
        self.used_agent_calls[agent_name] = self.used_agent_calls.get(agent_name, 0) + 1

    def can_retry(self, agent_name: str) -> bool:
        return self.used_retries.get(agent_name, 0) < self.max_retries

    def record_retry(self, agent_name: str):
        self.used_retries[agent_name] = self.used_retries.get(agent_name, 0) + 1

    def is_exhausted(self) -> bool:
        elapsed = (datetime.now() - datetime.strptime(self.started_at, "%Y-%m-%dT%H:%M:%S")).total_seconds()
        if elapsed > self.max_total_seconds: return True
        total_calls = sum(self.used_agent_calls.values())
        if total_calls >= self.max_total_tasks: return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {"max_agents": self.max_agents, "max_total_tasks": self.max_total_tasks,
                "used_agent_calls": self.used_agent_calls, "used_retries": self.used_retries,
                "started_at": self.started_at}
