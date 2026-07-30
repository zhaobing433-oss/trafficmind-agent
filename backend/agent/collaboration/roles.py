"""
Agent 角色能力注册 — Phase 9.1
每个 Agent 有明确的能力边界、输入输出规范和禁止职责。
"""

from typing import List, Dict

AgentCapability = Dict


REGISTERED_AGENTS: Dict[str, AgentCapability] = {
    "ConflictDetector": {
        "name": "ConflictDetector", "role": "冲突检测",
        "responsibilities": ["比较结构化 proposals，检测冲突"],
        "forbidden_responsibilities": ["不得重新分析业务", "不得修改 Agent 结论"],
        "accepted_message_types": ["task.assign"], "produced_message_types": ["task.result"],
        "allowed_tools": [], "allowed_input_fields": ["task_results"],
        "required_input_fields": [], "max_calls": 1, "max_retries": 0, "timeout_seconds": 10, "dependencies": [],
    },
    "CongestionAgent": {
        "name": "CongestionAgent",
        "role": "拥堵分析",
        "responsibilities": ["分析平均速度、排队长度、拥堵等级、拥堵扩散和通行能力"],
        "forbidden_responsibilities": ["不得给出信号配时具体秒数", "不得声称已通知交警", "不得代替 FusionAgent 做最终决策"],
        "accepted_message_types": ["task.assign", "task.started"],
        "produced_message_types": ["task.result", "task.failed"],
        "allowed_tools": [],
        "allowed_input_fields": ["eventType", "roadName", "direction", "avgSpeed", "queueLength", "duration", "timePeriod", "weather", "isMainRoad"],
        "required_input_fields": ["roadName", "avgSpeed", "queueLength"],
        "max_calls": 2,
        "max_retries": 1,
        "timeout_seconds": 30,
        "dependencies": [],
    },
    "SignalAgent": {
        "name": "SignalAgent",
        "role": "信号控制分析",
        "responsibilities": ["分析信号状态、绿信比、周期和协调控制"],
        "forbidden_responsibilities": ["不得直接控制信号灯", "不得给出未经验证的配时秒数", "不得代替 FusionAgent 做最终决策"],
        "accepted_message_types": ["task.assign", "task.started"],
        "produced_message_types": ["task.result", "task.failed"],
        "allowed_tools": [],
        "allowed_input_fields": ["eventType", "roadName", "direction", "avgSpeed", "queueLength", "isMainRoad",
                                  "signalStatus", "cycleLength", "greenRatio", "phasePlan", "trafficFlow",
                                  "intersectionId", "coordinationStatus"],
        "required_input_fields": ["roadName"],
        "max_calls": 2,
        "max_retries": 1,
        "timeout_seconds": 30,
        "dependencies": [],
    },
    "PublicSafetyAgent": {
        "name": "PublicSafetyAgent",
        "role": "公共安全分析",
        "responsibilities": ["分析学校、医院、事故、行人和次生安全风险"],
        "forbidden_responsibilities": ["不得代替 DispatchAgent 调度资源", "不得代替 FusionAgent 做最终决策"],
        "accepted_message_types": ["task.assign", "task.started"],
        "produced_message_types": ["task.result", "task.failed"],
        "allowed_tools": [],
        "allowed_input_fields": ["eventType", "roadName", "nearbySchool", "nearbyHospital", "accidentType",
                                  "pedestrianRisk", "weather", "riskLevel", "isMainRoad"],
        "required_input_fields": ["roadName"],
        "max_calls": 2,
        "max_retries": 1,
        "timeout_seconds": 30,
        "dependencies": [],
    },
    "DispatchAgent": {
        "name": "DispatchAgent",
        "role": "调度处置",
        "responsibilities": ["读取已完成的领域 Agent 结果，生成分流、警力、联动和处置顺序"],
        "forbidden_responsibilities": ["不得在领域 Agent 完成前自行分析拥堵/信号/安全", "不得代替 FusionAgent 做最终决策"],
        "accepted_message_types": ["task.assign", "task.started"] + [f"task.result.{a}" for a in ["CongestionAgent", "SignalAgent", "PublicSafetyAgent"]],
        "produced_message_types": ["task.result", "task.failed"],
        "allowed_tools": [],
        "allowed_input_fields": ["eventType", "roadName", "riskLevel", "isMainRoad", "nearbyHospital", "nearbySchool"],
        "required_input_fields": [],
        "max_calls": 2,
        "max_retries": 1,
        "timeout_seconds": 30,
        "dependencies": ["CongestionAgent", "SignalAgent"],
    },
    "ConflictArbiter": {
        "name": "ConflictArbiter",
        "role": "冲突仲裁",
        "responsibilities": ["只处理结构化冲突，不重新执行完整业务分析"],
        "forbidden_responsibilities": ["不得重新分析拥堵/信号/安全", "不得修改 Agent 原始结论"],
        "accepted_message_types": ["arbitration.request"],
        "produced_message_types": ["arbitration.result"],
        "allowed_tools": [],
        "allowed_input_fields": ["conflict.type", "conflict.agents", "conflict.description", "agent_proposals"],
        "required_input_fields": ["conflict.type"],
        "max_calls": 5,
        "max_retries": 1,
        "timeout_seconds": 30,
        "dependencies": [],
    },
    "AccidentAgent": {
        "name": "AccidentAgent",
        "role": "事故分析",
        "responsibilities": ["分析事故类型、严重程度、涉事车辆、伤亡估计和交通影响"],
        "forbidden_responsibilities": ["不得代替 DispatchAgent 调度救援", "不得代替 FusionAgent 做最终决策"],
        "accepted_message_types": ["task.assign", "task.started"],
        "produced_message_types": ["task.result", "task.failed"],
        "allowed_tools": [],
        "allowed_input_fields": ["eventType", "roadName", "direction", "avgSpeed", "queueLength",
                                  "accidentType", "hasAccident", "weather", "timePeriod",
                                  "isMainRoad", "nearbyHospital"],
        "required_input_fields": ["roadName"],
        "max_calls": 2,
        "max_retries": 1,
        "timeout_seconds": 30,
        "dependencies": [],
    },
    "FusionAgent": {
        "name": "FusionAgent",
        "role": "融合总结",
        "responsibilities": ["只融合已确认的结果，不生成没有依据的新事实"],
        "forbidden_responsibilities": ["不得在领域 Agent 完成前融合", "不得编造未经验证的结论", "不得跳过冲突仲裁"],
        "accepted_message_types": ["fusion.request"],
        "produced_message_types": ["run.completed"],
        "allowed_tools": [],
        "allowed_input_fields": ["agent_results", "arbitration_results", "conflicts"],
        "required_input_fields": ["agent_results"],
        "max_calls": 2,
        "max_retries": 1,
        "timeout_seconds": 30,
        "dependencies": ["CongestionAgent", "SignalAgent", "DispatchAgent", "ConflictArbiter"],
    },
}


def is_registered_agent(name: str) -> bool:
    return name in REGISTERED_AGENTS or name == "Orchestrator"


def get_agent_capability(name: str) -> AgentCapability:
    if name not in REGISTERED_AGENTS:
        raise ValueError(f"Agent '{name}' 未注册。已注册: {list(REGISTERED_AGENTS.keys())}")
    return REGISTERED_AGENTS[name]


def get_all_registered_agents() -> List[str]:
    return list(REGISTERED_AGENTS.keys())
