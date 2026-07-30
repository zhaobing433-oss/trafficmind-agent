"""
Memory V2 SQLite 实现 — Phase 10 可移植加固

实现 MemoryStore 接口，所有 SQL 细节封装在此文件内。
业务层不得直接 import sqlite3。

变更：
- 时间统一使用 UTC（time_utils.to_iso_utc）
- INSERT 不再使用 OR REPLACE；save_trace 改用 UPDATE-then-INSERT
- create_item 检查 dedup_key 幂等去重
- transaction() 提供显式事务上下文
- PRAGMA 仅用于连接初始化
"""
import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Tuple

from backend.memory.repository import MemoryStore, MemoryTransaction
from backend.memory.models import MemoryItem, MemoryTrace, compute_dedup_key
from backend.memory.constants import (
    MemoryStatus,
    EXCLUDED_STATUSES,
)
from backend.memory.time_utils import utc_now, to_iso_utc, parse_iso_datetime
from backend.memory.event_thread import (
    MemoryEventThread, MemorySessionState,
    EVENT_THREAD_DDL, EVENT_THREAD_MIGRATION,
    generate_thread_id,
)


# ================================================================
# 时间归一化
# ================================================================

def _normalize_timestamp(ts: Optional[str]) -> Optional[str]:
    """将时间字符串归一化为 UTC ISO 格式（+00:00）。

    已有 timezone offset 的原样返回；
    无 timezone 的（旧格式）视为 UTC 并添加 offset。
    """
    if not ts:
        return ts
    ts = ts.strip()
    if "+" in ts or ts.endswith("Z"):
        return ts.replace("Z", "+00:00")
    # 旧格式（无时区）：视为 UTC
    try:
        dt = parse_iso_datetime(ts)
        return to_iso_utc(dt)
    except Exception:
        return ts  # 解析失败，保留原值


# ================================================================
# 连接与路径
# ================================================================

def _get_db_path() -> str:
    """动态获取数据库路径，支持测试时 patch。"""
    from backend.config import DB_PATH
    return DB_PATH


# 事务连接注册表（线程局部），确保事务内操作共用同一连接
_tx_connections = threading.local()


def _is_in_transaction() -> bool:
    """检查当前线程是否在事务上下文中。"""
    return getattr(_tx_connections, "current", None) is not None


def _tx_safe_commit(conn: sqlite3.Connection) -> None:
    """在事务内跳过 commit，事务外正常 commit。"""
    if not _is_in_transaction():
        conn.commit()


def _tx_safe_close(conn: sqlite3.Connection) -> None:
    """在事务内跳过 close，事务外正常 close。"""
    if not _is_in_transaction():
        conn.close()


def _get_raw_conn() -> sqlite3.Connection:
    """获取底层 SQLite 连接（仅供本模块内部使用）。

    如果在事务上下文中，返回事务专用连接；
    否则创建新连接。
    """
    tx_conn = getattr(_tx_connections, "current", None)
    if tx_conn is not None:
        return tx_conn

    db_path = _get_db_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # PRAGMA 仅允许在此处，业务层不接触
    conn.execute("PRAGMA journal_mode=WAL")
    # 启用外键约束
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ================================================================
# 表初始化 (幂等)
# ================================================================

def init_memory_tables():
    """幂等初始化 memory_items 和 memory_traces 表。

    使用 CREATE TABLE IF NOT EXISTS，可安全反复调用。
    dedup_key 列通过 ALTER TABLE 非破坏性添加，兼容已有表。
    """
    conn = _get_raw_conn()
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
            dedup_key TEXT DEFAULT '',
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
    # 非破坏性迁移：添加 dedup_key 列和唯一索引（兼容已有表）
    try:
        c.execute("ALTER TABLE memory_items ADD COLUMN dedup_key TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # 列已存在
    try:
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_items_dedup_key "
            "ON memory_items(dedup_key) WHERE dedup_key != ''"
        )
    except sqlite3.OperationalError:
        pass  # 索引已存在

    # Phase 10 M3: Event Thread tables
    c.executescript(EVENT_THREAD_DDL)
    for migration_sql in EVENT_THREAD_MIGRATION:
        try:
            c.execute(migration_sql)
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.commit()
    conn.close()


