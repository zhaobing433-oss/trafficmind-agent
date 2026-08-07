"""
Workflow Repository — Phase 12

SQLite 持久化实现。表结构与 PostgreSQL 迁移解耦：
  - workflow_definitions
  - workflow_definition_versions
  - workflow_runs
  - workflow_node_runs
  - workflow_events
  - workflow_approvals
  - workflow_action_records

所有 JSON 字段使用 ensure_ascii=False 序列化。
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import backend.config as _config

from backend.workflow.models import (
    ActionStatus,
    ApprovalDecision,
    DefinitionStatus,
    NodeConfig,
    NodeStatus,
    NodeType,
    WorkflowActionRecord,
    WorkflowApproval,
    WorkflowDefinition,
    WorkflowDefinitionVersion,
    WorkflowEvent,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowRunStatus,
)
from backend.workflow.definition import WorkflowRepository as AbstractWorkflowRepository


# ═══════════════════════════════════════════════════════════════════════════════
# 数据库连接
# ═══════════════════════════════════════════════════════════════════════════════


def _get_conn() -> sqlite3.Connection:
    """获取 SQLite 连接。"""
    os.makedirs(os.path.dirname(_config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_parse_status(status_str: str) -> WorkflowRunStatus:
    """安全解析状态字符串，未知状态按 paused 处理。"""
    try:
        return WorkflowRunStatus(status_str)
    except ValueError:
        return WorkflowRunStatus.PAUSED


def _ensure_wait_columns():
    """非破坏性添加 wait 相关列（幂等）。"""
    conn = _get_conn()
    try:
        for col_def in [
            "wait_type TEXT DEFAULT ''",
            "wake_at TEXT DEFAULT NULL",
            "resumed_at TEXT DEFAULT NULL",
            "resume_reason TEXT DEFAULT ''",
        ]:
            col_name = col_def.split()[0]
            try:
                conn.execute(f"ALTER TABLE workflow_runs ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# 表初始化（幂等）
# ═══════════════════════════════════════════════════════════════════════════════


def init_workflow_tables() -> None:
    """初始化 Workflow 相关表（幂等 CREATE TABLE IF NOT EXISTS）。"""
    conn = _get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS workflow_definitions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT '',
            status TEXT DEFAULT 'draft',
            nodes_json TEXT DEFAULT '[]',
            entry_node_id TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS workflow_definition_versions (
            id TEXT PRIMARY KEY,
            definition_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            definition_json TEXT DEFAULT '{}',
            changelog TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            UNIQUE(definition_id, version)
        );

        CREATE TABLE IF NOT EXISTS workflow_runs (
            run_id TEXT PRIMARY KEY,
            definition_id TEXT DEFAULT '',
            version INTEGER DEFAULT 1,
            session_id TEXT DEFAULT '',
            event_thread_id TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            current_node_id TEXT DEFAULT '',
            state_json TEXT DEFAULT '{}',
            started_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            completed_at TEXT DEFAULT '',
            triggered_by TEXT DEFAULT 'system'
        );

        CREATE TABLE IF NOT EXISTS workflow_node_runs (
            node_run_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            node_type TEXT DEFAULT 'trigger',
            status TEXT DEFAULT 'pending',
            attempt INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 1,
            input_snapshot_json TEXT DEFAULT '{}',
            output_snapshot_json TEXT DEFAULT '{}',
            error TEXT DEFAULT '',
            started_at TEXT DEFAULT '',
            completed_at TEXT DEFAULT '',
            duration_ms INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS workflow_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_id TEXT DEFAULT '',
            event_type TEXT DEFAULT '',
            payload_json TEXT DEFAULT '{}',
            sequence INTEGER DEFAULT 0,
            created_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS workflow_approvals (
            approval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_id TEXT DEFAULT '',
            proposed_actions_json TEXT DEFAULT '[]',
            edited_actions_json TEXT DEFAULT '[]',
            decision TEXT DEFAULT 'pending',
            reviewer TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            decided_at TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS workflow_action_records (
            action_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_id TEXT DEFAULT '',
            action_type TEXT DEFAULT '',
            idempotency_key TEXT NOT NULL UNIQUE,
            params_json TEXT DEFAULT '{}',
            result_json TEXT DEFAULT '{}',
            status TEXT DEFAULT 'pending',
            error TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            completed_at TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_wf_runs_session ON workflow_runs(session_id);
        CREATE INDEX IF NOT EXISTS idx_wf_runs_status ON workflow_runs(status);
        CREATE INDEX IF NOT EXISTS idx_wf_node_runs_run ON workflow_node_runs(run_id);
        CREATE INDEX IF NOT EXISTS idx_wf_events_run ON workflow_events(run_id);
        CREATE INDEX IF NOT EXISTS idx_wf_approvals_run ON workflow_approvals(run_id);
        CREATE INDEX IF NOT EXISTS idx_wf_actions_run ON workflow_action_records(run_id);
        CREATE INDEX IF NOT EXISTS idx_wf_actions_idem ON workflow_action_records(idempotency_key);
        CREATE INDEX IF NOT EXISTS idx_wf_versions_def ON workflow_definition_versions(definition_id, version);
    """)
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SQLiteWorkflowRepository
# ═══════════════════════════════════════════════════════════════════════════════


