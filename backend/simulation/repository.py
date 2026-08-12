"""
Simulation Repository — Phase 13 SQLite 持久化

复用现有 _get_conn() 模式。
表设计：
  - simulation_runs
  - simulation_events
  - simulation_snapshots
  - simulation_actions

所有 JSON 字段使用 ensure_ascii=False 序列化。
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

import backend.config as _config

from backend.simulation.models import (
    TrafficSimulationRun,
    TrafficSnapshot,
    TrafficRoadState,
    TrafficEvent,
    TrafficSimulationAction,
    SimulationStatus,
    CongestionLevel,
    ActionType,
    _utc_now_iso,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 数据库连接
# ═══════════════════════════════════════════════════════════════════════════════


def _get_conn() -> sqlite3.Connection:
    """获取 SQLite 连接（复用项目风格）。"""
    os.makedirs(os.path.dirname(_config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ═══════════════════════════════════════════════════════════════════════════════
# 表初始化
# ═══════════════════════════════════════════════════════════════════════════════


def init_simulation_tables():
    """幂等初始化 Simulation 表。"""
    conn = _get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS simulation_runs (
                run_id          TEXT PRIMARY KEY,
                scenario_id     TEXT NOT NULL DEFAULT '',
                status          TEXT NOT NULL DEFAULT 'created',
                current_snapshot_id TEXT DEFAULT '',
                snapshot_count  INTEGER NOT NULL DEFAULT 0,
                session_id      TEXT DEFAULT '',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS simulation_events (
                event_id        TEXT PRIMARY KEY,
                run_id          TEXT NOT NULL,
                event_type      TEXT NOT NULL DEFAULT '',
                severity        TEXT NOT NULL DEFAULT 'medium',
                road_id         TEXT NOT NULL DEFAULT '',
                intersection_id TEXT DEFAULT '',
                longitude       REAL DEFAULT 0.0,
                latitude        REAL DEFAULT 0.0,
                description     TEXT DEFAULT '',
                started_at      TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'active',
                simulated       INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS simulation_snapshots (
                snapshot_id             TEXT PRIMARY KEY,
                run_id                  TEXT NOT NULL,
                sequence                INTEGER NOT NULL DEFAULT 0,
                timestamp               TEXT NOT NULL,
                road_states_json        TEXT NOT NULL DEFAULT '{}',
                intersection_states_json TEXT NOT NULL DEFAULT '{}',
                active_event_ids_json   TEXT NOT NULL DEFAULT '[]',
                description             TEXT DEFAULT '',
                FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS simulation_actions (
                action_id           TEXT PRIMARY KEY,
                run_id              TEXT NOT NULL,
                action_type         TEXT NOT NULL DEFAULT '',
                target_ids_json     TEXT NOT NULL DEFAULT '[]',
                parameters_json     TEXT NOT NULL DEFAULT '{}',
                source              TEXT NOT NULL DEFAULT 'manual',
                workflow_run_id     TEXT DEFAULT '',
                idempotency_key     TEXT NOT NULL UNIQUE,
                before_snapshot_id  TEXT NOT NULL DEFAULT '',
                after_snapshot_id   TEXT DEFAULT '',
                status              TEXT NOT NULL DEFAULT 'pending',
                simulation          INTEGER NOT NULL DEFAULT 1,
                created_at          TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES simulation_runs(run_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_sim_events_run
                ON simulation_events(run_id);
            CREATE INDEX IF NOT EXISTS idx_sim_snapshots_run
                ON simulation_snapshots(run_id);
            CREATE INDEX IF NOT EXISTS idx_sim_actions_run
                ON simulation_actions(run_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_sim_actions_idem
                ON simulation_actions(idempotency_key);
        """)
        conn.commit()
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SQLiteSimulationRepository
# ═══════════════════════════════════════════════════════════════════════════════


