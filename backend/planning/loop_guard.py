"""
Loop Guard — Phase 17 Round 2

三层循环检测 + 硬上限 maxReplans：
  1. visitedFingerprints（planFingerprint 重复）
  2. failedActionSignatures（canonical actionType + normalized params 重复）
  3. decisionSignatures（observation.type + decision 重复）

canonical signature 排除 timestamp / request id / trace id / 随机 ID，保证稳定。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

# 排除的瞬态 key（hash 前移除）
_TRANSIENT_KEYS = frozenset({
    "timestamp", "ts", "request_id", "requestId", "trace_id", "traceId",
    "id", "run_id", "runId", "created_at", "createdAt", "random", "uuid",
})


def canonicalize_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """canonicalize params：移除瞬态 key，稳定序列化。"""
    cleaned = {}
    for k, v in (params or {}).items():
        if k in _TRANSIENT_KEYS:
            continue
        cleaned[k] = v
    return cleaned


def canonical_action_signature(action_type: str, params: Dict[str, Any]) -> str:
    """稳定 action 签名。"""
    return action_type + ":" + json.dumps(canonicalize_params(params), sort_keys=True, ensure_ascii=False)


@dataclass
class LoopGuard:
    visitedFingerprints: Set[str] = field(default_factory=set)
    failedActionSignatures: Set[str] = field(default_factory=set)
    decisionSignatures: Set[str] = field(default_factory=set)

    def register_fingerprint(self, fingerprint: str) -> bool:
        """注册 fingerprint。返回 True 表示已访问（loop）。"""
        if fingerprint in self.visitedFingerprints:
            return True
        self.visitedFingerprints.add(fingerprint)
        return False

    def register_failure(self, action_type: str, params: Dict[str, Any]) -> bool:
        """注册失败 action。返回 True 表示重复失败（loop）。"""
        sig = canonical_action_signature(action_type, params)
        if sig in self.failedActionSignatures:
            return True
        self.failedActionSignatures.add(sig)
        return False

    def register_decision(self, signature: str) -> bool:
        """注册 decision。返回 True 表示重复 decision（loop）。"""
        if signature in self.decisionSignatures:
            return True
        self.decisionSignatures.add(signature)
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "visitedFingerprints": sorted(self.visitedFingerprints),
            "failedActionSignatures": sorted(self.failedActionSignatures),
            "decisionSignatures": sorted(self.decisionSignatures),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LoopGuard":
        if not d:
            return cls()
        return cls(
            visitedFingerprints=set(d.get("visitedFingerprints", [])),
            failedActionSignatures=set(d.get("failedActionSignatures", [])),
            decisionSignatures=set(d.get("decisionSignatures", [])),
        )
