"""
Memory V2 枚举与常量 — Phase 10
"""

from enum import Enum
from typing import Set


class MemoryType(str, Enum):
    """记忆类型枚举。"""
    SESSION_GOAL = "session_goal"           # 会话目标
    STABLE_FACT = "stable_fact"             # 稳定事实
    CONSTRAINT = "constraint"               # 约束条件
    CONFIRMED_DECISION = "confirmed_decision"  # 已确认决策
    UNRESOLVED_ISSUE = "unresolved_issue"   # 未解决问题
    USER_CORRECTION = "user_correction"     # 用户纠正
    RUN_SUMMARY = "run_summary"             # 运行摘要
    PROPOSAL = "proposal"                   # 提案
    TEMPORARY_FACT = "temporary_fact"       # 临时事实（必须有 validUntil）


class MemoryStatus(str, Enum):
    """记忆状态枚举。"""
    CANDIDATE = "candidate"      # 候选（待确认）
    ACTIVE = "active"            # 活跃
    CONFIRMED = "confirmed"      # 已确认
    REJECTED = "rejected"        # 已拒绝
    SUPERSEDED = "superseded"    # 已被取代
    EXPIRED = "expired"          # 已过期


class MemorySourceType(str, Enum):
    """记忆来源类型枚举。"""
    USER_EXPLICIT = "user_explicit"       # 用户明确说明
    USER_CORRECTION = "user_correction"   # 用户纠正
    EVENT_PARSER = "event_parser"         # 事件解析器
    AGENT_PROPOSAL = "agent_proposal"     # Agent 提案
    AGENT_FUSION = "agent_fusion"         # Agent 融合结论
    HUMAN_REVIEW = "human_review"         # 人工审核
    SYSTEM_RULE = "system_rule"           # 系统规则


class ScopeType(str, Enum):
    """作用域类型。本阶段只实现 session。"""
    SESSION = "session"


class AuthorityLevel:
    """权威等级常量。"""
    USER_CORRECTION = 100    # 最高：用户纠正
    HUMAN_REVIEW = 80        # 人工审核
    AGENT_FUSION = 60        # Agent 融合结论
    AGENT_PROPOSAL = 40      # Agent 提案
    EVENT_PARSER = 20        # 事件解析
    SYSTEM_RULE = 10         # 系统规则
    DEFAULT = 0              # 默认


# 默认排除的查询状态
EXCLUDED_STATUSES: Set[str] = {"rejected", "superseded", "expired"}

# 动态字段黑名单 — 这些字段禁止写入 stable_fact / confirmed_decision
DYNAMIC_FIELD_BLOCKLIST: Set[str] = {
    "avgSpeed",
    "queueLength",
    "duration",
    "weather",
    "signalState",
    "trafficFlow",
    "pedestrianCount",
    "laneAvailability",
    "accidentStatus",
}

# 允许作为 stable_fact memory_key 的安全前缀
SAFE_MEMORY_KEY_PREFIXES: Set[str] = {
    "road.",
    "route.",
    "school.",
    "hospital.",
    "intersection.",
    "rule.",
    "policy.",
    "decision.",
    "constraint.",
    "goal.",
}

# 默认最大每 Session 记忆条数
MAX_ITEMS_PER_SESSION = 200

# 默认最大每 Session 记忆 traces 数
MAX_TRACES_PER_SESSION = 50
