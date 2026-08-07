"""
Phase 12 Workflow V1 单元测试 — Repository

测试 SQLiteWorkflowRepository 的 CRUD 操作。

使用临时 SQLite 数据库，不影响主数据库。
"""
import pytest
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

TEST_DB = os.path.join(tempfile.gettempdir(), f"test_phase12_repo_{os.getpid()}.db")


@pytest.fixture(scope="module", autouse=True)
def patch_db_for_module():
    """模块级：覆写 DB_PATH 到临时数据库。"""
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
    """每个测试前重建干净数据库。"""
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
from backend.workflow.models import (
    NodeConfig, NodeType, NodeStatus, WorkflowRunStatus,
    ApprovalDecision, ActionStatus, DefinitionStatus,
    WorkflowDefinition, WorkflowDefinitionVersion,
    WorkflowRun, WorkflowNodeRun,
    WorkflowEvent, WorkflowApproval, WorkflowActionRecord,
)
from backend.workflow.definition import DefinitionManager


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: Definition CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestDefinitionCRUD:
    def test_save_and_get_definition(self):
        repo = SQLiteWorkflowRepository()
        d = WorkflowDefinition(
            id="wfdef_test001",
            name="测试定义",
            description="用于测试",
            category="拥堵处置",
            status=DefinitionStatus.DRAFT,
            nodes=[
                NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER,
                           next_nodes=["close"]),
                NodeConfig(node_id="close", node_type=NodeType.CLOSE),
            ],
            entry_node_id="trigger",
        )
        repo.save_definition(d)

        loaded = repo.get_definition("wfdef_test001")
        assert loaded is not None
        assert loaded.name == "测试定义"
        assert loaded.category == "拥堵处置"
        assert len(loaded.nodes) == 2

    def test_list_definitions(self):
        repo = SQLiteWorkflowRepository()
        for i in range(3):
            d = WorkflowDefinition(
                id=f"wfdef_list{i}",
                name=f"定义{i}",
                nodes=[
                    NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER,
                               next_nodes=["close"]),
                    NodeConfig(node_id="close", node_type=NodeType.CLOSE),
                ],
                entry_node_id="trigger",
            )
            repo.save_definition(d)

        all_defs = repo.list_definitions()
        assert len(all_defs) >= 3

        active_defs = repo.list_definitions(status="active")
        assert len(active_defs) == 0

    def test_get_nonexistent(self):
        repo = SQLiteWorkflowRepository()
        assert repo.get_definition("nonexistent") is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Version CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestVersionCRUD:
    def test_save_and_get_version(self):
        repo = SQLiteWorkflowRepository()
        # 先保存一个 definition
        d = WorkflowDefinition(
            id="wfdef_ver_test",
            name="版本测试",
            nodes=[
                NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER, next_nodes=["close"]),
                NodeConfig(node_id="close", node_type=NodeType.CLOSE),
            ],
            entry_node_id="trigger",
        )
        repo.save_definition(d)

        ver = WorkflowDefinitionVersion(
            id="wfver_001",
            definition_id="wfdef_ver_test",
            version=1,
            definition_json=d.to_dict(),
            changelog="初始版本",
        )
        repo.save_definition_version(ver)

        loaded = repo.get_definition_version("wfdef_ver_test", 1)
        assert loaded is not None
        assert loaded.version == 1
        assert loaded.changelog == "初始版本"

    def test_version_increment(self):
        repo = SQLiteWorkflowRepository()
        d = WorkflowDefinition(
            id="wfdef_incr_v2",
            name="递增测试",
            nodes=[
                NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER, next_nodes=["close"]),
                NodeConfig(node_id="close", node_type=NodeType.CLOSE),
            ],
            entry_node_id="trigger",
        )
        repo.save_definition(d)

        assert repo.get_latest_version_number("wfdef_incr_v2") == 0

        repo.save_definition_version(WorkflowDefinitionVersion(
            id="v1a", definition_id="wfdef_incr_v2", version=1,
        ))
        repo.save_definition_version(WorkflowDefinitionVersion(
            id="v2a", definition_id="wfdef_incr_v2", version=2,
        ))

        assert repo.get_latest_version_number("wfdef_incr_v2") == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Run CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunCRUD:
    def test_save_and_get_run(self):
        repo = SQLiteWorkflowRepository()
        run = WorkflowRun(
            run_id="wfrun_test001",
            definition_id="wfdef_001",
            version=1,
            session_id="sess_001",
            status=WorkflowRunStatus.RUNNING,
            current_node_id="node_agent",
            state={"currentEvent": {"roadName": "中山路"}},
        )
        repo.save_run(run)

        loaded = repo.get_run("wfrun_test001")
        assert loaded is not None
        assert loaded.definition_id == "wfdef_001"
        assert loaded.status == WorkflowRunStatus.RUNNING

    def test_list_runs_by_session(self):
        repo = SQLiteWorkflowRepository()
        repo.save_run(WorkflowRun(run_id="r1", session_id="s1", status=WorkflowRunStatus.COMPLETED))
        repo.save_run(WorkflowRun(run_id="r2", session_id="s1", status=WorkflowRunStatus.FAILED))
        repo.save_run(WorkflowRun(run_id="r3", session_id="s2", status=WorkflowRunStatus.RUNNING))

        s1_runs = repo.list_runs(session_id="s1")
        assert len(s1_runs) == 2

        failed = repo.list_runs(status="failed")
        assert len(failed) == 1

    def test_get_nonexistent_run(self):
        repo = SQLiteWorkflowRepository()
        assert repo.get_run("nonexistent") is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: NodeRun CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestNodeRunCRUD:
    def test_save_and_get_node_runs(self):
        repo = SQLiteWorkflowRepository()
        nr = WorkflowNodeRun(
            node_run_id="wfnr_001",
            run_id="r_noderun",
            node_id="agent_congestion",
            node_type=NodeType.AGENT_TASK,
            status=NodeStatus.SUCCEEDED,
            attempt=1,
            max_attempts=2,
            error="",
        )
        repo.save_node_run(nr)

        runs = repo.get_node_runs("r_noderun")
        assert len(runs) == 1
        assert runs[0].node_id == "agent_congestion"

    def test_update_node_run(self):
        repo = SQLiteWorkflowRepository()
        nr = WorkflowNodeRun(
            node_run_id="wfnr_update",
            run_id="r2",  # 不同 run_id 避免与上一个测试冲突
            node_id="n1",
            status=NodeStatus.RUNNING,
        )
        repo.save_node_run(nr)

        nr.status = NodeStatus.FAILED
        nr.error = "timeout"
        repo.save_node_run(nr)

        loaded = repo.get_node_runs("r2")
        assert len(loaded) == 1
        assert loaded[0].status == NodeStatus.FAILED
        assert loaded[0].error == "timeout"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: Event CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventCRUD:
    def test_save_and_list_events(self):
        repo = SQLiteWorkflowRepository()
        for i in range(5):
            e = WorkflowEvent(
                event_id=f"evt_{i}",
                run_id="r1",
                event_type="node_started",
                sequence=i,
            )
            repo.save_event(e)

        events = repo.list_events("r1")
        assert len(events) == 5
        assert events[0].sequence == 0
        assert events[4].sequence == 4


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6: Approval CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class TestApprovalCRUD:
    def test_save_and_get_approval(self):
        repo = SQLiteWorkflowRepository()
        approval = WorkflowApproval(
            approval_id="wfappr_001",
            run_id="r1",
            node_id="human_approval",
            proposed_actions=[{"action": "notify"}],
            decision=ApprovalDecision.PENDING,
        )
        repo.save_approval(approval)

        loaded = repo.get_approval("wfappr_001")
        assert loaded is not None
        assert loaded.decision == ApprovalDecision.PENDING

    def test_get_pending_approval(self):
        repo = SQLiteWorkflowRepository()
        approval = WorkflowApproval(
            approval_id="wfappr_pending",
            run_id="r_pending",  # 不同 run_id 避免冲突
            node_id="human_approval",
            decision=ApprovalDecision.PENDING,
        )
        repo.save_approval(approval)

        pending = repo.get_pending_approval("r_pending", "human_approval")
        assert pending is not None
        assert pending.approval_id == "wfappr_pending"

    def test_approval_decision_update(self):
        repo = SQLiteWorkflowRepository()
        approval = WorkflowApproval(
            approval_id="wfappr_dec",
            run_id="r1",
            node_id="n1",
            decision=ApprovalDecision.PENDING,
        )
        repo.save_approval(approval)

        approval.decision = ApprovalDecision.APPROVED
        approval.reviewer = "张三"
        repo.save_approval(approval)

        loaded = repo.get_approval("wfappr_dec")
        assert loaded.decision == ApprovalDecision.APPROVED
        assert loaded.reviewer == "张三"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7: ActionRecord CRUD + 幂等