# ================================================================
# 事务上下文管理器
# ================================================================

class _SQLiteTransaction(MemoryTransaction):
    """SQLite 事务句柄。内部持有专用连接。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._committed = False
        self._rolled_back = False

    def commit(self) -> None:
        if self._committed or self._rolled_back:
            return
        self._conn.commit()
        self._committed = True

    def rollback(self) -> None:
        if self._committed or self._rolled_back:
            return
        self._conn.rollback()
        self._rolled_back = True


# ================================================================
# SQLiteMemoryRepository
# ================================================================

class SQLiteMemoryRepository(MemoryStore):
    """MemoryStore 的 SQLite 实现。

    所有 JSON 编解码在此层完成，业务层只处理 Python dict/list。
    """

    def __init__(self):
        init_memory_tables()

    # ----- 事务 -----

    @contextmanager
    def transaction(self) -> Generator[MemoryTransaction, None, None]:
        """事务上下文管理器。事务内所有操作共享同一连接。

        不支持嵌套事务（检测到嵌套时抛出 RuntimeError）。
        """
        if getattr(_tx_connections, "current", None) is not None:
            raise RuntimeError("不支持嵌套 Memory 事务")

        conn = _get_raw_conn()  # 创建新连接（未注册前不会命中事务检查）
        tx = _SQLiteTransaction(conn)
        try:
            # 注册为当前事务连接
            _tx_connections.current = conn
            conn.execute("BEGIN IMMEDIATE")
            yield tx
            if not tx._committed and not tx._rolled_back:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _tx_connections.current = None
            conn.close()

    # ----- Create (幂等 dedupKey) -----

    def create_item(
        self,
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
        event_thread_id: str = "",
        item_id: Optional[str] = None,
    ) -> MemoryItem:
        """创建一条新记忆。相同 dedupKey 返回已有记录。

        所有时间字段自动归一化为 UTC ISO 格式（+00:00）。
        """
        now = to_iso_utc()
        value = value or {}
        scope_id = scope_id or session_id

        # 归一化时间字段为 UTC
        valid_from = _normalize_timestamp(valid_from)
        valid_until = _normalize_timestamp(valid_until)

        # 计算幂等去重键
        dk = compute_dedup_key(
            session_id=session_id,
            memory_type=memory_type,
            memory_key=memory_key,
            value=value,
            source_run_id=source_run_id,
            source_message_id=source_message_id,
        )

        conn = _get_raw_conn()
        try:
            # 检查去重
            if dk:
                existing = conn.execute(
                    "SELECT id FROM memory_items WHERE dedup_key = ? AND dedup_key != ''",
                    (dk,),
                ).fetchone()
                if existing:
                    return self.get_item(existing[0])

            mid = item_id or f"mem_{uuid.uuid4().hex[:16]}"

            conn.execute(
                """INSERT INTO memory_items (
                    id, memory_type, scope_type, scope_id, session_id,
                    memory_key, value_json, text_content, status,
                    confidence, authority_level, source_type, source_id,
                    source_run_id, source_message_id, valid_from, valid_until,
                    supersedes_id, dedup_key, event_thread_id,
                    created_at, updated_at, last_accessed_at, access_count
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    mid, memory_type, scope_type, scope_id, session_id,
                    memory_key, json.dumps(value, ensure_ascii=False),
                    text_content, status,
                    confidence, authority_level, source_type, source_id,
                    source_run_id, source_message_id, valid_from, valid_until,
                    supersedes_id, dk, event_thread_id,
                    now, now, None, 0,
                ),
            )
            _tx_safe_commit(conn)
        finally:
            _tx_safe_close(conn)

        return self.get_item(mid)

    # ----- Read -----

    def get_item(self, item_id: str) -> Optional[MemoryItem]:
        conn = _get_raw_conn()
        try:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE id = ?", (item_id,)
            ).fetchone()
        finally:
            _tx_safe_close(conn)
        if not row:
            return None
        return MemoryItem.from_row(dict(row))

    def list_session_items(
        self,
        session_id: str,
        memory_type: Optional[str] = None,
        memory_key: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_inactive: bool = False,
    ) -> List[MemoryItem]:
        conn = _get_raw_conn()
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
            query = (
                f"SELECT * FROM memory_items WHERE {where} "
                f"ORDER BY updated_at DESC LIMIT ? OFFSET ?"
            )
            params.extend([limit, offset])
            rows = conn.execute(query, params).fetchall()
        finally:
            _tx_safe_close(conn)
        return [MemoryItem.from_row(dict(r)) for r in rows]

    def find_active_by_key(
        self, session_id: str, memory_key: str
    ) -> Optional[MemoryItem]:
        conn = _get_raw_conn()
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
            _tx_safe_close(conn)
        if not rows:
            return None
        return MemoryItem.from_row(dict(rows[0]))

    def find_items_by_run(
        self, session_id: str, source_run_id: str
    ) -> List[MemoryItem]:
        conn = _get_raw_conn()
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
            _tx_safe_close(conn)
        return [MemoryItem.from_row(dict(r)) for r in rows]

    def find_duplicate(
        self,
        session_id: str,
        memory_type: str,
        memory_key: str,
        source_type: str,
        text_content: str,
    ) -> Optional[MemoryItem]:
        conn = _get_raw_conn()
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
            _tx_safe_close(conn)
        if not row:
            return None
        return MemoryItem.from_row(dict(row))

    # ----- Count -----

    def count_session_items(self, session_id: str) -> Dict[str, int]:
        conn = _get_raw_conn()
        try:
            rows = conn.execute(
                """SELECT status, COUNT(*) as cnt
                   FROM memory_items WHERE session_id = ?
                   GROUP BY status""",
                (session_id,),
            ).fetchall()
            counts: Dict[str, int] = {}
            for r in rows:
                counts[r["status"]] = r["cnt"]
            total = sum(counts.values())

            by_type_rows = conn.execute(
                """SELECT memory_type, COUNT(*) as cnt
                   FROM memory_items WHERE session_id = ?
                   GROUP BY memory_type""",
                (session_id,),
            ).fetchall()
            by_type = {r["memory_type"]: r["cnt"] for r in by_type_rows}

            trace_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM memory_traces WHERE session_id = ?",
                (session_id,),
            ).fetchone()["cnt"]
        finally:
            _tx_safe_close(conn)

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
        allowed = {
            "memory_type", "memory_key", "text_content", "status",
            "confidence", "authority_level", "valid_from", "valid_until",
            "supersedes_id", "event_thread_id",
            "last_accessed_at", "access_count",
        }
        # 归一化时间字段
        for field in ("valid_from", "valid_until"):
            if field in kwargs and kwargs[field] is not None:
                kwargs[field] = _normalize_timestamp(kwargs[field])
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if "value" in kwargs:
            updates["value_json"] = json.dumps(kwargs["value"], ensure_ascii=False)
        # 如果 value 变更，重算 dedup_key
        if "value" in kwargs:
            item = self.get_item(item_id)
            if item:
                new_dk = compute_dedup_key(
                    session_id=item.session_id,
                    memory_type=item.memory_type,
                    memory_key=item.memory_key,
                    value=kwargs["value"],
                    source_run_id=item.source_run_id,
                    source_message_id=item.source_message_id,
                )
                updates["dedup_key"] = new_dk

        if not updates:
            return False

        updates["updated_at"] = to_iso_utc()
        set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
        values = list(updates.values()) + [item_id]

        conn = _get_raw_conn()
        try:
            conn.execute(
                f"UPDATE memory_items SET {set_clause} WHERE id = ?", values
            )
            _tx_safe_commit(conn)
            affected = conn.total_changes > 0
        finally:
            _tx_safe_close(conn)
        return affected

    def confirm_item(self, item_id: str) -> bool:
        return self.update_item(item_id, status=MemoryStatus.CONFIRMED.value)

    def reject_item(self, item_id: str) -> bool:
        return self.update_item(item_id, status=MemoryStatus.REJECTED.value)

    def expire_item(self, item_id: str) -> bool:
        return self.update_item(item_id, status=MemoryStatus.EXPIRED.value)

    def supersede_item(
        self, old_item_id: str, new_item: MemoryItem
    ) -> Tuple[MemoryItem, MemoryItem]:
        old = self.get_item(old_item_id)
        if not old:
            raise ValueError(f"被取代的记忆 '{old_item_id}' 不存在")
        old.status = MemoryStatus.SUPERSEDED.value
        self.update_item(old_item_id, status=MemoryStatus.SUPERSEDED.value)

        new_item.supersedes_id = old_item_id

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

        old_updated = self.get_item(old_item_id)
        return old_updated or old, created

    # ----- Expiry -----

    def expire_due_items(self) -> int:
        now = to_iso_utc()
        conn = _get_raw_conn()
        try:
            result = conn.execute(
                """UPDATE memory_items
                   SET status = ?, updated_at = ?
                   WHERE valid_until IS NOT NULL
                     AND valid_until < ?
                     AND status IN ('candidate', 'active', 'confirmed')""",
                (MemoryStatus.EXPIRED.value, now, now),
            )
            _tx_safe_commit(conn)
            count = result.rowcount
        finally:
            _tx_safe_close(conn)
        return count

    def expire_session_items(self, session_id: str) -> int:
        now = to_iso_utc()
        conn = _get_raw_conn()
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
            _tx_safe_commit(conn)
            count = result.rowcount
        finally:
            _tx_safe_close(conn)
        return count

    # ----- Access Tracking -----

    def increment_access(self, item_id: str) -> bool:
        now = to_iso_utc()
        conn = _get_raw_conn()
        try:
            conn.execute(
                """UPDATE memory_items
                   SET access_count = access_count + 1,
                       last_accessed_at = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (now, now, item_id),
            )
            _tx_safe_commit(conn)
            affected = conn.total_changes > 0
        finally:
            _tx_safe_close(conn)
        return affected

    # ----- MemoryTrace -----

    def merge_trace(self, trace: MemoryTrace, phase: str = "write") -> MemoryTrace:
        """合并保存 MemoryTrace。只更新当前 phase 的字段，保留已有字段。

        phase='recall': 写入 recallDecision/Plan/candidates/selected/rejected/injectionMap
        phase='write': 写入 writeCandidates/writeResults，保留 recall 字段

        规则：
        1. patch 中未提供的字段保留 existing 值
        2. 空字符串不覆盖已有非空字符串
        3. 空 JSON 数组/字典不覆盖已有非空数据
        4. runId/sessionId 创建后不可修改
        5. createdAt 保持不变，updatedAt 每次更新
        """
        now = to_iso_utc()
        existing = self.get_trace_by_run(trace.run_id)

        if existing:
            # Merge: preserve existing values for fields not in this phase
            if phase == "write":
                # Keep recall fields from existing
                if not trace.recall_intent and existing.recall_intent:
                    trace.recall_intent = existing.recall_intent
                if trace.recall_decision_json in ("", "{}") and existing.recall_decision_json not in ("", "{}"):
                    trace.recall_decision_json = existing.recall_decision_json
                if trace.recall_plan_json in ("", "{}") and existing.recall_plan_json not in ("", "{}"):
                    trace.recall_plan_json = existing.recall_plan_json
                if trace.candidates_json in ("", "[]") and existing.candidates_json not in ("", "[]"):
                    trace.candidates_json = existing.candidates_json
                if trace.selected_json in ("", "[]") and existing.selected_json not in ("", "[]"):
                    trace.selected_json = existing.selected_json
                if trace.rejected_json in ("", "[]") and existing.rejected_json not in ("", "[]"):
                    trace.rejected_json = existing.rejected_json
                if trace.injection_map_json in ("", "{}") and existing.injection_map_json not in ("", "{}"):
                    trace.injection_map_json = existing.injection_map_json
                if not trace.recall_latency_ms and existing.recall_latency_ms:
                    trace.recall_latency_ms = existing.recall_latency_ms
                if not trace.token_estimate and existing.token_estimate:
                    trace.token_estimate = existing.token_estimate
            elif phase == "recall":
                # Keep write fields from existing
                if trace.write_candidates_json in ("", "[]") and existing.write_candidates_json not in ("", "[]"):
                    trace.write_candidates_json = existing.write_candidates_json
                if trace.write_results_json in ("", "[]") and existing.write_results_json not in ("", "[]"):
                    trace.write_results_json = existing.write_results_json
                if not trace.write_latency_ms and existing.write_latency_ms:
                    trace.write_latency_ms = existing.write_latency_ms

            # Preserve immutable fields
            if existing.session_id:
                trace.session_id = existing.session_id
            if existing.created_at:
                trace.created_at = existing.created_at
            if existing.run_id:
                trace.run_id = existing.run_id
            # Preserve event_thread_id from existing if patch is empty
            if not trace.event_thread_id and existing.event_thread_id:
                trace.event_thread_id = existing.event_thread_id
            trace.trace_id = existing.trace_id

        if not trace.created_at:
            trace.created_at = now
        trace.updated_at = now

        # Use existing save_trace logic
        return self._save_trace_internal(trace)

    def _save_trace_internal(self, trace: MemoryTrace) -> MemoryTrace:
        """内部 save_trace 实现（无合并逻辑）。由 save_trace 和 merge_trace 共用。"""
        conn = _get_raw_conn()
        try:
            result = conn.execute(
                """UPDATE memory_traces
                   SET session_id = ?, recall_intent = ?,
                       recall_decision_json = ?,
                       recall_plan_json = ?, candidates_json = ?,
                       selected_json = ?, rejected_json = ?,
                       injection_map_json = ?,
                       write_candidates_json = ?, write_results_json = ?,
                       token_estimate = ?, recall_latency_ms = ?,
                       write_latency_ms = ?, event_thread_id = ?,
                       updated_at = ?
                   WHERE run_id = ?""",
                (
                    trace.session_id, trace.recall_intent,
                    trace.recall_decision_json,
                    trace.recall_plan_json, trace.candidates_json,
                    trace.selected_json, trace.rejected_json,
                    trace.injection_map_json,
                    trace.write_candidates_json, trace.write_results_json,
                    trace.token_estimate, trace.recall_latency_ms,
                    trace.write_latency_ms, trace.event_thread_id,
                    trace.updated_at,
                    trace.run_id,
                ),
            )
            if result.rowcount == 0:
                conn.execute(
                    """INSERT INTO memory_traces (
                        trace_id, run_id, session_id, recall_intent,
                        recall_decision_json, recall_plan_json,
                        candidates_json, selected_json,
                        rejected_json, injection_map_json,
                        write_candidates_json, write_results_json,
                        token_estimate, recall_latency_ms, write_latency_ms,
                        event_thread_id, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        trace.trace_id, trace.run_id, trace.session_id,
                        trace.recall_intent,
                        trace.recall_decision_json,
                        trace.recall_plan_json, trace.candidates_json,
                        trace.selected_json,
                        trace.rejected_json, trace.injection_map_json,
                        trace.write_candidates_json, trace.write_results_json,
                        trace.token_estimate, trace.recall_latency_ms,
                        trace.write_latency_ms, trace.event_thread_id,
                        trace.created_at, trace.updated_at,
                    ),
                )
            _tx_safe_commit(conn)
        finally:
            _tx_safe_close(conn)
        return trace

    def save_trace(self, trace: MemoryTrace) -> MemoryTrace:
        """保存或更新一条 MemoryTrace。

        不使用 INSERT OR REPLACE：先 UPDATE，若无影响行再 INSERT。
        新代码应使用 merge_trace 以保留 phase 字段。
        """
        now = to_iso_utc()
        if not trace.created_at:
            trace.created_at = now
        trace.updated_at = now
        return self._save_trace_internal(trace)

    def get_trace_by_run(self, run_id: str) -> Optional[MemoryTrace]:
        conn = _get_raw_conn()
        try:
            row = conn.execute(
                "SELECT * FROM memory_traces WHERE run_id = ?", (run_id,)
            ).fetchone()
        finally:
            _tx_safe_close(conn)
        if not row:
            return None
        return MemoryTrace.from_row(dict(row))

    def list_traces(
        self, session_id: str, limit: int = 20
    ) -> List[MemoryTrace]:
        conn = _get_raw_conn()
        try:
            rows = conn.execute(
                """SELECT * FROM memory_traces
                   WHERE session_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
        finally:
            _tx_safe_close(conn)
        return [MemoryTrace.from_row(dict(r)) for r in rows]

    # ----- Session 清理 -----

    def delete_session_memory(self, session_id: str) -> int:
        """删除 Session 的所有记忆相关数据。

        使用事务保证原子性。异常时全部 rollback。
        """
        import logging
        logger = logging.getLogger(__name__)
        conn = _get_raw_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            c1 = conn.execute(
                "DELETE FROM memory_items WHERE session_id = ?",
                (session_id,),
            ).rowcount
            c2 = conn.execute(
                "DELETE FROM memory_traces WHERE session_id = ?",
                (session_id,),
            ).rowcount
            c3 = conn.execute(
                "DELETE FROM memory_event_threads WHERE session_id = ?",
                (session_id,),
            ).rowcount
            c4 = conn.execute(
                "DELETE FROM memory_session_states WHERE session_id = ?",
                (session_id,),
            ).rowcount
            conn.commit()
            total = c1 + c2 + c3 + c4
            logger.info("Deleted %d memory rows for session %s", total, session_id)
            return total
        except Exception:
            conn.rollback()
            logger.error("Failed to delete memory for session %s", session_id, exc_info=True)
            raise
        finally:
            _tx_safe_close(conn)

    # ================================================================
    # Event Thread (Phase 10 M3)
    # ================================================================

    def create_event_thread(
        self, session_id: str, title: str = "",
        started_run_id: str = "",
    ) -> MemoryEventThread:
        thread_id = generate_thread_id()
        now = to_iso_utc()
        conn = _get_raw_conn()
        try:
            # Close any existing active thread
            conn.execute(
                "UPDATE memory_event_threads SET status='closed', "
                "closed_at=?, updated_at=? WHERE session_id=? AND status='active'",
                (now, now, session_id),
            )
            # Create new thread
            conn.execute(
                "INSERT INTO memory_event_threads "
                "(id, session_id, status, title, started_run_id, last_run_id, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (thread_id, session_id, "active", title, started_run_id,
                 started_run_id, now, now),
            )
            # Update session state
            conn.execute(
                "INSERT OR REPLACE INTO memory_session_states "
                "(session_id, active_event_thread_id, updated_at) VALUES (?,?,?)",
                (session_id, thread_id, now),
            )
            _tx_safe_commit(conn)
        finally:
            _tx_safe_close(conn)
        return MemoryEventThread(
            id=thread_id, session_id=session_id, status="active",
            title=title, started_run_id=started_run_id,
            last_run_id=started_run_id, created_at=now, updated_at=now,
        )

    def get_event_thread(self, thread_id: str) -> Optional[MemoryEventThread]:
        conn = _get_raw_conn()
        try:
            row = conn.execute(
                "SELECT * FROM memory_event_threads WHERE id=?", (thread_id,)
            ).fetchone()
        finally:
            _tx_safe_close(conn)
        if not row:
            return None
        return MemoryEventThread.from_row(dict(row))

    def get_active_event_thread(self, session_id: str) -> Optional[MemoryEventThread]:
        conn = _get_raw_conn()
        try:
            row = conn.execute(
                "SELECT * FROM memory_event_threads "
                "WHERE session_id=? AND status='active' LIMIT 1",
                (session_id,),
            ).fetchone()
        finally:
            _tx_safe_close(conn)
        if not row:
            return None
        return MemoryEventThread.from_row(dict(row))

    def close_event_thread(self, thread_id: str) -> bool:
        now = to_iso_utc()
        conn = _get_raw_conn()
        try:
            conn.execute(
                "UPDATE memory_event_threads SET status='closed', "
                "closed_at=?, updated_at=? WHERE id=?",
                (now, now, thread_id),
            )
            _tx_safe_commit(conn)
            return conn.total_changes > 0
        finally:
            _tx_safe_close(conn)

    def update_event_thread_last_run(self, thread_id: str, run_id: str):
        now = to_iso_utc()
        conn = _get_raw_conn()
        try:
            conn.execute(
                "UPDATE memory_event_threads SET last_run_id=?, "
                "updated_at=? WHERE id=?",
                (run_id, now, thread_id),
            )
            _tx_safe_commit(conn)
        finally:
            _tx_safe_close(conn)

    def get_session_memory_state(self, session_id: str) -> Optional[MemorySessionState]:
        conn = _get_raw_conn()
        try:
            row = conn.execute(
                "SELECT * FROM memory_session_states WHERE session_id=?",
                (session_id,),
            ).fetchone()
        finally:
            _tx_safe_close(conn)
        if not row:
            return None
        return MemorySessionState.from_row(dict(row))

    def list_event_threads(self, session_id: str) -> List[MemoryEventThread]:
        conn = _get_raw_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM memory_event_threads WHERE session_id=? "
                "ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        finally:
            _tx_safe_close(conn)
        return [MemoryEventThread.from_row(dict(r)) for r in rows]

    def count_event_thread_items(self, session_id: str, thread_id: str) -> int:
        conn = _get_raw_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as c FROM memory_items "
                "WHERE session_id=? AND event_thread_id=?",
                (session_id, thread_id),
            ).fetchone()
            return row["c"] if row else 0
        finally:
            _tx_safe_close(conn)

    def count_event_thread_runs(self, session_id: str, thread_id: str) -> int:
        conn = _get_raw_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(DISTINCT run_id) as c FROM memory_traces "
                "WHERE session_id=? AND event_thread_id=?",
                (session_id, thread_id),
            ).fetchone()
            return row["c"] if row else 0
        finally:
            _tx_safe_close(conn)

    def get_session_memory_view(self, session_id: str) -> Dict[str, Any]:
        """获取 Session 的完整 Memory 视图。仅通过 MemoryStore 方法，零 SQL。"""
        state = self.get_session_memory_state(session_id)
        active_thread_id = state.active_event_thread_id if state else ""

        threads = self.list_event_threads(session_id)
        thread_dicts = []
        for t in threads:
            td = t.to_dict()
            td["itemCount"] = self.count_event_thread_items(session_id, t.id)
            td["runCount"] = self.count_event_thread_runs(session_id, t.id)
            thread_dicts.append(td)

        current_thread_items: Dict[str, List[Dict]] = {}
        if active_thread_id:
            items = self.list_session_items(session_id, limit=500, include_inactive=True)
            for item in items:
                if item.event_thread_id == active_thread_id:
                    mt = item.memory_type
                    if mt not in current_thread_items:
                        current_thread_items[mt] = []
                    current_thread_items[mt].append(item.to_dict())

        historical = [t for t in thread_dicts if t["id"] != active_thread_id]
        stats = self.count_session_items(session_id)

        return {
            "sessionId": session_id,
            "activeEventThreadId": active_thread_id,
            "eventThreads": thread_dicts,
            "summary": {
                "totalItems": stats.get("total_items", 0),
                "activeItems": stats.get("active_items", 0),
                "confirmedItems": stats.get("confirmed_items", 0),
                "candidateItems": stats.get("candidate_items", 0),
                "supersededItems": stats.get("superseded_items", 0),
                "expiredItems": stats.get("expired_items", 0),
                "rejectedItems": stats.get("rejected_items", 0),
            },
            "currentThread": current_thread_items,
            "historicalThreads": historical,
        }

    def get_item_superseded_by(self, memory_id: str) -> Optional[MemoryItem]:
        conn = _get_raw_conn()
        try:
            row = conn.execute(
                "SELECT * FROM memory_items WHERE supersedes_id=? LIMIT 1",
                (memory_id,),
            ).fetchone()
        finally:
            _tx_safe_close(conn)
        if not row:
            return None
        return MemoryItem.from_row(dict(row))
