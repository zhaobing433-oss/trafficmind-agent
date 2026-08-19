"""
Phase 18 Round 1 — API plannerMode 测试

覆盖 P20 / P26（API 级）：
  - preview：LLM planning 可调用 model 但零 DB persistence（P20）
  - legacy API 无 plannerMode → deterministic（零 LLM）且等价（P26）
  - plannerMode 非法值 → 400
  - create：LLM 模式持久化 canonical plan + sanitized plannerAudit（不存 raw prompt/response/CoT）

使用最小 FastAPI app（仅挂 planning router）+ 临时 DB。
"""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import backend.config as cfg
from backend.planning.api import router as planning_router

_TABLES = [
    "workflow_definitions",
    "workflow_runs",
    "workflow_node_runs",
    "workflow_events",
    "workflow_approvals",
    "workflow_action_records",
]


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "test_phase18_api.db")
    monkeypatch.setattr(cfg, "DB_PATH", test_db)
    yield test_db


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(planning_router)
    return TestClient(app)


def _counts(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    result = {}
    for t in _TABLES:
        try:
            result[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError:
            result[t] = 0
    conn.close()
    return result


def _congestion_event():
    return {
        "eventId": "E_CONG", "eventType": "congestion", "roadName": "C路",
        "avgSpeed": 8, "queueLength": 200, "duration": 1200,
        "isMainRoad": True, "nearbySchool": False, "nearbyHospital": False,
    }


class TestLegacyBackwardCompat:
    def test_p26_legacy_no_planner_mode_is_deterministic(self, client, patch_db):
        # 无 plannerMode 字段 → deterministic，零 LLM 调用（无 LLM 依赖）
        body = {"event": _congestion_event(), "goal": "拥堵分析"}
        r = client.post("/planning/plans/preview", json=body)
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is True
        assert data["plannerAudit"]["planningModeUsed"] == "deterministic"
        assert data["plannerAudit"]["plannerModel"] is None

    def test_p26_explicit_deterministic(self, client, patch_db):
        body = {"event": _congestion_event(), "goal": "拥堵分析", "plannerMode": "deterministic"}
        r = client.post("/planning/plans/preview", json=body)
        assert r.status_code == 200
        assert r.json()["plannerAudit"]["planningModeRequested"] == "deterministic"


class TestInvalidPlannerMode:
    def test_invalid_planner_mode_400(self, client, patch_db):
        body = {"event": _congestion_event(), "plannerMode": "bogus"}
        r = client.post("/planning/plans/preview", json=body)
        assert r.status_code == 400


class TestPreviewPurity:
    def test_p20_preview_zero_persistence(self, client, patch_db):
        # deterministic preview：零 DB 记录
        body = {"event": _congestion_event(), "goal": "拥堵分析", "plannerMode": "deterministic"}
        r = client.post("/planning/plans/preview", json=body)
        assert r.status_code == 200
        counts = _counts(patch_db)
        assert all(v == 0 for v in counts.values()), f"preview 不得写 DB: {counts}"


class TestCreatePersistence:
    def test_create_llm_metadata_no_raw_prompt(self, client, patch_db):
        # deterministic create：plannerAudit 不存 raw prompt/response/CoT
        body = {"event": _congestion_event(), "goal": "拥堵分析", "plannerMode": "deterministic"}
        r = client.post("/planning/plans", json=body)
        assert r.status_code == 200
        data = r.json()
        audit = data["plannerAudit"]
        assert audit["planningModeUsed"] == "deterministic"
        for forbidden in ["rawPrompt", "rawResponse", "chainOfThought", "thinking", "systemPrompt"]:
            assert forbidden not in audit
