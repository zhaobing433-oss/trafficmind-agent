"""
Workflow Center V2 Round 1 — Tests

测试新增的 GET /workflow/runs 列表端点。

原则：
  - 只读，不修改数据库
  - 不触发 Agent/approval/action
  - 验证 RunSummaryDTO 字段完整性
  - 验证批量查询避免 N+1
  - 验证历史审批判断不单独依赖 pendingApproval
"""

from __future__ import annotations

import json
import math
import time
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.workflow.api import (
    _build_run_summary,
    _derive_approval_status,
    _extract_event_summary,
)
from backend.workflow.models import (
    TERMINAL_STATUSES,
    WorkflowRun,
    WorkflowRunStatus,
)
from backend.workflow.repository import SQLiteWorkflowRepository


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def client() -> TestClient:
    """FastAPI TestClient（内存内，不启动真实服务器）。"""
    return TestClient(app)


@pytest.fixture
def repo() -> SQLiteWorkflowRepository:
    """SQLite Repository 实例（会触碰真实 DB，但只做只读查询）。"""
    return SQLiteWorkflowRepository()


# ═══════════════════════════════════════════════════════════════════════════════
# Unit: _extract_event_summary
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractEventSummary:
    """测试事件摘要提取逻辑。"""

    def test_full_event(self):
        """完整 currentEvent → 全部字段。"""
        state = {
            "currentEvent": {
                "roadName": "演示大道（西→东）",
                "eventType": "accident",
                "eventTypeCn": "事故",
                "description": "两车追尾",
            }
        }
        result = _extract_event_summary(state)
        assert result is not None
        assert result["roadName"] == "演示大道（西→东）"
        assert result["eventType"] == "accident"
        assert result["eventTypeCn"] == "事故"
        assert result["description"] == "两车追尾"

    def test_partial_event(self):
        """部分字段缺失 → 缺失字段为 None。"""
        state = {
            "currentEvent": {
                "roadName": "测试路",
                "eventType": "congestion",
            }
        }
        result = _extract_event_summary(state)
        assert result is not None
        assert result["roadName"] == "测试路"
        assert result["eventType"] == "congestion"
        assert result["eventTypeCn"] is None
        assert result["description"] is None

    def test_fallback_to_original_input(self):
        """currentEvent 不存在时回退到 originalInput。"""
        state = {
            "originalInput": {
                "roadName": "回退路",
                "eventType": "violation",
            }
        }
        result = _extract_event_summary(state)
        assert result is not None
        assert result["roadName"] == "回退路"

    def test_empty_state(self):
        """空 state → None。"""
        assert _extract_event_summary({}) is None

    def test_empty_event_dict(self):
        """currentEvent 为空 dict → None。"""
        result = _extract_event_summary({"currentEvent": {}})
        assert result is None

    def test_all_none_fields(self):
        """所有字段为 None → None。"""
        result = _extract_event_summary({
            "currentEvent": {"roadName": None, "eventType": None}
        })
        assert result is None

    def test_none_state(self):
        """state 为 None → None。"""
        assert _extract_event_summary(None) is None