class SQLiteWorkflowRepository(AbstractWorkflowRepository):
    """Workflow SQLite 持久化实现。

    表结构与 PostgreSQL 迁移解耦：
      - 所有 JSON 字段用单独列（_json 后缀）
      - 不使用 ORM，直接 SQL
      - JSON 序列化统一使用 ensure_ascii=False
    """

    # ── Definition CRUD ──────────────────────────────────────────────────

    def save_definition(self, definition: WorkflowDefinition) -> None:
        init_workflow_tables()
        conn = _get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO workflow_definitions VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                definition.id,
                definition.name,
                definition.description,
                definition.category,
                definition.status.value,
                json.dumps([n.to_dict() for n in definition.nodes], ensure_ascii=False),
                definition.entry_node_id,
                json.dumps(definition.metadata, ensure_ascii=False),
                definition.created_at,
                definition.updated_at,
            ),
        )
        conn.commit()
        conn.close()

    def get_definition(self, definition_id: str) -> Optional[WorkflowDefinition]:
        init_workflow_tables()
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM workflow_definitions WHERE id=?", (definition_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return self._row_to_definition(dict(row))

    def list_definitions(
        self, status: Optional[str] = None
    ) -> List[WorkflowDefinition]:
        init_workflow_tables()
        conn = _get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM workflow_definitions WHERE status=? ORDER BY updated_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM workflow_definitions ORDER BY updated_at DESC"
            ).fetchall()
        conn.close()
        return [self._row_to_definition(dict(r)) for r in rows]

    def _row_to_definition(self, d: Dict[str, Any]) -> WorkflowDefinition:
        nodes_raw = d.get("nodes_json", "[]")
        if isinstance(nodes_raw, str):
            nodes_list = json.loads(nodes_raw) if nodes_raw else []
        else:
            nodes_list = nodes_raw
        metadata_raw = d.get("metadata_json", "{}")
        if isinstance(metadata_raw, str):
            metadata = json.loads(metadata_raw) if metadata_raw else {}
        else:
            metadata = metadata_raw
        return WorkflowDefinition(
            id=d["id"],
            name=d["name"],
            description=d.get("description", ""),
            category=d.get("category", ""),
            status=DefinitionStatus(d.get("status", "draft")),
            nodes=[NodeConfig.from_dict(n) for n in (nodes_list or [])],
            entry_node_id=d.get("entry_node_id", ""),
            metadata=metadata or {},
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )

    # ── Version CRUD ─────────────────────────────────────────────────────

    def save_definition_version(self, version: WorkflowDefinitionVersion) -> None:
        init_workflow_tables()
        conn = _get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO workflow_definition_versions VALUES (?, ?, ?, ?, ?, ?)""",
            (
                version.id,
                version.definition_id,
                version.version,
                json.dumps(version.definition_json, ensure_ascii=False),
                version.changelog,
                version.created_at,
            ),
        )
        conn.commit()
        conn.close()

    def get_definition_version(
        self, definition_id: str, version: int
    ) -> Optional[WorkflowDefinitionVersion]:
        init_workflow_tables()
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM workflow_definition_versions WHERE definition_id=? AND version=?",
            (definition_id, version),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        d = dict(row)
        def_json = d.get("definition_json", "{}")
        if isinstance(def_json, str):
            def_json = json.loads(def_json)
        return WorkflowDefinitionVersion(
            id=d["id"],
            definition_id=d["definition_id"],
            version=d["version"],
            definition_json=def_json,
            changelog=d.get("changelog", ""),
            created_at=d.get("created_at", ""),
        )

    def get_latest_version_number(self, definition_id: str) -> int:
        init_workflow_tables()
        conn = _get_conn()
        row = conn.execute(
            "SELECT MAX(version) as mv FROM workflow_definition_versions WHERE definition_id=?",
            (definition_id,),
        ).fetchone()
        conn.close()
        return row["mv"] if row and row["mv"] is not None else 0

    def list_definition_versions(
        self, definition_id: str
    ) -> List[WorkflowDefinitionVersion]:
        init_workflow_tables()
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM workflow_definition_versions WHERE definition_id=? ORDER BY version DESC",
            (definition_id,),
        ).fetchall()
        conn.close()
        results = []
        for row in rows:
            d = dict(row)
            def_json = d.get("definition_json", "{}")
            if isinstance(def_json, str):
                def_json = json.loads(def_json)
            results.append(WorkflowDefinitionVersion(
                id=d["id"],
                definition_id=d["definition_id"],
                version=d["version"],
                definition_json=def_json,
                changelog=d.get("changelog", ""),
                created_at=d.get("created_at", ""),
            ))
        return results

    # ── Run CRUD ─────────────────────────────────────────────────────────

    def save_run(self, run: WorkflowRun) -> None:
        init_workflow_tables()
        _ensure_wait_columns()
        conn = _get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO workflow_runs VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                run.run_id,
                run.definition_id,
                run.version,
                run.session_id,
                run.event_thread_id,
                run.status.value,
                run.current_node_id,
                json.dumps(run.state, ensure_ascii=False),
                run.started_at,
                run.updated_at,
                run.completed_at,
                run.triggered_by,
                "",     # wait_type
                None,   # wake_at
                None,   # resumed_at
                "",     # resume_reason
            ),
        )
        conn.commit()
        conn.close()

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        init_workflow_tables()
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM workflow_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return self._row_to_run(dict(row))

    def list_runs(
        self,
        session_id: str = "",
        definition_id: str = "",
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[WorkflowRun]:
        init_workflow_tables()
        conn = _get_conn()
        query = "SELECT * FROM workflow_runs WHERE 1=1"
        params: List[Any] = []
        if session_id:
            query += " AND session_id=?"
            params.append(session_id)
        if definition_id:
            query += " AND definition_id=?"
            params.append(definition_id)
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [self._row_to_run(dict(r)) for r in rows]

    def _row_to_run(self, d: Dict[str, Any]) -> WorkflowRun:
        state_raw = d.get("state_json", "{}")
        if isinstance(state_raw, str):
            state = json.loads(state_raw) if state_raw else {}
        else:
            state = state_raw
        return WorkflowRun(
            run_id=d["run_id"],
            definition_id=d.get("definition_id", ""),
            version=d.get("version", 1),
            session_id=d.get("session_id", ""),
            event_thread_id=d.get("event_thread_id", ""),
            status=_safe_parse_status(d.get("status", "pending")),
            current_node_id=d.get("current_node_id", ""),
            state=state or {},
            started_at=d.get("started_at", ""),
            updated_at=d.get("updated_at", ""),
            completed_at=d.get("completed_at", ""),
            triggered_by=d.get("triggered_by", "system"),
        )

    # ── NodeRun CRUD ─────────────────────────────────────────────────────

    def save_node_run(self, node_run: WorkflowNodeRun) -> None:
        init_workflow_tables()
        conn = _get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO workflow_node_runs VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                node_run.node_run_id,
                node_run.run_id,
                node_run.node_id,
                node_run.node_type.value,
                node_run.status.value,
                node_run.attempt,
                node_run.max_attempts,
                json.dumps(node_run.input_snapshot, ensure_ascii=False),
                json.dumps(node_run.output_snapshot, ensure_ascii=False),
                node_run.error,
                node_run.started_at,
                node_run.completed_at,
                node_run.duration_ms,
            ),
        )
        conn.commit()
        conn.close()

    def get_node_runs(self, run_id: str) -> List[WorkflowNodeRun]:
        init_workflow_tables()
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM workflow_node_runs WHERE run_id=? ORDER BY started_at",
            (run_id,),
        ).fetchall()
        conn.close()
        return [self._row_to_node_run(dict(r)) for r in rows]

    def _row_to_node_run(self, d: Dict[str, Any]) -> WorkflowNodeRun:
        inp = d.get("input_snapshot_json", "{}")
        out = d.get("output_snapshot_json", "{}")
        if isinstance(inp, str):
            inp = json.loads(inp) if inp else {}
        if isinstance(out, str):
            out = json.loads(out) if out else {}
        return WorkflowNodeRun(
            node_run_id=d["node_run_id"],
            run_id=d["run_id"],
            node_id=d["node_id"],
            node_type=NodeType(d.get("node_type", "trigger")),
            status=NodeStatus(d.get("status", "pending")),
            attempt=d.get("attempt", 0),
            max_attempts=d.get("max_attempts", 1),
            input_snapshot=inp or {},
            output_snapshot=out or {},
            error=d.get("error", ""),
            started_at=d.get("started_at", ""),
            completed_at=d.get("completed_at", ""),
            duration_ms=d.get("duration_ms", 0),
        )

    # ── Event CRUD ───────────────────────────────────────────────────────

    def save_event(self, event: WorkflowEvent) -> None:
        init_workflow_tables()
        conn = _get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO workflow_events VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.run_id,
                event.node_id,
                event.event_type,
                json.dumps(event.payload, ensure_ascii=False),
                event.sequence,
                event.created_at,
            ),
        )
        conn.commit()
        conn.close()

    def list_events(self, run_id: str) -> List[WorkflowEvent]:
        init_workflow_tables()
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM workflow_events WHERE run_id=? ORDER BY sequence",
            (run_id,),
        ).fetchall()
        conn.close()
        results = []
        for row in rows:
            d = dict(row)
            payload = d.get("payload_json", "{}")
            if isinstance(payload, str):
                payload = json.loads(payload) if payload else {}
            results.append(WorkflowEvent(
                event_id=d["event_id"],
                run_id=d["run_id"],
                node_id=d.get("node_id", ""),
                event_type=d.get("event_type", ""),
                payload=payload or {},
                sequence=d.get("sequence", 0),
                created_at=d.get("created_at", ""),
            ))
        return results

    # ── Approval CRUD ────────────────────────────────────────────────────

    def save_approval(self, approval: WorkflowApproval) -> None:
        init_workflow_tables()
        conn = _get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO workflow_approvals VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                approval.approval_id,
                approval.run_id,
                approval.node_id,
                json.dumps(approval.proposed_actions, ensure_ascii=False),
                json.dumps(approval.edited_actions, ensure_ascii=False),
                approval.decision.value,
                approval.reviewer,
                approval.comment,
                approval.created_at,
                approval.decided_at,
            ),
        )
        conn.commit()
        conn.close()

    def get_approval(self, approval_id: str) -> Optional[WorkflowApproval]:
        init_workflow_tables()
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM workflow_approvals WHERE approval_id=?",
            (approval_id,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return self._row_to_approval(dict(row))

    def get_pending_approval(
        self, run_id: str, node_id: str
    ) -> Optional[WorkflowApproval]:
        init_workflow_tables()
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM workflow_approvals WHERE run_id=? AND node_id=? AND decision='pending' ORDER BY created_at DESC LIMIT 1",
            (run_id, node_id),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return self._row_to_approval(dict(row))

    def _row_to_approval(self, d: Dict[str, Any]) -> WorkflowApproval:
        proposed = d.get("proposed_actions_json", "[]")
        edited = d.get("edited_actions_json", "[]")
        if isinstance(proposed, str):
            proposed = json.loads(proposed) if proposed else []
        if isinstance(edited, str):
            edited = json.loads(edited) if edited else []
        return WorkflowApproval(
            approval_id=d["approval_id"],
            run_id=d["run_id"],
            node_id=d.get("node_id", ""),
            proposed_actions=proposed or [],
            edited_actions=edited or [],
            decision=ApprovalDecision(d.get("decision", "pending")),
            reviewer=d.get("reviewer", ""),
            comment=d.get("comment", ""),
            created_at=d.get("created_at", ""),
            decided_at=d.get("decided_at", ""),
        )

    # ── ActionRecord CRUD ────────────────────────────────────────────────

    def save_action_record(self, record: WorkflowActionRecord) -> None:
        init_workflow_tables()
        conn = _get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO workflow_action_records VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            (
                record.action_id,
                record.run_id,
                record.node_id,
                record.action_type,
                record.idempotency_key,
                json.dumps(record.params, ensure_ascii=False),
                json.dumps(record.result, ensure_ascii=False),
                record.status.value,
                record.error,
                record.created_at,
                record.completed_at,
            ),
        )
        conn.commit()
        conn.close()

    def get_action_record_by_idempotency_key(
        self, idempotency_key: str
    ) -> Optional[WorkflowActionRecord]:
        init_workflow_tables()
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM workflow_action_records WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return self._row_to_action_record(dict(row))

    def list_action_records(self, run_id: str) -> List[WorkflowActionRecord]:
        init_workflow_tables()
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM workflow_action_records WHERE run_id=? ORDER BY created_at",
            (run_id,),
        ).fetchall()
        conn.close()
        return [self._row_to_action_record(dict(r)) for r in rows]

    def _row_to_action_record(self, d: Dict[str, Any]) -> WorkflowActionRecord:
        params = d.get("params_json", "{}")
        result = d.get("result_json", "{}")
        if isinstance(params, str):
            params = json.loads(params) if params else {}
        if isinstance(result, str):
            result = json.loads(result) if result else {}
        return WorkflowActionRecord(
            action_id=d["action_id"],
            run_id=d["run_id"],
            node_id=d.get("node_id", ""),
            action_type=d.get("action_type", ""),
            idempotency_key=d.get("idempotency_key", ""),
            params=params or {},
            result=result or {},
            status=ActionStatus(d.get("status", "pending")),
            error=d.get("error", ""),
            created_at=d.get("created_at", ""),
            completed_at=d.get("completed_at", ""),
        )
