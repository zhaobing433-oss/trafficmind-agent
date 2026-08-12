"""
多 Agent 协同研判模块
--------------------
子 Agent：CongestionAgent / AccidentAgent / SignalAgent / DispatchAgent / ReportAgent
每个 Agent 独立分析，最终汇总为 finalDecision。
"""

from typing import Dict, Any, List, Optional
from datetime import datetime


def _get_event_info(event: Dict[str, Any]) -> Dict[str, Any]:
    se = event.get("standardEvent", event)
    def _safe_float(key, default=0.0):
        v = se.get(key)
        if v is None:
            return None
        try: return float(v)
        except (ValueError, TypeError): return default
    return {
        "eventType": se.get("eventTypeCn", se.get("eventType", "")),
        "roadName": se.get("roadName", ""),
        "direction": se.get("direction", ""),
        "avgSpeed": _safe_float("avgSpeed"),
        "queueLength": _safe_float("queueLength"),
        "duration": _safe_float("duration", 0),
        "weather": se.get("weather", "clear"),
        "timePeriod": se.get("timePeriod", "off_peak"),
        "isMainRoad": bool(se.get("isMainRoad", False)),
        "nearbySchool": bool(se.get("nearbySchool", False)),
        "nearbyHospital": bool(se.get("nearbyHospital", False)),
        "pedestrianRisk": se.get("pedestrianRisk", "low"),
        "signalOptimizationRequested": se.get("signalOptimizationRequested", False),
        "conflictIntent": se.get("conflictIntent", False),
        "riskLevel": se.get("riskLevel", event.get("riskLevel", "")),
        "riskScore": se.get("riskScore", event.get("riskScore", 0)),
    }


class CongestionAgent:
    """拥堵研判 Agent — Phase 13: 支持 Simulation Context"""

    def analyze(self, info: Dict[str, Any]) -> Dict[str, Any]:
        findings: list = []
        urgency = "low"
        proposed_actions: list = []
        evidence_refs: list = []
        spd = info.get("avgSpeed")
        qlen = info.get("queueLength")
        sim_ctx = info.get("simulation_context")

        if spd is not None and spd < 10:
            findings.append(f"平均车速仅 {spd} km/h，严重拥堵"); urgency = "high"
        elif spd is not None and spd < 20:
            findings.append(f"平均车速 {spd} km/h，缓行状态")
        elif spd is None:
            findings.append("未提供具体车速数据，无法精确评估拥堵程度")

        if qlen is not None and qlen > 200:
            findings.append(f"排队 {qlen}m，建议上游分流"); urgency = "high"
        elif qlen is not None and qlen > 100:
            findings.append(f"排队 {qlen}m，关注蔓延趋势")
        elif qlen is None:
            findings.append("未提供具体排队长度数据")

        if info.get("timePeriod") in ("morning_peak", "evening_peak"):
            findings.append("高峰时段，建议调整信号配时")
        if info.get("isMainRoad"): findings.append("主干道，影响范围广")
        if info.get("nearbySchool"): findings.append("邻近学校，需关注行人安全")
        if info.get("pedestrianRisk") == "high": findings.append("存在行人/学生横穿风险")

        # Phase 13: Simulation Spatial Context → ActionProposal
        if sim_ctx and isinstance(sim_ctx, dict):
            affected = sim_ctx.get("affectedRoad") or {}
            traffic = sim_ctx.get("currentTrafficState") or {}
            upstream = sim_ctx.get("upstreamRoads") or []
            sim_refs = info.get("simulation_refs") or {}

            # 证据引用
            evidence_refs.append({
                "type": "spatial_context",
                "simulationRunId": sim_refs.get("simulationRunId"),
                "snapshotId": sim_refs.get("decisionSnapshotId"),
            })

            # 拥堵严重时生成分流提议
            if urgency == "high" and upstream:
                affected_road_id = affected.get("roadId", "")
                upstream_ids = [r.get("roadId", "") for r in upstream[:2] if r.get("roadId")]
                if affected_road_id and upstream_ids:
                    proposed_actions.append({
                        "actionType": "traffic_diversion",
                        "sourceRoadId": affected_road_id,
                        "targetRoadIds": upstream_ids,
                        "diversionRatio": 0.35,
                        "simulation": True,
                        "rationale": (
                            f"{affected.get('name', affected_road_id)}严重拥堵"
                            f"(speed={spd}km/h, queue={qlen}m)，"
                            f"建议分流至{len(upstream_ids)}条上游道路"
                        ),
                        "evidenceRefs": [
                            "spatial_context",
                            "current_traffic_state",
                        ],
                    })
                    findings.append(
                        f"基于仿真空间上下文生成分流建议: "
                        f"{affected_road_id}→{', '.join(upstream_ids)}"
                    )

        return {
            "agentName": "CongestionAgent",
            "relevant": (
                info.get("eventType") in ("拥堵", "congestion")
                or (spd is not None and spd < 15)
            ),
            "findings": findings,
            "urgency": urgency,
            "suggestion": "通知交警+信号中心，上游分流" if findings else "正常监控",
            "proposed_actions": proposed_actions,
            "evidence_refs": evidence_refs,
            "simulation_refs": info.get("simulation_refs", {}),
        }


class AccidentAgent:
    """事故研判 Agent"""
    def analyze(self, info: Dict[str, Any]) -> Dict[str, Any]:
        findings = []; urgency = "low"
        if info["riskLevel"] in ("高风险", "重大风险"):
            findings.append(f"风险 {info['riskLevel']}，需多部门联动"); urgency = "critical"
        if int(info["duration"] / 60) > 30:
            findings.append(f"已持续 {int(info['duration']/60)}min，建议优先清障"); urgency = "high"
        if info["nearbyHospital"]: findings.append("邻近医院，保障急救通道")
        return {"agentName": "AccidentAgent",
                "relevant": info["eventType"] in ("事故", "accident") or info["riskLevel"] in ("高风险", "重大风险"),
                "findings": findings, "urgency": urgency,
                "suggestion": "通知122+120，拖车清障" if findings else "持续监测"}


