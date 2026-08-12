"""
RAG V2 Query Rewriter — 基于 Memory V2 和当前上下文重写查询。

Rules:
- May use: session_goal, active stable_fact, confirmed user_correction
- May NOT use dynamic fields: avgSpeed, queueLength, duration, weather, signalState, etc.
- After user correction, only use active new fact
- currentEvent is immutable
- RAG context stored separately in ragContext
- Memory NOT written back to currentEvent
"""
from __future__ import annotations
from typing import Dict, List, Optional

from backend.rag.v2.models import QueryAnalysis


# Dynamic fields that MUST NOT be used for query rewrite
FORBIDDEN_DYNAMIC_FIELDS = {
    "avgSpeed", "queueLength", "duration", "weather", "signalState",
    "trafficFlow", "pedestrianCount", "laneAvailability", "accidentStatus",
    "avg_speed", "queue_length",
}

# Allowed Memory fields for query rewrite
ALLOWED_MEMORY_FIELDS = {
    "road.name", "road_name", "event_type", "event.type",
    "location", "intersection", "district",
    "nearbySchool", "nearbyHospital", "isMainRoad",
    "session_goal", "user_intent",
}


class RagQueryRewriter:
    """基于当前上下文和 Memory 的查询重写器。"""

    def rewrite(
        self,
        query: str,
        analysis: QueryAnalysis,
        memory_context: Optional[Dict] = None,
        event_info: Optional[Dict] = None,
        session_context: Optional[Dict] = None,
    ) -> str:
        """重写查询，添加上下文信息。

        Args:
            query: 原始查询
            analysis: 查询分析结果
            memory_context: Phase 10 Memory V2 上下文（已过滤）
            event_info: 当前事件信息（只读）
            session_context: 会话上下文

        Returns:
            重写后的查询
        """
        parts = [query]

        # Use session_goal if available
        if session_context:
            goal = session_context.get("session_goal", "")
            if goal:
                parts.append(f"[会话目标: {goal}]")

        # Use stable memory facts (not dynamic fields)
        if memory_context:
            memory_hints = self._extract_stable_hints(memory_context)
            if memory_hints:
                parts.append(f"[上下文: {memory_hints}]")

        # Use event static info (not dynamic measurements)
        if event_info:
            static_hints = self._extract_static_event_info(event_info)
            if static_hints:
                parts.append(f"[当前事件: {static_hints}]")

        if len(parts) == 1:
            return query

        return " ".join(parts)

    def rewrite_with_correction(
        self,
        query: str,
        analysis: QueryAnalysis,
        original_event_info: Optional[Dict],
        corrected_facts: Dict[str, str],
        memory_context: Optional[Dict] = None,
    ) -> str:
        """用户纠正后的查询重写 — 只使用 corrected facts 中的新值。

        Args:
            query: 原始查询
            analysis: 查询分析结果
            original_event_info: 原始事件信息（不可变，用于非纠正字段）
            corrected_facts: 用户纠正的事实，如 {"road.name": "中山路"}
            memory_context: Memory V2 上下文
        """
        parts = [query]

        # Build corrected context
        corrected_hints = []
        for key, value in corrected_facts.items():
            # Only use allowed memory fields
            if key in ALLOWED_MEMORY_FIELDS or any(key.startswith(p) for p in ["road.", "event."]):
                corrected_hints.append(f"{key}={value}")

        if corrected_hints:
            parts.append(f"[纠正后事实: {'; '.join(corrected_hints)}]")

        # Add other stable context
        if memory_context:
            stable_hints = self._extract_stable_hints(memory_context)
            if stable_hints:
                parts.append(f"[上下文: {stable_hints}]")

        return " ".join(parts) if len(parts) > 1 else query

    def _extract_stable_hints(self, memory_context: Dict) -> str:
        """从 Memory 上下文中提取稳定事实（排除动态字段）。"""
        hints = []
        for key, value in memory_context.items():
            if key in FORBIDDEN_DYNAMIC_FIELDS:
                continue
            if key in ALLOWED_MEMORY_FIELDS or any(
                key.startswith(p) for p in ["road.", "event.", "session_"]
            ):
                if isinstance(value, str) and value:
                    hints.append(f"{key}: {value}")
                elif isinstance(value, (int, float)):
                    hints.append(f"{key}: {value}")
        return "; ".join(hints[:5])

    def _extract_static_event_info(self, event_info: Dict) -> str:
        """从事件中提取静态信息（排除动态测量值）。"""
        hints = []
        allowed_static = {
            "eventType", "eventTypeCn", "roadName", "direction",
            "isMainRoad", "nearbySchool", "nearbyHospital",
        }
        for key in allowed_static:
            val = event_info.get(key, "")
            if val:
                hints.append(f"{key}: {val}")
        return "; ".join(hints[:5])

    def extract_used_memory_ids(self, memory_context: Optional[Dict]) -> List[str]:
        """提取查询重写中使用的 Memory ID。"""
        if not memory_context:
            return []
        ids = []
        for key, value in memory_context.items():
            if isinstance(value, dict) and "memory_id" in value:
                ids.append(value["memory_id"])
        return ids
