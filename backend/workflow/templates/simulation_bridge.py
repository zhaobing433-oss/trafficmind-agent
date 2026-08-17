"""
simulation_bridge — Phase 13 Round 2

Simulation Event → Workflow Bridge 模板。

节点链:
  trigger → validate_event → rule_router →
  memory_context → agent_task → evidence_evaluate →
  risk_gate → human_approval → action → close

Agent task 通过 simulation_refs 获取 spatial context，
生成 ActionProposal（只读），不直接修改 Simulation。

所有写操作必须经过 human_approval → action node。
"""

from backend.workflow.models import (
    NodeConfig,
    NodeType,
    WorkflowDefinition,
    DefinitionStatus,
)


def build_simulation_bridge_definition() -> WorkflowDefinition:
    """构建 Simulation Bridge Workflow 定义。"""

    nodes = [
        NodeConfig(
            node_id="trigger",
            node_type=NodeType.TRIGGER,
            label="仿真事件触发",
            description="接收来自 Simulation 的交通事件",
            next_nodes=["validate_event"],
        ),
        NodeConfig(
            node_id="validate_event",
            node_type=NodeType.VALIDATE_EVENT,
            label="事件校验",
            description="验证事件字段完整性",
            next_nodes=["rule_router"],
        ),
        NodeConfig(
            node_id="rule_router",
            node_type=NodeType.RULE_ROUTER,
            label="规则路由",
            description="根据事件类型和严重程度路由",
            config={
                "force_agents": ["CongestionAgent", "DispatchAgent"],
            },
            next_nodes=["memory_context"],
        ),
        NodeConfig(
            node_id="memory_context",
            node_type=NodeType.MEMORY_CONTEXT,
            label="记忆上下文",
            description="加载历史记忆上下文",
            next_nodes=["agent_task"],
        ),
        NodeConfig(
            node_id="agent_task",
            node_type=NodeType.AGENT_TASK,
            label="Agent 协同研判",
            description="Agent 基于 spatial context 生成 ActionProposal",
            config={
                "agent_name": "CongestionAgent",
                "include_spatial_context": True,
            },
            timeout_seconds=90,
            max_attempts=2,
            next_nodes=["evidence_evaluate"],
        ),
        NodeConfig(
            node_id="evidence_evaluate",
            node_type=NodeType.EVIDENCE_EVALUATE,
            label="证据评估",
            description="评估 Agent proposal 的证据充分性",
            next_nodes=["human_approval"],
        ),
        NodeConfig(
            node_id="human_approval",
            node_type=NodeType.HUMAN_APPROVAL,
            label="人工审批",
            description="审批 Agent 提议的模拟处置动作",
            timeout_seconds=300,
            next_nodes=["action"],
            config={"action_types": ["simulation_traffic_diversion"]},
        ),
        NodeConfig(
            node_id="action",
            node_type=NodeType.ACTION,
            label="执行模拟动作",
            description="调用 DemoSimulationProvider 执行经审批的 traffic_diversion",
            config={
                "action_type": "simulation_traffic_diversion",
            },
            next_nodes=["close"],
        ),
        NodeConfig(
            node_id="close",
            node_type=NodeType.CLOSE,
            label="关闭",
            description="工作流完成",
            next_nodes=[],
        ),
    ]

    return WorkflowDefinition(
        id="simulation_bridge",
        name="仿真事件研判桥接",
        description=(
            "Simulation Event → Agent Analysis → ActionProposal → "
            "Human Approval → Diversion Action → Map Feedback → Close"
        ),
        category="simulation",
        status=DefinitionStatus.ACTIVE,
        nodes=nodes,
        entry_node_id="trigger",
        metadata={
            "phase": "13",
            "round": "2",
            "supported_actions": ["traffic_diversion"],
            "simulation": True,
        },
    )
