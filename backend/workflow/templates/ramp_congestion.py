"""
模板 1: 高速匝道拥堵分流与闭环 — Phase 12

完整 Workflow 定义，首期优先实现。

流程节点：
  trigger → validate_event → rule_router → rag_retrieve → memory_context
  → agent_task(CongestionAgent) → evidence_evaluate → risk_gate
  → [高/重大风险] human_approval → action(notify + save)
  → close

条件分支：
  - risk_gate: requires_approval → human_approval 路径 | → action 路径
"""

from backend.workflow.models import (
    DefinitionStatus,
    NodeConfig,
    NodeType,
    WorkflowDefinition,
)
from backend.workflow.definition import generate_definition_id


def build_ramp_congestion_definition() -> WorkflowDefinition:
    """构建高速匝道拥堵分流与闭环 Workflow 定义。

    Returns:
        完整的 WorkflowDefinition
    """
    def_id = generate_definition_id()

    nodes = [
        # ── 1. trigger ────────────────────────────────────────────────
        NodeConfig(
            node_id="trigger",
            node_type=NodeType.TRIGGER,
            label="触发入口",
            description="接收拥堵事件，设置 current_event",
            next_nodes=["validate_event"],
            config={"initial_event": {}},  # 运行时由 API 注入
        ),

        # ── 2. validate_event ─────────────────────────────────────────
        NodeConfig(
            node_id="validate_event",
            node_type=NodeType.VALIDATE_EVENT,
            label="事件校验",
            description="校验事件字段完整性，标准化事件类型",
            next_nodes=["rule_router"],
            config={
                "required_fields": [
                    "eventType", "roadName", "avgSpeed", "queueLength", "duration"
                ],
            },
            timeout_seconds=10,
        ),

        # ── 3. rule_router ────────────────────────────────────────────
        NodeConfig(
            node_id="rule_router",
            node_type=NodeType.RULE_ROUTER,
            label="规则路由",
            description="根据事件类型和风险特征确定处置路线",
            next_nodes=["rag_retrieve"],
        ),

        # ── 4. rag_retrieve ───────────────────────────────────────────
        NodeConfig(
            node_id="rag_retrieve",
            node_type=NodeType.RAG_RETRIEVE,
            label="RAG 知识检索",
            description="检索相关预案、历史案例、处置经验",
            next_nodes=["memory_context"],
            config={
                "top_k": 5,
                "query_template": "{event_type} 匝道拥堵 分流方案 处置预案",
            },
            timeout_seconds=15,
        ),

        # ── 5. memory_context ─────────────────────────────────────────
        NodeConfig(
            node_id="memory_context",
            node_type=NodeType.MEMORY_CONTEXT,
            label="Memory 上下文",
            description="加载该路段历史决策和稳定事实",
            next_nodes=["agent_congestion"],
            config={
                "agent_targets": ["CongestionAgent"],
            },
            timeout_seconds=10,
        ),

        # ── 6. agent_task (CongestionAgent) ───────────────────────────
        NodeConfig(
            node_id="agent_congestion",
            node_type=NodeType.AGENT_TASK,
            label="拥堵分析 Agent",
            description="CongestionAgent 分析拥堵等级、扩散趋势、通行能力",
            next_nodes=["evidence_evaluate"],
            config={
                "agent_name": "CongestionAgent",
            },
            timeout_seconds=30,
            max_attempts=2,
            retry_delay_seconds=5,
        ),

        # ── 7. evidence_evaluate ──────────────────────────────────────
        NodeConfig(
            node_id="evidence_evaluate",
            node_type=NodeType.EVIDENCE_EVALUATE,
            label="证据评估",
            description="评估 Agent 输出和 RAG 检索的证据质量",
            next_nodes=["risk_gate"],
            config={
                "min_confidence": 0.3,
                "min_evidence_count": 1,
            },
        ),

        # ── 8. risk_gate ──────────────────────────────────────────────
        NodeConfig(
            node_id="risk_gate",
            node_type=NodeType.RISK_GATE,
            label="风险门控",
            description="高风险 → 人工审批；低/中风险 → 自动处置",
            next_nodes=["human_approval", "action_notify"],
            condition="requires_approval",
        ),

        # ── 9a. human_approval ────────────────────────────────────────
        NodeConfig(
            node_id="human_approval",
            node_type=NodeType.HUMAN_APPROVAL,
            label="人工审批",
            description="高风险事件需人工审核后方可执行外部动作",
            next_nodes=["action_notify"],
            config={"action_types": ["notify_wechat"]},
        ),

        # ── 9b/10. action ─────────────────────────────────────────────
        NodeConfig(
            node_id="action_notify",
            node_type=NodeType.ACTION,
            label="通知与保存",
            description="发送企业微信通知并持久化分析结果",
            next_nodes=["close"],
            config={
                "action_type": "notify_wechat",
                "action_params": {
                    "channels": ["wechat"],
                },
            },
            timeout_seconds=15,
        ),

        # ── 11. close ─────────────────────────────────────────────────
        NodeConfig(
            node_id="close",
            node_type=NodeType.CLOSE,
            label="闭环归档",
            description="汇总所有结果，标记 Workflow 完成",
        ),
    ]

    definition = WorkflowDefinition(
        id=def_id,
        name="高速匝道拥堵分流与闭环",
        description=(
            "针对高速公路匝道拥堵事件的完整处置流程："
            "事件校验 → 规则路由 → RAG 检索 → Memory 上下文 → 拥堵 Agent 分析 "
            "→ 证据评估 → 风险门控 → [人工审批] → 通知与保存 → 闭环归档。"
            "高风险事件须经人工审批后方可执行外部动作。"
        ),
        category="拥堵处置",
        status=DefinitionStatus.ACTIVE,
        nodes=nodes,
        entry_node_id="trigger",
        metadata={
            "version": "1.0",
            "tags": ["拥堵", "匝道", "高速", "分流", "闭环"],
            "estimatedDuration": "60s",
            "requiresApproval": True,
        },
    )

    return definition
