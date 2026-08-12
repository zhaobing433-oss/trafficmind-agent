"""
trigger 节点 — 工作流入口。

负责：
  - 接收触发事件
  - 设置 current_event 和 original_input
  - 初始化 state 基础字段
  - 不做任何外部调用
"""

from typing import Any, Dict

from backend.workflow.models import NodeConfig
from backend.workflow.state import TrafficWorkflowState


async def execute_trigger(state: TrafficWorkflowState, config: NodeConfig) -> Dict[str, Any]:
    """执行 trigger 节点。

    优先使用 state.current_event（由 executor 注入），
    其次使用 config.config.initial_event。

    Args:
        state: 工作流状态
        config: 节点配置（config.initial_event 包含触发事件数据）

    Returns:
        更新后的 state 字段
    """
    # 优先使用 state 中已有的 current_event（由 executor.start() 注入）
    initial_event = state.current_event or {}
    if not initial_event:
        initial_event = config.config.get("initial_event", {})

    if not initial_event:
        return {
            "error": "trigger 节点缺少 initial_event 数据",
        }

    state.current_event = initial_event
    state.original_input = dict(initial_event)

    # 提取标识字段
    event_type = initial_event.get("eventType", initial_event.get("event_type", ""))
    road_name = initial_event.get("roadName", initial_event.get("road_name", ""))

    state.add_audit_event("workflow_triggered", config.node_id, {
        "eventType": event_type,
        "roadName": road_name,
    })

    return {
        "current_event": initial_event,
        "original_input": initial_event,
    }
