"""
wait 和 monitor 节点 — 等待与监控。

wait: 暂停 Workflow 等待条件满足
  - wait_type: time_delay（固定时长）或 external_event（外部事件触发）

monitor: 监控外部状态变化
  - 轮询检查条件直到满足或超时
"""

from typing import Any, Dict

from backend.workflow.models import NodeConfig, WaitConditionType, MonitorConditionType
from backend.workflow.state import TrafficWorkflowState, WorkflowRunStatus


async def execute_wait(
    state: TrafficWorkflowState, config: NodeConfig
) -> Dict[str, Any]:
    """执行等待节点。

    恢复场景检测：若 node 已有输出记录（被 scheduler 恢复），直接跳过。
    """
    # ── 恢复场景：已完成等待，跳过 ──────────────────────────────────
    node_outputs = state.node_outputs or {}
    if config.node_id in node_outputs:
        state.add_audit_event("wait_resumed", config.node_id, {
            "status": "already_waited",
        })
        return {"wait_skipped": True, "status": "already_waited"}

    wait_type = config.config.get("wait_type", WaitConditionType.TIME_DELAY.value)
    delay_seconds = config.config.get("delay_seconds", 0)
    event_name = config.config.get("event_name", "")

    if wait_type == WaitConditionType.TIME_DELAY.value:
        pause_reason = f"等待 {delay_seconds} 秒后自动恢复"
        state.transition(WorkflowRunStatus.PAUSED)
        state.add_audit_event("wait_started", config.node_id, {
            "waitType": "time_delay",
            "delaySeconds": delay_seconds,
        })

        return {
            "wait_type": "time_delay",
            "delay_seconds": delay_seconds,
            "pause_reason": pause_reason,
            "auto_resume": True,
        }

    elif wait_type == WaitConditionType.EXTERNAL_EVENT.value:
        pause_reason = f"等待外部事件: {event_name}"
        state.transition(WorkflowRunStatus.PAUSED)
        state.add_audit_event("wait_started", config.node_id, {
            "waitType": "external_event",
            "eventName": event_name,
        })

        return {
            "wait_type": "external_event",
            "event_name": event_name,
            "pause_reason": pause_reason,
            "auto_resume": False,
        }

    return {
        "error": f"未知的 wait_type: {wait_type}",
    }


async def execute_monitor(
    state: TrafficWorkflowState, config: NodeConfig
) -> Dict[str, Any]:
    """执行监控节点。

    设置监控条件，后续由 executor 轮询检查。

    Args:
        state: 工作流状态
        config: 节点配置
          - config.monitor_type: 监控类型
          - config.check_condition: 检查条件表达式
          - config.timeout_seconds: 监控超时

    Returns:
        监控配置
    """
    monitor_type = config.config.get("monitor_type", MonitorConditionType.STATUS_CHANGE.value)
    condition_expr = config.config.get("check_condition", "")
    timeout_seconds = config.config.get("timeout_seconds", 300)

    state.add_audit_event("monitor_started", config.node_id, {
        "monitorType": monitor_type,
        "condition": condition_expr,
        "timeoutSeconds": timeout_seconds,
    })

    return {
        "monitor_type": monitor_type,
        "condition": condition_expr,
        "timeout_seconds": timeout_seconds,
        "monitoring": True,
    }
