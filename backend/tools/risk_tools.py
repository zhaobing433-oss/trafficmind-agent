"""
风险评分工具模块
--------------
根据事件特征和加权规则计算风险分数、风险等级和研判依据。
"""

from typing import Dict, Any, List
from backend.config import EVENT_BASE_SCORES, RISK_LEVELS


def calculate_risk_score(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据事件特征计算综合风险分数。

    评分规则：
      1. 基础分：按事件类型取固定分值
      2. 加权项：速度、排队长度、持续时间、天气、时段、道路等级、周边环境
      3. 置信度低时不加分但提示人工复核
      4. 上限 100 分

    Args:
        event: 标准化后的事件字典

    Returns:
        {
            "riskScore": int,         # 风险分数 (0-100)
            "riskLevel": str,         # 风险等级
            "riskReasons": List[str], # 研判依据（每个加分项一条说明）
        }
    """
    event_type = event.get("eventType", "")
    base_score = EVENT_BASE_SCORES.get(event_type, 15)

    reasons: List[str] = []
    total = base_score

    # 基础分说明
    cn_type = event.get("eventTypeCn", event_type)
    reasons.append(f"事件类型为「{cn_type}」，基础风险分 +{base_score}")

    # ----- 加权规则 -----

    avg_speed = float(event.get("avgSpeed", 30))
    if avg_speed < 10:
        total += 15
        reasons.append(f"平均车速 {avg_speed} km/h < 10 km/h，严重缓行，+15")

    queue_length = float(event.get("queueLength", 0))
    if queue_length > 150:
        total += 15
        reasons.append(f"排队长度 {queue_length} 米 > 150 米，拥堵范围大，+15")

    duration = float(event.get("duration", 0))
    if duration > 600:
        total += 10
        reasons.append(f"持续 {int(duration)} 秒 > 600 秒，事件未快速消散，+10")
    if duration > 900:
        total += 10
        reasons.append(f"持续 {int(duration)} 秒 > 900 秒，长时间事件，再额外 +10")

    weather = event.get("weather", "clear")
    if weather in ("rain", "snow", "fog"):
        total += 10
        weather_cn = {"rain": "雨", "snow": "雪", "fog": "雾"}.get(weather, weather)
        reasons.append(f"天气为{weather_cn}，影响通行安全，+10")

    time_period = event.get("timePeriod", "off_peak")
    if time_period in ("morning_peak", "evening_peak"):
        total += 10
        period_cn = {"morning_peak": "早高峰", "evening_peak": "晚高峰"}.get(time_period, time_period)
        reasons.append(f"当前为{period_cn}时段，交通压力大，+10")

    if event.get("isMainRoad", False):
        total += 10
        reasons.append("事发路段为主干道，影响范围广，+10")

    if event.get("nearbySchool", False):
        total += 10
        reasons.append("事发路段邻近学校，行人密度高，+10")

    if event.get("nearbyHospital", False):
        total += 10
        reasons.append("事发路段邻近医院，需保障急救通道，+10")

    # 置信度检查
    confidence = float(event.get("confidence", 0.9))
    if confidence < 0.7:
        reasons.append("⚠ 算法置信度偏低（< 0.7），建议人工复核确认事件真实性")

    # 上限 100
    total = min(total, 100)

    # ----- 等级判定 -----
    level = "重大风险"
    for threshold, label in RISK_LEVELS:
        if total <= threshold:
            level = label
            break

    return {
        "riskScore": total,
        "riskLevel": level,
        "riskReasons": reasons,
    }
