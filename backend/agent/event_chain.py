"""
事件驱动链式协同
---------------
让 Agent 之间通过规则触发链式调用——不是自由对话，而是"如果发现 A，则触发 B"。

触发规则：
1. CongestionAgent 发现 queueLength>200 且 avgSpeed<10 → 触发 SignalAgent
2. AccidentAgent 发现 riskLevel=重大风险 → 触发 DispatchAgent
3. SignalAgent 发现信号异常 → 触发 DispatchAgent
4. 任意 Agent 发现 nearbyHospital=true → 触发 PublicSafetyAgent
"""

from typing import Dict, Any, List, Optional

from backend.tools.event_tools import safe_float


# 触发规则表（数值判断均经 safe_float 处理 None/非法值，不抛 TypeError）
TRIGGER_RULES = [
    {
        "name": "congestion_to_signal",
        "sourceAgent": "CongestionAgent",
        "check": lambda info, result: (
            safe_float(info.get("queueLength"), 0.0) > 200 and
            safe_float(info.get("avgSpeed"), 99.0) < 10 and
            info.get("isMainRoad", False)
        ),
        "targetAgent": "SignalAgent",
        "reason": "排队长度超过200米且均速低于10km/h的主干道拥堵，需信号配时优化",
    },
    {
        "name": "accident_to_dispatch",
        "sourceAgent": "AccidentAgent",
        "check": lambda info, result: (
            info.get("riskLevel", "") == "重大风险" and
            safe_float(info.get("duration"), 0.0) > 600
        ),
        "targetAgent": "DispatchAgent",
        "reason": "重大风险事故持续超过10分钟，需优先联动多部门",
    },
    {
        "name": "signal_abnormal_to_dispatch",
        "sourceAgent": "SignalAgent",
        "check": lambda info, result: (
            info.get("eventTypeCn", info.get("eventType", "")) in ("信号灯异常", "signal_fault")
        ),
        "targetAgent": "DispatchAgent",
        "reason": "信号灯异常事件，需通知运维单位和交警现场指挥",
    },
    {
        "name": "any_to_public_safety",
        "sourceAgent": "*",
        "check": lambda info, result: (
            bool(info.get("nearbyHospital", False)) or bool(info.get("nearbySchool", False))
        ),
        "targetAgent": "PublicSafetyAgent",
        "reason": "邻近医院或学校，需附加公共安全评估",
    },
    {
        "name": "weather_to_all",
        "sourceAgent": "*",
        "check": lambda info, result: (
            info.get("weather", "clear") in ("rain", "snow", "fog")
        ),
        "targetAgent": "DispatchAgent",
        "reason": "恶劣天气条件，建议 DispatchAgent 关注安全警告",
    },
]


def _get_single_agent_result(agent_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """获取单个 Agent 的分析结果（用于链中触发目标 Agent）。"""
    from backend.agent.multi_agent import CongestionAgent, AccidentAgent, SignalAgent, DispatchAgent

    agent_map = {
        "CongestionAgent": CongestionAgent,
        "AccidentAgent": AccidentAgent,
        "SignalAgent": SignalAgent,
        "DispatchAgent": DispatchAgent,
    }

    cls = agent_map.get(agent_name)
    if cls is None:
        return {"agentName": agent_name, "findings": ["Agent 未注册"], "urgency": "low", "suggestion": ""}

    instance = cls()
    return instance.analyze(info)


def build_event_chain(
    event_info: Dict[str, Any],
    initial_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    根据初始 Agent 结果和触发规则，构建事件驱动的链式调用序列。

    Args:
        event_info: 事件信息字典
        initial_results: 初始 Agent 分析结果列表

    Returns:
        EventChainResult 结构
    """
    chain_steps: List[Dict] = []
    trigger_reasons: List[str] = []
    triggered_agents: set = set()
    all_results: List[Dict] = list(initial_results)
    warnings: List[str] = []

    # 遍历触发规则
    for rule in TRIGGER_RULES:
        source_agent = rule["sourceAgent"]
        target_agent = rule["targetAgent"]

        # 跳过已经触发的（避免重复）
        if target_agent in triggered_agents:
            continue

        # 查找源 Agent 的结果
        source_result = None
        for r in initial_results:
            if source_agent == "*" or r.get("agentName") == source_agent:
                source_result = r
                if rule["check"](event_info, r):
                    break

        source_to_check = source_result if source_result else {}
        if source_agent == "*":
            source_to_check = initial_results[0] if initial_results else {}

        # 检查触发条件
        if rule["check"](event_info, source_to_check):
            trigger_reasons.append(rule["reason"])

            # 执行目标 Agent
            target_result = _get_single_agent_result(target_agent, event_info)
            if target_result.get("findings"):
                triggered_agents.add(target_agent)
                chain_steps.append({
                    "triggerAgent": source_agent,
                    "triggerReason": rule["reason"],
                    "targetAgent": target_agent,
                    "result": target_result,
                })
                all_results.append(target_result)
        else:
            warnings.append(f"触发规则 '{rule['name']}' 条件不满足，未触发 {target_agent}")

    return {
        "chain": chain_steps,
        "triggerReasons": trigger_reasons,
        "stepResults": all_results,
        "finalPlan": {
            "totalAgents": len(all_results),
            "triggeredCount": len(triggered_agents),
            "triggeredAgents": list(triggered_agents),
        },
        "warnings": warnings,
    }
