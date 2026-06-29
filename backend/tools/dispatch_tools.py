"""
调度话术工具模块
--------------
生成面向指挥中心/交警的调度指令话术，
以及面向公众的诱导屏提示语。
"""

from typing import Dict, Any


def generate_dispatch_message(
    event: Dict[str, Any],
    risk_result: Dict[str, Any],
    matched_rule: Dict[str, Any],
) -> str:
    """
    生成面向交通指挥中心 / 交警 / 巡查人员的调度话术。
    话术风格：正式、简洁、明确地点、方向、事件类型、风险等级和动作。

    Args:
        event: 标准化事件对象
        risk_result: 风险评估结果
        matched_rule: 规则匹配结果

    Returns:
        调度话术字符串
    """
    road = event.get("roadName", "未知路段")
    direction = event.get("direction", "")
    event_type_cn = event.get("eventTypeCn", event.get("eventType", "未知事件"))
    risk_level = risk_result.get("riskLevel", "未知")
    duration_min = int(float(event.get("duration", 0)) / 60)

    rule_sections = matched_rule.get("ruleSections", {})
    department = rule_sections.get("联动部门", "指挥中心")
    actions = rule_sections.get("处置建议", "请按预案处置")

    # 方向描述
    dir_text = f"，{direction}方向" if direction else ""

    lines = [
        f"【调度指令】",
        f"事件编号：{event.get('eventId', '')}",
        f"事发位置：{road}{dir_text}",
        f"事件类型：{event_type_cn}",
        f"风险等级：{risk_level}（{risk_result.get('riskScore', 0)}分）",
        f"持续时间：约 {duration_min} 分钟",
        f"",
        f"联动部门：{department}",
        f"处置要求：{actions}",
        f"",
        f"请相关单位立即响应，前往现场处置并反馈情况。",
    ]

    return "\n".join(lines)


def generate_public_message(
    event: Dict[str, Any],
    risk_result: Dict[str, Any],
) -> str:
    """
    生成面向公众 / 诱导屏的提示信息。
    要求简短、通俗，方便司机理解并绕行。

    Args:
        event: 标准化事件对象
        risk_result: 风险评估结果

    Returns:
        公众提示语字符串（建议不超过60字）
    """
    road = event.get("roadName", "前方路段")
    direction = event.get("direction", "")
    event_type_cn = event.get("eventTypeCn", event.get("eventType", "异常"))
    risk_level = risk_result.get("riskLevel", "")

    dir_text = f"{direction}方向" if direction else ""

    # 根据事件类型生成不同话术模板
    templates = {
        "拥堵": f"{road}{dir_text}通行缓慢，请过往车辆提前绕行。",
        "事故": f"{road}{dir_text}发生交通事故，请减速避让，服从现场指挥。",
        "违停": f"{road}{dir_text}有车辆违停，请勿占用应急通道。",
        "逆行": f"{road}{dir_text}发现逆行车辆，请过往车辆注意避让，减速慢行。",
        "行人闯入": f"{road}{dir_text}有行人闯入机动车道，请减速慢行，注意避让。",
        "信号灯异常": f"{road}{dir_text}信号灯运行异常，请按交警指挥通行，减速通过路口。",
        "车辆滞留": f"{road}{dir_text}有车辆滞留占用车道，请提前变道，注意避让。",
        "施工占道": f"{road}{dir_text}施工占道，车道变窄，请减速慢行，有序通过。",
    }

    message = templates.get(event_type_cn, f"{road}{dir_text}发生{event_type_cn}事件，请注意行车安全。")

    # 高风险提示加强
    if risk_level in ("高风险", "重大风险"):
        message = f"【注意】{message}"

    return message
