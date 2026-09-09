"""SQLite repository for Traffic Case Memory."""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

import backend.config as _config
from backend.case_memory.models import CaseMemoryQuality, TrafficCaseMemory, utc_now_iso


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(_config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _json_dump(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _json_load(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return value if value is not None else default
    try:
        return json.loads(value) if value else default
    except json.JSONDecodeError:
        return default


def init_case_memory_tables() -> None:
    conn = _get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS traffic_case_memories (
                case_id TEXT PRIMARY KEY,
                region_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                road_id TEXT DEFAULT NULL,
                intersection_id TEXT DEFAULT NULL,
                source_session_id TEXT DEFAULT NULL,
                source_collaboration_run_id TEXT DEFAULT NULL,
                source_plan_id TEXT DEFAULT NULL,
                source_workflow_run_id TEXT NOT NULL UNIQUE,
                final_status TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                event_snapshot_json TEXT NOT NULL DEFAULT '{}',
                agent_facts_json TEXT NOT NULL DEFAULT '{}',
                plan_facts_json TEXT NOT NULL DEFAULT '{}',
                human_decisions_json TEXT NOT NULL DEFAULT '[]',
                workflow_outcome_json TEXT NOT NULL DEFAULT '{}',
                lessons_json TEXT NOT NULL DEFAULT '[]',
                generated_summary TEXT DEFAULT NULL,
                started_at TEXT DEFAULT NULL,
                completed_at TEXT DEFAULT NULL,
                source_type TEXT NOT NULL DEFAULT 'workflow_case_builder',
                source_reference TEXT DEFAULT '',
                provenance_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_case_memory_region_event
                ON traffic_case_memories(region_id, event_type);
            CREATE INDEX IF NOT EXISTS idx_case_memory_region_road
                ON traffic_case_memories(region_id, road_id);
            CREATE INDEX IF NOT EXISTS idx_case_memory_region_intersection
                ON traffic_case_memories(region_id, intersection_id);
            CREATE INDEX IF NOT EXISTS idx_case_memory_source_event
                ON traffic_case_memories(event_id);
            CREATE INDEX IF NOT EXISTS idx_case_memory_source_plan
                ON traffic_case_memories(source_plan_id);
            CREATE INDEX IF NOT EXISTS idx_case_memory_status
                ON traffic_case_memories(final_status, quality_status);
            CREATE INDEX IF NOT EXISTS idx_case_memory_completed
                ON traffic_case_memories(completed_at);
            """
        )
        conn.commit()
    finally:
        conn.close()


class SQLiteCaseMemoryRepository:
    def get_case(self, case_id: str) -> Optional[TrafficCaseMemory]:
        init_case_memory_tables()
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM traffic_case_memories WHERE case_id = ?",
                (case_id,),
            ).fetchone()
            return self._row_to_case(row) if row else None
        finally:
            conn.close()

    def get_case_by_source_workflow_run_id(self, run_id: str) -> Optional[TrafficCaseMemory]:
        init_case_memory_tables()
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM traffic_case_memories WHERE source_workflow_run_id = ?",
                (run_id,),
            ).fetchone()
            return self._row_to_case(row) if row else None
        finally:
            conn.close()

    def list_cases_for_source_event(self, event_id: str) -> List[TrafficCaseMemory]:
        init_case_memory_tables()
        conn = _get_conn()
        try:
            rows = conn.execute(
                """
                SELECT * FROM traffic_case_memories
                WHERE event_id = ?
                ORDER BY completed_at DESC, updated_at DESC, case_id
                """,
                (event_id,),
            ).fetchall()
            return [self._row_to_case(row) for row in rows]
        finally:
            conn.close()

    def insert_case(self, case: TrafficCaseMemory) -> TrafficCaseMemory:
        init_case_memory_tables()
        conn = _get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO traffic_case_memories (
                    case_id, region_id, event_id, event_type, road_id, intersection_id,
                    source_session_id, source_collaboration_run_id, source_plan_id,
                    source_workflow_run_id, final_status, quality_status,
                    event_snapshot_json, agent_facts_json, plan_facts_json,
                    human_decisions_json, workflow_outcome_json, lessons_json,
                    generated_summary, started_at, completed_at, source_type,
                    source_reference, provenance_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._case_values(case),
            )
            conn.commit()
            return case
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_case_preserving_identity(
        self,
        existing: TrafficCaseMemory,
        rebuilt: TrafficCaseMemory,
    ) -> TrafficCaseMemory:
        init_case_memory_tables()
        rebuilt.case_id = existing.case_id
        rebuilt.created_at = existing.created_at
        rebuilt.updated_at = utc_now_iso()
        conn = _get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE traffic_case_memories SET
                    region_id = ?, event_id = ?, event_type = ?, road_id = ?,
                    intersection_id = ?, source_session_id = ?,
                    source_collaboration_run_id = ?, source_plan_id = ?,
                    source_workflow_run_id = ?, final_status = ?, quality_status = ?,
                    event_snapshot_json = ?, agent_facts_json = ?,
                    plan_facts_json = ?, human_decisions_json = ?,
                    workflow_outcome_json = ?, lessons_json = ?, generated_summary = ?,
                    started_at = ?, completed_at = ?, source_type = ?,
                    source_reference = ?, provenance_json = ?, created_at = ?,
                    updated_at = ?
                WHERE case_id = ?
                """,
                self._case_values(rebuilt)[1:] + (rebuilt.case_id,),
            )
            conn.commit()
            return rebuilt
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def query_cases(
        self,
        *,
        region_id: str,
        event_type: str,
        road_id: Optional[str] = None,
        intersection_id: Optional[str] = None,
        final_status: Optional[str] = None,
        quality_status: Optional[str] = None,
        as_of: Optional[str] = None,
        limit: int = 5,
        for_agent: bool = False,
    ) -> Dict[str, Any]:
        init_case_memory_tables()
        bounded_limit = max(1, min(int(limit or 5), 50))
        where = ["region_id = ?", "event_type = ?"]
        params: List[Any] = [region_id, event_type]
        if road_id:
            where.append("road_id = ?")
            params.append(road_id)
        if intersection_id:
            where.append("intersection_id = ?")
            params.append(intersection_id)
        if final_status:
            where.append("final_status = ?")
            params.append(final_status)
        if quality_status:
            where.append("quality_status = ?")
            params.append(quality_status)
        elif for_agent:
            where.append("quality_status IN (?, ?)")
            params.extend([CaseMemoryQuality.VALIDATED.value, CaseMemoryQuality.PARTIAL.value])
        if as_of:
            where.append("datetime(completed_at) IS NOT NULL")
            where.append("datetime(completed_at) < datetime(?)")
            params.append(as_of)

        clause = " AND ".join(where)
        conn = _get_conn()
        try:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS total FROM traffic_case_memories WHERE {clause}",
                tuple(params),
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT * FROM traffic_case_memories
                WHERE {clause}
                ORDER BY completed_at DESC, updated_at DESC, case_id
                LIMIT ?
                """,
                tuple(params + [bounded_limit]),
            ).fetchall()
            return {
                "cases": [self._row_to_case(row) for row in rows],
                "total": total_row["total"] if total_row else 0,
                "limit": bounded_limit,
            }
        finally:
            conn.close()

    def find_context_candidates(
        self,
        *,
        region_id: str,
        event_type: str,
        road_id: Optional[str],
        intersection_id: Optional[str],
        as_of: Optional[str],
        limit: int,
    ) -> Dict[str, Any]:
        bounded_limit = max(1, min(int(limit or 5), 20))
        where = [
            "region_id = ?",
            "event_type = ?",
            "quality_status IN (?, ?)",
        ]
        params: List[Any] = [
            region_id,
            event_type,
            CaseMemoryQuality.VALIDATED.value,
            CaseMemoryQuality.PARTIAL.value,
        ]
        if as_of:
            where.append("datetime(completed_at) IS NOT NULL")
            where.append("datetime(completed_at) < datetime(?)")
            params.append(as_of)
        clause = " AND ".join(where)
        order_params: List[Any] = [intersection_id, intersection_id, road_id, road_id]
        conn = _get_conn()
        try:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS total FROM traffic_case_memories WHERE {clause}",
                tuple(params),
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT * FROM traffic_case_memories
                WHERE {clause}
                ORDER BY
                    CASE
                        WHEN ? IS NOT NULL AND intersection_id = ? THEN 3
                        WHEN ? IS NOT NULL AND road_id = ? THEN 2
                        ELSE 1
                    END DESC,
                    datetime(completed_at) DESC,
                    updated_at DESC,
                    case_id
                LIMIT ?
                """,
                tuple(params + order_params + [bounded_limit]),
            ).fetchall()
            return {
                "cases": [self._row_to_case(row) for row in rows],
                "total": total_row["total"] if total_row else 0,
                "limit": bounded_limit,
            }
        finally:
            conn.close()

    def _case_values(self, case: TrafficCaseMemory) -> Sequence[Any]:
        return (
            case.case_id,
            case.region_id,
            case.event_id,
            case.event_type,
            case.road_id,
            case.intersection_id,
            case.source_session_id,
            case.source_collaboration_run_id,
            case.source_plan_id,
            case.source_workflow_run_id,
            case.final_status,
            case.quality_status.value,
            _json_dump(case.event_snapshot),
            _json_dump(case.agent_facts),
            _json_dump(case.plan_facts),
            _json_dump(case.human_decisions),
            _json_dump(case.workflow_outcome),
            _json_dump(case.lessons),
            case.generated_summary,
            case.started_at,
            case.completed_at,
            case.source_type,
            case.source_reference,
            _json_dump(case.provenance),
            case.created_at,
            case.updated_at,
        )

    def _row_to_case(self, row: sqlite3.Row) -> TrafficCaseMemory:
        return TrafficCaseMemory(
            case_id=row["case_id"],
            region_id=row["region_id"],
            event_id=row["event_id"],
            event_type=row["event_type"],
            road_id=row["road_id"],
            intersection_id=row["intersection_id"],
            source_session_id=row["source_session_id"],
            source_collaboration_run_id=row["source_collaboration_run_id"],
            source_plan_id=row["source_plan_id"],
            source_workflow_run_id=row["source_workflow_run_id"],
            final_status=row["final_status"],
            quality_status=row["quality_status"],
            event_snapshot=_json_load(row["event_snapshot_json"], {}),
            agent_facts=_json_load(row["agent_facts_json"], {}),
            plan_facts=_json_load(row["plan_facts_json"], {}),
            human_decisions=_json_load(row["human_decisions_json"], []),
            workflow_outcome=_json_load(row["workflow_outcome_json"], {}),
            lessons=_json_load(row["lessons_json"], []),
            generated_summary=row["generated_summary"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            source_type=row["source_type"],
            source_reference=row["source_reference"],
            provenance=_json_load(row["provenance_json"], {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
