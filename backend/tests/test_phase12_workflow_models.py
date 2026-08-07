"""
Phase 12 Workflow V1 单元测试 — 数据模型

测试 WorkflowDefinition, WorkflowDefinitionVersion, WorkflowRun,
WorkflowNodeRun, WorkflowEvent, WorkflowApproval, WorkflowActionRecord
的创建、序列化和校验。

使用 Fake/Mock，不加载真实模型。
"""
import pytest
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.workflow.models import (
    NodeConfig,
    NodeType,
    NodeStatus,
    WorkflowRunStatus,
    ApprovalDecision,
    ActionStatus,
    DefinitionStatus,
    WorkflowDefinition,
    WorkflowDefinitionVersion,
    WorkflowRun,
    WorkflowNodeRun,
    WorkflowEvent,
    WorkflowApproval,
    WorkflowActionRecord,
    generate_run_id,
    generate_approval_id,
    generate_action_id,
    compute_action_idempotency_key,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: NodeConfig — 节点配置
# ═══════════════════════════════════════════════════════════════════════════════

class TestNodeConfig:
    def test_create_basic_node(self):
        node = NodeConfig(
            node_id="test_node",
            node_type=NodeType.TRIGGER,
            label="测试节点",
        )
        assert node.node_id == "test_node"
        assert node.node_type == NodeType.TRIGGER
        assert node.timeout_seconds == 60
        assert node.max_attempts == 1

    def test_to_dict_and_back(self):
        node = NodeConfig(
            node_id="n1",
            node_type=NodeType.AGENT_TASK,
            label="Agent Task",
            config={"agent_name": "CongestionAgent"},
            next_nodes=["n2", "n3"],
            timeout_seconds=30,
            max_attempts=3,
            retry_delay_seconds=10,
        )
        d = node.to_dict()
        restored = NodeConfig.from_dict(d)
        assert restored.node_id == node.node_id
        assert restored.node_type == node.node_type
        assert restored.config == node.config
        assert restored.next_nodes == node.next_nodes
        assert restored.max_attempts == 3

    def test_from_dict_with_camel_case(self):
        d = {
            "nodeId": "n1",
            "nodeType": "risk_gate",
            "label": "Risk Gate",
            "nextNodes": ["approval", "auto"],
            "condition": "requires_approval",
            "timeoutSeconds": 15,
        }
        node = NodeConfig.from_dict(d)
        assert node.node_id == "n1"
        assert node.node_type == NodeType.RISK_GATE
        assert node.condition == "requires_approval"
        assert len(node.next_nodes) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: WorkflowDefinition — 定义校验
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflowDefinition:
    def _make_def(self, name="测试定义", nodes=None, entry="trigger"):
        return WorkflowDefinition(
            id="wfdef_test001",
            name=name,
            nodes=nodes or [],
            entry_node_id=entry,
            status=DefinitionStatus.DRAFT,
        )

    def test_validate_missing_entry_node(self):
        d = self._make_def(entry="")
        issues = d.validate()
        assert any("入口节点" in i for i in issues)

    def test_validate_entry_not_in_nodes(self):
        d = self._make_def(entry="nonexistent")
        issues = d.validate()
        assert any("不在节点列表" in i for i in issues)

    def test_validate_entry_not_trigger(self):
        d = self._make_def(
            nodes=[NodeConfig(node_id="trigger", node_type=NodeType.CLOSE)],
            entry="trigger",
        )
        issues = d.validate()
        assert any("trigger 类型" in i for i in issues)

    def test_validate_missing_close(self):
        d = self._make_def(
            nodes=[NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER)],
        )
        issues = d.validate()
        assert any("close" in i for i in issues)

    def test_validate_invalid_next_ref(self):
        d = self._make_def(
            nodes=[
                NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER,
                           next_nodes=["nonexistent"]),
                NodeConfig(node_id="close", node_type=NodeType.CLOSE),
            ],
        )
        issues = d.validate()
        assert any("不存在的后继" in i for i in issues)

    def test_validate_risk_gate_missing_condition(self):
        d = self._make_def(
            nodes=[
                NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER,
                           next_nodes=["gate"]),
                NodeConfig(node_id="gate", node_type=NodeType.RISK_GATE,
                           next_nodes=["close"]),
                NodeConfig(node_id="close", node_type=NodeType.CLOSE),
            ],
        )
        issues = d.validate()
        assert any("条件表达式" in i for i in issues)

    def test_validate_parallel_missing_branches(self):
        d = self._make_def(
            nodes=[
                NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER,
                           next_nodes=["p"]),
                NodeConfig(node_id="p", node_type=NodeType.PARALLEL,
                           next_nodes=["close"]),
                NodeConfig(node_id="close", node_type=NodeType.CLOSE),
            ],
        )
        issues = d.validate()
        assert any("并行分支" in i for i in issues)

    def test_validate_valid_definition(self):
        d = self._make_def(
            nodes=[
                NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER,
                           next_nodes=["gate"]),
                NodeConfig(node_id="gate", node_type=NodeType.RISK_GATE,
                           next_nodes=["approval", "auto"],
                           condition="requires_approval"),
                NodeConfig(node_id="approval", node_type=NodeType.HUMAN_APPROVAL,
                           next_nodes=["close"]),
                NodeConfig(node_id="auto", node_type=NodeType.ACTION,
                           next_nodes=["close"]),
                NodeConfig(node_id="close", node_type=NodeType.CLOSE),
            ],
        )
        issues = d.validate()
        assert len(issues) == 0

    def test_get_node(self):
        d = self._make_def(
            nodes=[
                NodeConfig(node_id="trigger", node_type=NodeType.TRIGGER),
                NodeConfig(node_id="close", node_type=NodeType.CLOSE),
            ],
        )
        assert d.get_node("trigger") is not None
        assert d.get_node("nonexistent") is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: WorkflowRun — 运行实例
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflowRun:
    def test_create_run(self):
        run_id = generate_run_id()
        assert run_id.startswith("wfrun_")

        run = WorkflowRun(
            run_id=run_id,
            definition_id="wfdef_001",
            version=1,
            session_id="sess_001",
        )
        assert run.run_id == run_id
        assert run.status == WorkflowRunStatus.PENDING
        assert not run.is_terminal()
        assert run.is_interruptible() is False  # pending is not interruptible

    def test_is_terminal(self):
        for status in [WorkflowRunStatus.COMPLETED, WorkflowRunStatus.FAILED,
                       WorkflowRunStatus.CANCELLED]:
            run = WorkflowRun(run_id="test", status=status)
            assert run.is_terminal()

    def test_roundtrip_dict(self):
        run = WorkflowRun(
            run_id="wfrun_test",
            definition_id="def1",
            version=2,
            session_id="s1",
            status=WorkflowRunStatus.RUNNING,
            current_node_id="node_agent",
            state={"key": "value"},
            triggered_by="user",
        )
        d = run.to_dict()
        restored = WorkflowRun.from_dict(d)
        assert restored.run_id == run.run_id
        assert restored.version == 2
        assert restored.status == WorkflowRunStatus.RUNNING
        assert restored.current_node_id == "node_agent"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: WorkflowNodeRun — 节点执行记录
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflowNodeRun:
    def test_create_node_run(self):
        nr = WorkflowNodeRun(
            node_run_id="wfnr_001",
            run_id="wfrun_001",
            node_id="agent_congestion",
            node_type=NodeType.AGENT_TASK,
            status=NodeStatus.SUCCEEDED,
            attempt=2,
            max_attempts=3,
        )
        assert nr.attempt == 2
        assert nr.status == NodeStatus.SUCCEEDED

    def test_roundtrip_dict(self):
        nr = WorkflowNodeRun(
            node_run_id="wfnr_001",
            run_id="wfrun_001",
            node_id="n1",
            node_type=NodeType.RAG_RETRIEVE,
            error="timeout",
            duration_ms=1500,
        )
        d = nr.to_dict()
        restored = WorkflowNodeRun.from_dict(d)
        assert restored.error == "timeout"
        assert restored.duration_ms == 1500


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: WorkflowApproval — 审批
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflowApproval:
    def test_create_approval(self):
        approval_id = generate_approval_id()
        assert approval_id.startswith("wfappr_")

        approval = WorkflowApproval(
            approval_id=approval_id,
            run_id="wfrun_001",
            node_id="human_approval",
            proposed_actions=[{"action": "notify"}],
            decision=ApprovalDecision.PENDING,
        )
        assert approval.decision == ApprovalDecision.PENDING

    def test_approval_decisions(self):
        for dec in ApprovalDecision:
            approval = WorkflowApproval(
                approval_id="test", run_id="r1", decision=dec
            )
            assert approval.decision == dec


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6: WorkflowActionRecord — 动作幂等
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflowActionRecord:
    def test_idempotency_key(self):
        k1 = compute_action_idempotency_key("run1", "node1", "notify")
        k2 = compute_action_idempotency_key("run1", "node1", "notify")
        k3 = compute_action_idempotency_key("run1", "node2", "notify")
        assert k1 == k2  # 相同输入 → 相同幂等键
        assert k1 != k3  # 不同 node → 不同幂等键
        assert len(k1) == 16  # SHA-256 前 16 位

    def test_auto_idempotency_key(self):
        record = WorkflowActionRecord(
            action_id="test", run_id="run1", node_id="n1",
            action_type="notify_wechat",
        )
        assert record.idempotency_key != ""

    def test_action_roundtrip(self):
        record = WorkflowActionRecord(
            action_id=generate_action_id(),
            run_id="run1",
            node_id="n1",
            action_type="notify",
            idempotency_key="key123",
            params={"channel": "wechat"},
            status=ActionStatus.SUCCEEDED,
        )
        d = record.to_dict()
        restored = WorkflowActionRecord.from_dict(d)
        assert restored.action_type == "notify"
        assert restored.idempotency_key == "key123"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7: WorkflowDefinitionVersion — 版本快照
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkflowDefinitionVersion:
    def test_create_version(self):
        ver = WorkflowDefinitionVersion(
            id="wfver_001",
            definition_id="wfdef_001",
            version=3,
            definition_json={"nodes": [], "entryNodeId": "trigger"},
            changelog="添加人工审批节点",
        )
        assert ver.version == 3
        assert ver.definition_json["entryNodeId"] == "trigger"

    def test_version_roundtrip(self):
        ver = WorkflowDefinitionVersion(
            id="wfver_001",
            definition_id="wfdef_001",
            version=1,
        )
        d = ver.to_dict()
        restored = WorkflowDefinitionVersion.from_dict(d)
        assert restored.version == 1
        assert restored.definition_id == "wfdef_001"