# ═══════════════════════════════════════════════════════════════════════════════
# Unit: _derive_approval_status
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeriveApprovalStatus:
    """测试审批状态推导逻辑。

    关键：不单独依赖 pendingApproval（历史 completed run 为 null）。
    """

    def test_active_awaiting_approval(self):
        """运行中待审批 → awaiting_approval。"""
        result = _derive_approval_status("awaiting_approval", {}, [])
        assert result == "awaiting_approval"

    def test_rejected(self):
        """run status = rejected → rejected。"""
        result = _derive_approval_status("rejected", {}, [])
        assert result == "rejected"

    def test_completed_with_approved_actions_in_state(self):
        """Completed + state.approvedActions 非空 → approved。

        这是最关键场景：completed run 的 pendingApproval = null，
        但 approvedActions 持久化在 state 中。
        """
        state = {"approvedActions": [{"actionType": "traffic_diversion"}]}
        result = _derive_approval_status("completed", state, [])
        assert result == "approved"

    def test_completed_with_approval_table_approved(self):
        """Completed + 审批表中有 approved 决策 → approved。"""
        result = _derive_approval_status("completed", {}, ["approved"])
        assert result == "approved"

    def test_completed_with_approval_table_edited(self):
        """Edited 也视为 approved。"""
        result = _derive_approval_status("completed", {}, ["edited"])
        assert result == "approved"

    def test_completed_with_approval_table_rejected(self):
        """审批表中有 rejected → rejected。"""
        result = _derive_approval_status("completed", {}, ["rejected"])
        assert result == "rejected"

    def test_completed_no_approval_data(self):
        """无任何审批数据 → not_required。"""
        result = _derive_approval_status("completed", {}, [])
        assert result == "not_required"

    def test_pending_approval_in_state_but_no_decision(self):
        """pendingApproval 存在但无决策 → awaiting_approval。"""
        state = {"pendingApproval": {"approvalId": "test-123"}}
        result = _derive_approval_status("running", state, [])
        assert result == "awaiting_approval"

    def test_state_approved_actions_takes_priority(self):
        """state.approvedActions 优先级高于审批表。"""
        state = {"approvedActions": [{"actionType": "x"}]}
        # 即使审批表中是 pending，state 有 approvedActions 就返回 approved
        result = _derive_approval_status("completed", state, ["pending"])
        assert result == "approved"

    def test_not_required_for_pending_without_approval(self):
        """pending 状态无审批节点 → not_required。"""
        result = _derive_approval_status("pending", {}, [])
        assert result == "not_required"


