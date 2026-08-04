"""
Chat 会话持久化 — SQLite 表管理
新增 4 张表：chat_sessions / chat_messages / chat_memory_summaries / rag_evidence_logs
"""
import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from backend.tools.db_tools import get_connection as _base_connection, DB_PATH

_initialized = False
_initialized_db_path: str = ""


def reset_initialized():
    """Reset initialization state — for tests that use temp DBs."""
    global _initialized, _initialized_db_path
    _initialized = False
    _initialized_db_path = ""


def get_conn():
    import os
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_chat_tables():
    """Initialize tables, indexes, and WAL mode. Idempotent. Bound to DB_PATH."""
    global _initialized, _initialized_db_path
    if _initialized and _initialized_db_path == DB_PATH:
        return

    # Step 1: Set WAL mode once — requires exclusive lock, do before anything else
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    finally:
        conn.close()

    # Step 2: Create tables and indexes
    conn = get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT DEFAULT '新对话',
                mode TEXT DEFAULT 'react',
                summary TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT DEFAULT '',
                mode TEXT DEFAULT 'react',
                result_summary TEXT DEFAULT '{}',
                evidence_ids TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chat_memory_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                summary TEXT DEFAULT '',
                key_topics TEXT DEFAULT '[]',
                unresolved_questions TEXT DEFAULT '[]',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS rag_evidence_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                query TEXT DEFAULT '',
                evidence TEXT DEFAULT '{}',
                score REAL DEFAULT 0,
                doc_type TEXT DEFAULT '',
                accepted INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            );

            -- Performance indexes
            CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at
                ON chat_sessions(updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
                ON chat_messages(session_id, created_at);
        """)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    _initialized = True
    _initialized_db_path = DB_PATH


# ===== Session CRUD =====

def create_session(session_id: str, mode: str = "react") -> Dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    try:
        conn.execute("INSERT INTO chat_sessions (id, mode, created_at, updated_at) VALUES (?, ?, ?, ?)",
                     (session_id, mode, now, now))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"sessionId": session_id, "title": "新对话", "mode": mode, "createdAt": now}


def list_sessions(limit: int = 30) -> List[Dict[str, Any]]:
    """Return recent sessions ordered by updated_at. Only loads sidebar-relevant fields."""
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT id, title, mode, updated_at
            FROM chat_sessions
            ORDER BY updated_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def delete_session(session_id: str) -> bool:
    # Init collaboration and memory tables for cascade delete
    try:
        from backend.agent.collaboration.db_repository import init_collaboration_tables
        init_collaboration_tables()
    except Exception:
        pass
    try:
        from backend.memory.store import init_memory_tables
        init_memory_tables()
    except Exception:
        pass

    conn = get_conn()
    try:
        # 0. Delete Phase 10 memory data
        try:
            conn.execute("DELETE FROM memory_items WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM memory_traces WHERE session_id = ?", (session_id,))
        except sqlite3.OperationalError:
            pass

        # 1. Delete collaboration data (child tables first)
        run_ids = [r[0] for r in conn.execute(
            "SELECT run_id FROM collaboration_runs WHERE session_id = ?", (session_id,)
        ).fetchall()]
        for run_id in run_ids:
            conn.execute("DELETE FROM collaboration_tasks WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM collaboration_messages WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM collaboration_conflicts WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM collaboration_events WHERE run_id = ?", (run_id,))
        conn.execute("DELETE FROM collaboration_runs WHERE session_id = ?", (session_id,))

        # 2. Delete chat data
        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM chat_memory_summaries WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM rag_evidence_logs WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))

        affected = conn.total_changes
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return affected > 0


def update_session_title(session_id: str, title: str):
    conn = get_conn()
    try:
        conn.execute("UPDATE chat_sessions SET title = ? WHERE id = ?", (title, session_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def update_session_summary(session_id: str, summary: str):
    conn = get_conn()
    try:
        conn.execute("UPDATE chat_sessions SET summary = ?, updated_at = ? WHERE id = ?",
                     (summary[:800], datetime.now().strftime("%Y-%m-%d %H:%M:%S"), session_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ===== Message CRUD =====

def add_message(msg_id: str, session_id: str, role: str, content: str, mode: str = "react",
                result_summary: Optional[Dict] = None, evidence_ids: Optional[List[str]] = None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO chat_messages (id, session_id, role, content, mode, result_summary, evidence_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (msg_id, session_id, role, content[:3000], mode,
             json.dumps(result_summary or {}, ensure_ascii=False),
             json.dumps(evidence_ids or [], ensure_ascii=False), now))
        conn.execute("UPDATE chat_sessions SET updated_at = ? WHERE id = ?", (now, session_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_session_messages(session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_recent_messages(session_id: str, limit: int = 6) -> List[Dict[str, Any]]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at DESC LIMIT ?",
            (session_id, limit)).fetchall()
    finally:
        conn.close()
    return list(reversed([dict(r) for r in rows]))


# ===== Memory Summary =====

def get_memory_summary(session_id: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM chat_memory_summaries WHERE session_id = ?", (session_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def upsert_memory_summary(session_id: str, summary: str, key_topics: List[str], unresolved: List[str]):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO chat_memory_summaries (session_id, summary, key_topics, unresolved_questions, updated_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, summary[:800], json.dumps(key_topics, ensure_ascii=False), json.dumps(unresolved, ensure_ascii=False), now))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ===== Evidence Log =====

def log_evidence(session_id: str, message_id: str, query: str, evidence: Dict, score: float,
                 doc_type: str = "", accepted: bool = True):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO rag_evidence_logs (session_id, message_id, query, evidence, score, doc_type, accepted, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (session_id, message_id, query, json.dumps(evidence, ensure_ascii=False), score, doc_type, 1 if accepted else 0, now))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
