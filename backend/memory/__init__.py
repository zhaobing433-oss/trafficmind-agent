"""
Memory V2 — 结构化 Session Memory

Phase 10 里程碑二: 结构化记忆抽取、写入门控、用户纠正和 Supersede。

本里程碑实现写入侧：Extractor → WriteGate → ConflictResolver → Store → Trace。
Memory 召回和 Agent 注入留待后续里程碑。
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

# Phase 10 里程碑二
from backend.memory.extractor import MemoryExtractor, MemoryExtractionResult
from backend.memory.write_gate import MemoryWriteGate, GateDecision
from backend.memory.conflict_resolver import ConflictResolver
from backend.memory.coordinator import MemoryCoordinator

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
    # Phase 10 Milestone 2
    "MemoryExtractor",
    "MemoryExtractionResult",
    "MemoryWriteGate",
    "GateDecision",
    "ConflictResolver",
    "MemoryCoordinator",
]