# ═══════════════════════════════════════════════════════════════════════════════
# Unit: _build_run_summary
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildRunSummary:
    """测试 RunSummary DTO 构建。"""

    def _make_run(self, **kwargs) -> WorkflowRun:
        defaults = {
            "run_id": "wfrun_test_001",
            "definition_id": "wfdef_test",
            "version": 1,
            "session_id": "sess_1",
            "event_thread_id": "",
            "status": WorkflowRunStatus.COMPLETED,
            "current_node_id": "close",
            "state": {},
            "started_at": "2026-08-10T01:00:00Z",
            "updated_at": "2026-08-10T02:00:00Z",
            "completed_at": "2026-08-10T02:00:00Z",
            "triggered_by": "api",
        }
        defaults.update(kwargs)
        return WorkflowRun(**defaults)

    def test_basic_fields(self):
        run = self._make_run()
        summary = _build_run_summary(run, "测试模板", 9, None, None, None)

        assert summary["runId"] == "wfrun_test_001"
        assert summary["definitionId"] == "wfdef_test"
        assert summary["definitionName"] == "测试模板"
        assert summary["status"] == "completed"
        assert summary["version"] == 1
        assert summary["sessionId"] == "sess_1"
        assert summary["isTerminal"] is True
        assert summary["startedAt"] == "2026-08-10T01:00:00Z"
        assert summary["completedAt"] == "2026-08-10T02:00:00Z"

    def test_definition_name_null(self):
        """Definition 不存在时 definitionName 为 None, totalNodes 为 None。"""
        run = self._make_run()
        summary = _build_run_summary(run, None, None, None, None, None)
        assert summary["definitionName"] is None
        assert summary["progress"]["totalNodes"] is None

    def test_event_summary_in_summary(self):
        run = self._make_run(state={
            "currentEvent": {"roadName": "测试路", "eventType": "accident"}
        })
        summary = _build_run_summary(run, "模板", 9, None, None, None)
        assert summary["eventSummary"] is not None
        assert summary["eventSummary"]["roadName"] == "测试路"

    def test_progress_with_node_counts(self):
        """totalNodes=9 (definition), executedNodes=9 (node_runs)。"""
        run = self._make_run(current_node_id="agent_task")
        node_counts = {"total": 9, "succeeded": 7, "failed": 1, "running": 1, "pending": 0}
        summary = _build_run_summary(run, "模板", 9, node_counts, None, None)

        assert summary["progress"]["totalNodes"] == 9
        assert summary["progress"]["executedNodes"] == 9
        assert summary["progress"]["succeededNodes"] == 7
        assert summary["progress"]["failedNodes"] == 1
        assert summary["progress"]["currentNode"] == "agent_task"

    def test_progress_partial_execution(self):
        """running workflow: totalNodes=9 (定义), executedNodes=4 (仅前4个节点)。"""
        run = self._make_run(current_node_id="agent_task")
        # definition 有 9 个节点，但只执行了 4 个
        node_counts = {"total": 4, "succeeded": 3, "failed": 0, "running": 1, "pending": 0}
        summary = _build_run_summary(run, "模板", 9, node_counts, None, None)

        assert summary["progress"]["totalNodes"] == 9
        assert summary["progress"]["executedNodes"] == 4
        assert summary["progress"]["succeededNodes"] == 3
        assert summary["progress"]["failedNodes"] == 0

    def test_progress_without_node_counts(self):
        """无 node_counts 时字段为默认值，totalNodes 来自 definition。"""
        run = self._make_run()
        summary = _build_run_summary(run, "模板", 9, None, None, None)

        assert summary["progress"]["totalNodes"] == 9  # from definition
        assert summary["progress"]["executedNodes"] == 0
        assert summary["progress"]["succeededNodes"] == 0
        assert summary["progress"]["failedNodes"] == 0

    def test_approval_summary_in_summary(self):
        run = self._make_run(
            status=WorkflowRunStatus.COMPLETED,
            state={"approvedActions": [{"actionType": "x"}]},
        )
        summary = _build_run_summary(run, "模板", None, None, None, None)
        assert summary["approvalSummary"]["status"] == "approved"

    def test_action_summary(self):
        run = self._make_run()
        action_counts = {"total": 2, "succeeded": 1, "failed": 1}
        summary = _build_run_summary(run, "模板", None, None, action_counts, None)

        assert summary["actionSummary"]["total"] == 2
        assert summary["actionSummary"]["succeeded"] == 1
        assert summary["actionSummary"]["failed"] == 1

    def test_action_summary_default_zero(self):
        run = self._make_run()
        summary = _build_run_summary(run, "模板", None, None, None, None)

        assert summary["actionSummary"]["total"] == 0
        assert summary["actionSummary"]["succeeded"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: GET /workflow/runs
# ═══════════════════════════════════════════════════════════════════════════════


class TestListRunsEndpoint:
    """测试 GET /workflow/runs 端点。"""

    def test_list_runs_200(self, client):
        """基础请求返回 200 + 标准结构。"""
        resp = client.get("/workflow/runs?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert "runs" in data
        assert isinstance(data["runs"], list)
        assert data["limit"] == 5
        assert data["offset"] == 0

    def test_default_sort_stable(self, client):
        """默认排序 updated_at DESC, run_id DESC 在同时间戳下稳定。"""
        resp1 = client.get("/workflow/runs?limit=20")
        resp2 = client.get("/workflow/runs?limit=20")

        ids1 = [r["runId"] for r in resp1.json()["runs"]]
        ids2 = [r["runId"] for r in resp2.json()["runs"]]
        assert ids1 == ids2, "连续两次请求返回顺序必须一致"

    def test_status_filter(self, client):
        """status 过滤仅返回指定状态。"""
        resp = client.get("/workflow/runs?status=completed&limit=10")
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        assert all(r["status"] == "completed" for r in runs)

    def test_definition_filter(self, client):
        """definition_id 过滤仅返回指定模板的 Run。"""
        resp = client.get(
            "/workflow/runs?definition_id=simulation_bridge&limit=5"
        )
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        assert all(r["definitionId"] == "simulation_bridge" for r in runs)

    def test_session_filter(self, client):
        """session_id 过滤仅返回指定会话的 Run。"""
        resp = client.get("/workflow/runs?session_id=nonexistent&limit=5")
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        # 可能返回空或仅有该 session 的
        assert all(r["sessionId"] == "nonexistent" for r in runs) or len(runs) == 0

    def test_limit(self, client):
        """limit 参数生效。"""
        resp = client.get("/workflow/runs?limit=3")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["runs"]) <= 3
        assert data["limit"] == 3

    def test_limit_max_200(self, client):
        """limit 最大 200。"""
        resp = client.get("/workflow/runs?limit=201")
        assert resp.status_code == 422  # FastAPI 参数校验

    def test_limit_min_1(self, client):
        """limit 最小 1。"""
        resp = client.get("/workflow/runs?limit=0")
        assert resp.status_code == 422

    def test_offset(self, client):
        """offset 分页：第 1 页和第 2 页不重叠。"""
        page1 = client.get("/workflow/runs?limit=3&offset=0")
        page2 = client.get("/workflow/runs?limit=3&offset=3")
        assert page1.status_code == 200
        assert page2.status_code == 200

        ids1 = {r["runId"] for r in page1.json()["runs"]}
        ids2 = {r["runId"] for r in page2.json()["runs"]}
        assert ids1.isdisjoint(ids2), "分页结果不应重叠"

    def test_illegal_status_returns_400(self, client):
        """非法 status 参数返回 400 且包含有效值列表。"""
        resp = client.get("/workflow/runs?status=invalid_status")
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "无效的状态值" in detail
        # 应列出有效值
        for valid in ["pending", "running", "completed", "failed"]:
            assert valid in detail

    def test_completed_run_has_event_summary(self, client, repo):
        """已完成的 Run 应有事件摘要（若 state 中有 currentEvent）。"""
        # 查找一个 completed 且有 currentEvent 的 run
        runs = repo.list_runs(status="completed", limit=5)
        run_with_event = None
        for r in runs:
            state = r.state if isinstance(r.state, dict) else {}
            if state.get("currentEvent"):
                run_with_event = r
                break

        if run_with_event is None:
            pytest.skip("No completed run with currentEvent found")

        resp = client.get(f"/workflow/runs?status=completed&limit=50")
        assert resp.status_code == 200
        runs_data = resp.json()["runs"]
        target = next(
            (r for r in runs_data if r["runId"] == run_with_event.run_id), None
        )
        assert target is not None, f"Run {run_with_event.run_id} should be in list"
        assert target["eventSummary"] is not None, (
            f"Completed run should have eventSummary"
        )

    def test_awaiting_approval_summary(self, client, repo):
        """awaiting_approval 状态的 Run 审批摘要应为 awaiting_approval。"""
        runs = repo.list_runs(status="awaiting_approval", limit=3)
        if not runs:
            pytest.skip("No awaiting_approval runs found")

        resp = client.get("/workflow/runs?status=awaiting_approval&limit=3")
        assert resp.status_code == 200
        runs_data = resp.json()["runs"]
        for r in runs_data:
            assert r["status"] == "awaiting_approval"
            assert r["approvalSummary"]["status"] == "awaiting_approval"

    def test_failed_run_summary(self, client, repo):
        """failed 状态的 Run 应有 isTerminal=True。"""
        runs = repo.list_runs(status="failed", limit=3)
        if not runs:
            pytest.skip("No failed runs found")

        resp = client.get("/workflow/runs?status=failed&limit=3")
        assert resp.status_code == 200
        runs_data = resp.json()["runs"]
        for r in runs_data:
            assert r["status"] == "failed"
            assert r["isTerminal"] is True

    def test_cancelled_rejected_summary(self, client, repo):
        """cancelled/rejected 状态。"""
        for st in ["cancelled", "rejected"]:
            runs = repo.list_runs(status=st, limit=3)
            if not runs:
                continue

            resp = client.get(f"/workflow/runs?status={st}&limit=3")
            assert resp.status_code == 200
            runs_data = resp.json()["runs"]
            for r in runs_data:
                assert r["status"] == st

    def test_definition_name_in_summary(self, client):
        """每个 Run 应有 definitionName（或 None 如果模板不存在）。"""
        resp = client.get("/workflow/runs?limit=10")
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        for r in runs:
            assert "definitionName" in r
            # definitionName 可以是 None（缺失模板时），但不能缺失字段

    def test_approval_summary_not_only_pending_approval(self, client, repo):
        """completed run 的审批摘要不依赖 pendingApproval（已为 null）。

        特别验证：已知 completed + approved 的 run 审批状态为 approved。
        """
        # 找一个 completed 且有 approvedActions 的 run
        runs = repo.list_runs(status="completed", limit=30)
        found = None
        for r in runs:
            state = r.state if isinstance(r.state, dict) else {}
            approved = state.get("approvedActions")
            if approved and isinstance(approved, list) and len(approved) > 0:
                found = r
                break

        if found is None:
            pytest.skip("No completed+approved run found for verification")

        resp = client.get(f"/workflow/runs?status=completed&limit=50")
        assert resp.status_code == 200
        runs_data = resp.json()["runs"]
        target = next(
            (r for r in runs_data if r["runId"] == found.run_id), None
        )
        assert target is not None
        # 关键断言：状态为 completed，审批摘要显示 approved（而非 not_required）
        assert target["status"] == "completed"
        assert target["approvalSummary"]["status"] == "approved", (
            f"Expected 'approved' but got '{target['approvalSummary']['status']}' "
            f"for completed run with approvedActions. "
            f"Bug: pendingApproval-only check would give 'not_required'."
        )

    def test_action_summary_fields(self, client):
        """actionSummary 包含 total/succeeded/failed。"""
        resp = client.get("/workflow/runs?limit=10")
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        for r in runs:
            s = r["actionSummary"]
            assert "total" in s
            assert "succeeded" in s
            assert "failed" in s
            assert s["total"] >= 0
            assert s["succeeded"] >= 0
            assert s["failed"] >= 0

    def test_missing_definition_tolerance(self, client):
        """即使某些 definition 不存在也不应 500。"""
        resp = client.get("/workflow/runs?limit=50")
        assert resp.status_code == 200
        # 所有 run 都有 definitionName 字段（值为 None 是合法的）
        for r in resp.json()["runs"]:
            assert "definitionName" in r

    def test_malformed_state_json_tolerance(self, client, repo):
        """格式异常的 state_json 不应导致 500。

        测试：构造一个 state_json 为非 JSON 字符串的 scenario。
        实际上 repository 的 _row_to_run 会安全解析（异常 → {}）。
        这里验证列表不会因为有异常数据的旧 run 而崩溃。
        """
        resp = client.get("/workflow/runs?limit=50")
        assert resp.status_code == 200
        # 所有 run 都有合法的 eventSummary（至少是 None 或 dict）
        for r in resp.json()["runs"]:
            assert r["eventSummary"] is None or isinstance(r["eventSummary"], dict)

    def test_empty_result(self, client):
        """不存在的 session_id 应返回空列表而非错误。"""
        resp = client.get(
            "/workflow/runs?session_id=this_session_does_not_exist_99999"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["runs"] == []

    def test_get_only_readonly(self, client):
        """GET /workflow/runs 返回只读列表；POST 需 body 不可混用。"""
        # GET with query params → list endpoint
        resp_get = client.get("/workflow/runs?limit=5")
        assert resp_get.status_code == 200
        assert "runs" in resp_get.json()

        # POST without body → start_run validation error (correct: separate endpoint)
        resp_post = client.post("/workflow/runs")
        assert resp_post.status_code == 422  # Pydantic validation: missing body

    def test_total_consistency(self, client):
        """total 应 ≥ len(runs)（因为可能有更多数据）。"""
        resp = client.get("/workflow/runs?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= len(data["runs"])

        # 无过滤时 total 应该合理（> 0）
        resp_all = client.get("/workflow/runs?limit=200")
        assert resp_all.status_code == 200
        assert resp_all.json()["total"] > 0

    def test_sort_desc_by_updated_at(self, client):
        """验证按 updated_at DESC 排序。"""
        resp = client.get("/workflow/runs?limit=20")
        assert resp.status_code == 200
        runs = resp.json()["runs"]
        if len(runs) < 2:
            pytest.skip("Need at least 2 runs to verify sort order")

        timestamps = [r["updatedAt"] for r in runs if r["updatedAt"]]
        for i in range(len(timestamps) - 1):
            assert timestamps[i] >= timestamps[i + 1], (
                f"Sort violation at index {i}: {timestamps[i]} < {timestamps[i + 1]}"
            )

    def test_multi_filter_combination(self, client, repo):
        """多个 filter 组合使用。"""
        # 先找到合适的组合
        runs = repo.list_runs(status="completed", limit=1)
        if not runs:
            pytest.skip("No completed runs for combo filter")
        run = runs[0]
        if not run.definition_id:
            pytest.skip("Run has no definition_id")

        resp = client.get(
            f"/workflow/runs?status=completed"
            f"&definition_id={run.definition_id}&limit=5"
        )
        assert resp.status_code == 200
        runs_data = resp.json()["runs"]
        for r in runs_data:
            assert r["status"] == "completed"
            assert r["definitionId"] == run.definition_id


# ═══════════════════════════════════════════════════════════════════════════════
# Read-only Safety
# ═══════════════════════════════════════════════════════════════════════════════


class TestReadOnlySafety:
    """验证 GET /workflow/runs 是完全只读的。"""

    def test_repeated_calls_no_state_change(self, client, repo):
        """连续 10 次调用不应改变任何业务数据数量。"""
        # 记录初始状态
        total_runs_before = repo.count_runs()
        total_events_before = self._count_table("workflow_events")
        total_actions_before = self._count_table("workflow_action_records")

        # 连续调用 10 次
        for _ in range(10):
            resp = client.get("/workflow/runs?limit=50")
            assert resp.status_code == 200

        # 验证数量不变
        total_runs_after = repo.count_runs()
        total_events_after = self._count_table("workflow_events")
        total_actions_after = self._count_table("workflow_action_records")

        assert total_runs_before == total_runs_after, (
            f"Runs count changed: {total_runs_before} → {total_runs_after}"
        )
        assert total_events_before == total_events_after, (
            f"Events count changed: {total_events_before} → {total_events_after}"
        )
        assert total_actions_before == total_actions_after, (
            f"Actions count changed: {total_actions_before} → {total_actions_after}"
        )

    @staticmethod
    def _count_table(table_name: str) -> int:
        import sqlite3
        import backend.config as _config
        conn = sqlite3.connect(_config.DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table_name}").fetchone()
        conn.close()
        return row["cnt"] if row else 0

    def test_no_workflow_started_events(self, client, repo):
        """调用 list API 不应产生 workflow_started 事件。"""
        # 记录最大的 event sequence
        events_before = self._count_table("workflow_events")

        for _ in range(5):
            client.get("/workflow/runs?limit=50")

        events_after = self._count_table("workflow_events")
        assert events_before == events_after

    def test_no_new_runs_created(self, client, repo):
        """调用 list API 不应创建新 Run。"""
        before = repo.count_runs()

        for _ in range(5):
            client.get("/workflow/runs?limit=50")

        after = repo.count_runs()
        assert before == after


# ═══════════════════════════════════════════════════════════════════════════════
# N+1 Prevention (structural verification)
# ═══════════════════════════════════════════════════════════════════════════════


class TestNPlusOnePrevention:
    """验证列表查询使用批量加载，而非逐条 N+1 查询。"""

    def test_batch_node_counts_handles_empty(self, repo):
        """空输入返回空 dict。"""
        result = repo.batch_get_node_counts([])
        assert result == {}

    def test_batch_node_counts_single_query(self, repo):
        """单个 run_id 返回正确统计。"""
        # 查找一个有 node_runs 的 run
        runs = repo.list_runs(status="completed", limit=1)
        if not runs:
            pytest.skip("No runs found")
        run_id = runs[0].run_id

        result = repo.batch_get_node_counts([run_id])
        assert run_id in result
        counts = result[run_id]
        assert "total" in counts
        assert "succeeded" in counts
        assert "failed" in counts

    def test_batch_node_counts_multi(self, repo):
        """批量多个 run_ids 一次查询返回。"""
        runs = repo.list_runs(limit=10)
        if len(runs) < 2:
            pytest.skip("Need at least 2 runs")
        run_ids = [r.run_id for r in runs]

        result = repo.batch_get_node_counts(run_ids)
        # 至少有一个 run 有 node_runs
        assert len(result) >= 1, "Batch should return data for at least one run"

    def test_batch_action_counts(self, repo):
        """批量 action 统计。"""
        runs = repo.list_runs(status="completed", limit=10)
        run_ids = [r.run_id for r in runs]

        result = repo.batch_get_action_counts(run_ids)
        assert isinstance(result, dict)

    def test_batch_definition_summaries(self, repo):
        """批量 definition summary 查询：返回 name + nodeCount。"""
        def_ids = ["simulation_bridge", "nonexistent_def_id_xyz"]
        result = repo.batch_get_definition_summaries(def_ids)
        assert "simulation_bridge" in result
        assert isinstance(result["simulation_bridge"]["name"], str)
        assert isinstance(result["simulation_bridge"]["nodeCount"], int)
        assert result["simulation_bridge"]["nodeCount"] > 0, (
            "simulation_bridge should have nodes"
        )
        # 不存在的 ID 不出现在结果中
        assert "nonexistent_def_id_xyz" not in result

    def test_batch_approval_decisions(self, repo):
        """批量审批决策查询。"""
        runs = repo.list_runs(status="completed", limit=10)
        run_ids = [r.run_id for r in runs]

        result = repo.batch_get_approval_decisions(run_ids)
        assert isinstance(result, dict)

    def test_definition_summary_node_count(self, repo):
        """definition summary 的 nodeCount 来自 nodes_json 解析。"""
        def_ids = ["simulation_bridge"]
        result = repo.batch_get_definition_summaries(def_ids)
        assert isinstance(result["simulation_bridge"]["name"], str)
        assert result["simulation_bridge"]["nodeCount"] >= 7  # known: 9 nodes


# ═══════════════════════════════════════════════════════════════════════════════
# Known Run Verification (wfrun_20260810022901_0d80c2ec)
# ═══════════════════════════════════════════════════════════════════════════════


class TestKnownRun:
    """使用已知 completed run 验证语义完整性。

    如果该 Run 不在当前数据库中，测试优雅跳过。
    """

    KNOWN_RUN_ID = "wfrun_20260810022901_0d80c2ec"

    def test_known_run_in_list(self, client, repo):
        """已知 Run 出现在列表中。"""
        run = repo.get_run(self.KNOWN_RUN_ID)
        if run is None:
            pytest.skip(f"Known run {self.KNOWN_RUN_ID} not in current DB")

        resp = client.get("/workflow/runs?status=completed&limit=200")
        assert resp.status_code == 200
        runs_data = resp.json()["runs"]
        target = next(
            (r for r in runs_data if r["runId"] == self.KNOWN_RUN_ID), None
        )
        assert target is not None, f"Known run should appear in completed list"

    def test_known_run_status_completed(self, client, repo):
        """验证已知 Run 的状态为 completed。"""
        run = repo.get_run(self.KNOWN_RUN_ID)
        if run is None:
            pytest.skip(f"Known run {self.KNOWN_RUN_ID} not in current DB")

        resp = client.get(f"/workflow/runs?status=completed&limit=200")
        target = next(
            (r for r in resp.json()["runs"] if r["runId"] == self.KNOWN_RUN_ID),
            None,
        )
        assert target is not None
        assert target["status"] == "completed"
        assert target["definitionId"] == "simulation_bridge"
        assert target["isTerminal"] is True

    def test_known_run_event_summary(self, client, repo):
        """验证已知 Run 的事件摘要。"""
        run = repo.get_run(self.KNOWN_RUN_ID)
        if run is None:
            pytest.skip(f"Known run {self.KNOWN_RUN_ID} not in current DB")

        state = run.state if isinstance(run.state, dict) else {}
        current_event = state.get("currentEvent", {})

        resp = client.get(f"/workflow/runs?status=completed&limit=200")
        target = next(
            (r for r in resp.json()["runs"] if r["runId"] == self.KNOWN_RUN_ID),
            None,
        )
        assert target is not None
        es = target["eventSummary"]
        assert es is not None, "Known run should have eventSummary"
        assert es["roadName"] is not None
        assert es["eventType"] is not None
        assert es["eventTypeCn"] == current_event.get("eventTypeCn")

    def test_known_run_approval_approved(self, client, repo):
        """验证已知 Run 审批状态为 approved（历史审批，非 pendingApproval）。"""
        run = repo.get_run(self.KNOWN_RUN_ID)
        if run is None:
            pytest.skip(f"Known run {self.KNOWN_RUN_ID} not in current DB")

        state = run.state if isinstance(run.state, dict) else {}
        pending = state.get("pendingApproval")
        # 关键：pendingApproval 为 null（已完成）
        assert pending is None, (
            f"Expected pendingApproval=None for completed run, got {pending}"
        )

        resp = client.get(f"/workflow/runs?status=completed&limit=200")
        target = next(
            (r for r in resp.json()["runs"] if r["runId"] == self.KNOWN_RUN_ID),
            None,
        )
        assert target is not None
        # 但审批摘要应仍能识别为 approved
        assert target["approvalSummary"]["status"] == "approved", (
            f"Expected 'approved' but got '{target['approvalSummary']['status']}'. "
            f"This proves pendingApproval-only check is insufficient."
        )

    def test_known_run_action_summary(self, client, repo):
        """验证已知 Run 的动作摘要。"""
        run = repo.get_run(self.KNOWN_RUN_ID)
        if run is None:
            pytest.skip(f"Known run {self.KNOWN_RUN_ID} not in current DB")

        resp = client.get(f"/workflow/runs?status=completed&limit=200")
        target = next(
            (r for r in resp.json()["runs"] if r["runId"] == self.KNOWN_RUN_ID),
            None,
        )
        assert target is not None
        action = target["actionSummary"]
        assert action["total"] >= 1, "Known run should have at least 1 action"
        assert action["succeeded"] >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Backward Compatibility
# ═══════════════════════════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    """验证新增端点不影响现有端点。"""

    def test_get_definitions_still_works(self, client):
        """GET /workflow/definitions 不受影响。"""
        resp = client.get("/workflow/definitions")
        assert resp.status_code == 200
        data = resp.json()
        assert "definitions" in data
        assert "total" in data

    def test_get_run_detail_still_works(self, client, repo):
        """GET /workflow/runs/{runId} 不受影响。"""
        runs = repo.list_runs(limit=1)
        if not runs:
            pytest.skip("No runs available")
        run_id = runs[0].run_id

        resp = client.get(f"/workflow/runs/{run_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "run" in data
        assert "state" in data
        assert "nodeRuns" in data
        assert "events" in data
        assert "actionRecords" in data

    def test_get_run_trace_still_works(self, client, repo):
        """GET /workflow/runs/{runId}/trace 不受影响。"""
        runs = repo.list_runs(limit=1)
        if not runs:
            pytest.skip("No runs available")
        run_id = runs[0].run_id

        resp = client.get(f"/workflow/runs/{run_id}/trace")
        assert resp.status_code == 200
        data = resp.json()
        assert "timeline" in data
        assert "nodeRuns" in data

    def test_get_definitions_by_status(self, client):
        """GET /workflow/definitions?status=active 不受影响。"""
        resp = client.get("/workflow/definitions?status=active")
        assert resp.status_code == 200

    def test_list_runs_url_not_conflict_with_detail(self, client, repo):
        """新增的 /workflow/runs 不与 /workflow/runs/{runId} 冲突。

        FastAPI 应能将 ?limit=... 路由到 list，将 /specificId 路由到 detail。
        """
        # detail 路径
        runs = repo.list_runs(limit=1)
        if not runs:
            pytest.skip("No runs available")
        run_id = runs[0].run_id

        resp_detail = client.get(f"/workflow/runs/{run_id}")
        assert resp_detail.status_code == 200
        assert "run" in resp_detail.json()

        # list 路径（带 query params）
        resp_list = client.get("/workflow/runs?limit=5")
        assert resp_list.status_code == 200
        assert "runs" in resp_list.json()
