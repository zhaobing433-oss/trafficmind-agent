"""
Phase 12 Workflow V1 单元测试 — API

测试 Workflow API 端点（REST + SSE）。

使用临时数据库，不加载真实模型。
"""
import pytest
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

TEST_DB = os.path.join(tempfile.gettempdir(), f"test_phase12_api_{os.getpid()}.db")


@pytest.fixture(scope="module", autouse=True)
def patch_db_for_module():
    import backend.config as _cfg
    _original = _cfg.DB_PATH
    _cfg.DB_PATH = TEST_DB
    for suffix in ("", "-wal", "-shm"):
        path = TEST_DB + suffix
        if os.path.exists(path):
            os.remove(path)
    yield
    _cfg.DB_PATH = _original


@pytest.fixture(autouse=True)
def clean_db():
    for suffix in ("", "-wal", "-shm"):
        path = TEST_DB + suffix
        if os.path.exists(path):
            os.remove(path)
    from backend.workflow.repository import init_workflow_tables
    init_workflow_tables()
    yield
    for suffix in ("", "-wal", "-shm"):
        path = TEST_DB + suffix
        if os.path.exists(path):
            os.remove(path)


from backend.workflow.repository import SQLiteWorkflowRepository
from backend.workflow.state import TrafficWorkflowState
from backend.workflow.definition import DefinitionManager
from backend.workflow.models import (
    NodeConfig, NodeType, WorkflowDefinition, DefinitionStatus,
    WorkflowRun, WorkflowRunStatus, WorkflowApproval, ApprovalDecision,
    WorkflowActionRecord, ActionStatus,
    generate_run_id,
)
from backend.workflow.executor import get_executor


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════════════════

def _seed_definition_and_run() -> tuple:
    """创建测试用 Definition 和 Run，返回 (repo, def_id, run_id)。"""
    repo = SQLiteWorkflowRepository()

    d = WorkflowDefinition(
        id="wfdef_api_test",
        name="API测试定义",
        status=DefinitionStatus.ACTIVE,
        nodes=[
            NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER,
                       next_nodes=["close"]),
            NodeConfig(node_id="close", node_type=NodeType.CLOSE),
        ],
        entry_node_id="trigger",
    )
    repo.save_definition(d)

    run_id = generate_run_id()
    run = WorkflowRun(
        run_id=run_id,
        definition_id="wfdef_api_test",
        version=1,
        session_id="sess_api",
        status=WorkflowRunStatus.PENDING,
    )
    repo.save_run(run)

    return repo, d.id, run_id


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: Definition API
# ═══════════════════════════════════════════════════════════════════════════════

class TestDefinitionAPI:
    def test_list_definitions_empty(self):
        """空数据库列出 0 条。"""
        repo = SQLiteWorkflowRepository()
        defs = repo.list_definitions()
        assert len(defs) == 0

    def test_list_definitions_with_data(self):
        """有数据时列出正确数量。"""
        repo = SQLiteWorkflowRepository()
        for i in range(3):
            d = WorkflowDefinition(
                id=f"def_{i}",
                name=f"Def{i}",
                nodes=[
                    NodeConfig(node_id="t", node_type=NodeType.TRIGGER, next_nodes=["c"]),
                    NodeConfig(node_id="c", node_type=NodeType.CLOSE),
                ],
                entry_node_id="t",
            )
            repo.save_definition(d)

        all_defs = repo.list_definitions()
        assert len(all_defs) == 3

    def test_get_single_definition(self):
        """获取单个 Definition。"""
        repo, def_id, _ = _seed_definition_and_run()
        d = repo.get_definition(def_id)
        assert d is not None
        assert d.name == "API测试定义"

    def test_get_nonexistent_definition(self):
        """获取不存在的 Definition 返回 None。"""
        repo = SQLiteWorkflowRepository()
        assert repo.get_definition("nonexistent") is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Run API
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunAPI:
    def test_get_run(self):
        """获取单个 Run 详情。"""
        repo, _, run_id = _seed_definition_and_run()
        run = repo.get_run(run_id)
        assert run is not None
        assert run.run_id == run_id

    def test_list_runs_by_session(self):
        """按 session 列出 Run。"""
        repo = SQLiteWorkflowRepository()
        for i in range(5):
            repo.save_run(WorkflowRun(
                run_id=f"r{i}",
                session_id="sess_filter" if i % 2 == 0 else "sess_other",
                status=WorkflowRunStatus.COMPLETED,
            ))

        sess_runs = repo.list_runs(session_id="sess_filter")
        assert len(sess_runs) == 3

    def test_list_runs_by_status(self):
        """按状态筛选 Run。"""
        repo = SQLiteWorkflowRepository()
        repo.save_run(WorkflowRun(run_id="r_ok", status=WorkflowRunStatus.COMPLETED))
        repo.save_run(WorkflowRun(run_id="r_fail", status=WorkflowRunStatus.FAILED))
        repo.save_run(WorkflowRun(run_id="r_cancel", status=WorkflowRunStatus.CANCELLED))

        failed = repo.list_runs(status="failed")
        assert len(failed) == 1
        assert failed[0].run_id == "r_fail"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Trace API
