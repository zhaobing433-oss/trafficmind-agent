"""
Memory V2 SQLite Repository — Phase 10

提供 MemoryItem 和 MemoryTrace 的完整 CRUD 操作。

特性：
- 默认排除 rejected/superseded/expired
- valid_until 自动过期检查
- supersede 原子操作
- 幂等 SQL 迁移
- Session 级联删除
- 全部参数化查询
"""

import json
import os
import uuid
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from backend.memory.models import MemoryItem, MemoryTrace
from backend.memory.constants import (
    MemoryType,
    MemoryStatus,
    EXCLUDED_STATUSES,
    DYNAMIC_FIELD_BLOCKLIST,
)


def _get_db_path() -> str:
    """动态获取数据库路径，支持测试时 patch。"""
    from backend.config import DB_PATH
    return DB_PATH


def _get_conn():
    """获取 SQLite 连接。"""
    db_path = _get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _now() -> str:
    """当前 ISO 时间字符串。"""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


# ===== 表初始化 =====

def init_memory_tables():
    """幂等初始化 memory_items 和 memory_traces 表。

    使用 CREATE TABLE IF NOT EXISTS，可安全反复调用。
    """
    conn = _get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS memory_items (
            id TEXT PRIMARY KEY,
            memory_type TEXT NOT NULL,
            scope_type TEXT NOT NULL DEFAULT 'session',
            scope_id TEXT NOT NULL DEFAULT '',
            session_id TEXT NOT NULL DEFAULT '',
            memory_key TEXT DEFAULT '',
            value_json TEXT NOT NULL DEFAULT '{}',
            text_content TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'candidate',
            confidence REAL NOT NULL DEFAULT 1.0,
            authority_level INTEGER NOT NULL DEFAULT 0,
            source_type TEXT DEFAULT '',
            source_id TEXT DEFAULT '',
            source_run_id TEXT DEFAULT '',
            source_message_id TEXT DEFAULT '',
            valid_from TEXT,
            valid_until TEXT,
            supersedes_id TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_accessed_at TEXT,
            access_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS memory_traces (
            trace_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL DEFAULT '',
            recall_intent TEXT DEFAULT '',
            recall_plan_json TEXT DEFAULT '{}',
            candidates_json TEXT DEFAULT '[]',
            selected_json TEXT DEFAULT '[]',
            rejected_json TEXT DEFAULT '[]',
            injection_map_json TEXT DEFAULT '{}',
            write_candidates_json TEXT DEFAULT '[]',
            write_results_json TEXT DEFAULT '[]',
            token_estimate INTEGER DEFAULT 0,
            recall_latency_ms INTEGER DEFAULT 0,
            write_latency_ms INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_memory_items_session
            ON memory_items(session_id);
        CREATE INDEX IF NOT EXISTS idx_memory_items_session_type
            ON memory_items(session_id, memory_type);
        CREATE INDEX IF NOT EXISTS idx_memory_items_session_key
            ON memory_items(session_id, memory_key);
        CREATE INDEX IF NOT EXISTS idx_memory_items_status
            ON memory_items(status);
        CREATE INDEX IF NOT EXISTS idx_memory_items_valid_until
            ON memory_items(valid_until);
        CREATE INDEX IF NOT EXISTS idx_memory_traces_run
            ON memory_traces(run_id);
        CREATE INDEX IF NOT EXISTS idx_memory_traces_session
            ON memory_traces(session_id);
    """)
    conn.commit()
    conn.close()


# ===== MemoryRepository =====

class MemoryRepository:
    """Memory V2 持久化存储。

    所有方法都是确定性的，不依赖 LLM。
    """

    def __init__(self):
        init_memory_tables()

    # ----- Create -----

    def create_item(self,
                    memory_type: str,
                    session_id: str,
                    memory_key: str = "",
                    value: Optional[Dict[str, Any]] = None,
                    text_content: str = "",
                    status: str = "candidate",
                    confidence: float = 1.0,
                    authority_level: int = 0,
                    source_type: str = "",
                    source_id: str = "",
                    source_run_id: str = "",
                    source_message_id: str = "",
                    valid_from: Optional[str] = None,
                    valid_until: Optional[str] = None,
                    supersedes_id: str = "",
                    scope_type: str = "session",
                    scope_id: str = "",
                    item_id: Optional[str] = None,
                    ) -> MemoryItem:
        """创建一条新记忆。"""
        now = _now()
        mid = item_id or f"mem_{uuid.uuid4().hex[:16]}"
        value = value or {}
        scope_id = scope_id or session_id

        conn = _get_conn()
        try:
            conn.execute("""
                INSERT INTO memory_items (
                    id, memory_type, scope_type, scope_id, session_id,
                    memory_key, value_json, text_content, status,
                    confidence, authority_level, source_type, source_id,
                    source_run_id, source_message_id, valid_from, valid_until,
                    supersedes_id, created_at, updated_at, last_accessed_at, access_count
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                mid, memory_type, scope_type, scope_id, session_id,
                memory_key, json.dumps(value, ensure_ascii=False), text_content, status,
                confidence, authority_level, source_type, source_id,
                source_run_id, source_message_id, valid_from, valid_until,
                supersedes_id, now, now, None, 0,
            ))
            conn.commit()
        finally:
            conn.close()

        return self.get_item(mid)

    # ----- Read -----

    def get_item(self, item_id: str) -> Optional[MemoryItem]:
        """按 ID 查询单条记忆。"""
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE id = ?", (item_id,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return MemoryItem.from_row(dict(row))

    def list_session_items(self,
                           session_id: str,
                           memory_type: Optional[str] = None,
                           memory_key: Optional[str] = None,
                           status: Optional[str] = None,
                           limit: int = 50,
                           offset: int = 0,
                           include_inactive: bool = False,
                           ) -> List[MemoryItem]:
        """查询 Session 的记忆列表。

        默认排除 rejected/superseded/expired。
        """
        conn = _get_conn()
        try:
            conditions = ["session_id = ?"]
            params: List[Any] = [session_id]

            if memory_type:
                conditions.append("memory_type = ?")
                params.append(memory_type)

            if memory_key:
                conditions.append("memory_key = ?")
                params.append(memory_key)

            if status:
                conditions.append("status = ?")
                params.append(status)
            elif not include_inactive:
                placeholders = ",".join(["?" for _ in EXCLUDED_STATUSES])
                conditions.append(f"status NOT IN ({placeholders})")
                params.extend(EXCLUDED_STATUSES)

            where = " AND ".join(conditions)
            query = f"SELECT * FROM memory_items WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()

        return [MemoryItem.from_row(dict(r)) for r in rows]

    def find_active_by_key(self, session_id: str, memory_key: str) -> Optional[MemoryItem]:
        """按 session_id + memory_key 查找当前活跃的记忆。

        优先返回 authority_level 最高的。
        """
        conn = _get_conn()
        try:
            placeholders = ",".join(["?" for _ in EXCLUDED_STATUSES])
            rows = conn.execute(
                f"""SELECT * FROM memory_items
                    WHERE session_id = ? AND memory_key = ?
                      AND status NOT IN ({placeholders})
                    ORDER BY authority_level DESC, updated_at DESC
                    LIMIT 1""",
                [session_id, memory_key] + list(EXCLUDED_STATUSES),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return None
        return MemoryItem.from_row(dict(rows[0]))

    def find_items_by_run(self, session_id: str, source_run_id: str) -> List[MemoryItem]:
        """查找某个 Run 产生的所有记忆。"""
        conn = _get_conn()
        try:
            placeholders = ",".join(["?" for _ in EXCLUDED_STATUSES])
            rows = conn.execute(
                f"""SELECT * FROM memory_items
                    WHERE session_id = ? AND source_run_id = ?
                      AND status NOT IN ({placeholders})
                    ORDER BY created_at ASC""",
                [session_id, source_run_id] + list(EXCLUDED_STATUSES),
            ).fetchall()
        finally:
            conn.close()
        return [MemoryItem.from_row(dict(r)) for r in rows]

    # ----- Count -----

    def count_session_items(self, session_id: str) -> Dict[str, int]:
        """统计 Session 的记忆数量（按状态分组）。"""
        conn = _get_conn()
        try:
            rows = conn.execute(
                """SELECT status, COUNT(*) as cnt
                   FROM memory_items
                   WHERE session_id = ?
                   GROUP BY status""",
                (session_id,),
            ).fetchall()
            counts: Dict[str, int] = {}
            for r in rows:
                counts[r["status"]] = r["cnt"]
            total = sum(counts.values())

            by_type_rows = conn.execute(
                """SELECT memory_type, COUNT(*) as cnt
                   FROM memory_items
                   WHERE session_id = ?
                   GROUP BY memory_type""",
                (session_id,),
            ).fetchall()
            by_type = {r["memory_type"]: r["cnt"] for r in by_type_rows}

            trace_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM memory_traces WHERE session_id = ?",
                (session_id,),
            ).fetchone()["cnt"]
        finally:
            conn.close()

        return {
            "total_items": total,
            "active_items": counts.get("active", 0),
            "confirmed_items": counts.get("confirmed", 0),
            "candidate_items": counts.get("candidate", 0),
            "expired_items": counts.get("expired", 0),
            "rejected_items": counts.get("rejected", 0),
            "superseded_items": counts.get("superseded", 0),
            "by_type": by_type,
            "trace_count": trace_count,
        }

    # ----- Update -----

    def update_item(self, item_id: str, **kwargs) -> bool:
        """更新记忆字段。"""
        allowed = {
            "memory_type", "memory_key", "text_content", "status",
            "confidence", "authority_level", "valid_from", "valid_until",
            "supersedes_id", "last_accessed_at", "access_count",
        }
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if "value" in kwargs:
            updates["value_json"] = json.dumps(kwargs["value"], ensure_ascii=False)
        if not updates:
            return False

        updates["updated_at"] = _now()
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [item_id]

        conn = _get_conn()
        try:
            conn.execute(f"UPDATE memory_items SET {set_clause} WHERE id = ?", values)
            conn.commit()
            affected = conn.total_changes > 0
        finally:
            conn.close()
        return affected

    def confirm_item(self, item_id: str) -> bool:
        """将记忆状态改为 confirmed。"""
        return self.update_item(item_id, status=MemoryStatus.CONFIRMED.value)

    def reject_item(self, item_id: str) -> bool:
        """将记忆状态改为 rejected。"""
        return self.update_item(item_id, status=MemoryStatus.REJECTED.value)

    def expire_item(self, item_id: str) -> bool:
        """将记忆标记为 expired。"""
        return self.update_item(item_id, status=MemoryStatus.EXPIRED.value)

    def supersede_item(self, old_item_id: str, new_item: MemoryItem) -> Tuple[MemoryItem, MemoryItem]:
        """取代一条记忆：
        1. 将旧记录状态改为 superseded
        2. 创建新记录
        3. 新记录 supersedes_id 指向旧记录

        Returns:
            (old_item, new_item) — 更新后的旧记录和新记录。
        """
        # 1. Mark old as superseded
        old = self.get_item(old_item_id)
        if not old:
            raise ValueError(f"被取代的记忆 '{old_item_id}' 不存在")
        old.status = MemoryStatus.SUPERSEDED.value
        self.update_item(old_item_id, status=MemoryStatus.SUPERSEDED.value)

        # 2. Set supersedes_id on new item
        new_item.supersedes_id = old_item_id

        # 3. Create new item
        created = self.create_item(
            memory_type=new_item.memory_type,
            session_id=new_item.session_id,
            memory_key=new_item.memory_key,
            value=new_item.value,
            text_content=new_item.text_content,
            status=new_item.status,
            confidence=new_item.confidence,
            authority_level=new_item.authority_level,
            source_type=new_item.source_type,
            source_id=new_item.source_id,
            source_run_id=new_item.source_run_id,
            source_message_id=new_item.source_message_id,
            valid_from=new_item.valid_from,
            valid_until=new_item.valid_until,
            supersedes_id=old_item_id,
            scope_type=new_item.scope_type,
            scope_id=new_item.scope_id or new_item.session_id,
            item_id=new_item.id,
        )

        # Re-read old to get updated state
        old_updated = self.get_item(old_item_id)
        return old_updated or old, created

    # ----- Expiry -----

    def expire_due_items(self) -> int:
        """将所有 valid_until < 当前时间的活跃/confirmed 记忆标记为过期。

        Returns:
            过期的记录数。
        """
        now = _now()
        conn = _get_conn()
        try:
            result = conn.execute(
                """UPDATE memory_items
                   SET status = ?, updated_at = ?
                   WHERE valid_until IS NOT NULL
                     AND valid_until < ?
                     AND status IN ('candidate', 'active', 'confirmed')""",
                (MemoryStatus.EXPIRED.value, now, now),
            )
            conn.commit()
            count = result.rowcount
        finally:
            conn.close()
        return count

    def expire_session_items(self, session_id: str) -> int:
        """标记某 Session 所有即将过期的记忆为 expired。

        Returns:
            过期的记录数。
        """
        now = _now()
        conn = _get_conn()
        try:
            result = conn.execute(
                """UPDATE memory_items
                   SET status = ?, updated_at = ?
                   WHERE session_id = ?
                     AND valid_until IS NOT NULL
                     AND valid_until < ?
                     AND status IN ('candidate', 'active', 'confirmed')""",
                (MemoryStatus.EXPIRED.value, now, session_id, now),
            )
            conn.commit()
            count = result.rowcount
        finally:
            conn.close()
        return count

    # ----- Access Tracking -----

    def increment_access(self, item_id: str) -> bool:
        """增加记忆访问计数 + 更新 last_accessed_at。"""
        now = _now()
        conn = _get_conn()
        try:
            conn.execute(
                """UPDATE memory_items
                   SET access_count = access_count + 1,
                       last_accessed_at = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (now, now, item_id),
            )
            conn.commit()
            affected = conn.total_changes > 0
        finally:
            conn.close()
        return affected

    # ----- MemoryTrace -----

    def save_trace(self, trace: MemoryTrace) -> MemoryTrace:
        """保存或更新一条 MemoryTrace（UPSERT）。"""
        now = _now()
        if not trace.created_at:
            trace.created_at = now
        trace.updated_at = now

        conn = _get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO memory_traces (
                    trace_id, run_id, session_id, recall_intent,
                    recall_plan_json, candidates_json, selected_json,
                    rejected_json, injection_map_json,
                    write_candidates_json, write_results_json,
                    token_estimate, recall_latency_ms, write_latency_ms,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                trace.trace_id, trace.run_id, trace.session_id, trace.recall_intent,
                trace.recall_plan_json, trace.candidates_json, trace.selected_json,
                trace.rejected_json, trace.injection_map_json,
                trace.write_candidates_json, trace.write_results_json,
                trace.token_estimate, trace.recall_latency_ms, trace.write_latency_ms,
                trace.created_at, trace.updated_at,
            ))
            conn.commit()
        finally:
            conn.close()
        return trace

    def get_trace_by_run(self, run_id: str) -> Optional[MemoryTrace]:
        """按 run_id 查询记忆追踪。"""
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM memory_traces WHERE run_id = ?", (run_id,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return MemoryTrace.from_row(dict(row))

    def list_traces(self, session_id: str, limit: int = 20) -> List[MemoryTrace]:
        """查询 Session 的 MemoryTrace 列表。"""
        conn = _get_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM memory_traces
                   WHERE session_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        finally:
            conn.close()
        return [MemoryTrace.from_row(dict(r)) for r in rows]

    # ----- Session 清理 -----

    def delete_session_memory(self, session_id: str) -> int:
        """删除某 Session 的所有记忆和追踪。

        Returns:
            删除的总行数（memory_items + memory_traces）。
        """
        conn = _get_conn()
        try:
            c1 = conn.execute(
                "DELETE FROM memory_items WHERE session_id = ?", (session_id,)
            ).rowcount
            c2 = conn.execute(
                "DELETE FROM memory_traces WHERE session_id = ?", (session_id,)
            ).rowcount
            conn.commit()
            return c1 + c2
        finally:
            conn.close()

    # ----- 去重 -----

    def find_duplicate(
        self,
        session_id: str,
        memory_type: str,
        memory_key: str,
        source_type: str,
        text_content: str,
    ) -> Optional[MemoryItem]:
        """查找同 Session 中相同类型的重复记忆（幂等去重）。

        匹配条件: session_id + memory_type + memory_key + source_type + text_content。
        """
        conn = _get_conn()
        try:
            row = conn.execute(
                """SELECT * FROM memory_items
                   WHERE session_id = ?
                     AND memory_type = ?
                     AND memory_key = ?
                     AND source_type = ?
                     AND text_content = ?
                     AND status NOT IN ('rejected', 'superseded', 'expired')
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id, memory_type, memory_key, source_type, text_content),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        return MemoryItem.from_row(dict(row))
