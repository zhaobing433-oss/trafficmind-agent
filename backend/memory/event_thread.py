"""
Event Thread — Phase 10 里程碑三

一个 chat_session 可包含多个独立交通事件，每个事件形成一个 Event Thread。
Memory 查询默认限定在当前 Event Thread，历史 Thread 事实不污染当前 Run。

models: MemoryEventThread, MemorySessionState
tables: memory_event_threads, memory_session_states
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.memory.time_utils import to_iso_utc


# ================================================================
# Models
# ================================================================

@dataclass
class MemoryEventThread:
    """一个独立的交通事件线程。"""
    id: str = ""
    session_id: str = ""
    status: str = "active"     # active | closed
    title: str = ""
    started_run_id: str = ""
    last_run_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    closed_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "status": self.status,
            "title": self.title,
            "started_run_id": self.started_run_id,
            "last_run_id": self.last_run_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "closed_at": self.closed_at,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "MemoryEventThread":
        return cls(
            id=row.get("id", ""),
            session_id=row.get("session_id", ""),
            status=row.get("status", "active"),
            title=row.get("title", ""),
            started_run_id=row.get("started_run_id", ""),
            last_run_id=row.get("last_run_id", ""),
            created_at=row.get("created_at", ""),
            updated_at=row.get("updated_at", ""),
            closed_at=row.get("closed_at", ""),
        )


@dataclass
class MemorySessionState:
    """Session 级 Memory 状态。"""
    session_id: str = ""
    active_event_thread_id: str = ""
    memory_version: int = 1
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "active_event_thread_id": self.active_event_thread_id,
            "memory_version": self.memory_version,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "MemorySessionState":
        return cls(
            session_id=row.get("session_id", ""),
            active_event_thread_id=row.get("active_event_thread_id", ""),
            memory_version=int(row.get("memory_version", 1)),
            updated_at=row.get("updated_at", ""),
        )


# ================================================================
# SQL DDL (for sqlite_repository)
# ================================================================

EVENT_THREAD_DDL = """
    CREATE TABLE IF NOT EXISTS memory_event_threads (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        title TEXT DEFAULT '',
        started_run_id TEXT DEFAULT '',
        last_run_id TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        closed_at TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS memory_session_states (
        session_id TEXT PRIMARY KEY,
        active_event_thread_id TEXT DEFAULT '',
        memory_version INTEGER DEFAULT 1,
        updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_met_session
        ON memory_event_threads(session_id);
    CREATE INDEX IF NOT EXISTS idx_met_status
        ON memory_event_threads(session_id, status);
    CREATE INDEX IF NOT EXISTS idx_mss_active_thread
        ON memory_session_states(active_event_thread_id);
"""

# Non-destructive migration: add event_thread_id to existing tables
EVENT_THREAD_MIGRATION = [
    "ALTER TABLE memory_items ADD COLUMN event_thread_id TEXT DEFAULT ''",
    "ALTER TABLE memory_traces ADD COLUMN event_thread_id TEXT DEFAULT ''",
]

# ================================================================
# Thread Management Functions (pure logic, no DB)
# ================================================================

def generate_thread_id() -> str:
    return f"ethread_{uuid.uuid4().hex[:12]}"


def build_thread_title(user_input: str, current_event: Dict[str, Any]) -> str:
    """从用户输入和事件信息生成 Thread 标题。"""
    road = current_event.get("roadName", "")
    etype = current_event.get("eventTypeCn", "")
    if road and road not in ("未知路段", "未命名路段", "未命名"):
        if etype:
            return f"{road}{etype}"
        return road
    if etype:
        return f"{etype}研判"
    return user_input[:20] if user_input else "交通研判"
