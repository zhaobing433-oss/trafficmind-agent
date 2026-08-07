"""
Workflow V1 节点实现 — Phase 12

每个节点类型对应一个模块，统一接口：
  async def execute(state: TrafficWorkflowState, config: NodeConfig) -> Dict[str, Any]

返回 dict 包含节点执行结果（会被合并到 state）。
"""

from backend.workflow.nodes.base import NodeRegistry, get_node_registry
from backend.workflow.nodes.trigger import execute_trigger
from backend.workflow.nodes.validate_event import execute_validate_event
from backend.workflow.nodes.rule_router import execute_rule_router
from backend.workflow.nodes.rag_retrieve import execute_rag_retrieve
from backend.workflow.nodes.memory_context import execute_memory_context
from backend.workflow.nodes.agent_task import execute_agent_task
from backend.workflow.nodes.parallel_join import execute_parallel, execute_join
from backend.workflow.nodes.evidence_evaluate import execute_evidence_evaluate
from backend.workflow.nodes.risk_gate import execute_risk_gate
from backend.workflow.nodes.human_approval import execute_human_approval
from backend.workflow.nodes.action import execute_action
from backend.workflow.nodes.wait_monitor import execute_wait, execute_monitor
from backend.workflow.nodes.close import execute_close


def register_all_nodes() -> NodeRegistry:
    """注册所有节点类型到全局注册表。"""
    registry = get_node_registry()
    registry.register("trigger", execute_trigger)
    registry.register("validate_event", execute_validate_event)
    registry.register("rule_router", execute_rule_router)
    registry.register("rag_retrieve", execute_rag_retrieve)
    registry.register("memory_context", execute_memory_context)
    registry.register("agent_task", execute_agent_task)
    registry.register("parallel", execute_parallel)
    registry.register("join", execute_join)
    registry.register("evidence_evaluate", execute_evidence_evaluate)
    registry.register("risk_gate", execute_risk_gate)
    registry.register("human_approval", execute_human_approval)
    registry.register("action", execute_action)
    registry.register("wait", execute_wait)
    registry.register("monitor", execute_monitor)
    registry.register("close", execute_close)
    return registry
