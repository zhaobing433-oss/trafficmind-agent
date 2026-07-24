"""
Recall Planner — Phase 10 里程碑三

根据 RecallDecision 构建 MemoryRecallPlan，决定召回哪些类型/Key。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from backend.memory.constants import MemoryType


@dataclass
class MemoryRecallPlan:
    """记忆召回计划。"""
    intent: str = "ambiguous"
    session_id: str = ""
    event_thread_id: str = ""
    requested_types: List[str] = field(default_factory=list)
    requested_keys: List[str] = field(default_factory=list)
    include_run_summaries: bool = False
    include_proposals: bool = False
    include_historical_threads: bool = False
    max_items: int = 20
    max_token_estimate: int = 2000
    agent_targets: List[str] = field(default_factory=list)
    filters: Dict[str, Any] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "sessionId": self.session_id,
            "eventThreadId": self.event_thread_id,
            "requestedTypes": self.requested_types,
            "requestedKeys": self.requested_keys,
            "includeRunSummaries": self.include_run_summaries,
            "includeProposals": self.include_proposals,
            "includeHistoricalThreads": self.include_historical_threads,
            "maxItems": self.max_items,
            "maxTokenEstimate": self.max_token_estimate,
            "agentTargets": self.agent_targets,
            "filters": self.filters,
            "reasons": self.reasons,
        }


class RecallPlanner:
    """根据 Intent 构建 Recall Plan。"""

    def build_plan(
        self,
        decision,
        session_id: str,
        active_thread_id: str,
        agent_targets: Optional[List[str]] = None,
    ) -> MemoryRecallPlan:
        """构建召回计划。

        Args:
            decision: MemoryRecallDecision。
            session_id: 当前 Session ID。
            active_thread_id: 当前活跃的 Event Thread ID（None 表示无活跃 Thread）。
            agent_targets: 目标 Agent 列表。
        """
        plan = MemoryRecallPlan(
            intent=decision.primary_intent,
            session_id=session_id,
            event_thread_id=active_thread_id or "",
            agent_targets=agent_targets or [],
        )

        if decision.primary_intent == "fresh_event":
            return self._plan_fresh(plan)

        elif decision.primary_intent == "continue_event":
            return self._plan_continue(plan)

        elif decision.primary_intent == "correction":
            return self._plan_correction(plan, decision)

        elif decision.primary_intent == "previous_decision_query":
            return self._plan_decision_query(plan)

        elif decision.primary_intent == "memory_query":
            return self._plan_memory_query(plan)

        else:  # ambiguous
            return self._plan_ambiguous(plan)

    def _plan_fresh(self, plan: MemoryRecallPlan) -> MemoryRecallPlan:
        plan.requested_types = []
        plan.include_run_summaries = False
        plan.include_proposals = False
        plan.include_historical_threads = False
        plan.max_items = 0
        plan.reasons.append("fresh_event_no_recall")
        return plan

    def _plan_continue(self, plan: MemoryRecallPlan) -> MemoryRecallPlan:
        plan.requested_types = [
            MemoryType.SESSION_GOAL.value,
            MemoryType.STABLE_FACT.value,
            MemoryType.CONSTRAINT.value,
            MemoryType.CONFIRMED_DECISION.value,
            MemoryType.UNRESOLVED_ISSUE.value,
            MemoryType.USER_CORRECTION.value,
        ]
        plan.include_run_summaries = True
        plan.include_proposals = False
        plan.max_items = 20
        plan.filters["run_summary_limit"] = 3
        plan.reasons.append("continue_event_recall_current_thread")
        return plan

    def _plan_correction(
        self, plan: MemoryRecallPlan, decision
    ) -> MemoryRecallPlan:
        plan.requested_types = [
            MemoryType.SESSION_GOAL.value,
            MemoryType.STABLE_FACT.value,
            MemoryType.USER_CORRECTION.value,
        ]
        # Request specific keys if detected
        if decision.corrected_keys:
            for key_hint in decision.corrected_keys:
                if "路" in key_hint:
                    plan.requested_keys.append("road.name")
                if "学校" in key_hint:
                    plan.requested_keys.append("school.nearby")
                if "医院" in key_hint:
                    plan.requested_keys.append("hospital.nearby")
        plan.include_run_summaries = True
        plan.filters["run_summary_limit"] = 1
        plan.reasons.append("correction_recall_targeted")
        return plan

    def _plan_decision_query(self, plan: MemoryRecallPlan) -> MemoryRecallPlan:
        plan.requested_types = [
            MemoryType.CONFIRMED_DECISION.value,
            MemoryType.PROPOSAL.value,
            MemoryType.UNRESOLVED_ISSUE.value,
        ]
        plan.include_proposals = True
        plan.include_run_summaries = True
        plan.filters["run_summary_limit"] = 3
        plan.reasons.append("decision_query_recall")
        return plan

    def _plan_memory_query(self, plan: MemoryRecallPlan) -> MemoryRecallPlan:
        plan.requested_types = [
            MemoryType.RUN_SUMMARY.value,
        ]
        plan.include_run_summaries = True
        plan.include_historical_threads = True
        plan.max_items = 10
        plan.reasons.append("memory_query_recall_historical")
        return plan

    def _plan_ambiguous(self, plan: MemoryRecallPlan) -> MemoryRecallPlan:
        plan.requested_types = []
        plan.max_items = 0
        plan.reasons.append("ambiguous_no_recall")
        return plan