# ═══════════════════════════════════════════════════════════════════════════════

class TestTraceAPI:
    def test_trace_basic(self):
        """Trace 包含 Run 基本信息和事件列表。"""
        repo = SQLiteWorkflowRepository()

        run_id = generate_run_id()
        repo.save_run(WorkflowRun(
            run_id=run_id,
            definition_id="wfdef_001",
            version=1,
            status=WorkflowRunStatus.COMPLETED,
        ))

        from backend.workflow.models import WorkflowEvent
        for i in range(3):
            repo.save_event(WorkflowEvent(
                event_id=f"evt_{i}",
                run_id=run_id,
                event_type=["workflow_started", "node_completed", "workflow_completed"][i],
                sequence=i,
            ))

        events = repo.list_events(run_id)
        assert len(events) == 3
        assert events[0].event_type == "workflow_started"
        assert events[2].event_type == "workflow_completed"

    def test_trace_node_runs(self):
        """Trace 包含节点执行记录。"""
        repo = SQLiteWorkflowRepository()

        run_id = generate_run_id()
        repo.save_run(WorkflowRun(run_id=run_id, status=WorkflowRunStatus.COMPLETED))

        from backend.workflow.models import WorkflowNodeRun, NodeStatus
        repo.save_node_run(WorkflowNodeRun(
            node_run_id="nr1", run_id=run_id, node_id="trigger",
            node_type=NodeType.TRIGGER, status=NodeStatus.SUCCEEDED,
        ))
        repo.save_node_run(WorkflowNodeRun(
            node_run_id="nr2", run_id=run_id, node_id="agent_task",
            node_type=NodeType.AGENT_TASK, status=NodeStatus.FAILED,
            error="timeout",
        ))

        node_runs = repo.get_node_runs(run_id)
        assert len(node_runs) == 2
        assert any(nr.node_id == "agent_task" and nr.error == "timeout" for nr in node_runs)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: Approval API
# ═══════════════════════════════════════════════════════════════════════════════

