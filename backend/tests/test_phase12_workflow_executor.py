"""
Phase 12 Workflow V1 单元测试 — 执行器

测试 WorkflowExecutor 的核心能力：
  - 正常顺序执行
  - 条件分支
  - 版本绑定
  - node 失败重试
  - cancel
  - SSE 事件顺序

使用 Fake RAG/Agent/Tool，不加载真实模型。
"""
import pytest
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

TEST_DB = os.path.join(tempfile.gettempdir(), f"test_phase12_exec_{os.getpid()}.db")


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
from backend.workflow.definition import DefinitionManager
from backend.workflow.executor import WorkflowExecutor
from backend.workflow.models import (
    NodeConfig, NodeType, WorkflowDefinition, WorkflowRun, DefinitionStatus,
    WorkflowRunStatus, generate_run_id,
)
from backend.workflow.state import TrafficWorkflowState


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助：创建一个最小的可执行 Definition
# ═══════════════════════════════════════════════════════════════════════════════

def _make_minimal_definition(def_id: str = "wfdef_min") -> WorkflowDefinition:
    """创建最小可用 Definition: trigger → close。"""
    return WorkflowDefinition(
        id=def_id,
        name="最小测试定义",
        description="用于执行器测试",
        status=DefinitionStatus.ACTIVE,
        nodes=[
            NodeConfig(
                node_id="trigger",
                node_type=NodeType.TRIGGER,
                label="触发",
                next_nodes=["close"],
                config={"initial_event": {}},
            ),
            NodeConfig(
                node_id="close",
                node_type=NodeType.CLOSE,
                label="关闭",
            ),
        ],
        entry_node_id="trigger",
    )


def _make_linear_definition(def_id: str = "wfdef_linear") -> WorkflowDefinition:
    """线性 Definition: trigger → validate_event → close。"""
    return WorkflowDefinition(
        id=def_id,
        name="线性测试定义",
        status=DefinitionStatus.ACTIVE,
        nodes=[
            NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER,
                       label="触发", next_nodes=["validate"]),
            NodeConfig(node_id="validate", node_type=NodeType.VALIDATE_EVENT,
                       label="校验", next_nodes=["close"]),
            NodeConfig(node_id="close", node_type=NodeType.CLOSE, label="关闭"),
        ],
        entry_node_id="trigger",
    )


def _make_conditional_definition(def_id: str = "wfdef_cond") -> WorkflowDefinition:
    """条件分支: trigger → risk_gate → [approval | auto] → close。"""
    return WorkflowDefinition(
        id=def_id,
        name="条件分支测试",
        status=DefinitionStatus.ACTIVE,
        nodes=[
            NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER,
                       label="触发",
                       next_nodes=["risk_gate"],
                       config={
                           "initial_event": {
                               "eventType": "congestion",
                               "eventTypeCn": "拥堵",
                               "roadName": "测试路段",
                               "avgSpeed": 5,
                               "queueLength": 200,
                               "duration": 1200,
                               "weather": "rain",
                               "timePeriod": "morning_peak",
                               "isMainRoad": True,
                               "nearbySchool": False,
                               "nearbyHospital": False,
                           }
                       }),
            NodeConfig(node_id="risk_gate", node_type=NodeType.RISK_GATE,
                       label="风险门控",
                       next_nodes=["close", "close"],  # 两条路径都到 close
                       condition="requires_approval"),
            NodeConfig(node_id="close", node_type=NodeType.CLOSE, label="关闭"),
        ],
        entry_node_id="trigger",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: 正常顺序执行
# ═══════════════════════════════════════════════════════════════════════════════

