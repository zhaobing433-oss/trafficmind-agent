"""
Memory V2 核心数据模型 — Phase 10

MemoryItem: 一条结构化记忆
MemoryTrace: 一次记忆召回+注入+写入的完整追踪
"""

import hashlib
import json as _json_lib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.tools.event_tools import safe_float, safe_int


def compute_dedup_key(
    session_id: str,
    memory_type: str,
    memory_key: str,
    value: Dict[str, Any],
    source_run_id: str = "",
    source_message_id: str = "",
) -> str:
    """计算幂等去重键（SHA-256）。

    组成: sessionId + memoryType + memoryKey + canonical JSON value
          + sourceRunId + sourceMessageId

    canonical JSON: sort_keys=True, ensure_ascii=False, separators 紧凑。
    相同逻辑数据（dict key 顺序不同）产生相同 dedupKey。

    Returns:
        SHA-256 hex digest (64 chars)，空字段返回空字符串。
    """
    if not session_id:
        return ""
    canonical = _json_lib.dumps(
        value or {}, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    raw = (
        f"{session_id}|{memory_type}|{memory_key}|"
        f"{canonical}|{source_run_id}|{source_message_id}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class MemoryItem:
    """单条结构化 Session 记忆。

    Attributes:
        id: 全局唯一 ID
        memory_type: 记忆类型 (session_goal, stable_fact, constraint, ...)
        scope_type: 作用域类型 (本阶段仅 session)
        scope_id: 作用域 ID (= session_id 本阶段)
        session_id: 所属会话 ID
        memory_key: 记忆键名 (如 "road.name", "constraint.speed_limit")
        value: 记忆值 (JSON dict)
        text_content: 自然语言描述
        status: 状态 (candidate, active, confirmed, rejected, superseded, expired)
        confidence: 置信度 0.0-1.0
        authority_level: 权威等级 (user_correction=100 > ... > default=0)
        source_type: 来源类型
        source_id: 来源标识
        source_run_id: 来源 Run ID
        source_message_id: 来源消息 ID
        valid_from: 生效时间 (ISO UTC)
        valid_until: 失效时间 (ISO UTC)
        supersedes_id: 取代的记忆 ID
        dedup_key: 幂等去重键 (SHA-256)
        created_at: 创建时间 (ISO UTC)
        updated_at: 更新时间 (ISO UTC)
        last_accessed_at: 最后访问时间 (ISO UTC)
        access_count: 访问计数
    """
    id: str
    memory_type: str                                            # MemoryType
    scope_type: str = "session"                                 # ScopeType
    scope_id: str = ""
    session_id: str = ""
    memory_key: str = ""
    value: Dict[str, Any] = field(default_factory=dict)
    text_content: str = ""
    status: str = "candidate"                                   # MemoryStatus
    confidence: float = 1.0
    authority_level: int = 0
    source_type: str = ""                                       # MemorySourceType
    source_id: str = ""
    source_run_id: str = ""
    source_message_id: str = ""
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    supersedes_id: str = ""
    dedup_key: str = ""
    event_thread_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_accessed_at: Optional[str] = None
    access_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转为字典（Python dict/list，不含 JSON 字符串）。"""
        return {
            "id": self.id,
            "memory_type": self.memory_type,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "session_id": self.session_id,
            "memory_key": self.memory_key,
            "value": self.value,
            "text_content": self.text_content,
            "status": self.status,
            "confidence": self.confidence,
            "authority_level": self.authority_level,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_run_id": self.source_run_id,
            "source_message_id": self.source_message_id,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "supersedes_id": self.supersedes_id,
            "dedup_key": self.dedup_key,
            "event_thread_id": self.event_thread_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_accessed_at": self.last_accessed_at,
            "access_count": self.access_count,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "MemoryItem":
        """从数据库行（dict）创建 MemoryItem。

        此方法处理 JSON 字符串 → Python dict 转换（边界层）。
        适用于任何提供 dict 的数据源（SQLite Row、PostgreSQL dict、测试数据）。
        """
        value = {}
        try:
            raw = row.get("value_json", "{}")
            if isinstance(raw, str):
                value = _json_lib.loads(raw)
            elif isinstance(raw, dict):
                value = raw
        except Exception:
            value = {}
        return cls(
            id=row["id"],
            memory_type=row["memory_type"],
            scope_type=row.get("scope_type", "session"),
            scope_id=row.get("scope_id", ""),
            session_id=row.get("session_id", ""),
            memory_key=row.get("memory_key", ""),
            value=value,
            text_content=row.get("text_content", ""),
            status=row.get("status", "candidate"),
            confidence=safe_float(row.get("confidence"), 1.0),
            authority_level=safe_int(row.get("authority_level"), 0),
            source_type=row.get("source_type", ""),
            source_id=row.get("source_id", ""),
            source_run_id=row.get("source_run_id", ""),
            source_message_id=row.get("source_message_id", ""),
            valid_from=row.get("valid_from") or None,
            valid_until=row.get("valid_until") or None,
            supersedes_id=row.get("supersedes_id", ""),
            dedup_key=row.get("dedup_key", ""),
            event_thread_id=row.get("event_thread_id", ""),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
            last_accessed_at=row.get("last_accessed_at") or None,
            access_count=int(row.get("access_count", 0)),
        )

    def is_valid(self, now: Optional[str] = None) -> bool:
        """判断当前是否有效（未过期）。

        使用 UTC 比较。
        """
        if self.status in ("rejected", "superseded", "expired"):
            return False
        if self.valid_until:
            ref = now or datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S+00:00"
            )
            if self.valid_until < ref:
                return False
        return True


@dataclass
class MemoryRecallPlan:
    """记忆召回计划。"""
    session_id: str = ""
    intent: str = ""
    candidate_types: List[str] = field(default_factory=list)
    candidate_keys: List[str] = field(default_factory=list)
    max_items: int = 20
    token_budget: int = 2000


@dataclass
class MemoryInjectionContext:
    """向 Agent 注入记忆时的上下文。"""
    agent_name: str = ""
    items: List[MemoryItem] = field(default_factory=list)
    total_tokens_estimate: int = 0
    truncated: bool = False


@dataclass
class MemoryWriteCandidate:
    """待写入的记忆候选。"""
    memory_type: str = ""
    memory_key: str = ""
    value: Dict[str, Any] = field(default_factory=dict)
    text_content: str = ""
    status: str = "candidate"
    confidence: float = 0.8
    authority_level: int = 0
    source_type: str = ""
    source_id: str = ""
    source_run_id: str = ""
    source_message_id: str = ""
    valid_until: Optional[str] = None
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    policy_check: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryWriteResult:
    """写入结果。"""
    candidate: MemoryWriteCandidate = field(default_factory=MemoryWriteCandidate)
    accepted: bool = False
    reason: str = ""
    item_id: str = ""
    superseded_ids: List[str] = field(default_factory=list)


@dataclass
class MemoryTrace:
    """一次 Run 的记忆召回+注入+写入的完整追踪。

    Attributes:
        trace_id: 追踪 ID
        run_id: 关联 Run ID (唯一)
        session_id: 会话 ID
        recall_intent: 召回意图
        recall_plan_json: 召回计划 (JSON 字符串)
        candidates_json: 候选记忆 (JSON 字符串)
        selected_json: 选中的记忆 (JSON 字符串)
        rejected_json: 被拒绝的记忆 (JSON 字符串)
        injection_map_json: 注入映射 agent_name → [item_id] (JSON 字符串)
        write_candidates_json: 写入候选 (JSON 字符串)
        write_results_json: 写入结果 (JSON 字符串)
        token_estimate: token 估算
        recall_latency_ms: 召回耗时 (ms)
        write_latency_ms: 写入耗时 (ms)
        created_at: 创建时间
        updated_at: 更新时间
    """
    trace_id: str = ""
    run_id: str = ""
    session_id: str = ""
    recall_intent: str = ""
    recall_decision_json: str = "{}"
    recall_plan_json: str = "{}"
    candidates_json: str = "[]"
    selected_json: str = "[]"
    rejected_json: str = "[]"
    injection_map_json: str = "{}"
    write_candidates_json: str = "[]"
    write_results_json: str = "[]"
    token_estimate: int = 0
    recall_latency_ms: int = 0
    write_latency_ms: int = 0
    event_thread_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "recall_intent": self.recall_intent,
            "recall_decision_json": self.recall_decision_json,
            "recall_plan_json": self.recall_plan_json,
            "candidates_json": self.candidates_json,
            "selected_json": self.selected_json,
            "rejected_json": self.rejected_json,
            "injection_map_json": self.injection_map_json,
            "write_candidates_json": self.write_candidates_json,
            "write_results_json": self.write_results_json,
            "token_estimate": self.token_estimate,
            "recall_latency_ms": self.recall_latency_ms,
            "write_latency_ms": self.write_latency_ms,
            "event_thread_id": self.event_thread_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "MemoryTrace":
        trace = cls()
        trace.trace_id = row.get("trace_id", "")
        trace.run_id = row.get("run_id", "")
        trace.session_id = row.get("session_id", "")
        trace.recall_intent = row.get("recall_intent", "")
        trace.recall_decision_json = row.get("recall_decision_json", "{}")
        trace.recall_plan_json = row.get("recall_plan_json", "{}")
        trace.candidates_json = row.get("candidates_json", "[]")
        trace.selected_json = row.get("selected_json", "[]")
        trace.rejected_json = row.get("rejected_json", "[]")
        trace.injection_map_json = row.get("injection_map_json", "{}")
        trace.write_candidates_json = row.get("write_candidates_json", "[]")
        trace.write_results_json = row.get("write_results_json", "[]")
        trace.token_estimate = int(row.get("token_estimate", 0))
        trace.recall_latency_ms = int(row.get("recall_latency_ms", 0))
        trace.write_latency_ms = int(row.get("write_latency_ms", 0))
        trace.event_thread_id = row.get("event_thread_id", "")
        trace.created_at = row.get("created_at", "")
        trace.updated_at = row.get("updated_at", "")
        return trace
