"""
LangGraph 工作流
---------------
定义 TrafficMind Agent 的线性流水线：

  parse_event → calculate_risk → retrieve_rule
  → generate_suggestions → generate_dispatch
  → generate_report → save_result → send_notification

若 parse_event 校验失败（含 error），直接跳到 END。
"""

from typing import Dict, Any
from typing import TypedDict
from langgraph.graph import StateGraph, END

from backend.agent.nodes import (
    parse_event_node,
    calculate_risk_node,
    retrieve_rule_node,
    generate_suggestions_node,
    generate_dispatch_node,
    generate_report_node,
    save_result_node,
    send_notification_node,
)


class AgentState(TypedDict, total=False):
    """Agent 状态定义（total=False 表示所有字段可选）"""
    raw_event: Dict[str, Any]
    standard_event: Dict[str, Any]
    risk_result: Dict[str, Any]
    matched_rule: Dict[str, Any]
    suggestions: list
    dispatch_message: str
    public_message: str
    report: str
    result: Dict[str, Any]
    step: str
    error: str | None


def _has_error(state: AgentState) -> str:
    """条件路由：若有 error 则直接结束，否则继续。"""
    if state.get("error"):
        return END
    return "ok"


def build_graph() -> StateGraph:
    """
    构建并编译 LangGraph 工作流。

    流程：parse_event → ... → save_result → END
    若 parse_event 校验失败（含 error），直接跳到 END。
    """
    workflow = StateGraph(AgentState)

    # 添加节点
    workflow.add_node("parse_event", parse_event_node)
    workflow.add_node("calculate_risk", calculate_risk_node)
    workflow.add_node("retrieve_rule", retrieve_rule_node)
    workflow.add_node("generate_suggestions", generate_suggestions_node)
    workflow.add_node("generate_dispatch", generate_dispatch_node)
    workflow.add_node("generate_report", generate_report_node)
    workflow.add_node("save_result", save_result_node)
    workflow.add_node("send_notification", send_notification_node)

    # 定义流程边
    workflow.set_entry_point("parse_event")

    # parse_event 之后条件路由：有错则 END，无错则继续
    workflow.add_conditional_edges(
        "parse_event",
        _has_error,
        {"ok": "calculate_risk", END: END},
    )

    # 后续节点线性连接（后续节点内部有容错处理）
    workflow.add_edge("calculate_risk", "retrieve_rule")
    workflow.add_edge("retrieve_rule", "generate_suggestions")
    workflow.add_edge("generate_suggestions", "generate_dispatch")
    workflow.add_edge("generate_dispatch", "generate_report")
    workflow.add_edge("generate_report", "save_result")
    workflow.add_edge("save_result", "send_notification")
    workflow.add_edge("send_notification", END)

    return workflow.compile()
