"""
validate_event 节点 — 事件数据校验。

负责：
  - 校验事件字段完整性和合法性
  - 标准化事件类型名称
  - 添加默认值

不调用外部服务。
"""

from typing import Any, Dict

from backend.workflow.models import NodeConfig
from backend.workflow.state import TrafficWorkflowState


async def execute_validate_event(
    state: TrafficWorkflowState, config: NodeConfig
) -> Dict[str, Any]:
    """执行事件校验。

    使用 tools/event_tools.py 的校验逻辑，但不直接导入避免循环依赖。
    若校验失败，设置 error 但继续执行（让后续节点决定处理方式）。

    Args:
        state: 工作流状态
        config: 节点配置

    Returns:
        校验结果
    """
    event = state.current_event or {}
    required_fields = config.config.get("required_fields", [
        "eventType", "roadName", "avgSpeed", "queueLength", "duration"
    ])

    errors = []
    warnings = []

    # 检查必填字段
    for field in required_fields:
        if field not in event or event.get(field) is None:
            errors.append(f"缺少必填字段: {field}")

    # 检查字段合法性
    avg_speed = event.get("avgSpeed")
    if avg_speed is not None:
        if not isinstance(avg_speed, (int, float)) or avg_speed < 0:
            errors.append(f"avgSpeed 值非法: {avg_speed}")

    queue_length = event.get("queueLength")
    if queue_length is not None:
        if not isinstance(queue_length, (int, float)) or queue_length < 0:
            errors.append(f"queueLength 值非法: {queue_length}")

    duration = event.get("duration")
    if duration is not None:
        if not isinstance(duration, (int, float)) or duration < 0:
            errors.append(f"duration 值非法: {duration}")

    # 标准化事件类型
    event_type = event.get("eventType", "")
    event_type_cn = event.get("eventTypeCn", "")
    if event_type and not event_type_cn:
        from backend.tools.event_tools import EVENT_TYPE_MAP
        event_type_cn = EVENT_TYPE_MAP.get(event_type, event_type)
        event["eventTypeCn"] = event_type_cn

    # 默认值补充
    defaults = {
        "weather": "clear",
        "timePeriod": "off_peak",
        "isMainRoad": False,
        "nearbySchool": False,
        "nearbyHospital": False,
        "confidence": 0.9,
    }
    for k, v in defaults.items():
        if k not in event:
            event[k] = v

    result = {
        "validated_event": event,
        "validation_errors": errors,
        "validation_warnings": warnings,
        "is_valid": len(errors) == 0,
    }

    if errors:
        state.record_error(config.node_id, f"校验失败: {'; '.join(errors)}")

    state.add_audit_event("event_validated", config.node_id, {
        "isValid": result["is_valid"],
        "errorCount": len(errors),
        "warningCount": len(warnings),
    })

    return result
