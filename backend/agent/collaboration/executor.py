"""Agent 执行适配器 — Phase 9.2"""

import asyncio, copy, time
from typing import Any, Dict, List, Optional

from backend.agent.collaboration.state import CollaborationRunState
from backend.agent.collaboration.context_projection import project_context_for_agent, validate_required_fields
from backend.agent.collaboration.protocol import AgentResult
from backend.agent.collaboration.event_bus import get_event_bus
from backend.agent.collaboration.task_graph import AgentTaskNode
from backend.tools.event_tools import safe_float


class AgentExecutionResult:
    def __init__(self, success: bool, agent_name: str, task_id: str,
                 result: Optional[AgentResult] = None, error: str = "", attempt: int = 1):
        self.success = success
        self.agent_name = agent_name
        self.task_id = task_id
        self.result = result
        self.error = error
        self.attempt = attempt


async def execute_single_agent(
    task: AgentTaskNode,
    state: CollaborationRunState,
    budget,
    retry_delay: float = 0.01,
) -> AgentExecutionResult:
    """执行单个 Agent，含上下文裁剪、校验、重试。"""
    agent_name = task.agent_name
    bus = get_event_bus()
    run_id = task.run_id

    # Publish task.started
    bus.publish({"message_id": f"msg_{run_id}_{task.task_id}_start", "run_id": run_id,
                 "sender": "Orchestrator", "receiver": agent_name, "message_type": "task.started",
                 "task_id": task.task_id, "payload": {"attempt": task.attempt}})

    for attempt in range(1, task.max_retries + 2):
        task.attempt = attempt
        try:
            # Check budget
            if not budget.can_call_agent(agent_name):
                return AgentExecutionResult(False, agent_name, task.task_id, error="Budget exhausted", attempt=attempt)

            budget.record_agent_call(agent_name)

            # Project context
            ctx = project_context_for_agent(state.to_dict(), agent_name)
            audit_ctx = copy.deepcopy(ctx)

            # Validate required fields
            missing = validate_required_fields(state.to_dict(), agent_name)
            if missing:
                raise ValueError(f"缺少必要输入字段: {missing}")

            # Execute existing agent
            result_dict = await _call_agent_function(agent_name, ctx)
            result_dict = _augment_agent_result_with_grounding(agent_name, audit_ctx, result_dict)

            # Wrap in protocol
            agent_result = AgentResult(
                agent_name=agent_name, task_id=task.task_id, status="completed",
                findings=result_dict.get("findings", []),
                confidence=min(safe_float(result_dict.get("confidence"), 0.5), 1.0),
                suggestion=result_dict.get("suggestion", ""),
                urgency=result_dict.get("urgency", "low"),
                evidence_refs=result_dict.get("evidence_refs", []),
                proposed_actions=result_dict.get("proposed_actions", []),
                assumptions=result_dict.get("assumptions", []),
                duration_ms=int(result_dict.get("duration_ms", 0)),
            )

            # Publish task.result
            bus.publish({"message_id": f"msg_{run_id}_{task.task_id}_result", "run_id": run_id,
                         "sender": agent_name, "receiver": "Orchestrator", "message_type": "task.result",
                         "task_id": task.task_id, "payload": agent_result.model_dump()})

            return AgentExecutionResult(True, agent_name, task.task_id, result=agent_result, attempt=attempt)

        except asyncio.TimeoutError:
            bus.publish({"message_id": f"msg_{run_id}_{task.task_id}_timeout", "run_id": run_id,
                         "sender": "Orchestrator", "receiver": agent_name, "message_type": "task.failed",
                         "task_id": task.task_id, "payload": {"error": "timeout", "attempt": attempt}})
            if attempt > task.max_retries:
                return AgentExecutionResult(False, agent_name, task.task_id, error="timeout after max retries", attempt=attempt)
            await asyncio.sleep(retry_delay * attempt)

        except Exception as e:
            error_msg = str(e)
            # Non-retryable errors
            if any(kw in error_msg for kw in ["ValidationError", "缺少必要", "未注册", "非法"]):
                return AgentExecutionResult(False, agent_name, task.task_id, error=error_msg, attempt=attempt)

            bus.publish({"message_id": f"msg_{run_id}_{task.task_id}_failed", "run_id": run_id,
                         "sender": "Orchestrator", "receiver": agent_name, "message_type": "task.failed",
                         "task_id": task.task_id, "payload": {"error": error_msg, "attempt": attempt}})
            if attempt > task.max_retries:
                return AgentExecutionResult(False, agent_name, task.task_id, error=error_msg, attempt=attempt)
            await asyncio.sleep(retry_delay * attempt)

    return AgentExecutionResult(False, agent_name, task.task_id, error="max retries exceeded", attempt=task.max_retries + 1)