class SignalAgent:
    """信号灯分析 Agent"""
    def analyze(self, info: Dict[str, Any]) -> Dict[str, Any]:
        findings = []; urgency = "low"
        if info["eventType"] in ("信号灯异常", "signal_fault"):
            findings.append("信号灯异常，通知运维单位检修"); urgency = "high"
        spd = info["avgSpeed"]
        if info["eventType"] in ("拥堵", "congestion") and spd is not None and spd < 10 and info["isMainRoad"]:
            findings.append(f"建议 {info['roadName']} 上游路口加大绿信比")
            if urgency != "high": urgency = "medium"
        if info.get("signalOptimizationRequested"):
            findings.append("检测到信号优化需求，建议分析信号周期资源分配")
            if urgency != "high": urgency = "high"
        if info.get("conflictIntent"):
            findings.append("存在信号资源竞争，需与其他Agent协调")
        return {"agentName": "SignalAgent",
                "relevant": info["eventType"] in ("信号灯异常", "signal_fault", "拥堵", "congestion") or info.get("signalOptimizationRequested"),
                "findings": findings if findings else ["信号系统正常"],
                "urgency": urgency,
                "suggestion": "通知信号运维单位" if findings else "无需干预"}


class DispatchAgent:
    """调度 Agent"""
    def analyze(self, info: Dict[str, Any]) -> Dict[str, Any]:
        departments = {"拥堵": ["交警大队", "信号控制中心", "交通广播中心"],
            "事故": ["122事故处理中心", "120急救中心", "交警大队", "拖车公司"],
            "违停": ["交警大队", "交通指挥中心"], "逆行": ["交警大队", "高速交警", "122指挥中心"],
            "行人闯入": ["交警大队", "高速交警", "辖区派出所"],
            "信号灯异常": ["信号灯运维单位", "交警大队", "市政部门"],
            "车辆滞留": ["交警大队", "道路救援", "拖车公司"],
            "施工占道": ["交警大队", "市政部门", "路政部门"]}
        deps = departments.get(info["eventType"], ["交警大队", "指挥中心"])
        notes = []
        if info["riskLevel"] in ("高风险", "重大风险"): notes.append("高风险，优先派单30min响应")
        if info["nearbySchool"]: notes.append("邻近学校，注意学生安全")
        if info["nearbyHospital"]: notes.append("邻近医院，保障急救通道")
        return {"agentName": "DispatchAgent", "relevant": True, "findings": notes,
                "urgency": "high" if info["riskLevel"] in ("高风险", "重大风险") else "medium",
                "suggestion": f"联动部门：{'、'.join(deps)}"}


class ReportAgent:
    """报告整合 Agent"""
    def summarize(self, agent_results, info):
        urgency_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        max_urgency, max_score = "low", 1
        findings, suggestions = [], []
        for r in agent_results:
            findings.extend(r.get("findings", []))
            score = urgency_order.get(r.get("urgency", "low"), 1)
            if score > max_score: max_score, max_urgency = score, r.get("urgency", "low")
            if r.get("suggestion"): suggestions.append(r["suggestion"])
        return {"summary": f"共 {len(agent_results)} 个 Agent 参与，紧急度：{max_urgency}",
                "allFindings": findings, "urgency": max_urgency, "suggestions": suggestions}


def multi_agent_analyze(raw_event: Dict[str, Any]) -> Dict[str, Any]:
    info = _get_event_info(raw_event)
    agents = [CongestionAgent(), AccidentAgent(), SignalAgent(), DispatchAgent()]
    agent_results = [a.analyze(info) for a in agents]
    summary = ReportAgent().summarize(agent_results, info)
    risk_warnings = []
    if info["riskLevel"] == "重大风险": risk_warnings.append("重大风险，立即启动应急预案")
    if info["weather"] in ("rain", "snow", "fog"): risk_warnings.append(f"{info['weather']}天，注意安全")
    if info["duration"] > 900: risk_warnings.append("持续>15min，注意次生事故")
    return {"eventSummary": {"eventType": info["eventType"], "roadName": info["roadName"],
            "direction": info["direction"], "riskLevel": info.get("riskLevel", ""),
            "riskScore": info.get("riskScore", 0),
            "analyzedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            "agentResults": agent_results,
            "finalDecision": summary["summary"],
            "dispatchPlan": {"urgency": summary["urgency"], "actions": summary["suggestions"]},
            "riskWarnings": risk_warnings,
            "report": _build_multi_agent_report(info, agent_results, summary, risk_warnings)}


def _build_multi_agent_report(info, results, summary, warnings):
    lines = ["=" * 50, "   TrafficMind Agent 多 Agent 协同研判报告", "=" * 50, "",
             f"事件类型：{info['eventType']}", f"路段：{info['roadName']}",
             f"风险：{info.get('riskLevel', '')} ({info.get('riskScore', 0)}分)", "", "各子 Agent 研判："]
    for r in results:
        lines.append(f"\n  [{r['agentName']}] 紧急度: {r['urgency']}")
        for f in r.get("findings", []): lines.append(f"    - {f}")
    lines += ["", f"综合：{summary['summary']}", "", "风险警告："]
    for w in warnings: lines.append(f"  - {w}")
    if not warnings: lines.append("  无特殊警告")
    lines += ["", "=" * 50]
    return "\n".join(lines)
