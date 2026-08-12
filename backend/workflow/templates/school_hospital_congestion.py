"""
模板 2: 学校/医院周边拥堵协同 — Phase 12

基础 Workflow Definition，第一轮不要求完整测试。

流程节点：
  trigger → validate_event → rule_router → rag_retrieve → memory_context
  → agent_task(SignalAgent) → agent_task(PublicSafetyAgent) → evidence_evaluate
  → risk_gate → [human_approval] → action → close
"""

from backend.workflow.models import (
    DefinitionStatus,
    NodeConfig,
    NodeType,
    WorkflowDefinition,
)
from backend.workflow.definition import generate_definition_id


def build_school_hospital_congestion_definition() -> WorkflowDefinition:
    """构建学校/医院周边拥堵协同 Workflow 定义。

    特点：
      - 并行调用 SignalAgent（信号配时）+ PublicSafetyAgent（安全评估）
      - 安全优先原则
      - 高风险须审批

    Returns:
        完整的 WorkflowDefinition
    """
    def_id = generate_definition_id()

    nodes = [
        NodeConfig(
            node_id="trigger",
            node_type=NodeType.TRIGGER,
            label="触发入口",
            description="接收学校/医院周边拥堵事件",
            next_nodes=["validate_event"],
        ),

        NodeConfig(
            node_id="validate_event",
            node_type=NodeType.VALIDATE_EVENT,
            label="事件校验",
            description="校验事件数据完整性",
            next_nodes=["rule_router"],
            config={
                "required_fields": [
                    "eventType", "roadName", "avgSpeed", "queueLength", "duration"
                ],
            },
        ),

        NodeConfig(
            node_id="rule_router",
            node_type=NodeType.RULE_ROUTER,
            label="规则路由",
            description="确定安全优先处置路线",
            next_nodes=["rag_retrieve"],
        ),

        NodeConfig(
            node_id="rag_retrieve",
            node_type=NodeType.RAG_RETRIEVE,
            label="RAG 知识检索",
            description="检索学校/医院周边交通管理预案",
            next_nodes=["memory_context"],
            config={
                "top_k": 5,
                "query_template": "{event_type} 学校 医院 周边拥堵 安全 信号配时",
            },
            timeout_seconds=15,
        ),

        NodeConfig(
            node_id="memory_context",
            node_type=NodeType.MEMORY_CONTEXT,
            label="Memory 上下文",
            description="加载该区域历史决策",
            next_nodes=["agent_signal"],
            config={
                "agent_targets": ["SignalAgent", "PublicSafetyAgent"],
            },
            timeout_seconds=10,
        ),

        NodeConfig(
            node_id="agent_signal",
            node_type=NodeType.AGENT_TASK,
            label="信号分析 Agent",
            description="SignalAgent 分析信号配时方案",
            next_nodes=["agent_safety"],
            config={"agent_name": "SignalAgent"},
            timeout_seconds=30,
            max_attempts=2,
        ),

        NodeConfig(
            node_id="agent_safety",
            node_type=NodeType.AGENT_TASK,
            label="公共安全 Agent",
            description="PublicSafetyAgent 评估行人安全和急救通道需求",
            next_nodes=["evidence_evaluate"],
            config={"agent_name": "PublicSafetyAgent"},
            timeout_seconds=30,
            max_attempts=2,
        ),

        NodeConfig(
            node_id="evidence_evaluate",
            node_type=NodeType.EVIDENCE_EVALUATE,
            label="证据评估",
            description="评估多 Agent 输出质量",
            next_nodes=["risk_gate"],
            config={
                "min_confidence": 0.3,
                "min_evidence_count": 1,
            },
        ),

        NodeConfig(
            node_id="risk_gate",
            node_type=NodeType.RISK_GATE,
            label="风险门控",
            description="安全相关事件高风险须审批",
            next_nodes=["human_approval", "action_notify"],
            condition="requires_approval",
        ),

        NodeConfig(
            node_id="human_approval",
            node_type=NodeType.HUMAN_APPROVAL,
            label="人工审批",
            description="安全优先：须人工审核信号配时方案",
            next_nodes=["action_notify"],
        ),

        NodeConfig(
            node_id="action_notify",
            node_type=NodeType.ACTION,
            label="通知与保存",
            description="发送通知并保存结果",
            next_nodes=["close"],
            config={
                "action_type": "notify_wechat",
            },
        ),

        NodeConfig(
            node_id="close",
            node_type=NodeType.CLOSE,
            label="闭环归档",
            description="汇总并归档",
        ),
    ]

    definition = WorkflowDefinition(
        id=def_id,
        name="学校/医院周边拥堵协同",
        description=(
            "针对学校/医院周边拥堵的协同处置流程，包含信号配时分析和公共安全评估。"
            "安全优先原则：行人安全与急救通道保障为最高优先级。"
        ),
        category="拥堵处置",
        status=DefinitionStatus.ACTIVE,
        nodes=nodes,
        entry_node_id="trigger",
        metadata={
            "version": "1.0",
            "tags": ["学校", "医院", "安全", "信号", "协同"],
            "estimatedDuration": "60s",
            "requiresApproval": True,
        },
    )

    return definition