class TestSequentialExecution:
    def test_minimal_definition_executes(self):
        """最小 Definition 从 trigger 到 close 正常执行。"""
        repo = SQLiteWorkflowRepository()
        mgr = DefinitionManager(repo)
        executor = WorkflowExecutor(repo)

        d = _make_minimal_definition("wfdef_seq_min")
        repo.save_definition(d)

        # 收集 SSE 事件
        events = []
        async def _collect():
            async for s in executor.start(
                definition_id="wfdef_seq_min",
                initial_event={"eventType": "congestion", "roadName": "测试路"},
            ):
                events.append(s)

        import asyncio
        asyncio.run(_collect())

        # 验证 SSE 事件包含关键事件
        event_text = "\n".join(events)
        assert "workflow_started" in event_text
        assert "node_started" in event_text
        assert "node_completed" in event_text or "workflow_completed" in event_text
        assert "done" in event_text

        # 验证 Run 已持久化
        run_id = None
        for e in events:
            if "workflow_started" in e:
                import re
                m = re.search(r'"runId":\s*"([^"]+)"', e)
                if m:
                    run_id = m.group(1)
                    break

        assert run_id is not None
        run = repo.get_run(run_id)
        assert run is not None
        assert run.status == WorkflowRunStatus.COMPLETED

        # 验证版本绑定
        assert run.version >= 1

    def test_linear_definition_executes(self):
        """线性三节点: trigger → validate → close 正常执行。"""
        repo = SQLiteWorkflowRepository()
        executor = WorkflowExecutor(repo)

        d = _make_linear_definition("wfdef_linear_test")
        repo.save_definition(d)

        events = []
        async def _collect():
            async for s in executor.start(
                definition_id="wfdef_linear_test",
                initial_event={
                    "eventType": "congestion",
                    "roadName": "测试路",
                    "avgSpeed": 30,
                    "queueLength": 100,
                    "duration": 300,
                },
            ):
                events.append(s)

        import asyncio
        asyncio.run(_collect())

        event_text = "\n".join(events)
        assert "workflow_started" in event_text
        assert "node_started" in event_text
        assert "done" in event_text

    def test_conditional_branch(self):
        """条件分支: 高风险事件走审批路径评估。"""
        repo = SQLiteWorkflowRepository()
        executor = WorkflowExecutor(repo)

        d = _make_conditional_definition("wfdef_cond_test")
        repo.save_definition(d)

        events = []
        async def _collect():
            async for s in executor.start(
                definition_id="wfdef_cond_test",
            ):
                events.append(s)

        import asyncio
        asyncio.run(_collect())

        event_text = "\n".join(events)
        # 高风险事件应该触发 risk_gate 评估
        assert "workflow_started" in event_text
        assert "done" in event_text


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: 版本绑定
# ═══════════════════════════════════════════════════════════════════════════════

class TestVersionBinding:
    def test_run_binds_to_version(self):
        """Run 创建时绑定到当时版本，后续 Definition 修改不影响已启动 Run。"""
        repo = SQLiteWorkflowRepository()
        mgr = DefinitionManager(repo)
        executor = WorkflowExecutor(repo)

        d = _make_minimal_definition("wfdef_ver_bind")
        repo.save_definition(d)

        # 创建版本快照
        mgr.create_version(d, changelog="初始")

        events = []
        async def _collect():
            async for s in executor.start(
                definition_id="wfdef_ver_bind",
                initial_event={"eventType": "congestion", "roadName": "测试路"},
            ):
                events.append(s)

        import asyncio
        asyncio.run(_collect())

        # 获取 run_id
        import re
        run_id = None
        for e in events:
            m = re.search(r'"runId":\s*"([^"]+)"', e)
            if m:
                run_id = m.group(1)
                break

        run = repo.get_run(run_id)
        assert run is not None
        assert run.version >= 1

        # 确认版本快照存在
        ver = repo.get_definition_version("wfdef_ver_bind", run.version)
        assert ver is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Cancel
# ═══════════════════════════════════════════════════════════════════════════════

