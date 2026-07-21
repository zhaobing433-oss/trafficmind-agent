"""
自然语言事件解析器 — Phase 9.6
支持中文文本提取交通事件结构化字段。
"""
import re
from typing import Dict, Any


def parse_content_to_event(content: str) -> Dict[str, Any]:
    """从自然语言内容中提取结构化事件信息。"""
    result: Dict[str, Any] = {
        "eventTypeCn": "拥堵",
        "eventType": "congestion",
        "roadName": "未命名路段",
        "avgSpeed": None,
        "queueLength": None,
        "duration": None,
        "weather": "clear",
        "timePeriod": "off_peak",
        "isMainRoad": False,
        "nearbySchool": False,
        "nearbyHospital": False,
        "hasAccident": False,
        "pedestrianRisk": "low",
        "signalOptimizationRequested": False,
        "conflictIntent": False,
        "missingFields": [],
        "limitations": [],
    }

    # School/pedestrian/conflict detection
    result["nearbySchool"] = any(w in content for w in ["学校", "小学", "中学", "大学", "校园", "学生", "校门口"])
    result["pedestrianRisk"] = "high" if any(w in content for w in ["学生", "横穿", "过街", "穿越", "集中过"]) else "low"
    result["signalOptimizationRequested"] = any(w in content for w in ["绿灯", "绿信比", "相位", "信号", "配时", "放行"])
    result["conflictIntent"] = any(w in content for w in ["冲突", "权衡", "矛盾", "兼顾", "平衡", "评估.*与"])

    # Negations first
    has_no_accident = any(w in content for w in ["无事故", "没有事故", "未发生事故", "没出事故"])
    has_accident_kw = any(w in content for w in ["事故", "碰撞", "追尾", "剐蹭", "撞车", "车祸"])

    # Event type detection
    if has_accident_kw and not has_no_accident:
        result["eventTypeCn"] = "事故"
        result["eventType"] = "accident"
        result["hasAccident"] = True
    elif any(w in content for w in ["信号", "红绿灯", "灯控"]) and not has_no_accident:
        result["eventTypeCn"] = "信号灯异常"
        result["eventType"] = "signal_fault"
    elif any(w in content for w in ["拥堵", "堵车", "排队", "缓行", "通行缓慢", "堵了"]):
        result["eventTypeCn"] = "拥堵"
        result["eventType"] = "congestion"

    # Speed extraction: "8km/h", "8 km/h", "时速8公里", "平均车速 8"
    speed_match = re.search(r'(\d+\.?\d*)\s*(?:km/?h|公里/?[时小]时|码)', content)
    if not speed_match:
        speed_match = re.search(r'(?:速度|车速|均速).*?(\d+\.?\d*)', content)
    if speed_match:
        result["avgSpeed"] = float(speed_match.group(1))
    else:
        result["missingFields"].append("avgSpeed")
        result["limitations"].append("未提取到具体车速")

    # Queue length: "排队约400米", "排队长度400m", "排队400米"
    queue_match = re.search(r'排队.*?(\d+\.?\d*)\s*(?:米|m)', content)
    if queue_match:
        result["queueLength"] = float(queue_match.group(1))
    else:
        result["missingFields"].append("queueLength")
        result["limitations"].append("未提取到具体排队长度")

    # Duration: "持续20分钟", "持续20分"
    dur_match = re.search(r'持续.*?(\d+\.?\d*)\s*(?:分钟|分)', content)
    if dur_match:
        result["duration"] = float(dur_match.group(1)) * 60  # convert to seconds
    else:
        result["missingFields"].append("duration")
        result["limitations"].append("未提取到持续时间")

    # Time period
    if any(w in content for w in ["早高峰", "早间高峰", "上班高峰"]):
        result["timePeriod"] = "morning_peak"
    elif any(w in content for w in ["晚高峰", "晚间高峰", "下班高峰"]):
        result["timePeriod"] = "evening_peak"

    # Road type
    if any(w in content for w in ["主干道", "主路", "主干路"]):
        result["isMainRoad"] = True
    if result["isMainRoad"] and "未命名" in str(result.get("roadName", "")):
        result["roadName"] = "未命名主干道"

    # Weather
    if any(w in content for w in ["雨", "下雨", "雨天"]):
        result["weather"] = "rain"
    elif any(w in content for w in ["雪", "下雪", "雪天"]):
        result["weather"] = "snow"
    elif any(w in content for w in ["雾", "大雾", "雾天", "霾"]):
        result["weather"] = "fog"

    # Nearby facilities
    if any(w in content for w in ["医院", "急救"]):
        result["nearbyHospital"] = True
    if any(w in content for w in ["学校", "小学", "中学", "大学", "校园"]):
        result["nearbySchool"] = True

    # Explicit negatives
    if any(w in content for w in ["无事故", "没有事故", "未发生事故"]):
        result["hasAccident"] = False
    if any(w in content for w in ["无医院", "没有医院", "无学校", "没有学校"]):
        result["nearbyHospital"] = False
        result["nearbySchool"] = False

    return result
