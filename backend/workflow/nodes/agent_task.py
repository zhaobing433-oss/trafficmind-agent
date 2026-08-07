"""
agent_task 节点 — Agent 执行。

调用现有 Multi-Agent 执行分析任务。

设计约束：
  - 只传 summary 和 evidence refs（不传完整内部状态）
  - Agent 不自行创建节点或循环
  - 错误时记录但不阻止后续节点
"""

from typing import Any, Dict

from backend.workflow.models import NodeConfig
from backend.workflow.state import TrafficWorkflowState


async def execute_agent_task(
    state: TrafficWorkflowState, config: NodeConfig
) -> Dict[str, Any]:
    """执行 Agent 分析任务。

    Args:
        state: 工作流状态
        config: 节点配置
          - config.agent_name: Agent 名称（如 "CongestionAgent"）
          - config.task_prompt: 自定义任务提示（可选）

    Returns:
        Agent 输出（summary + evidence refs only）
    """
    agent_name = config.config.get("agent_name", "")
    if not agent_name:
        return {"error": "agent_task 缺少 agent_name 配置"}

    event = state.current_event or {}
    rag_ctx = state.rag_context or {}
    mem_ctx = state.memory_context or {}

    findings = []
    suggestion = ""
    urgency = "low"
    confidence = 0.5
    evidence_refs: list = []

    try:
        # 使用 multi_agent 模块的 Agent 类
        from backend.agent.multi_agent import (
            CongestionAgent, SignalAgent, AccidentAgent, DispatchAgent,
            PublicSafetyAgent,
            _get_event_info,
        )

        # 构建 Agent 输入
        info = _get_event_info(event)

        agent_map = {
            "CongestionAgent": CongestionAgent,
            "SignalAgent": SignalAgent,
            "AccidentAgent": AccidentAgent,
            "DispatchAgent": DispatchAgent,
            "PublicSafetyAgent": PublicSafetyAgent,
        }

        cls = agent_map.get(agent_name)
        if cls is not None:
            instance = cls()
            result = instance.analyze(info)
            findings = result.get("findings", [])
            suggestion = result.get("suggestion", "")
            urgency = result.get("urgency", "low")
            confidence = result.get("confidence", 0.5)
        else:
            findings = [f"[{agent_name}] 未找到对应 Agent 实现，使用默认分析"]
            suggestion = "按常规流程处置"
            urgency = "low"
            confidence = 0.3

    except Exception as e:
        findings = [f"[{agent_name}] 执行异常: {str(e)[:200]}"]
        suggestion = "Agent 执行失败，建议人工介入"
        urgency = "high"
        confidence = 0.0
        state.record_error(config.node_id, str(e))

    # 提取 RAG evidence refs
    if isinstance(rag_ctx, dict):
        for r in rag_ctx.get("results", [])[:3]:
            rid = r.get("id", r.get("evidenceId", ""))
            if rid:
                evidence_refs.append(rid)

    # 只在 state 中存 summary + evidence refs
    state.record_agent_output(agent_name, suggestion, evidence_refs)

    output = {
        "agent_name": agent_name,
        "findings": findings,
        "suggestion": suggestion,
        "urgency": urgency,
        "confidence": confidence,
        "evidence_refs": evidence_refs,
        "status": "succeeded" if confidence > 0 else "failed",
    }

    state.add_audit_event("agent_completed", config.node_id, {
        "agentName": agent_name,
        "confidence": confidence,
        "urgency": urgency,
        "findingCount": len(findings),
    })

    return output
