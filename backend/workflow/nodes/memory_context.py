"""
memory_context 节点 — Memory 上下文加载。

调用 Memory V2 召回相关记忆：
  - 同一 Event Thread 的历史决策
  - 路段稳定事实
  - 用户纠正记录

召回结果存入 memory_context，与 rag_context 严格分离。
不覆盖 current_event。
"""

from typing import Any, Dict

from backend.workflow.models import NodeConfig
from backend.workflow.state import TrafficWorkflowState


async def execute_memory_context(
    state: TrafficWorkflowState, config: NodeConfig
) -> Dict[str, Any]:
    """执行 Memory 上下文加载。

    Args:
        state: 工作流状态
        config: 节点配置

    Returns:
        Memory 召回结果（存入 memory_context）
    """
    event = state.current_event or {}
    session_id = state.session_id
    event_thread_id = state.event_thread_id

    mem_ctx: Dict[str, Any] = {
        "sessionGoal": None,
        "stableFacts": [],
        "userCorrections": [],
        "confirmedDecisions": [],
        "recentRunSummaries": [],
        "recallCount": 0,
    }
    trace_id = ""

    try:
        from backend.memory.coordinator import MemoryCoordinator
        coordinator = MemoryCoordinator()
        recall_result = coordinator.recall_and_inject(
            session_id=session_id,
            run_id=state.workflow_run_id,
            user_input=config.config.get("query_override", ""),
            current_event=event,
            agent_targets=config.config.get("agent_targets", []),
            context_policy=event.get("contextPolicy", "fresh_event"),
        )

        if recall_result:
            mem_ctx = recall_result.get("injectionContext", mem_ctx)
            trace_id = recall_result.get("traceId", "")
    except Exception:
        # Memory 不可用时降级为空上下文
        pass

    # 存入 memory_context（与 rag_context 分离）
    state.set_memory_context(mem_ctx)

    # 加载稳定事实到 state
    stable_facts = mem_ctx.get("stableFacts", [])
    if isinstance(stable_facts, list):
        for fact in stable_facts:
            if isinstance(fact, dict):
                key = fact.get("memoryKey", fact.get("key", ""))
                value = fact.get("value", fact.get("val", ""))
                if key:
                    state.add_stable_fact(key, value)

    state.add_audit_event("memory_loaded", config.node_id, {
        "recallCount": mem_ctx.get("recallCount", 0),
        "traceId": trace_id,
    })

    return {"memory_context": mem_ctx}
