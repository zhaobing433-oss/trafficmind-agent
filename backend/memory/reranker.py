"""
Memory Reranker — Phase 10 里程碑三

确定性评分排序：scopeMatch(0.25) + authority(0.25) + relevance(0.20) +
freshness(0.15) + taskFit(0.15)
"""

import time
from typing import Any, Dict, List, Optional

from backend.memory.constants import AuthorityLevel, MemoryType


class MemoryReranker:
    """确定性记忆重排序器。

    每个选中项目记录 score / scoreBreakdown / selectedReason。
    """

    def rerank(
        self,
        selected: List,   # List[FilteredItem]
        plan,              # MemoryRecallPlan
        current_event: Dict[str, Any],
    ) -> List:
        """对选中项进行评分排序。

        Args:
            selected: 已筛选通过的 FilteredItem 列表。
            plan: RecallPlan。
            current_event: 当前事件。

        Returns:
            按 finalScore 降序排列的 selected 列表（原地排序 + 返回）。
        """
        for fi in selected:
            item = fi.item
            breakdown = {}

            # 1. scopeMatchScore (0.25)
            scope_score = self._scope_match(item, plan, current_event)
            breakdown["scopeMatchScore"] = scope_score

            # 2. authorityScore (0.25)
            auth_score = self._authority_score(item)
            breakdown["authorityScore"] = auth_score

            # 3. relevanceScore (0.20)
            relevance_score = self._relevance_score(item, current_event)
            breakdown["relevanceScore"] = relevance_score

            # 4. freshnessScore (0.15)
            freshness_score = self._freshness_score(item)
            breakdown["freshnessScore"] = freshness_score

            # 5. taskFitScore (0.15)
            task_fit = self._task_fit_score(item, plan)
            breakdown["taskFitScore"] = task_fit

            final = (
                scope_score * 0.25
                + auth_score * 0.25
                + relevance_score * 0.20
                + freshness_score * 0.15
                + task_fit * 0.15
            )
            fi.score = round(final, 4)
            fi.score_breakdown = breakdown
            fi.selected_reason = self._reason(item, breakdown)

        selected.sort(key=lambda fi: fi.score, reverse=True)
        return selected

    def _scope_match(self, item, plan, current_event: Dict[str, Any]) -> float:
        """scopeMatchScore: 记忆是否属于当前 Thread 且与当前输入相关。"""
        score = 1.0
        event_thread_id = getattr(item, "event_thread_id", "")
        if plan.event_thread_id:
            if event_thread_id == plan.event_thread_id:
                score = 1.0
            elif not event_thread_id:
                score = 0.3  # legacy
            else:
                score = 0.1  # different thread
        return score

    def _authority_score(self, item) -> float:
        """authorityScore: 基于权威等级。"""
        al = item.authority_level
        if al >= AuthorityLevel.USER_CORRECTION:
            return 1.0
        elif al >= AuthorityLevel.HUMAN_REVIEW:
            return 0.9
        elif al >= AuthorityLevel.AGENT_FUSION:
            return 0.7
        elif al >= AuthorityLevel.AGENT_PROPOSAL:
            return 0.5
        elif al >= AuthorityLevel.EVENT_PARSER:
            return 0.3
        return 0.1

    def _relevance_score(self, item, current_event: Dict[str, Any]) -> float:
        """relevanceScore: 记忆内容与当前事件的相关性。"""
        score = 0.5  # default
        value_text = str(item.value).lower()
        event_text = str(current_event).lower()

        # Key overlap: if memory key field appears in current_event
        field_map = {
            "road.name": "roadName",
            "school.nearby": "nearbySchool",
            "hospital.nearby": "nearbyHospital",
        }
        mapped_field = field_map.get(item.memory_key)
        if mapped_field and mapped_field in current_event:
            score = 0.8
            mem_val = str(item.value.get("value", "")).lower()
            curr_val = str(current_event[mapped_field]).lower()
            if mem_val in curr_val or curr_val in mem_val:
                score = 1.0

        # Constraint relevance
        if item.memory_type == "constraint":
            constraint_text = str(item.value).lower()
            if any(kw in event_text for kw in constraint_text.split()[:5]):
                score = max(score, 0.9)

        return score

    def _freshness_score(self, item) -> float:
        """freshnessScore: 基于 created_at 的时间新鲜度。"""
        if not item.created_at:
            return 0.3
        try:
            from backend.memory.time_utils import parse_iso_datetime, utc_now
            created = parse_iso_datetime(item.created_at)
            age_seconds = (utc_now() - created).total_seconds()
            # Decay: 0 seconds → 1.0, 1 hour → 0.5, 1 day → 0.1
            if age_seconds < 60:
                return 1.0
            elif age_seconds < 3600:
                return max(0.1, 1.0 - (age_seconds / 3600) * 0.5)
            else:
                return max(0.05, 1.0 - (age_seconds / 86400))
        except Exception:
            return 0.3

    def _task_fit_score(self, item, plan) -> float:
        """taskFitScore: 记忆类型是否符合当前任务意图。"""
        if plan.intent == "continue_event":
            priority_types = {
                MemoryType.STABLE_FACT.value: 1.0,
                MemoryType.CONSTRAINT.value: 0.9,
                MemoryType.CONFIRMED_DECISION.value: 0.8,
                MemoryType.UNRESOLVED_ISSUE.value: 0.7,
                MemoryType.USER_CORRECTION.value: 0.6,
                MemoryType.SESSION_GOAL.value: 0.5,
            }
            return priority_types.get(item.memory_type, 0.3)

        if plan.intent == "previous_decision_query":
            priority_types = {
                MemoryType.CONFIRMED_DECISION.value: 1.0,
                MemoryType.PROPOSAL.value: 0.9,
                MemoryType.UNRESOLVED_ISSUE.value: 0.7,
            }
            return priority_types.get(item.memory_type, 0.3)

        return 0.5  # default

    def _reason(self, item, breakdown: Dict[str, float]) -> str:
        """简短的解释性说明。"""
        parts = []
        if breakdown.get("scopeMatchScore", 0) < 0.5:
            parts.append("scope_low")
        if breakdown.get("authorityScore", 0) >= 0.9:
            parts.append("high_authority")
        if breakdown.get("relevanceScore", 0) >= 0.9:
            parts.append("high_relevance")
        return "; ".join(parts) if parts else "selected"
