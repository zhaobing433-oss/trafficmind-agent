"""
协作专用 Agent — Phase 9.3
dispatch / conflict_detector / conflict_arbiter / fusion
"""
from typing import Any, Dict, List


ERROR_CODES = {
    "COLLAB_VALIDATION_ERROR": "输入校验失败",
    "COLLAB_AGENT_NOT_REGISTERED": "Agent 未注册",
    "COLLAB_REQUIRED_FIELD_MISSING": "缺少必要字段",
    "COLLAB_TASK_TIMEOUT": "任务超时",
    "COLLAB_TASK_RETRY_EXHAUSTED": "重试次数耗尽",
    "COLLAB_BUDGET_EXCEEDED": "预算超限",
    "COLLAB_ILLEGAL_STATE_TRANSITION": "非法状态转换",
    "COLLAB_ARBITRATION_REQUIRED": "需要人工仲裁",
    "COLLAB_FUSION_FAILED": "融合失败",
    "COLLAB_REPOSITORY_ERROR": "存储错误",
    "COLLAB_INTERNAL_ERROR": "内部错误",
}


def dispatch_agent(domain_results: Dict[str, Any], event_info: Dict[str, Any]) -> Dict[str, Any]:
    """DispatchAgent: 读取领域结果，制定处置方案。不重复执行领域分析。"""
    suggestions = []
    for name, r in domain_results.items():
        if r.get("suggestion"):
            suggestions.append(f"[{name}] {r['suggestion']}")

    actions = []
    if event_info.get("isMainRoad"): actions.append({"action": "主干道优先处置", "priority": 1, "unit": "交警大队"})
    if event_info.get("nearbyHospital"): actions.append({"action": "保障急救通道", "priority": 1, "unit": "交警大队+医院"})
    if event_info.get("nearbySchool"): actions.append({"action": "注意学生安全，必要时通知校方", "priority": 2, "unit": "交警大队"})
    road = event_info.get("roadName", "未知路段")
    actions.append({"action": f"安排{road}现场疏导", "priority": 2 if actions else 1, "unit": "交警大队"})

    return {
        "dispatch_actions": actions,
        "action_priority": min((a["priority"] for a in actions), default=3),
        "responsible_units": list(set(a["unit"] for a in actions)),
        "expected_effect": "缓解交通压力，保障安全",
        "dependencies": list(domain_results.keys()),
        "confidence": 0.75,
        "suggestion": "；".join(suggestions) if suggestions else "按常规流程处置",
    }


def conflict_detector(agent_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """ConflictDetector: 比较结构化 proposals，检测冲突。无冲突返回空列表。"""
    conflicts = []
    proposals = []

    for r in agent_results:
        if r.get("suggestion"):
            proposals.append({"agent": r.get("agent_name", ""), "suggestion": r["suggestion"], "findings": r.get("findings", [])})

    # strategy conflict: signal optimization vs safety
    signal = next((r for r in agent_results if r.get("agent_name") == "SignalAgent"), None)
    safety = next((r for r in agent_results if r.get("agent_name") == "PublicSafetyAgent"), None)
    if signal and safety:
        sig_sug = signal.get("suggestion", "")
        saf_sug = safety.get("suggestion", "")
        if ("信号" in sig_sug or "配时" in sig_sug) and ("安全" in saf_sug or "医院" in saf_sug or "学校" in saf_sug):
            conflicts.append({"id": f"conflict_signal_safety", "type": "strategy_conflict",
                "description": "信号优化建议与公共安全需求存在潜在冲突",
                "participants": ["SignalAgent", "PublicSafetyAgent"], "proposals": proposals,
                "severity": "medium", "status": "open", "requires_human_review": False})

    return conflicts


def conflict_arbiter(conflict: Dict[str, Any]) -> Dict[str, Any]:
    """ConflictArbiter: 规则优先，规则不足时 requires_human_review。"""
    if conflict.get("type") == "strategy_conflict" and conflict.get("severity") in ("low", "medium"):
        return {"conflict_id": conflict.get("id", ""), "resolved": True,
                "resolution": "安全优先：在保障行人/急救通行的前提下实施信号优化",
                "reasoning": "安全优先级高于通行效率", "requires_human_review": False}
    if conflict.get("severity") == "high":
        return {"conflict_id": conflict.get("id", ""), "resolved": False,
                "resolution": "高风险冲突需要人工研判",
                "reasoning": "证据不足以自动裁决", "requires_human_review": True}
    return {"conflict_id": conflict.get("id", ""), "resolved": True,
            "resolution": "已按默认规则融合", "reasoning": "低风险冲突可自动解决", "requires_human_review": False}


def fusion_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """FusionAgent: 只读取完成结果，不增加无来源新事实。"""
    task_results = state.get("task_results", {})
    conflicts = state.get("conflicts", [])
    failed = state.get("failed_agents", [])

    resolved = [c for c in conflicts if c.get("resolved")]
    unresolved = [c for c in conflicts if not c.get("resolved")]

    action_plan = []
    for name, r in task_results.items():
        if r.get("suggestion"):
            action_plan.append(f"[{name}] {r['suggestion']}")

    core_risk = "高" if len(failed) > 1 else "中" if failed else "待评估"
    summary = f"综合 {len(task_results)} 个 Agent 分析"
    if resolved: summary += f"，{len(resolved)} 个冲突已解决"
    if unresolved: summary += f"，{len(unresolved)} 个冲突需要人工关注"
    if failed: summary += f"，{len(failed)} 个 Agent 未能完成"
    summary += "。"

    return {
        "core_risk": core_risk,
        "consensus": "各 Agent 建议无原则性矛盾" if not conflicts else "部分建议经融合已协调",
        "resolved_conflicts": len(resolved),
        "unresolved_conflicts": len(unresolved),
        "action_plan": action_plan,
        "monitoring_indicators": ["avgSpeed", "queueLength", "duration"],
        "limitations": failed or [],
        "confidence": 0.7 if not failed else 0.5,
        "requires_human_review": len(unresolved) > 0,
        "fusion_summary": summary,
    }
