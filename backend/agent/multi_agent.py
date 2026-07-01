"""
多 Agent 协同研判模块
--------------------
子 Agent：CongestionAgent / AccidentAgent / SignalAgent / DispatchAgent / ReportAgent
每个 Agent 独立分析，最终汇总为 finalDecision。
"""

from typing import Dict, Any, List, Optional
from datetime import datetime


def _get_event_info(event: Dict[str, Any]) -> Dict[str, Any]:
    """从事件字典中安全提取信息。"""
    se = event.get("standardEvent", event)
    return {
        "eventType": se.get("eventTypeCn", se.get("eventType", "")),
        "eventTypeRaw": se.get("eventType", ""),
        "roadName": se.get("roadName", ""),
        "direction": se.get("direction", ""),
        "avgSpeed": float(se.get("avgSpeed", 0)),
        "queueLength": float(se.get("queueLength", 0)),
        "duration": float(se.get("duration", 0)),
        "weather": se.get("weather", "clear"),
        "timePeriod": se.get("timePeriod", "off_peak"),
        "isMainRoad": bool(se.get("isMainRoad", False)),
        "nearbySchool": bool(se.get("nearbySchool", False)),
        "nearbyHospital": bool(se.get("nearbyHospital", False)),
        "riskLevel": se.get("riskLevel", event.get("riskLevel", "")),
        "riskScore": se.get("riskScore", event.get("riskScore", 0)),
    }


# ==================== 子 Agent ====================

class CongestionAgent:
    """拥堵研判 Agent — 关注速度、排队、时段、主干道。"""

    def analyze(self, info: Dict[str, Any]) -> Dict[str, Any]:
        findings = []
        urgency = "low"

        if info["avgSpeed"] < 10:
            findings.append(f"平均车速仅 {info['avgSpeed']} km/h，属于严重拥堵等级")
            urgency = "high"
        elif info["avgSpeed"] < 20:
            findings.append(f"平均车速 {info['avgSpeed']} km/h，缓行状态")

        if info["queueLength"] > 200:
            findings.append(f"排队长度 {info['queueLength']} 米，拥堵范围大，建议上游分流")
            urgency = "high"
        elif info["queueLength"] > 100:
            findings.append(f"排队长度 {info['queueLength']} 米，需关注蔓延趋势")

        if info["timePeriod"] in ("morning_peak", "evening_peak"):
            findings.append("发生在高峰时段，建议调整信号配时增加绿信比")

        if info["isMainRoad"]:
            findings.append("事发为主干道，影响范围广，建议优先处置")

        return {
            "agentName": "CongestionAgent",
            "relevant": info["eventType"] in ("拥堵", "congestion") or info["avgSpeed"] < 15,
            "findings": findings,
            "urgency": urgency,
            "suggestion": "建议通知交警大队和信号控制中心，上游路口实施分流" if findings else "正常监控",
        }


class AccidentAgent:
    """事故研判 Agent — 关注风险等级、持续时间、联动需求。"""

    def analyze(self, info: Dict[str, Any]) -> Dict[str, Any]:
        findings = []
        urgency = "low"

        if info["riskLevel"] in ("高风险", "重大风险"):
            findings.append(f"风险等级为 {info['riskLevel']}，需要多部门联动响应")
            urgency = "critical"

        duration_min = int(info["duration"] / 60)
        if duration_min > 30:
            findings.append(f"已持续 {duration_min} 分钟，建议优先清理恢复通行")
            urgency = "high"

        if info["nearbyHospital"]:
            findings.append("事发路段邻近医院，需保障急救通道畅通")

        return {
            "agentName": "AccidentAgent",
            "relevant": info["eventType"] in ("事故", "accident") or info["riskLevel"] in ("高风险", "重大风险"),
            "findings": findings,
            "urgency": urgency,
            "suggestion": "建议通知122事故中心和120急救中心，安排拖车快速清障" if findings else "持续监测",
        }


class SignalAgent:
    """信号灯分析 Agent — 关注信号灯异常和信号优化建议。"""

    def analyze(self, info: Dict[str, Any]) -> Dict[str, Any]:
        findings = []
        urgency = "low"

        if info["eventType"] in ("信号灯异常", "signal_fault"):
            findings.append("信号灯运行异常，需通知运维单位立即检修")
            urgency = "high"

        # 拥堵场景下的信号优化建议
        if info["eventType"] in ("拥堵", "congestion") and info["avgSpeed"] < 10 and info["isMainRoad"]:
            findings.append(f"建议调整 {info['roadName']} 上游路口信号配时，加大绿信比")
            if urgency != "high":
                urgency = "medium"

        return {
            "agentName": "SignalAgent",
            "relevant": info["eventType"] in ("信号灯异常", "signal_fault", "拥堵", "congestion"),
            "findings": findings if findings else ["信号系统运行正常"],
            "urgency": urgency,
            "suggestion": "通知信号运维单位" if findings else "信号系统无需干预",
        }