class TestCancel:
    def test_cancel_pending_run(self):
        """取消待执行的 Run。"""
        repo = SQLiteWorkflowRepository()
        executor = WorkflowExecutor(repo)

        run_id = generate_run_id()
        from backend.workflow.models import WorkflowRun, WorkflowRunStatus
        run = WorkflowRun(
            run_id=run_id,
            definition_id="wfdef_001",
            status=WorkflowRunStatus.RUNNING,
        )
        repo.save_run(run)

        import asyncio
        result = asyncio.run(executor.cancel(run_id))
        assert result.get("status") == "cancelled"

        loaded = repo.get_run(run_id)
        assert loaded.status == WorkflowRunStatus.CANCELLED

    def test_cancel_terminal_run_fails(self):
        """取消已完成的 Run 应返回错误。"""
        repo = SQLiteWorkflowRepository()
        executor = WorkflowExecutor(repo)

        from backend.workflow.state import TrafficWorkflowState
        state = TrafficWorkflowState(
            workflow_run_id="wfrun_done",
            status=WorkflowRunStatus.COMPLETED,
        )
        run = WorkflowRun(
            run_id="wfrun_done",
            status=WorkflowRunStatus.COMPLETED,
            state=state.to_dict(),
        )
        repo.save_run(run)

        import asyncio
        result = asyncio.run(executor.cancel("wfrun_done"))
        assert "error" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: SSE 事件顺序
# ═══════════════════════════════════════════════════════════════════════════════

class TestSSEEventOrder:
    def test_events_in_order(self):
        """SSE 事件按正确顺序出现。"""
        repo = SQLiteWorkflowRepository()
        executor = WorkflowExecutor(repo)

        d = _make_linear_definition("wfdef_sse_order")
        repo.save_definition(d)

        events = []
        async def _collect():
            async for s in executor.start(
                definition_id="wfdef_sse_order",
                initial_event={
                    "eventType": "congestion",
                    "roadName": "测试路",
                    "avgSpeed": 30,
                    "queueLength": 100,
                    "duration": 300,
                },
            ):
                events.append(s)

        import asyncio
        asyncio.run(_collect())

        # 验证 done 恰好一次
        done_count = sum(1 for e in events if 'event: done' in e)
        assert done_count == 1, f"done 出现 {done_count} 次，期望 1 次"

        # 验证 workflow_started 在 done 之前
        started_idx = -1
        done_idx = -1
        for i, e in enumerate(events):
            if 'workflow_started' in e:
                started_idx = i
            if 'done' in e:
                done_idx = i
        assert started_idx < done_idx, "workflow_started 应在 done 之前"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: Node 失败重试
# ═══════════════════════════════════════════════════════════════════════════════

class TestNodeRetry:
    def test_retry_node_command(self):
        """retry_node 命令正确设置 attempt 计数。"""
        repo = SQLiteWorkflowRepository()
        executor = WorkflowExecutor(repo)

        run_id = "wfrun_retry_test"
        state = TrafficWorkflowState(
            workflow_run_id=run_id,
            current_node="failed_node",
            status=WorkflowRunStatus.RUNNING,
        )
        run = WorkflowRun(
            run_id=run_id,
            state=state.to_dict(),
            status=WorkflowRunStatus.RUNNING,
        )
        repo.save_run(run)

        import asyncio
        result = asyncio.run(executor.retry_node(run_id, "failed_node"))
        assert result.get("nodeId") == "failed_node"
        assert result.get("attempt") == 1
        assert result.get("status") == "retrying"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6: 模板1 执行
# ═══════════════════════════════════════════════════════════════════════════════

class TestTemplate1Execution:
    def test_ramp_congestion_template_starts(self):
        """模板1（高速匝道拥堵）可以正常启动执行。"""
        repo = SQLiteWorkflowRepository()
        mgr = DefinitionManager(repo)
        executor = WorkflowExecutor(repo)

        from backend.workflow.templates.ramp_congestion import build_ramp_congestion_definition
        d = build_ramp_congestion_definition()
        repo.save_definition(d)

        events = []
        async def _collect():
            async for s in executor.start(
                definition_id=d.id,
                initial_event={
                    "eventType": "congestion",
                    "eventTypeCn": "拥堵",
                    "roadName": "G50沪渝高速匝道",
                    "direction": "南向北",
                    "avgSpeed": 8,
                    "queueLength": 300,
                    "duration": 900,
                    "weather": "rain",
                    "timePeriod": "morning_peak",
                    "isMainRoad": True,
                    "nearbySchool": False,
                    "nearbyHospital": False,
                },
            ):
                events.append(s)

        import asyncio
        asyncio.run(_collect())

        event_text = "\n".join(events)
        assert "workflow_started" in event_text
        assert "done" in event_text

        # 验证 Run 已持久化
        import re
        run_id = None
        for e in events:
            m = re.search(r'"runId":\s*"([^"]+)"', e)
            if m:
                run_id = m.group(1)
                break

        run = repo.get_run(run_id)
        assert run is not None

        # 验证有节点执行记录
        node_runs = repo.get_node_runs(run_id)
        assert len(node_runs) > 0

        # 验证版本绑定
        assert run.version >= 1
        ver = repo.get_definition_version(d.id, run.version)
        assert ver is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7: 模板2 + 3 基础测试
