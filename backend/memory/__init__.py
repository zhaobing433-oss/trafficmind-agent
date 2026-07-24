"""
Memory V2 — 结构化 Session Memory

Phase 10: 可追踪、可纠正、可过期、可按 Agent 精确注入的 Session 记忆系统。

本阶段不接入 Orchestrator，不改前端，不创建跨 Session 向量记忆。
"""

from backend.memory.models import (
    MemoryItem,
    MemoryTrace,
    MemoryRecallPlan,
    MemoryInjectionContext,
    MemoryWriteCandidate,
    MemoryWriteResult,
    compute_dedup_key,
)
from backend.memory.schemas import (
    MemoryItemSchema,
    MemoryItemCreateRequest,
    MemoryItemListResponse,
    MemoryTraceResponse,
    MemoryItemsBySessionRequest,
    MemoryStatsResponse,
)
from backend.memory.store import MemoryRepository, init_memory_tables
from backend.memory.sqlite_repository import SQLiteMemoryRepository
from backend.memory.repository import MemoryStore, MemoryTransaction
from backend.memory.factory import create_memory_repository
from backend.memory.policy import MemoryPolicy, DEFAULT_POLICY
from backend.memory.time_utils import utc_now, to_iso_utc, parse_iso_datetime, is_expired

__all__ = [
    # Models
    "MemoryItem",
    "MemoryTrace",
    "MemoryRecallPlan",
    "MemoryInjectionContext",
    "MemoryWriteCandidate",
    "MemoryWriteResult",
    "compute_dedup_key",
    # Schemas
    "MemoryItemSchema",
    "MemoryItemCreateRequest",
    "MemoryItemListResponse",
    "MemoryTraceResponse",
    "MemoryItemsBySessionRequest",
    "MemoryStatsResponse",
    # Store (compatibility)
    "MemoryRepository",
    "init_memory_tables",
    # New portability layer
    "MemoryStore",
    "MemoryTransaction",
    "SQLiteMemoryRepository",
    "create_memory_repository",
    # Policy
    "MemoryPolicy",
    "DEFAULT_POLICY",
    # Time
    "utc_now",
    "to_iso_utc",
    "parse_iso_datetime",
    "is_expired",
]