class SQLiteSimulationRepository:
    """Simulation 数据持久化仓库。

    复用项目 _get_conn() 风格，与 Workflow Repository 一致。
    """

    # ── Run ────────────────────────────────────────────────────────────────

    def save_run(self, run: TrafficSimulationRun) -> None:
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO simulation_runs
                   (run_id, scenario_id, status, current_snapshot_id,
                    snapshot_count, session_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.run_id, run.scenario_id, run.status.value,
                    run.current_snapshot_id, run.snapshot_count,
                    run.session_id, run.created_at, _utc_now_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM simulation_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            return dict(row)
        finally:
            conn.close()

    def list_runs(self, limit: int = 20) -> List[Dict[str, Any]]:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM simulation_runs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def update_run_status(self, run_id: str, status: str,
                          current_snapshot_id: str = "",
                          snapshot_count: int = 0) -> None:
        conn = _get_conn()
        try:
            parts = ["status = ?", "updated_at = ?"]
            params: list = [status, _utc_now_iso()]
            if current_snapshot_id:
                parts.append("current_snapshot_id = ?")
                params.append(current_snapshot_id)
            if snapshot_count:
                parts.append("snapshot_count = ?")
                params.append(snapshot_count)
            params.append(run_id)
            conn.execute(
                f"UPDATE simulation_runs SET {', '.join(parts)} WHERE run_id = ?",
                params,
            )
            conn.commit()
        finally:
            conn.close()

    # ── Event ──────────────────────────────────────────────────────────────

    def save_event(self, event: TrafficEvent, run_id: str = "") -> None:
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO simulation_events
                   (event_id, run_id, event_type, severity, road_id,
                    intersection_id, longitude, latitude, description,
                    started_at, status, simulated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.event_id, run_id,
                    event.event_type, event.severity, event.road_id,
                    event.intersection_id, event.longitude, event.latitude,
                    event.description, event.started_at, event.status,
                    1 if event.simulated else 0,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def update_event_run(self, event_id: str, run_id: str) -> None:
        """将事件关联到 Run。"""
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE simulation_events SET run_id = ? WHERE event_id = ?",
                (run_id, event_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM simulation_events WHERE event_id = ?", (event_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_run_events(self, run_id: str) -> List[Dict[str, Any]]:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM simulation_events WHERE run_id = ? ORDER BY started_at",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Snapshot ───────────────────────────────────────────────────────────

    def save_snapshot(self, snap: TrafficSnapshot) -> None:
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO simulation_snapshots
                   (snapshot_id, run_id, sequence, timestamp,
                    road_states_json, intersection_states_json,
                    active_event_ids_json, description)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snap.snapshot_id, snap.run_id, snap.sequence, snap.timestamp,
                    json.dumps(
                        {rid: rs.model_dump() for rid, rs in snap.road_states.items()},
                        ensure_ascii=False,
                    ),
                    json.dumps(snap.intersection_states, ensure_ascii=False),
                    json.dumps(snap.active_event_ids, ensure_ascii=False),
                    snap.description,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM simulation_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_run_snapshots(self, run_id: str) -> List[Dict[str, Any]]:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM simulation_snapshots WHERE run_id = ? ORDER BY sequence ASC",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_latest_snapshot(self, run_id: str) -> Optional[Dict[str, Any]]:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM simulation_snapshots WHERE run_id = ? ORDER BY sequence DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ── Action ─────────────────────────────────────────────────────────────

    def save_action(self, action: TrafficSimulationAction, run_id: str = "") -> None:
        conn = _get_conn()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO simulation_actions
                   (action_id, run_id, action_type, target_ids_json,
                    parameters_json, source, workflow_run_id,
                    idempotency_key, before_snapshot_id, after_snapshot_id,
                    status, simulation, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    action.action_id, run_id,
                    action.action_type.value if isinstance(action.action_type, ActionType) else str(action.action_type),
                    json.dumps(action.target_ids, ensure_ascii=False),
                    json.dumps(action.parameters, ensure_ascii=False),
                    action.source, action.workflow_run_id,
                    action.idempotency_key,
                    action.before_snapshot_id, action.after_snapshot_id or "",
                    action.status, 1 if action.simulation else 0,
                    _utc_now_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def update_action_run(self, action_id: str, run_id: str,
                          before_snapshot_id: str = "",
                          after_snapshot_id: str = "",
                          status: str = "") -> None:
        """更新动作关联和执行结果。"""
        conn = _get_conn()
        try:
            parts = ["run_id = ?"]
            params: list = [run_id]
            if before_snapshot_id:
                parts.append("before_snapshot_id = ?")
                params.append(before_snapshot_id)
            if after_snapshot_id:
                parts.append("after_snapshot_id = ?")
                params.append(after_snapshot_id)
            if status:
                parts.append("status = ?")
                params.append(status)
            params.append(action_id)
            conn.execute(
                f"UPDATE simulation_actions SET {', '.join(parts)} WHERE action_id = ?",
                params,
            )
            conn.commit()
        finally:
            conn.close()

    def get_action_by_idempotency_key(self, key: str) -> Optional[Dict[str, Any]]:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM simulation_actions WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_run_actions(self, run_id: str) -> List[Dict[str, Any]]:
        conn = _get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM simulation_actions WHERE run_id = ? ORDER BY created_at ASC",
                (run_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
