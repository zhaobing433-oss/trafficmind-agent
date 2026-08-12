"""
Memory V2 冲突解决器 — Phase 10 里程碑二

处理 MemoryWriteCandidate 与已有活跃记忆之间的冲突：
dedup、supersede、authority 冲突、状态混合。
"""

from typing import Any, Dict, List, Optional, Tuple

from backend.memory.models import MemoryItem, MemoryWriteCandidate, MemoryWriteResult
from backend.memory.constants import (
    MemoryType,
    MemoryStatus,
    MemorySourceType,
    AuthorityLevel,
)
from backend.memory.policy import DEFAULT_POLICY
from backend.memory.repository import MemoryStore


class ConflictResolver:
    """解决写入候选与已有记忆的冲突。

    所有冲突决策写入 trace。
    """

    def __init__(self):
        self.policy = DEFAULT_POLICY
        # 决策日志（每个 resolve 调用累积）
        self.decisions: List[Dict[str, Any]] = []

    def resolve(
        self,
        candidates: List[MemoryWriteCandidate],
        gate_decisions: List[Tuple[str, Optional[str], Optional[MemoryItem]]],
        existing_items: List[MemoryItem],
    ) -> List[Tuple[MemoryWriteCandidate, str, Optional[str], Optional[str]]]:
        """对门控决策后的候选进行最终冲突解决。

        Args:
            candidates: 原始候选列表。
            gate_decisions: write_gate 的决策结果，与 candidates 一一对应。
            existing_items: 同 session 的已有活跃记忆。

        Returns:
            List of (candidate, final_action, reason, superseded_item_id_or_None)
        """
        self.decisions = []
        results = []

        for i, (candidate, decision) in enumerate(zip(candidates, gate_decisions)):
            action, reason, conflicting = decision

            # 记录决策
            self.decisions.append({
                "index": i,
                "memory_type": candidate.memory_type,
                "memory_key": candidate.memory_key,
                "action": action,
                "reason": reason,
            })

            superseded_id = None

            if action == GateDecision.REJECT:
                results.append((candidate, "reject", reason, None))

            elif action == GateDecision.DEDUPLICATED:
                results.append((candidate, "deduplicated", reason, None))

            elif action == GateDecision.SUPERSEDE and conflicting:
                superseded_id = conflicting.id
                results.append((candidate, "supersede", reason, superseded_id))

            elif action == GateDecision.CONFIRM:
                results.append((candidate, "confirm", reason, None))

            elif action == GateDecision.CREATE:
                results.append((candidate, "create", reason, None))

            elif action == GateDecision.NO_OP:
                results.append((candidate, "no_op", reason, None))

            else:
                results.append((candidate, "create", None, None))

        return results

    def get_trace(self) -> Dict[str, Any]:
        """返回本次解决的 trace。"""
        return {
            "total_candidates": len(self.decisions),
            "decisions": self.decisions,
            "summary": {
                action: sum(1 for d in self.decisions if d["action"] == action)
                for action in ["create", "deduplicated", "supersede", "confirm",
                               "reject", "no_op"]
            },
        }


# Re-export GateDecision for convenience
from backend.memory.write_gate import GateDecision