# ═══════════════════════════════════════════════════════════════════════════════

class TestActionRecordCRUD:
    def test_save_and_get_by_idempotency_key(self):
        repo = SQLiteWorkflowRepository()
        record = WorkflowActionRecord(
            action_id="wfact_001",
            run_id="r1",
            node_id="action_notify",
            action_type="notify_wechat",
            idempotency_key="ik_001",
            status=ActionStatus.SUCCEEDED,
        )
        repo.save_action_record(record)

        loaded = repo.get_action_record_by_idempotency_key("ik_001")
        assert loaded is not None
        assert loaded.status == ActionStatus.SUCCEEDED

    def test_unique_idempotency_key(self):
        """幂等键冲突时 INSERT OR REPLACE 覆盖旧记录。"""
        repo = SQLiteWorkflowRepository()
        r1 = WorkflowActionRecord(
            action_id="wfact_a", run_id="r1", node_id="n1",
            action_type="notify", idempotency_key="same_key",
            status=ActionStatus.PENDING,
        )
        repo.save_action_record(r1)

        r2 = WorkflowActionRecord(
            action_id="wfact_b", run_id="r1", node_id="n1",
            action_type="notify", idempotency_key="same_key",
            status=ActionStatus.SUCCEEDED,
        )
        repo.save_action_record(r2)

        loaded = repo.get_action_record_by_idempotency_key("same_key")
        assert loaded.status == ActionStatus.SUCCEEDED


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8: DefinitionManager
# ═══════════════════════════════════════════════════════════════════════════════

