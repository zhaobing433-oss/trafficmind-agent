"""
Agent 冲突检测与融合
------------------
检测不同 Agent 建议之间的冲突，生成融合方案。

冲突类型：
1. 信号优化 vs 急救通道保障
2. 分流建议 vs 事故现场封控
3. 绿信比调整 vs 行人过街保障
4. 快速放行 vs 封控保护
"""

from typing import Dict, Any, List, Optional


# 冲突检测规则
CONFLICT_RULES = [
    {
        "type": "signal_vs_emergency",
        "description": "信号优化建议与急救通道保障冲突",
        "agents": ["SignalAgent", "PublicSafetyAgent"],
        "check": lambda results: _check_signal_vs_emergency(results),
        "severity": "high",
    },
    {
        "type": "diversion_vs_closure",
        "description": "分流建议与事故现场封控冲突",
        "agents": ["CongestionAgent", "AccidentAgent"],
        "check": lambda results: _check_diversion_vs_closure(results),
        "severity": "critical",
    },
    {
        "type": "green_wave_vs_pedestrian",
        "description": "绿信比延长与行人过街保障冲突",
        "agents": ["SignalAgent", "PublicSafetyAgent"],
        "check": lambda results: _check_green_wave_vs_pedestrian(results),
        "severity": "medium",
    },
    {
        "type": "release_vs_protect",
        "description": "快速放行与现场保护冲突",
        "agents": ["DispatchAgent", "AccidentAgent"],
        "check": lambda results: _check_release_vs_protect(results),
        "severity": "high",
    },
]


def _find_agent_result(agent_results: List[Dict], agent_name: str) -> Optional[Dict]:
    """从结果列表中查找指定 Agent 的结果。"""
    for r in agent_results:
        if r.get("agentName") == agent_name:
            return r
    return None


def _check_signal_vs_emergency(results: List[Dict]) -> Optional[Dict]:
    """检测信号优化 vs 急救通道冲突。"""
    signal = _find_agent_result(results, "SignalAgent")
    safety = _find_agent_result(results, "PublicSafetyAgent")
    if not signal or not safety:
        return None
    sig_findings = " ".join(signal.get("findings", []))
    saf_findings = " ".join(safety.get("findings", []))
    if ("信号配时" in sig_findings or "绿信比" in sig_findings) and ("医院" in saf_findings or "急救" in saf_findings):
        return {
            "type": "signal_vs_emergency",
            "description": "SignalAgent 建议调整信号配时，但 PublicSafetyAgent 提醒保障医院急救通道。这两者可能冲突：绿信比调整可能影响急救车辆通行。",
            "agents": ["SignalAgent", "PublicSafetyAgent"],
            "severity": "high",
            "resolution": "优先保障急救通道方向绿信比，在确认急救车辆可通行的前提下进行信号优化。",
        }
    return None


def _check_diversion_vs_closure(results: List[Dict]) -> Optional[Dict]:
    """检测分流 vs 封控冲突。"""
    congestion = _find_agent_result(results, "CongestionAgent")
    accident = _find_agent_result(results, "AccidentAgent")
    if not congestion or not accident:
        return None
    cong_findings = " ".join(congestion.get("findings", []))
    acc_findings = " ".join(accident.get("findings", []))
    if "分流" in cong_findings and ("封控" in acc_findings or "事故" in acc_findings or "警戒" in acc_findings):
        return {
            "type": "diversion_vs_closure",
            "description": "CongestionAgent 建议分流，但 AccidentAgent 可能需要现场封控。不能把车辆导向事故区域。",
            "agents": ["CongestionAgent", "AccidentAgent"],
            "severity": "critical",
            "resolution": "在事故区域外设置分流点，确保分流路线绕开事故核心区。优先保障事故处置，再实施外围分流。",
        }
    return None


