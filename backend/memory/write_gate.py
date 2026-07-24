"""
Memory V2 写入门控 — Phase 10 里程碑二

对每个 MemoryWriteCandidate 做出 gate_decision：
create / deduplicated / supersede / confirm / reject / expire / no_op

规则基于来源类型、权威等级、动态字段策略和现有记忆冲突分析。
"""

from typing import Any, Dict, List, Optional, Tuple

from backend.memory.models import MemoryItem, MemoryWriteCandidate, MemoryWriteResult
from backend.memory.constants import (
    MemoryType,
    MemoryStatus,
    MemorySourceType,
    AuthorityLevel,
    DYNAMIC_FIELD_BLOCKLIST,
)
from backend.memory.policy import DEFAULT_POLICY, MemoryPolicy
from backend.memory.repository import MemoryStore


# ================================================================
# Gate Decision 枚举
# ================================================================

class GateDecision:
    CREATE = "create"
    DEDUPLICATED = "deduplicated"
    SUPERSEDE = "supersede"
    CONFIRM = "confirm"
    REJECT = "reject"
    EXPIRE = "expire"
    NO_OP = "no_op"


# ================================================================
# MemoryWriteGate
# ================================================================

class MemoryWriteGate:
    """写入门控。

    对每个候选做出决策：创建、去重、取代、确认、拒绝或跳过。
    """

    def __init__(self, policy: Optional[MemoryPolicy] = None):
        self.policy = policy or DEFAULT_POLICY

    def decide(
        self,
        candidate: MemoryWriteCandidate,
        existing_items: List[MemoryItem],
        repo: Optional[MemoryStore] = None,
    ) -> Tuple[str, Optional[str], Optional[MemoryItem]]:
        """对单个候选做出门控决策。

        Args:
            candidate: 写入候选。
            existing_items: 同 session 的已有活跃记忆（用于冲突检测）。
            repo: MemoryStore（可选，用于查询重复项）。

        Returns:
            (gate_decision, reason, existing_conflicting_item_or_None)
        """
        mt = candidate.memory_type
        st = candidate.source_type

        # ---- 1. Policy 校验 ----
        policy_reason = self.policy.validate_write_candidate(
            memory_type=mt,
            memory_key=candidate.memory_key,
            value=candidate.value,
            source_type=st,
            valid_until=candidate.valid_until,
        )
        if policy_reason:
            return GateDecision.REJECT, policy_reason, None

        # ---- 2. 动态字段拦截 ----
        for field in DYNAMIC_FIELD_BLOCKLIST:
            if field in candidate.value:
                return (
                    GateDecision.REJECT,
                    f"dynamic_field_blocked: {field}",
                    None,
                )

        # ---- 3. 来源权限规则 ----
        decision = self._source_based_rules(candidate)
        if decision:
            return decision

        # ---- 4. 与已有记忆冲突检测 ----
        conflict_decision = self._check_conflicts(candidate, existing_items)
        if conflict_decision:
            return conflict_decision

        # ---- 5. 默认：允许创建 ----
        return GateDecision.CREATE, None, None

    def _source_based_rules(
        self, candidate: MemoryWriteCandidate
    ) -> Optional[Tuple[str, Optional[str], None]]:
        """基于来源类型和记忆类型的准入规则。"""
        mt = candidate.memory_type
        st = candidate.source_type

        # 用户纠正 → confirmed
        if st == MemorySourceType.USER_CORRECTION.value:
            if candidate.status != MemoryStatus.CONFIRMED.value:
                return None  # 允许，状态由调用方设置
            return None

        # Agent proposal → candidate only, never confirmed
        if st == MemorySourceType.AGENT_PROPOSAL.value:
            if candidate.status == MemoryStatus.CONFIRMED.value:
                return (
                    GateDecision.REJECT,
                    "agent_proposal_cannot_be_confirmed",
                    None,
                )

        # Agent fusion → 只允许 run_summary, proposal, unresolved_issue
        if st == MemorySourceType.AGENT_FUSION.value:
            allowed = {
                MemoryType.RUN_SUMMARY.value,
                MemoryType.PROPOSAL.value,
                MemoryType.UNRESOLVED_ISSUE.value,
            }
            if mt not in allowed:
                return (
                    GateDecision.REJECT,
                    f"agent_fusion_cannot_create_{mt}",
                    None,
                )

        # Event parser → confidence from parser, cannot exceed user facts
        if st == MemorySourceType.EVENT_PARSER.value:
            if candidate.confidence < 0.3:
                return (
                    GateDecision.REJECT,
                    "event_parser_confidence_too_low",
                    None,
                )

        # Human review → can create confirmed_decision
        if st == MemorySourceType.HUMAN_REVIEW.value:
            if mt == MemoryType.CONFIRMED_DECISION.value:
                return None  # 允许

        # User explicit → can create stable_fact, constraint, session_goal
        return None

    def _check_conflicts(
        self,
        candidate: MemoryWriteCandidate,
        existing_items: List[MemoryItem],
    ) -> Optional[Tuple[str, Optional[str], Optional[MemoryItem]]]:
        """检查候选与已有记忆的冲突。"""
        for existing in existing_items:
            if existing.memory_key != candidate.memory_key:
                continue
            if existing.memory_type != candidate.memory_type:
                continue

            # Same key, same type, same value → deduplicate
            if existing.value == candidate.value:
                return GateDecision.DEDUPLICATED, "identical_content", existing

            # Same key, same type, different value:
            new_authority = candidate.authority_level
            old_authority = existing.authority_level

            # User correction always supersedes
            if candidate.source_type == MemorySourceType.USER_CORRECTION.value:
                return GateDecision.SUPERSEDE, "user_correction_supersedes", existing

            # New authority higher → supersede
            if new_authority > old_authority:
                if self.policy.should_supersede(old_authority, new_authority):
                    return GateDecision.SUPERSEDE, "higher_authority", existing

            # New authority lower → reject (don't silently overwrite)
            if new_authority < old_authority:
                return (
                    GateDecision.REJECT,
                    f"lower_authority_conflict: new={new_authority} < old={old_authority}",
                    existing,
                )

            # Same authority, different value → deduplicate (keep existing)
            return GateDecision.DEDUPLICATED, "same_authority_keep_existing", existing

        return None