class DispatchAgent:
    """调度 Agent — 生成联动部门和调度话术。"""

    def analyze(self, info: Dict[str, Any]) -> Dict[str, Any]:
        departments = []
        dispatch_notes = []

        # 根据事件类型推荐联动部门
        type_department_map = {
            "拥堵": ["交警大队", "信号控制中心", "交通广播中心"],
            "事故": ["122事故处理中心", "120急救中心", "交警大队", "拖车公司"],
            "违停": ["交警大队", "交通指挥中心"],
            "逆行": ["交警大队", "高速交警", "122指挥中心"],
            "行人闯入": ["交警大队", "高速交警", "辖区派出所"],
            "信号灯异常": ["信号灯运维单位", "交警大队", "市政部门"],
            "车辆滞留": ["交警大队", "道路救援", "拖车公司"],
            "施工占道": ["交警大队", "市政部门", "路政部门"],
        }

        event_type_cn = info["eventType"]
        departments = type_department_map.get(event_type_cn, ["交警大队", "指挥中心"])

        if info["riskLevel"] in ("高风险", "重大风险"):
            dispatch_notes.append("高风险事件，建议优先派单，30分钟内响应")

        if info["nearbySchool"]:
            dispatch_notes.append("邻近学校，注意学生安全，必要时通知校方")
        if info["nearbyHospital"]:
            dispatch_notes.append("邻近医院，保障急救通道")

        return {
            "agentName": "DispatchAgent",
            "relevant": True,
            "findings": dispatch_notes,
            "urgency": "high" if info["riskLevel"] in ("高风险", "重大风险") else "medium",
            "suggestion": f"联动部门：{'、'.join(departments)}",
        }


class ReportAgent:
    """报告整合 Agent — 汇总各子 Agent 结果生成最终报告。"""

    def summarize(self, agent_results: List[Dict[str, Any]], info: Dict[str, Any]) -> Dict[str, Any]:
        # 合并所有发现
        all_findings = []
        for r in agent_results:
            all_findings.extend(r.get("findings", []))

        # 确定最高紧急度
        urgency_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        max_urgency = "low"
        max_score = 1
        for r in agent_results:
            score = urgency_order.get(r.get("urgency", "low"), 1)
            if score > max_score:
                max_score = score
                max_urgency = r.get("urgency", "low")

        # 汇总建议
        suggestions = []
        for r in agent_results:
            if r.get("suggestion"):
                suggestions.append(r["suggestion"])

        return {
            "summary": f"共 {len(agent_results)} 个子 Agent 参与研判，紧急度：{max_urgency}",
            "allFindings": all_findings,
            "urgency": max_urgency,
            "suggestions": suggestions,
        }


# ==================== 主入口 ====================

def multi_agent_analyze(raw_event: Dict[str, Any]) -> Dict[str, Any]:
    """
    多 Agent 协同研判主入口。

    Args:
        raw_event: 原始交通事件 JSON

    Returns:
        研判结果字典
    """
    info = _get_event_info(raw_event)

    # 初始化子 Agent
    agents = [
        CongestionAgent(),
        AccidentAgent(),
        SignalAgent(),
        DispatchAgent(),
    ]

    # 各 Agent 独立分析
    agent_results = []
    for agent in agents:
        result = agent.analyze(info)
        agent_results.append(result)

    # ReportAgent 汇总
    reporter = ReportAgent()
    summary = reporter.summarize(agent_results, info)

    # 风险警告
    risk_warnings = []
    if info["riskLevel"] == "重大风险":
        risk_warnings.append("重大风险事件，需要立即启动应急预案")
    if info["weather"] in ("rain", "snow", "fog"):
        weather_cn = {"rain": "雨", "snow": "雪", "fog": "雾"}.get(info["weather"], info["weather"])
        risk_warnings.append(f"{weather_cn}天出行，注意路面湿滑和能见度下降")
    if info["duration"] > 900:
        risk_warnings.append("事件持续时间超过15分钟，注意次生事故风险")

    return {
        "eventSummary": {
            "eventType": info["eventType"],
            "roadName": info["roadName"],
            "direction": info["direction"],
            "riskLevel": info.get("riskLevel", ""),
            "riskScore": info.get("riskScore", 0),
            "analyzedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "agentResults": agent_results,
        "finalDecision": summary["summary"],
        "dispatchPlan": {
            "urgency": summary["urgency"],
            "actions": summary["suggestions"],
        },
        "riskWarnings": risk_warnings,
        "report": _build_multi_agent_report(info, agent_results, summary, risk_warnings),
    }


def _build_multi_agent_report(info, agent_results, summary, warnings) -> str:
    """生成多 Agent 协同研判报告文本。"""
    lines = [
        "=" * 50,
        "   TrafficMind Agent 多 Agent 协同研判报告",
        "=" * 50,
        "",
        f"事件类型：{info['eventType']}",
        f"事发路段：{info['roadName']} {info.get('direction', '')}",
        f"风险等级：{info.get('riskLevel', '')} ({info.get('riskScore', 0)}分)",
        "",
        "各子 Agent 研判结果：",
    ]

    for r in agent_results:
        status = "参与" if r.get("relevant") else "跳过"
        lines.append(f"\n  [{r['agentName']}] {status} | 紧急度: {r['urgency']}")
        for f in r.get("findings", []):
            lines.append(f"    - {f}")

    lines += [
        "",
        f"综合研判：{summary['summary']}",
        "",
        "风险警告：",
    ]
    for w in warnings:
        lines.append(f"  - {w}")
    if not warnings:
        lines.append("  无特殊警告")

    lines += ["", "=" * 50]
    return "\n".join(lines)