async def _call_agent_function(agent_name: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """调用现有 Agent 分析函数（同步包装）。"""
    from backend.agent.multi_agent import AccidentAgent, CongestionAgent, SignalAgent
    agent_map = {
        "AccidentAgent": AccidentAgent,
        "CongestionAgent": CongestionAgent,
        "SignalAgent": SignalAgent,
    }
    cls = agent_map.get(agent_name)
    if cls is not None:
        instance = cls()
        return instance.analyze(ctx)

    # System agents — return structured results
    if agent_name == "PublicSafetyAgent":
        findings = []
        if ctx.get("nearbyHospital"): findings.append("邻近医院，需保障急救通道")
        if ctx.get("nearbySchool"): findings.append("邻近学校，注意行人安全")
        has_risk = bool(findings)
        return {"findings": findings or ["无特殊公共安全风险"], "confidence": 0.7 if has_risk else 0.5,
                "suggestion": "建议加强巡查" if has_risk else "无需额外安全措施",
                "urgency": "medium" if has_risk else "low"}
    if agent_name == "DispatchAgent":
        domain = ctx.get("domain_results", {})
        findings = []
        for name, r in domain.items():
            if r.get("findings"): findings.append(f"[{name}] {r['findings'][0]}")
        is_main = ctx.get("isMainRoad", False)
        if is_main: findings.append("主干道事件，影响范围广")
        return {"findings": findings or ["已综合领域分析结果"], "confidence": 0.75,
                "suggestion": "通知交警大队，实施分流管控", "urgency": "high" if is_main else "medium"}

    return {"findings": ["分析完成"], "confidence": 0.6, "suggestion": "按常规流程处置", "urgency": "low"}


def _augment_agent_result_with_grounding(
    agent_name: str,
    ctx: Dict[str, Any],
    result: Dict[str, Any],
) -> Dict[str, Any]:
    grounding = ctx.get("groundedContext")
    if not isinstance(grounding, dict) or not grounding:
        return result

    from backend.grounding.rendering import render_grounded_context_for_agent

    rendered = render_grounded_context_for_agent(grounding)
    augmented = dict(result or {})
    facts = list(rendered.get("facts") or [])
    refs = [ref for ref in (rendered.get("evidenceRefs") or []) if isinstance(ref, dict)]
    existing_refs = augmented.get("evidence_refs") or augmented.get("evidenceRefs") or []
    augmented["evidence_refs"] = _dedupe_refs(list(existing_refs) + refs)
    findings = list(augmented.get("findings") or [])
    if facts:
        findings.append(f"已提供GroundedEventContext输入: {'；'.join(facts[:4])}")
    augmented["findings"] = findings
    assumptions = list(augmented.get("assumptions") or [])
    assumptions.append(
        f"{agent_name} received shared grounding snapshot "
        f"status={rendered.get('groundingStatus', 'MINIMAL')}; "
        "grounding refs are available-input audit, not model-claimed usage"
    )
    augmented["assumptions"] = assumptions
    return augmented


def _dedupe_refs(refs: List[Any]) -> List[Any]:
    import json

    out: List[Any] = []
    seen = set()
    for ref in refs:
        key = json.dumps(ref, sort_keys=True, ensure_ascii=False) if isinstance(ref, dict) else str(ref)
        if key in seen:
            continue
        seen.add(key)
        out.append(ref)
    return out
