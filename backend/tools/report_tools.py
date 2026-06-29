"""
报告生成工具模块
--------------
按固定模板生成结构化事件研判报告。
"""

from datetime import datetime
from typing import Dict, Any, List


def generate_event_report(
    event: Dict[str, Any],
    risk_result: Dict[str, Any],
    matched_rule: Dict[str, Any],
    suggestions: List[str],
    dispatch_message: str,
) -> str:
    """
    按八段式模板生成结构化事件研判报告。

    Args:
        event: 标准化事件对象
        risk_result: 风险评估结果
        matched_rule: 规则匹配结果
        suggestions: 处置建议列表
        dispatch_message: 调度话术

    Returns:
        结构化报告文本
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ----- 一、事件概况 -----
    event_type_cn = event.get("eventTypeCn", event.get("eventType", ""))
    road = event.get("roadName", "")
    direction = event.get("direction", "")
    lane = event.get("lane", "")
    avg_speed = event.get("avgSpeed", 0)
    queue_length = event.get("queueLength", 0)
    duration_min = int(float(event.get("duration", 0)) / 60)
    vehicle_count = event.get("vehicleCount", 0)
    confidence = event.get("confidence", 0)

    overview = (
        f"报告生成时间：{now}\n"
        f"事件编号：{event.get('eventId', '')}\n"
        f"事件类型：{event_type_cn}\n"
        f"事发路段：{road}{'，' + direction if direction else ''}{'，' + lane if lane else ''}\n"
        f"平均车速：{avg_speed} km/h\n"
        f"排队长度：{queue_length} 米\n"
        f"持续时间：{duration_min} 分钟\n"
        f"涉及车辆：{vehicle_count} 辆\n"
        f"算法置信度：{confidence}"
    )

    # ----- 二、风险等级 -----
    risk_section = (
        f"风险分数：{risk_result.get('riskScore', 0)} 分\n"
        f"风险等级：{risk_result.get('riskLevel', '未知')}"
    )

    # ----- 三、研判依据 -----
    reasons = risk_result.get("riskReasons", [])
    reasons_text = "\n".join(f"  {i + 1}. {r}" for i, r in enumerate(reasons))
    analysis_section = f"经综合分析如下因素：\n{reasons_text}"

    # ----- 四、匹配预案 -----
    rule_text = matched_rule.get("rule", "无匹配预案")

    # ----- 五、建议处置 -----
    if suggestions:
        sug_text = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(suggestions))
    else:
        sug_text = "  暂无具体建议，请按通用流程处置"

    # ----- 六、调度话术 -----
    # 直接使用传入的话术

    # ----- 七、后续跟踪 -----
    rule_sections = matched_rule.get("ruleSections", {})
    follow_up = rule_sections.get("后续跟踪", "持续监测事件状态，确认处置完成后归档。")

    # ----- 八、复盘建议 -----
    review = (
        f"1. 分析事件成因，评估是否需要优化该路段信号配时或交通组织。\n"
        f"2. 如涉及算法检测，核对检测准确率和响应时效。\n"
        f"3. 总结本次处置经验，完善预案库。"
    )

    # ----- 组装完整报告 -----
    report_lines = [
        "=" * 50,
        "          交通事故/事件研判处置报告",
        "=" * 50,
        "",
        "一、事件概况",
        "-" * 30,
        overview,
        "",
        "二、风险等级",
        "-" * 30,
        risk_section,
        "",
        "三、研判依据",
        "-" * 30,
        analysis_section,
        "",
        "四、匹配预案",
        "-" * 30,
        rule_text,
        "",
        "五、建议处置",
        "-" * 30,
        sug_text,
        "",
        "六、调度话术",
        "-" * 30,
        dispatch_message,
        "",
        "七、后续跟踪",
        "-" * 30,
        follow_up,
        "",
        "八、复盘建议",
        "-" * 30,
        review,
        "",
        "=" * 50,
    ]

    return "\n".join(report_lines)
