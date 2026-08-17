"""
模板 3: 道路交通事故122/120联动 — Phase 12

基础 Workflow Definition，第一轮不要求完整测试。

流程节点：
  trigger → validate_event → rule_router → rag_retrieve → memory_context
  → agent_task(AccidentAgent) → evidence_evaluate → risk_gate
  → [human_approval] → action(notify + save) → close
"""

from backend.workflow.models import (
    DefinitionStatus,
    NodeConfig,
    NodeType,
    WorkflowDefinition,
)
from backend.workflow.definition import generate_definition_id


def build_accident_122_120_definition() -> WorkflowDefinition:
    """构建道路交通事故122/120联动 Workflow 定义。

    特点：
      - AccidentAgent 分析事故类型和严重程度
      - 自动评估是否需要120急救
      - 122交警联动通知
      - 高风险强制人工审批

    Returns:
        完整的 WorkflowDefinition
    """
    def_id = generate_definition_id()

    nodes = [
        NodeConfig(
            node_id="trigger",
            node_type=NodeType.TRIGGER,
            label="触发入口",
            description="接收道路交通事故事件",
            next_nodes=["validate_event"],
        ),

        NodeConfig(
            node_id="validate_event",
            node_type=NodeType.VALIDATE_EVENT,
            label="事件校验",
            description="校验事故事件数据完整性",
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
            description="确定事故处置路线和联动级别",
            next_nodes=["rag_retrieve"],
        ),

        NodeConfig(
            node_id="rag_retrieve",
            node_type=NodeType.RAG_RETRIEVE,
            label="RAG 知识检索",
            description="检索事故处置预案和历史案例",
            next_nodes=["memory_context"],
            config={
                "top_k": 5,
                "query_template": "交通事故 122 120 联动 处置预案 {event_type}",
            },
            timeout_seconds=15,
        ),

        NodeConfig(
            node_id="memory_context",
            node_type=NodeType.MEMORY_CONTEXT,
            label="Memory 上下文",
            description="加载该路段历史事故记录",
            next_nodes=["agent_accident"],
            config={
                "agent_targets": ["AccidentAgent"],
            },
            timeout_seconds=10,
        ),

        NodeConfig(
            node_id="agent_accident",
            node_type=NodeType.AGENT_TASK,
            label="事故分析 Agent",
            description="AccidentAgent 分析事故类型、严重程度、交通影响",
            next_nodes=["evidence_evaluate"],
            config={"agent_name": "AccidentAgent"},
            timeout_seconds=30,
            max_attempts=2,
        ),

        NodeConfig(
            node_id="evidence_evaluate",
            node_type=NodeType.EVIDENCE_EVALUATE,
            label="证据评估",
            description="评估事故分析结果质量",
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
            description="事故事件通常为高风险，须审批",
            next_nodes=["human_approval", "action_notify"],
            condition="requires_approval",
        ),

        NodeConfig(
            node_id="human_approval",
            node_type=NodeType.HUMAN_APPROVAL,
            label="人工审批",
            description="事故处置方案须人工审核",
            next_nodes=["action_notify"],
            config={"action_types": ["notify_wechat"]},
        ),

        NodeConfig(
            node_id="action_notify",
            node_type=NodeType.ACTION,
            label="联动通知",
            description="发送122/120联动通知并保存结果",
            next_nodes=["close"],
            config={
                "action_type": "notify_wechat",
                "action_params": {
                    "channels": ["wechat", "dingtalk"],
                },
            },
            timeout_seconds=15,
        ),

        NodeConfig(
            node_id="close",
            node_type=NodeType.CLOSE,
            label="闭环归档",
            description="汇总事故处置结果并归档",
        ),
    ]

    definition = WorkflowDefinition(
        id=def_id,
        name="道路交通事故122/120联动",
        description=(
            "针对道路交通事故的紧急联动处置流程："
            "事故分析 → 严重度评估 → 122交警联动 → 120急救联动 → 闭环归档。"
            "事故事件强制人工审批。"
        ),
        category="事故联动",
        status=DefinitionStatus.ACTIVE,
        nodes=nodes,
        entry_node_id="trigger",
        metadata={
            "version": "1.0",
            "tags": ["事故", "122", "120", "联动", "急救"],
            "estimatedDuration": "60s",
            "requiresApproval": True,
        },
    )

    return definition