class TestDefinitionManager:
    def _make_valid_def(self, def_id="wfdef_mgr_test"):
        return WorkflowDefinition(
            id=def_id,
            name="管理测试",
            nodes=[
                NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER,
                           next_nodes=["close"]),
                NodeConfig(node_id="close", node_type=NodeType.CLOSE),
            ],
            entry_node_id="trigger",
        )

    def test_create_definition(self):
        repo = SQLiteWorkflowRepository()
        mgr = DefinitionManager(repo)

        d = self._make_valid_def()
        repo.save_definition(d)

        loaded = mgr.get_latest_definition(d.id)
        assert loaded is not None
        assert loaded.name == "管理测试"

    def test_create_version_auto_increment(self):
        repo = SQLiteWorkflowRepository()
        mgr = DefinitionManager(repo)

        d = self._make_valid_def("wfdef_auto_ver_v2")
        repo.save_definition(d)

        v1 = mgr.create_version(d, changelog="初始")
        assert v1.version == 1

        v2 = mgr.create_version(d, changelog="更新")
        assert v2.version == 2

    def test_get_definition_at_version(self):
        repo = SQLiteWorkflowRepository()
        mgr = DefinitionManager(repo)

        d = self._make_valid_def("wfdef_at_ver")
        repo.save_definition(d)

        mgr.create_version(d, changelog="v1")

        frozen = mgr.get_definition_at_version("wfdef_at_ver", 1)
        assert frozen is not None
        assert frozen.name == "管理测试"

    def test_activate_deprecate(self):
        repo = SQLiteWorkflowRepository()
        mgr = DefinitionManager(repo)

        d = self._make_valid_def("wfdef_ad")
        repo.save_definition(d)

        assert d.status == DefinitionStatus.DRAFT

        mgr.activate_definition("wfdef_ad")
        loaded = repo.get_definition("wfdef_ad")
        assert loaded.status == DefinitionStatus.ACTIVE

        mgr.deprecate_definition("wfdef_ad")
        loaded = repo.get_definition("wfdef_ad")
        assert loaded.status == DefinitionStatus.DEPRECATED