def _check_green_wave_vs_pedestrian(results: List[Dict]) -> Optional[Dict]:
    """检测绿信比 vs 行人过街冲突。"""
    signal = _find_agent_result(results, "SignalAgent")
    safety = _find_agent_result(results, "PublicSafetyAgent")
    if not signal or not safety:
        return None
    sig_findings = " ".join(signal.get("findings", []))
    saf_findings = " ".join(safety.get("findings", []))
    if ("绿信比" in sig_findings or "绿灯" in sig_findings) and ("学校" in saf_findings or "行人" in saf_findings or "过街" in saf_findings):
        return {
            "type": "green_wave_vs_pedestrian",
            "description": "SignalAgent 建议延长主路绿灯，但 PublicSafetyAgent 提醒学校/行人过街需求。延长绿灯可能压缩行人过街时间。",
            "agents": ["SignalAgent", "PublicSafetyAgent"],
            "severity": "medium",
            "resolution": "在保障行人最小过街时间（通常20秒）的前提下适度延长绿灯。放学时段优先行人通行。",
        }
    return None


def _check_release_vs_protect(results: List[Dict]) -> Optional[Dict]:
    """检测快速放行 vs 现场保护冲突。"""
    dispatch = _find_agent_result(results, "DispatchAgent")
    accident = _find_agent_result(results, "AccidentAgent")
    if not dispatch or not accident:
        return None
    disp_findings = " ".join(dispatch.get("findings", []))
    acc_findings = " ".join(accident.get("findings", []))
    if ("快速" in disp_findings or "放行" in disp_findings) and ("重大风险" in acc_findings or "封控" in acc_findings):
        return {
            "type": "release_vs_protect",
            "description": "DispatchAgent 建议快速恢复通行，但 AccidentAgent 判断为重大风险需保护现场。",
            "agents": ["DispatchAgent", "AccidentAgent"],
            "severity": "high",
            "resolution": "重大风险事件优先保护现场和人员安全。待事故勘查完成后实施快速清障恢复通行。",
        }
    return None


def detect_conflicts(agent_results: List[Dict]) -> List[Dict]:
    """
    检测 Agent 建议之间的冲突。

    Args:
        agent_results: 各 Agent 的研判结果列表

    Returns:
        冲突条���列表
    """
    conflicts = []
    for rule in CONFLICT_RULES:
        result = rule["check"](agent_results)
        if result:
            conflicts.append(result)
    return conflicts


def resolve_conflicts(conflicts: List[Dict], agent_results: List[Dict], event_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    融合冲突、生成融合后的处置方案。

    Args:
        conflicts: 检测到的冲突列表
        agent_results: 各 Agent 研判结果
        event_info: 事件信息

    Returns:
        融合结果
    """
    risk_warnings = []
    for c in conflicts:
        risk_warnings.append(f"[{c['severity'].upper()}] {c['description']} → 融合方案: {c['resolution']}")

    # 提取最终决策
    urgency_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    max_urgency = "low"
    max_score = 1
    for r in agent_results:
        score = urgency_order.get(r.get("urgency", "low"), 1)
        if score > max_score:
            max_score = score
            max_urgency = r.get("urgency", "low")

    # 如果存在冲突，将紧急度提升一级
    if conflicts:
        levels = ["low", "medium", "high", "critical"]
        idx = levels.index(max_urgency)
        if idx < len(levels) - 1:
            max_urgency = levels[idx + 1]

    # 合成 resolvedPlan
    resolved_plan = {
        "conflictCount": len(conflicts),
        "resolved": len(conflicts) == 0,
        "urgency": max_urgency,
        "mergedSuggestions": _merge_suggestions(agent_results, conflicts),
    }

    return {
        "conflicts": conflicts,
        "conflictCount": len(conflicts),
        "resolvedPlan": resolved_plan,
        "riskWarnings": risk_warnings,
        "finalDecision": f"共 {len(agent_results)} 个 Agent 参与，检测到 {len(conflicts)} 个建议冲突（已融合），综合紧急度：{max_urgency}",
    }


def _merge_suggestions(agent_results: List[Dict], conflicts: List[Dict]) -> List[str]:
    """合并各 Agent 建议，考虑冲突融合。"""
    conflict_types = {c["type"] for c in conflicts}
    suggestions = []

    # 常规建议
    for r in agent_results:
        if r.get("suggestion"):
            suggestions.append(f"[{r.get('agentName', '')}] {r['suggestion']}")

    # 冲突融合建议
    for c in conflicts:
        if c.get("resolution"):
            suggestions.append(f"[ConflictResolver] {c['resolution']}")

    return suggestions