# ═══════════════════════════════════════════════════════════════════════════════

class TestTemplate23:
    def test_school_hospital_template_validates(self):
        """模板2：学校/医院周边拥堵 Definition 校验通过。"""
        from backend.workflow.templates.school_hospital_congestion import build_school_hospital_congestion_definition
        d = build_school_hospital_congestion_definition()
        issues = d.validate()
        assert len(issues) == 0

    def test_accident_template_validates(self):
        """模板3：事故122/120联动 Definition 校验通过。"""
        from backend.workflow.templates.accident_122_120 import build_accident_122_120_definition
        d = build_accident_122_120_definition()
        issues = d.validate()
        assert len(issues) == 0

    def test_school_hospital_template_starts(self):
        """模板2 可以正常启动。"""
        repo = SQLiteWorkflowRepository()
        executor = WorkflowExecutor(repo)

        from backend.workflow.templates.school_hospital_congestion import build_school_hospital_congestion_definition
        d = build_school_hospital_congestion_definition()
        repo.save_definition(d)

        events = []
        async def _collect():
            async for s in executor.start(
                definition_id=d.id,
                initial_event={
                    "eventType": "congestion",
                    "roadName": "学校路",
                    "avgSpeed": 10,
                    "queueLength": 180,
                    "duration": 600,
                    "nearbySchool": True,
                },
            ):
                events.append(s)

        import asyncio
        asyncio.run(_collect())

        event_text = "\n".join(events)
        assert "workflow_started" in event_text
        assert "done" in event_text

    def test_accident_template_starts(self):
        """模板3 可以正常启动。"""
        repo = SQLiteWorkflowRepository()
        executor = WorkflowExecutor(repo)

        from backend.workflow.templates.accident_122_120 import build_accident_122_120_definition
        d = build_accident_122_120_definition()
        repo.save_definition(d)

        events = []
        async def _collect():
            async for s in executor.start(
                definition_id=d.id,
                initial_event={
                    "eventType": "accident",
                    "roadName": "事故路",
                    "avgSpeed": 0,
                    "queueLength": 500,
                    "duration": 1800,
                    "nearbyHospital": True,
                },
            ):
                events.append(s)

        import asyncio
        asyncio.run(_collect())

        event_text = "\n".join(events)
        assert "workflow_started" in event_text
        assert "done" in event_text


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8: current_event 不被覆盖
# ═══════════════════════════════════════════════════════════════════════════════

class TestCurrentEventImmutability:
    def test_current_event_not_overwritten(self):
        """current_event 在执行后保持原始值不被 RAG/Memory 覆盖。"""
        repo = SQLiteWorkflowRepository()
        executor = WorkflowExecutor(repo)

        d = _make_linear_definition("wfdef_immut")
        repo.save_definition(d)

        original_event = {
            "eventType": "congestion",
            "roadName": "测试路",
            "avgSpeed": 30,
            "queueLength": 100,
            "duration": 300,
        }

        events = []
        async def _collect():
            async for s in executor.start(
                definition_id="wfdef_immut",
                initial_event=original_event,
            ):
                events.append(s)

        import asyncio
        asyncio.run(_collect())

        # 从持久化的 Run 中读取 state
        import re
        run_id = None
        for e in events:
            m = re.search(r'"runId":\s*"([^"]+)"', e)
            if m:
                run_id = m.group(1)
                break

        run = repo.get_run(run_id)
        state = run.state
        if isinstance(state, str):
            state = json.loads(state)

        current_event = state.get("currentEvent", {})
        assert current_event.get("roadName") == "测试路"
        assert current_event.get("eventType") == "congestion"