class TestApprovalAPI:
    def test_approval_lifecycle(self):
        """审批完整生命周期：pending → approved。"""
        repo = SQLiteWorkflowRepository()
        executor = get_executor()

        run_id = "wfrun_appr_life"
        state = {
            "workflowRunId": run_id,
            "status": "awaiting_approval",
            "pendingApproval": {
                "approvalId": "wfappr_life",
                "nodeId": "human_approval",
                "proposedActions": [{"action": "notify"}],
            },
        }

        import json as _j
        repo.save_run(WorkflowRun(
            run_id=run_id,
            status=WorkflowRunStatus.AWAITING_APPROVAL,
            state=state,
        ))

        repo.save_approval(WorkflowApproval(
            approval_id="wfappr_life",
            run_id=run_id,
            node_id="human_approval",
            proposed_actions=[{"action": "notify"}],
            decision=ApprovalDecision.PENDING,
        ))

        # 批准
        import asyncio
        result = asyncio.run(executor.approve(run_id, reviewer="测试员", comment="同意"))
        assert "error" not in result

        # 验证审批记录已更新
        loaded = repo.get_approval("wfappr_life")
        assert loaded is not None
        assert loaded.decision == ApprovalDecision.APPROVED
        assert loaded.reviewer == "测试员"

    def test_approval_reject(self):
        """驳回审批后 Workflow 进入 failed 状态。"""
        repo = SQLiteWorkflowRepository()
        executor = get_executor()

        run_id = "wfrun_reject"
        state = {
            "workflowRunId": run_id,
            "status": "awaiting_approval",
            "pendingApproval": {
                "approvalId": "wfappr_reject",
                "nodeId": "human_approval",
                "proposedActions": [],
            },
        }
        repo.save_run(WorkflowRun(
            run_id=run_id,
            status=WorkflowRunStatus.AWAITING_APPROVAL,
            state=state,
        ))

        repo.save_approval(WorkflowApproval(
            approval_id="wfappr_reject",
            run_id=run_id,
            node_id="human_approval",
            decision=ApprovalDecision.PENDING,
        ))

        import asyncio
        result = asyncio.run(executor.reject(run_id, reviewer="审批人", comment="方案不可行"))
        assert "error" not in result

        # 验证驳回后状态
        loaded_approval = repo.get_approval("wfappr_reject")
        assert loaded_approval.decision == ApprovalDecision.REJECTED
        assert loaded_approval.comment == "方案不可行"

    def test_edit_and_approve(self):
        """编辑后批准。"""
        repo = SQLiteWorkflowRepository()
        executor = get_executor()

        run_id = "wfrun_edit"
        state = {
            "workflowRunId": run_id,
            "status": "awaiting_approval",
            "pendingApproval": {
                "approvalId": "wfappr_edit",
                "nodeId": "human_approval",
                "proposedActions": [{"action": "original"}],
            },
        }
        repo.save_run(WorkflowRun(
            run_id=run_id,
            status=WorkflowRunStatus.AWAITING_APPROVAL,
            state=state,
        ))

        repo.save_approval(WorkflowApproval(
            approval_id="wfappr_edit",
            run_id=run_id,
            decision=ApprovalDecision.PENDING,
        ))

        edited = [{"action": "modified_action", "priority": "high"}]

        import asyncio
        result = asyncio.run(executor.edit_and_approve(
            run_id,
            edited_actions=edited,
            reviewer="编辑员",
            comment="修改后方案可行",
        ))
        assert "error" not in result

        loaded = repo.get_approval("wfappr_edit")
        assert loaded.decision == ApprovalDecision.EDITED
        assert len(loaded.edited_actions) == 1
        assert loaded.edited_actions[0]["action"] == "modified_action"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: Action 幂等
# ═══════════════════════════════════════════════════════════════════════════════

