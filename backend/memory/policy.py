"""
Memory V2 策略引擎 — Phase 10

职责：
1. 动态字段黑名单检查
2. 权威等级优先级比较
3. 记忆类型允许规则
4. Agent 注入白名单
5. 写入候选校验
"""

from typing import Any, Dict, List, Optional, Set
from backend.memory.constants import (
    DYNAMIC_FIELD_BLOCKLIST,
    SAFE_MEMORY_KEY_PREFIXES,
    MemoryType,
    MemoryStatus,
    MemorySourceType,
    AuthorityLevel,
)


class MemoryPolicy:
    """记忆策略引擎。

    决定哪些内容可以写入哪种记忆，哪些 Agent 可以接收哪些记忆。
    """

    def __init__(self):
        # 动态字段黑名单
        self.field_blocklist: Set[str] = set(DYNAMIC_FIELD_BLOCKLIST)

        # memory_type -> 允许的 source_type
        self.source_type_rules: Dict[str, Set[str]] = {
            MemoryType.USER_CORRECTION.value: {
                MemorySourceType.USER_CORRECTION.value,
            },
            MemoryType.STABLE_FACT.value: {
                MemorySourceType.USER_EXPLICIT.value,
                MemorySourceType.EVENT_PARSER.value,
                MemorySourceType.AGENT_FUSION.value,
                MemorySourceType.HUMAN_REVIEW.value,
                MemorySourceType.SYSTEM_RULE.value,
            },
            MemoryType.CONSTRAINT.value: {
                MemorySourceType.USER_EXPLICIT.value,
                MemorySourceType.SYSTEM_RULE.value,
                MemorySourceType.HUMAN_REVIEW.value,
            },
            MemoryType.CONFIRMED_DECISION.value: {
                MemorySourceType.AGENT_FUSION.value,
                MemorySourceType.HUMAN_REVIEW.value,
            },
            MemoryType.UNRESOLVED_ISSUE.value: {
                MemorySourceType.AGENT_PROPOSAL.value,
                MemorySourceType.AGENT_FUSION.value,
                MemorySourceType.USER_EXPLICIT.value,
            },
            MemoryType.RUN_SUMMARY.value: {
                MemorySourceType.AGENT_FUSION.value,
                MemorySourceType.AGENT_PROPOSAL.value,
            },
            MemoryType.PROPOSAL.value: {
                MemorySourceType.AGENT_PROPOSAL.value,
            },
            MemoryType.SESSION_GOAL.value: {
                MemorySourceType.USER_EXPLICIT.value,
                MemorySourceType.EVENT_PARSER.value,
            },
            MemoryType.TEMPORARY_FACT.value: {
                MemorySourceType.EVENT_PARSER.value,
                MemorySourceType.AGENT_PROPOSAL.value,
                MemorySourceType.USER_EXPLICIT.value,
            },
        }

        # Agent 注入白名单: agent_name -> 允许的 memory_type
        self.agent_injection_rules: Dict[str, Set[str]] = {
            "CongestionAgent": {
                MemoryType.STABLE_FACT.value,
                MemoryType.CONSTRAINT.value,
                MemoryType.CONFIRMED_DECISION.value,
                MemoryType.SESSION_GOAL.value,
            },
            "SignalAgent": {
                MemoryType.STABLE_FACT.value,
                MemoryType.CONSTRAINT.value,
                MemoryType.CONFIRMED_DECISION.value,
                MemoryType.SESSION_GOAL.value,
            },
            "PublicSafetyAgent": {
                MemoryType.STABLE_FACT.value,
                MemoryType.CONSTRAINT.value,
                MemoryType.CONFIRMED_DECISION.value,
                MemoryType.SESSION_GOAL.value,
            },
            "AccidentAgent": {
                MemoryType.STABLE_FACT.value,
                MemoryType.CONSTRAINT.value,
                MemoryType.CONFIRMED_DECISION.value,
                MemoryType.SESSION_GOAL.value,
            },
            "DispatchAgent": {
                MemoryType.STABLE_FACT.value,
                MemoryType.CONSTRAINT.value,
                MemoryType.CONFIRMED_DECISION.value,
                MemoryType.UNRESOLVED_ISSUE.value,
                MemoryType.SESSION_GOAL.value,
            },
            "ConflictDetector": {
                # 冲突检测器不需要记忆注入
            },
            "ConflictArbiter": {
                MemoryType.CONSTRAINT.value,
                MemoryType.CONFIRMED_DECISION.value,
            },
            "FusionAgent": {
                MemoryType.STABLE_FACT.value,
                MemoryType.CONSTRAINT.value,
                MemoryType.CONFIRMED_DECISION.value,
                MemoryType.UNRESOLVED_ISSUE.value,
                MemoryType.SESSION_GOAL.value,
            },
        }

    # ===== 字段检查 =====

    def is_dynamic_field(self, field_name: str) -> bool:
        """检查字段是否为动态字段（禁止写入稳定记忆）。

        大小写不敏感比较。
        """
        field_lower = field_name.lower()
        for blocked in self.field_blocklist:
            if blocked.lower() == field_lower:
                return True
        return False

    def is_safe_memory_key(self, memory_key: str) -> bool:
        """检查 memory_key 是否为安全前缀。"""
        for prefix in SAFE_MEMORY_KEY_PREFIXES:
            if memory_key.startswith(prefix):
                return True
        return False

    def validate_stable_fact_key(self, memory_key: str) -> Optional[str]:
        """验证 memory_key 是否可作为 stable_fact。

        Returns:
            None 表示通过，否则返回拒绝原因。
        """
        # 检查 memory_key 是否包含动态字段名
        key_lower = memory_key.lower()
        for field_name in self.field_blocklist:
            if field_name.lower() in key_lower:
                return f"memory_key 包含动态字段 '{field_name}'，禁止写入 stable_fact"
        # 检查是否为安全前缀
        if not self.is_safe_memory_key(memory_key):
            return f"memory_key '{memory_key}' 不在安全前缀列表中"
        return None  # OK

    def validate_stable_fact_value(self, value: Dict[str, Any]) -> List[str]:
        """检查 value 字典是否包含动态字段。返回违规字段列表。"""
        violations = []
        for key in value.keys():
            if self.is_dynamic_field(key):
                violations.append(key)
        return violations

    # ===== 类型规则 =====

    def is_source_allowed_for_type(self, memory_type: str, source_type: str) -> bool:
        """检查给定 source_type 是否可以创建给定 memory_type。"""
        allowed = self.source_type_rules.get(memory_type)
        if allowed is None:
            return False
        return source_type in allowed

    def validate_temporary_fact(self, valid_until: Optional[str]) -> Optional[str]:
        """验证 temporary_fact 必须有有效的 valid_until。

        Returns:
            None 表示通过，否则返回拒绝原因。
        """
        if not valid_until:
            return "temporary_fact 必须有 valid_until，否则拒绝写入"
        return None

    # ===== Agent 注入 =====

    def get_allowed_memory_types_for_agent(self, agent_name: str) -> Set[str]:
        """获取某 Agent 可接收的记忆类型集合。"""
        return self.agent_injection_rules.get(agent_name, set())

    def filter_items_for_agent(self, items: List, agent_name: str) -> List:
        """从记忆列表中筛选 Agent 允许接收的记忆。"""
        allowed_types = self.get_allowed_memory_types_for_agent(agent_name)
        if not allowed_types:
            return []
        return [item for item in items if item.memory_type in allowed_types]

    # ===== 权威检查 =====

    def should_supersede(self, existing_authority: int, new_authority: int) -> bool:
        """判断新记忆是否应该取代旧记忆（基于权威等级）。

        更高权威的可以取代低权威的；同一权威的不自动取代（保留旧记录）。
        """
        return new_authority > existing_authority

    def get_authority_for_source(self, source_type: str) -> int:
        """根据来源类型获取默认权威等级。"""
        mapping = {
            MemorySourceType.USER_CORRECTION.value: AuthorityLevel.USER_CORRECTION,
            MemorySourceType.HUMAN_REVIEW.value: AuthorityLevel.HUMAN_REVIEW,
            MemorySourceType.AGENT_FUSION.value: AuthorityLevel.AGENT_FUSION,
            MemorySourceType.AGENT_PROPOSAL.value: AuthorityLevel.AGENT_PROPOSAL,
            MemorySourceType.EVENT_PARSER.value: AuthorityLevel.EVENT_PARSER,
            MemorySourceType.SYSTEM_RULE.value: AuthorityLevel.SYSTEM_RULE,
            MemorySourceType.USER_EXPLICIT.value: AuthorityLevel.HUMAN_REVIEW,
        }
        return mapping.get(source_type, AuthorityLevel.DEFAULT)

    # ===== 写入候选校验 =====

    def validate_write_candidate(
        self,
        memory_type: str,
        memory_key: str,
        value: Dict[str, Any],
        source_type: str,
        valid_until: Optional[str] = None,
    ) -> Optional[str]:
        """全面校验写入候选。

        Returns:
            None 表示通过，否则返回拒绝原因。
        """
        # 1. 来源是否允许创建此类型
        if not self.is_source_allowed_for_type(memory_type, source_type):
            return f"source_type '{source_type}' 不允许创建 memory_type '{memory_type}'"

        # 2. stable_fact / confirmed_decision 检查 value 动态字段
        if memory_type in (MemoryType.STABLE_FACT.value, MemoryType.CONFIRMED_DECISION.value):
            violations = self.validate_stable_fact_value(value)
            if violations:
                return f"动态字段禁止写入 {memory_type}: {', '.join(violations)}"
            # 检查 memory_key
            key_error = self.validate_stable_fact_key(memory_key)
            if key_error:
                return key_error

        # 3. temporary_fact 必须有 valid_until
        if memory_type == MemoryType.TEMPORARY_FACT.value:
            tf_error = self.validate_temporary_fact(valid_until)
            if tf_error:
                return tf_error

        # 4. user_correction 只能是 user_correction 来源
        if memory_type == MemoryType.USER_CORRECTION.value:
            if source_type != MemorySourceType.USER_CORRECTION.value:
                return "user_correction 类型只能来自 user_correction 来源"

        return None  # OK


# 全局默认策略实例
DEFAULT_POLICY = MemoryPolicy()
