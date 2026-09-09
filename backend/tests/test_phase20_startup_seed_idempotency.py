"""Phase20 startup seed idempotency regression tests."""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "phase20_startup_seed.db")
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    init_workflow_tables()
    yield test_db


def _template_definition_count() -> int:
    conn = sqlite3.connect(cfg.DB_PATH)
    try:
        return conn.execute(
            """
            SELECT COUNT(*) FROM workflow_definitions
            WHERE
                (name='高速匝道拥堵分流与闭环' AND category='拥堵处置')
                OR (name='学校/医院周边拥堵协同' AND category='拥堵处置')
                OR (name='道路交通事故122/120联动' AND category='事故联动')
                OR id='simulation_bridge'
            """
        ).fetchone()[0]
    finally:
        conn.close()


def test_workflow_template_seed_is_idempotent_across_startups():
    import backend.app as app_mod

    repo = SQLiteWorkflowRepository()
    first_seeded = app_mod.seed_workflow_templates(repo)
    count_after_first = _template_definition_count()
    second_seeded = app_mod.seed_workflow_templates(repo)
    count_after_second = _template_definition_count()

    assert first_seeded == 4
    assert count_after_first == 4
    assert second_seeded == 0
    assert count_after_second == count_after_first