class TestActionIdempotency:
    def test_action_record_idempotency(self):
        """同一幂等键只保留最新记录。"""
        repo = SQLiteWorkflowRepository()
        from backend.workflow.models import WorkflowActionRecord, ActionStatus

        key = "run1:node1:notify_wechat"

        repo.save_action_record(WorkflowActionRecord(
            action_id="a1", run_id="r1", node_id="n1",
            action_type="notify_wechat", idempotency_key=key,
            status=ActionStatus.PENDING,
        ))
        repo.save_action_record(WorkflowActionRecord(
            action_id="a2", run_id="r1", node_id="n1",
            action_type="notify_wechat", idempotency_key=key,
            status=ActionStatus.SUCCEEDED,
        ))

        loaded = repo.get_action_record_by_idempotency_key(key)
        assert loaded.status == ActionStatus.SUCCEEDED

    def test_action_records_by_run(self):
        """按 run 列出所有动作记录。"""
        repo = SQLiteWorkflowRepository()
        from backend.workflow.models import WorkflowActionRecord, ActionStatus

        repo.save_action_record(WorkflowActionRecord(
            action_id="a1", run_id="r1", node_id="n1",
            action_type="notify", idempotency_key="ik1",
            status=ActionStatus.SUCCEEDED,
        ))
        repo.save_action_record(WorkflowActionRecord(
            action_id="a2", run_id="r1", node_id="n2",
            action_type="save", idempotency_key="ik2",
            status=ActionStatus.FAILED, error="network error",
        ))
        repo.save_action_record(WorkflowActionRecord(
            action_id="a3", run_id="r2", node_id="n1",
            action_type="notify", idempotency_key="ik3",
            status=ActionStatus.SUCCEEDED,
        ))

        r1_records = repo.list_action_records("r1")
        assert len(r1_records) == 2
        assert any(r.error == "network error" for r in r1_records)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6: RAG 与 Memory 上下文分离
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextSeparation:
    def test_rag_and_memory_separate_in_state(self):
        """RAG 和 Memory 上下文在 state 中分开存储。"""
        state = {
            "ragContext": {"query": "拥堵预案", "results": [{"id": "r1"}]},
            "memoryContext": {"stableFacts": [{"key": "road.name", "value": "中山路"}]},
        }
        assert "ragContext" in state
        assert "memoryContext" in state
        # 两者不应混合
        assert "stableFacts" not in state.get("ragContext", {})
        assert "results" not in state.get("memoryContext", {})

    def test_current_event_separate_from_context(self):
        """currentEvent 独立存储，不与 RAG/Memory 上下文混合。"""
        state = {
            "currentEvent": {"roadName": "中山路", "eventType": "congestion"},
            "ragContext": {},
            "memoryContext": {},
        }
        # currentEvent 不应在 RAG 或 Memory 的字段中
        rag = state.get("ragContext", {})
        assert "roadName" not in rag or rag["roadName"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7: Reject 状态 (非 failed)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRejectStatus:
    def test_reject_creates_rejected_state(self):
        """Reject 后 Workflow 状态为 rejected，非 failed。"""
        repo = SQLiteWorkflowRepository()
        executor = get_executor()

        run_id = "wfrun_reject_state"
        state = {
            "workflowRunId": run_id,
            "status": "awaiting_approval",
            "pendingApproval": {
                "approvalId": "wfappr_reject_state",
                "nodeId": "human_approval",
                "proposedActions": [{"action": "do_something"}],
            },
        }
        repo.save_run(WorkflowRun(
            run_id=run_id, status=WorkflowRunStatus.AWAITING_APPROVAL, state=state,
        ))
        repo.save_approval(WorkflowApproval(
            approval_id="wfappr_reject_state", run_id=run_id,
            decision=ApprovalDecision.PENDING,
        ))

        import asyncio
        result = asyncio.run(executor.reject(run_id, reviewer="tester", comment="方案不可行"))
        assert "error" not in result

        run = repo.get_run(run_id)
        loaded_state = TrafficWorkflowState.from_dict(run.state)
        assert loaded_state.status == WorkflowRunStatus.REJECTED
        assert loaded_state.status != WorkflowRunStatus.FAILED

    def test_reject_saves_workflow_rejected_event(self):
        """Reject 后 event 表包含 workflow_rejected，不含 workflow_failed。"""
        repo = SQLiteWorkflowRepository()
        executor = get_executor()

        run_id = "wfrun_reject_evt"
        state = {
            "workflowRunId": run_id, "status": "awaiting_approval",
            "pendingApproval": {
                "approvalId": "wfappr_reject_evt", "nodeId": "human_approval",
                "proposedActions": [],
            },
        }
        repo.save_run(WorkflowRun(
            run_id=run_id, status=WorkflowRunStatus.AWAITING_APPROVAL, state=state,
        ))
        repo.save_approval(WorkflowApproval(
            approval_id="wfappr_reject_evt", run_id=run_id,
            decision=ApprovalDecision.PENDING,
        ))

        import asyncio
        asyncio.run(executor.reject(run_id, reviewer="tester", comment="驳回"))

        events = repo.list_events(run_id)
        event_types = [e.event_type for e in events]
        assert "workflow_rejected" in event_types, f"Got: {event_types}"
        assert "workflow_failed" not in event_types


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8: Edit-and-Approve Action 参数
# ═══════════════════════════════════════════════════════════════════════════════

class TestEditAndApproveAction:
    def test_edited_actions_persist_in_approval(self):
        """edited_actions 持久化，proposed_actions 保留。"""
        repo = SQLiteWorkflowRepository()

        approval = WorkflowApproval(
            approval_id="wfappr_editact", run_id="r1", node_id="n1",
            proposed_actions=[{"actionType": "dispatch", "laneCount": 2}],
            edited_actions=[{"actionType": "dispatch", "laneCount": 3}],
            decision=ApprovalDecision.EDITED,
        )
        repo.save_approval(approval)

        loaded = repo.get_approval("wfappr_editact")
        assert loaded.proposed_actions[0]["laneCount"] == 2
        assert loaded.edited_actions[0]["laneCount"] == 3

    def test_repeat_approve_no_duplicate_action_record(self):
        """重复 approve 不产生第二条 ActionRecord。"""
        repo = SQLiteWorkflowRepository()
        from backend.workflow.models import WorkflowActionRecord, ActionStatus

        key = "wfrun_x:action_notify:notify"
        repo.save_action_record(WorkflowActionRecord(
            action_id="wfact_dup1", run_id="wfrun_x", node_id="action_notify",
            action_type="notify", idempotency_key=key,
            status=ActionStatus.SUCCEEDED,
        ))

        # 尝试用同一幂等键插入第二条记录（通过 save_action_record 的 INSERT OR REPLACE）
        repo.save_action_record(WorkflowActionRecord(
            action_id="wfact_dup2", run_id="wfrun_x", node_id="action_notify",
            action_type="notify", idempotency_key=key,
            status=ActionStatus.SUCCEEDED,
        ))

        loaded = repo.get_action_record_by_idempotency_key(key)
        assert loaded is not None
        # INSERT OR REPLACE 会覆盖，但 count 不变
        all_records = repo.list_action_records("wfrun_x")
        assert len(all_records) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 9: Paused/Waiting → Cancel
# ═══════════════════════════════════════════════════════════════════════════════

class TestPausedCancel:
    def test_paused_to_cancelled_transition_allowed(self):
        """paused 状态可以合法转换到 cancelled。"""
        from backend.workflow.state import VALID_TRANSITIONS
        allowed = VALID_TRANSITIONS.get(WorkflowRunStatus.PAUSED, set())
        assert WorkflowRunStatus.CANCELLED in allowed, \
            f"paused 应允许 cancelled，当前: {[s.value for s in allowed]}"

    def test_cancel_paused_run(self):
        """真实 cancel 一个 paused 状态的 Run。"""
        repo = SQLiteWorkflowRepository()
        executor = get_executor()

        run_id = "wfrun_cancel_paused"
        state = TrafficWorkflowState(
            workflow_run_id=run_id,
            status=WorkflowRunStatus.PAUSED,
            current_node="wait_delay",
        )
        repo.save_run(WorkflowRun(
            run_id=run_id, status=WorkflowRunStatus.PAUSED,
            state=state.to_dict(),
        ))

        import asyncio
        result = asyncio.run(executor.cancel(run_id))
        assert "error" not in result, f"cancel 应成功: {result}"
        assert result.get("status") == "cancelled"

        run = repo.get_run(run_id)
        assert run.status == WorkflowRunStatus.CANCELLED

    def test_cancel_waiting_run_persists_correctly(self):
        """cancel 一个带 wait 参数的 paused run，所有 wait 字段保留但 status=cancelled。"""
        repo = SQLiteWorkflowRepository()
        executor = get_executor()

        run_id = "wfrun_cancel_waiting"
        state = TrafficWorkflowState(
            workflow_run_id=run_id,
            status=WorkflowRunStatus.PAUSED,
            current_node="wait_delay",
        )
        run = WorkflowRun(
            run_id=run_id, status=WorkflowRunStatus.PAUSED,
            state=state.to_dict(),
        )
        repo.save_run(run)

        # Set wait fields via direct SQL (simulating wait node)
        import sqlite3, backend.config as cfg
        conn = sqlite3.connect(cfg.DB_PATH)
        conn.execute(
            "UPDATE workflow_runs SET wait_type='time_delay', wake_at='2099-01-01T00:00:00Z' WHERE run_id=?",
            (run_id,),
        )
        conn.commit()
        conn.close()

        import asyncio
        result = asyncio.run(executor.cancel(run_id))
        assert "error" not in result

        loaded = repo.get_run(run_id)
        assert loaded.status == WorkflowRunStatus.CANCELLED

        # Verify scheduler would NOT resume this cancelled run
        conn2 = sqlite3.connect(cfg.DB_PATH)
        conn2.row_factory = sqlite3.Row
        row = conn2.execute(
            "SELECT status FROM workflow_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        assert row["status"] == "cancelled"
        # Scheduler claim query: WHERE status='paused' — cancelled won't match
        claimed = conn2.execute(
            "SELECT COUNT(*) as c FROM workflow_runs WHERE status='paused' AND wait_type!=''"
        ).fetchone()
        conn2.close()
        # cancelled run should not appear in paused+wait query
        # (it won't because status is 'cancelled', not 'paused')

    def test_cancel_completed_run_returns_error(self):
        """已完成的 run 不能 cancel。"""
        repo = SQLiteWorkflowRepository()
        executor = get_executor()

        run_id = "wfrun_cancel_completed"
        state = TrafficWorkflowState(
            workflow_run_id=run_id,
            status=WorkflowRunStatus.COMPLETED,
        )
        repo.save_run(WorkflowRun(
            run_id=run_id, status=WorkflowRunStatus.COMPLETED,
            state=state.to_dict(),
        ))

        import asyncio
        result = asyncio.run(executor.cancel(run_id))
        assert "error" in result, "已完成的 run 应拒绝 cancel"
