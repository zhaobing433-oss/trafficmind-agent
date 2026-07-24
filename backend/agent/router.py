"""
动态 Agent 路由
--------------
根据事件类型、风险等级、道路特征等动态选择需要参与的 Agent。

路由规则是确定性的 — 不使用 LLM，保证可审计。
"""

from typing import Dict, Any, List


# Agent 注册表 — ReportAgent 已统一映射为 FusionAgent
ALL_AGENTS = [
    "CongestionAgent",
    "AccidentAgent",
    "SignalAgent",
    "DispatchAgent",
    "PublicSafetyAgent",
    "FusionAgent",
]
# Backward compat: ReportAgent → FusionAgent
AGENT_ALIASES = {"ReportAgent": "FusionAgent"}


def route_agents(event_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据事件特征动态选择需要参与研判的 Agent。

    Args:
        event_info: 事件信息字典（包含 eventType, riskLevel, roadName 等）

    Returns:
        RouteResult 结构
    """
    event_type = event_info.get("eventTypeCn", event_info.get("eventType", ""))
    event_type_raw = event_info.get("eventType", event_type)
    risk_level = event_info.get("riskLevel", "")
    is_main_road = bool(event_info.get("isMainRoad", False))
    nearby_school = bool(event_info.get("nearbySchool", False))
    nearby_hospital = bool(event_info.get("nearbyHospital", False))
    weather = event_info.get("weather", "clear")
    time_period = event_info.get("timePeriod", "off_peak")

    selected: List[str] = []
    reasons: List[str] = []
    skipped: List[str] = []
    risk_triggers: List[str] = []

    # ---- 规则 1: 按事件类型路由 ----
    if event_type in ("拥堵", "congestion"):
        selected.append("CongestionAgent")
        reasons.append(f"事件类型为「{event_type}」，触发 CongestionAgent")
        skipped.append("AccidentAgent")
        # SignalAgent: signal keywords or parsed signalOptimizationRequested
        signal_keywords = ["信号", "配时", "绿信比", "相位", "红绿灯", "灯控", "绿灯", "放行", "cycle", "signal", "intersection"]
        content = str(event_info.get("originalInput", event_info.get("content", ""))).lower()
        if any(kw in content for kw in signal_keywords) or event_info.get("signalOptimizationRequested"):
            selected.append("SignalAgent")
            reasons.append("存在信号/绿灯/配时相关需求，附加 SignalAgent")

    elif event_type in ("事故", "accident"):
        selected.extend(["AccidentAgent", "CongestionAgent"])
        reasons.append(f"事件类型为「{event_type}」，触发 AccidentAgent 和 CongestionAgent")
        skipped.append("SignalAgent")

    elif event_type in ("信号灯异常", "signal_fault"):
        selected.extend(["SignalAgent"])
        reasons.append(f"事件类型为「{event_type}」，触发 SignalAgent")
        skipped.extend(["CongestionAgent", "AccidentAgent"])

    elif event_type in ("逆行", "wrong_way"):
        selected.extend(["AccidentAgent", "DispatchAgent"])
        reasons.append(f"事件类型为「{event_type}」，逆行高风险，触发 AccidentAgent")
        skipped.append("SignalAgent")

    elif event_type in ("行人闯入", "pedestrian_intrusion"):
        selected.extend(["PublicSafetyAgent", "DispatchAgent"])
        reasons.append(f"事件类型为「{event_type}」，触发 PublicSafetyAgent")
        skipped.extend(["CongestionAgent", "AccidentAgent", "SignalAgent"])

    else:
        selected.extend(["CongestionAgent", "DispatchAgent"])
        reasons.append(f"事件类型为「{event_type}」，使用默认 Agent 组合")

    # ---- 规则 2: 风险等级触发 ----
    if risk_level in ("高风险", "重大风险"):
        if "DispatchAgent" not in selected:
            selected.append("DispatchAgent")
        if "ReportAgent" not in selected:
            selected.append("ReportAgent")
        reasons.append(f"风险等级为「{risk_level}」，强制触发 DispatchAgent 和 ReportAgent")
        risk_triggers.append(f"riskLevel={risk_level}")

    # ---- 规则 3: 环境因素附加 ----
    if nearby_hospital or nearby_school:
        if "PublicSafetyAgent" not in selected:
            selected.append("PublicSafetyAgent")
        if nearby_hospital:
            reasons.append("邻近医院，附加 PublicSafetyAgent（保障急救通道）")
            risk_triggers.append("nearbyHospital=true")
        if nearby_school:
            reasons.append("邻近学校，附加 PublicSafetyAgent（保障学生安全）")
            risk_triggers.append("nearbySchool=true")

    # Pedestrian risk triggers safety agent
    if event_info.get("pedestrianRisk") == "high" and "PublicSafetyAgent" not in selected:
        selected.append("PublicSafetyAgent")
        reasons.append("存在行人/学生横穿风险，附加 PublicSafetyAgent")
        risk_triggers.append("pedestrianRisk=high")

    if weather in ("rain", "snow", "fog"):
        reasons.append(f"天气为「{weather}」，建议所有 Agent 关注路面安全")
        risk_triggers.append(f"weather={weather}")

    if time_period in ("morning_peak", "evening_peak"):
        if "CongestionAgent" not in selected:
            selected.append("CongestionAgent")
        reasons.append("高峰时段，附加 CongestionAgent 关注交通压力")
        risk_triggers.append(f"timePeriod={time_period}")

    if is_main_road:
        reasons.append("主干道事件，影响范围广，需优先处置")
        risk_triggers.append("isMainRoad=true")

    # ---- 规则 4: 始终包含 DispatchAgent 和 FusionAgent ----
    if "DispatchAgent" not in selected:
        selected.append("DispatchAgent")
    if "FusionAgent" not in selected:
        selected.append("FusionAgent")

    # 去重保证顺序
    seen = set()
    final_selected = []
    for a in selected:
        if a not in seen:
            final_selected.append(a)
            seen.add(a)

    # 记录跳过的 Agent
    for a in ALL_AGENTS:
        if a not in final_selected and a not in skipped:
            skipped.append(a)

    return {
        "selectedAgents": final_selected,
        "routingReasons": reasons,
        "skippedAgents": skipped,
        "riskTriggers": risk_triggers,
    }
