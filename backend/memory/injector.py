"""
Memory Injector — Phase 10 里程碑三

按 Agent 精确注入结构化 Memory Context。
使用 MemoryPolicy 白名单，各 Agent 收到不同的 Memory 子集。
"""

import copy
from typing import Any, Dict, List, Optional

from backend.memory.models import MemoryItem, MemoryInjectionContext
from backend.memory.policy import DEFAULT_POLICY
from backend.memory.constants import DYNAMIC_FIELD_BLOCKLIST


class MemoryInjector:
    """按 Agent 精确注入 Memory Context。

    禁止：currentEvent.update(memoryContext)
    禁止：{**oldMemory, **currentEvent}
    """

    def __init__(self, policy=None):
        self.policy = policy or DEFAULT_POLICY
        # Field-level whitelist: agent_name → allowed memoryKey prefixes
        self.field_whitelist: Dict[str, set] = {
            "CongestionAgent": {
                "road.name", "road.direction", "road.is_main", "route.event_type",
                "goal.primary", "constraint.", "decision.",
            },
            "SignalAgent": {
                "road.name", "road.direction", "road.is_main", "route.event_type",
                "school.nearby", "hospital.nearby", "intersection.",
                "goal.primary", "constraint.", "decision.", "correction.",
            },
            "AccidentAgent": {
                "road.name", "road.direction", "route.event_type",
                "intersection.", "goal.primary", "constraint.",
                "decision.", "correction.", "unresolved.",
            },
            "PublicSafetyAgent": {
                "road.name", "school.nearby", "hospital.nearby",
                "goal.primary", "constraint.", "decision.", "correction.",
                "unresolved.",
            },
            "DispatchAgent": {
                "road.name", "road.direction", "route.event_type",
                "goal.primary", "constraint.", "decision.", "unresolved.",
            },
            "ConflictDetector": {
                "constraint.", "proposal.", "decision.",
            },
            "ConflictArbiter": {
                "constraint.", "decision.", "correction.", "unresolved.",
            },
            "FusionAgent": {
                "goal.primary", "constraint.", "decision.",
                "unresolved.", "run.summary.", "proposal.",
            },
        }

    def build_injection_context(
        self,
        selected_items: List,      # List[FilteredItem]
        agent_targets: List[str],
        current_event: Dict[str, Any],
        run_id: str,
        session_id: str,
    ) -> Dict[str, Any]:
        """构建完整的 MemoryInjectionContext 和各 Agent 注入映射。

        Returns:
            {
                "injectionContext": {...},
                "agentInjectionMap": {agent_name: {...}},
                "forbiddenInheritance": [...],
                "provenance": [...],
            }
        """
        # Partition items by type
        partitioned = self._partition(selected_items)

        # Build provenance
        provenance = []
        for fi in selected_items:
            provenance.append({
                "memoryId": fi.item.id,
                "memoryType": fi.item.memory_type,
                "memoryKey": fi.item.memory_key,
                "sourceType": fi.item.source_type,
                "sourceRunId": fi.item.source_run_id,
                "eventThreadId": getattr(fi.item, "event_thread_id", ""),
                "score": fi.score,
                "reason": getattr(fi, "selected_reason", ""),
            })

        # Shared context
        injection_context = {
            "sessionGoal": [self._item_dict(fi) for fi in partitioned.get("session_goal", [])],
            "stableFacts": [self._item_dict(fi) for fi in partitioned.get("stable_fact", [])],
            "userCorrections": [self._item_dict(fi) for fi in partitioned.get("user_correction", [])],
            "constraints": [self._item_dict(fi) for fi in partitioned.get("constraint", [])],
            "confirmedDecisions": [self._item_dict(fi) for fi in partitioned.get("confirmed_decision", [])],
            "unresolvedIssues": [self._item_dict(fi) for fi in partitioned.get("unresolved_issue", [])],
            "recentRunSummaries": [self._item_dict(fi) for fi in partitioned.get("run_summary", [])][:3],
            "proposals": [self._item_dict(fi) for fi in partitioned.get("proposal", [])],
            "historicalReferences": [self._item_dict(fi) for fi in partitioned.get("historical", [])],
            "forbiddenInheritance": sorted(DYNAMIC_FIELD_BLOCKLIST),
            "provenance": provenance,
        }

        # Per-agent injection
        agent_injection_map = {}
        for agent_name in agent_targets:
            agent_context = self._filter_for_agent(selected_items, agent_name, current_event)
            agent_injection_map[agent_name] = agent_context

        return {
            "injectionContext": injection_context,
            "agentInjectionMap": agent_injection_map,
            "forbiddenInheritance": sorted(DYNAMIC_FIELD_BLOCKLIST),
            "provenance": provenance,
        }

    def build_effective_agent_view(
        self,
        current_event: Dict[str, Any],
        projected_memory: Dict[str, Any],
    ) -> Dict[str, Any]:
        """为规则型 Agent 构建 effective_agent_view。

        规则：
        - deepcopy current_event
        - 只填充当前输入缺失的允许稳定字段
        - 当前输入永远覆盖 Memory
        - 动态字段永不从 Memory 填充
        """
        effective = copy.deepcopy(current_event)
        memory_injected_fields = []
        field_sources = copy.deepcopy(current_event.get("fieldSources", {}))

        allowed_memory_fields = {
            "road.name": "roadName",
            "road.direction": "direction",
            "school.nearby": "nearbySchool",
            "hospital.nearby": "nearbyHospital",
            "road.is_main": "isMainRoad",
        }

        stable_facts = projected_memory.get("stableFacts", [])
        for fact in stable_facts:
            mk = fact.get("memoryKey", "")
            if mk in allowed_memory_fields:
                event_key = allowed_memory_fields[mk]
                current_val = effective.get(event_key)
                mem_val = fact.get("value", {}).get("value")

                # Only fill if current is missing or None
                if current_val is None or current_val == "" or current_val is False:
                    if mem_val is not None and mem_val != "":
                        effective[event_key] = mem_val
                        memory_injected_fields.append(event_key)
                        field_sources[event_key] = "memory_session"

        effective["memoryInjectedFields"] = memory_injected_fields
        effective["fieldSources"] = field_sources
        return effective

    # ================================================================
    # Internal helpers
    # ================================================================

    def _partition(self, selected: List) -> Dict[str, List]:
        """按 memory_type 分区。"""
        result = {}
        for fi in selected:
            mt = fi.item.memory_type
            if mt not in result:
                result[mt] = []
            result[mt].append(fi)
        return result

    def _item_dict(self, fi) -> Dict[str, Any]:
        """将 FilteredItem 转为安全的字典。"""
        item = fi.item
        return {
            "memoryId": item.id,
            "memoryType": item.memory_type,
            "memoryKey": item.memory_key,
            "value": item.value,
            "sourceType": item.source_type,
            "sourceRunId": item.source_run_id,
            "eventThreadId": getattr(item, "event_thread_id", ""),
            "confidence": item.confidence,
            "authorityLevel": item.authority_level,
            "score": getattr(fi, "score", 0.0),
            "reason": getattr(fi, "selected_reason", ""),
        }

    def _filter_for_agent(
        self,
        selected: List,
        agent_name: str,
        current_event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """为特定 Agent 筛选 Memory 子集（类型 + 字段级白名单）。"""
        allowed_types = self.policy.get_allowed_memory_types_for_agent(agent_name)
        if not allowed_types:
            return {"items": [], "itemCount": 0, "allowedTypes": []}

        allowed_keys = self.field_whitelist.get(agent_name, set())

        filtered = []
        for fi in selected:
            item = fi.item
            # Type check
            if item.memory_type not in allowed_types:
                continue
            # Key check (if whitelist exists for this agent, it must match)
            if allowed_keys and not any(
                item.memory_key.startswith(prefix) for prefix in allowed_keys
            ):
                continue
            filtered.append(fi)

        return {
            "items": [self._item_dict(fi) for fi in filtered],
            "itemCount": len(filtered),
            "allowedTypes": sorted(allowed_types),
        }
