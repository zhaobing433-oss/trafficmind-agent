"""
Recall Intent Classifier — Phase 10 里程碑三

确定性规则分类器：判断用户意图是 continue / fresh / correction /
previous_decision_query / memory_query / ambiguous。

优先级：correction > fresh > previous_decision > continue > memory_query > ambiguous
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ================================================================
# Models
# ================================================================

@dataclass
class MemoryRecallDecision:
    """召回决策结果。"""
    primary_intent: str = "ambiguous"
    continue_previous_event: bool = False
    starts_new_event: bool = False
    has_correction: bool = False
    queries_previous_decision: bool = False
    explicit_memory_query: bool = False
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)
    detected_entities: Dict[str, str] = field(default_factory=dict)
    corrected_keys: List[str] = field(default_factory=list)
    current_event_thread_id: str = ""
    previous_event_thread_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primaryIntent": self.primary_intent,
            "continuePreviousEvent": self.continue_previous_event,
            "startsNewEvent": self.starts_new_event,
            "hasCorrection": self.has_correction,
            "queriesPreviousDecision": self.queries_previous_decision,
            "explicitMemoryQuery": self.explicit_memory_query,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "detectedEntities": self.detected_entities,
            "correctedKeys": self.corrected_keys,
            "currentEventThreadId": self.current_event_thread_id,
            "previousEventThreadId": self.previous_event_thread_id,
        }


# ================================================================
# Keyword patterns
# ================================================================

CONTINUE_KEYWORDS = [
    "继续", "基于刚才", "上述", "前面的", "同一路口",
    "沿用", "还是刚才", "第二种方案", "继续研判", "在此基础上",
    "在此基础上继续", "接下来", "再分析一下", "补充分析",
]

FRESH_EVENT_KEYWORDS = [
    "另外", "换一个问题", "新的问题", "再分析另一个",
    "现在改为分析", "重新研判另一路段", "与前述无关", "新事件",
    "改为研判", "切换", "换个路口", "换一个事件",
]

CORRECTION_KEYWORDS = [
    "刚才说错了", "更正", "改成", "应该是",
    "前面有误", "修改为", "不是", "而是",
    "纠正", "改一下", "前面的信息有误",
]

PREVIOUS_DECISION_KEYWORDS = [
    "上一轮", "刚才的方案", "之前建议", "已确认",
    "仲裁结果", "采用了", "前面的决策",
    "之前确认", "上轮", "采用了什么方案", "哪个方案",
]

MEMORY_QUERY_KEYWORDS = [
    "第一轮", "之前分析", "回顾前面", "前面",
    "对比上", "历史研判", "之前是怎么分析", "总结前面",
    "分析了什么",
]


# ================================================================
# RecallClassifier
# ================================================================

class RecallClassifier:
    """确定性 Recall Intent 分类器。

    不依赖 LLM，全部规则可解释。
    """

    def classify(
        self,
        user_input: str,
        current_event: Dict[str, Any],
        session_state: Optional[Dict[str, Any]] = None,
        active_thread: Optional[Dict[str, Any]] = None,
        context_policy: Optional[str] = None,
    ) -> MemoryRecallDecision:
        """分类用户意图。

        Args:
            user_input: 当前用户输入文本。
            current_event: 当前消息解析的结构化事件。
            session_state: 当前 Session 的 Memory 状态（含 active_event_thread_id）。
            active_thread: 当前活跃的 Event Thread（或 None）。
            context_policy: 前端传入的 hint（仅作参考，不可强制覆盖）。

        Returns:
            MemoryRecallDecision
        """
        decision = MemoryRecallDecision()
        if active_thread:
            decision.current_event_thread_id = active_thread.get("id", "")

        # ===== Priority 1: Correction =====
        has_correction = any(kw in user_input for kw in CORRECTION_KEYWORDS)
        if has_correction:
            decision.primary_intent = "correction"
            decision.has_correction = True
            decision.continue_previous_event = True
            decision.confidence = 0.95
            decision.reasons.append("correction_keywords_detected")

            # Detect corrected keys
            for kw in ["路", "街", "学校", "医院", "路口", "方向"]:
                if kw in user_input:
                    decision.corrected_keys.append(kw)

            return decision

        # ===== Priority 2: Fresh event =====
        has_fresh_kw = any(kw in user_input for kw in FRESH_EVENT_KEYWORDS)
        # Entity conflict check
        has_entity_conflict = False
        if active_thread and current_event.get("roadName"):
            current_road = current_event.get("roadName", "")
            # Check if this is a new road name not matching the thread
            if current_road not in ("未知路段", "未命名路段", "未命名"):
                thread_title = active_thread.get("title", "")
                # Simple check: if roadName not in thread title and not a correction
                if current_road not in thread_title and not has_correction:
                    has_entity_conflict = True

        if has_fresh_kw:
            decision.primary_intent = "fresh_event"
            decision.starts_new_event = True
            decision.confidence = 0.9 if has_entity_conflict else 0.75
            decision.reasons.append("fresh_event_keywords")
            if has_entity_conflict:
                decision.reasons.append("entity_conflict_with_current_thread")
            return decision

        # ===== Priority 3: Previous decision query =====
        if any(kw in user_input for kw in PREVIOUS_DECISION_KEYWORDS):
            decision.primary_intent = "previous_decision_query"
            decision.queries_previous_decision = True
            decision.continue_previous_event = True
            decision.confidence = 0.85
            decision.reasons.append("previous_decision_keywords")
            return decision

        # ===== Priority 4: Memory query =====
        if any(kw in user_input for kw in MEMORY_QUERY_KEYWORDS):
            decision.primary_intent = "memory_query"
            decision.explicit_memory_query = True
            decision.confidence = 0.8
            decision.reasons.append("memory_query_keywords")
            return decision

        # ===== Priority 5: Entity conflict → fresh_if_strong =====
        if has_entity_conflict and not has_continue_kw(user_input):
            decision.primary_intent = "fresh_event"
            decision.starts_new_event = True
            decision.confidence = 0.65
            decision.reasons.append("new_road_detected_without_continue_context")
            return decision

        # ===== Priority 6: Continue event =====
        has_continue_kw_flag = has_continue_kw(user_input)

        if has_continue_kw_flag and active_thread:
            decision.primary_intent = "continue_event"
            decision.continue_previous_event = True
            decision.confidence = 0.7
            decision.reasons.append("continue_keywords_with_active_thread")
            return decision

        # ===== Default: ambiguous =====
        decision.primary_intent = "ambiguous"
        decision.confidence = 0.3
        decision.reasons.append("no_clear_intent_signal")
        if context_policy:
            decision.reasons.append(f"context_policy_hint_ignored:{context_policy}")
        return decision


def has_continue_kw(user_input: str) -> bool:
    return any(kw in user_input for kw in CONTINUE_KEYWORDS)
