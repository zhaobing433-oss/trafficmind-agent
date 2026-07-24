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
)
from backend.memory.schemas import (
    MemoryItemSchema,
    MemoryItemCreateRequest,
    MemoryItemListResponse,
    MemoryTraceResponse,
    MemoryItemsBySessionRequest,
    MemoryStatsResponse,
)
from backend.memory.store import MemoryRepository
from backend.memory.policy import MemoryPolicy, DEFAULT_POLICY

__all__ = [
    # Models
    "MemoryItem",
    "MemoryTrace",
    "MemoryRecallPlan",
    "MemoryInjectionContext",
    "MemoryWriteCandidate",
    "MemoryWriteResult",
    # Schemas
    "MemoryItemSchema",
    "MemoryItemCreateRequest",
    "MemoryItemListResponse",
    "MemoryTraceResponse",
    "MemoryItemsBySessionRequest",
    "MemoryStatsResponse",
    # Store
    "MemoryRepository",
    # Policy
    "MemoryPolicy",
    "DEFAULT_POLICY",
]
