"""协作编排器 — Phase 9.2"""

import asyncio, copy, time
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List

from backend.agent.collaboration.state import CollaborationRunState
from backend.agent.collaboration.task_graph import CollaborationTaskGraph, AgentTaskNode
from backend.agent.collaboration.budget import ExecutionBudget
from backend.agent.collaboration.executor import execute_single_agent
from backend.agent.collaboration.context_projection import project_context_for_agent
from backend.agent.collaboration.event_bus import get_event_bus
from backend.agent.collaboration.db_repository import SQLiteCollaborationRepository
from backend.agent.streaming import sse_event
from backend.config import LLM_ENABLED


async def _llm_fusion_stream(state) -> str:
    """使用 DeepSeek stream=true 生成融合总结。返回完整文本用于持久化。"""
    full_text = ""
    try:
        from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        from openai import OpenAI
        agent_text = "\n".join(
            f"[{a}] findings: {r.get('findings', [])} suggestion: {r.get('suggestion', '')}"
            for a, r in state.task_results.items()
        )
        prompt = f"基于以下多Agent协同分析结果，生成一段自然语言融合决策总结（200字以内）：\n\n{agent_text}\n\n融合决策："
        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        stream = client.chat.completions.create(model=DEEPSEEK_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.3, max_tokens=500, stream=True, timeout=20)
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                full_text += delta
        return full_text
    except Exception as e:
        print(f"[Fusion] LLM failed, using template: {e}")
        return _build_fusion(state)


def _llm_fusion(state) -> str:
    """同步包装 — 用于非流式场景。"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(_llm_fusion_stream(state))


class CollaborationOrchestrator:
    """多 Agent 协作编排器。不负责交通专业判断，只负责编排和控制。"""

    def __init__(self):
        self.repo = SQLiteCollaborationRepository()

    async def execute(
        self,
        run_id: str,
        session_id: str,
        event_info: Dict[str, Any],
        selected_agents: List[str],
        skipped_agents: List[str] = None,
        routing_reasons: List[str] = None,
        budget: ExecutionBudget = None,
        previous_run_context: Dict[str, Any] = None,
        grounding_context: Dict[str, Any] = None,
    ) -> AsyncGenerator[str, None]:
        """执行一次协作。生成 SSE 事件。

        event_info = currentEvent (仅当前消息解析结果)
        previous_run_context = 独立的上一次运行上下文（不合并到 currentEvent）
        """
        bus = get_event_bus()
        trace_id = f"trace_{run_id}"
        budget = budget or ExecutionBudget()
        state = CollaborationRunState(run_id, session_id, trace_id)
        state.original_input = event_info
        state.normalized_event = event_info  # = currentEvent only
        state.previous_run_context = previous_run_context  # separate!
        state.grounding_context = copy.deepcopy(grounding_context) if isinstance(grounding_context, dict) else {}
        state.selected_agents = selected_agents
        state.skipped_agents = skipped_agents or []
        self.repo.save_run(state.to_dict())

        # Parse NL content — caller (app.py) already handled NL parsing and fieldSources.
        # Only re-parse as fallback if event_info has no parsed fields and originalInput is present.
        context_policy = event_info.get("contextPolicy", "fresh_event")
        field_sources = event_info.get("fieldSources", {})
        if not event_info.get("avgSpeed") and not event_info.get("queueLength") and not field_sources:
            from backend.agent.collaboration.event_parser import parse_content_to_event
            content = event_info.get("originalInput", event_info.get("content", ""))
            if content:
                parsed = parse_content_to_event(content)
                event_info.update(parsed)
                yield sse_event("event_parse_done", {"normalizedEvent": event_info})

        user_query = event_info.get("originalInput", event_info.get("content", ""))
        yield sse_event("run_created", {
            "runId": run_id, "traceId": trace_id,
            "sessionId": session_id,
            "userQuery": user_query,
            "contextPolicy": context_policy,
            "fieldSources": field_sources,
            "previousRunContext": previous_run_context,
            "groundingStatus": state.grounding_context.get("groundingStatus") if state.grounding_context else None,
            "selectedAgents": [a for a in selected_agents if a not in ("FusionAgent", "ConflictDetector")],
        })
        if state.grounding_context:
            yield sse_event("grounding_ready", {
                "runId": run_id,
                "groundingStatus": state.grounding_context.get("groundingStatus"),
                "assembledAt": state.grounding_context.get("assembledAt"),
                "refs": state.grounding_context.get("groundingRefs", []),
            })
        state.transition("routing")
        yield sse_event("agent_route_done", {"selectedAgents": selected_agents, "routingReasons": routing_reasons or []})

        # Build DAG
        graph = CollaborationTaskGraph(run_id)
        domain_agents = [a for a in selected_agents if a in ("CongestionAgent", "SignalAgent", "PublicSafetyAgent", "AccidentAgent")]
        dep_ids = []
        for i, name in enumerate(domain_agents):
            tid = f"task_{i}_{name}"
            graph.add_task(AgentTaskNode(tid, run_id, name, "analyze", timeout_seconds=30))
            dep_ids.append(tid)

        # DispatchAgent always after domain agents
        graph.add_task(AgentTaskNode("task_dispatch", run_id, "DispatchAgent", "dispatch", depends_on=dep_ids, timeout_seconds=30))

        # ConflictDetector always after Dispatch
        graph.add_task(AgentTaskNode("task_conflict_detect", run_id, "ConflictDetector", "conflict_detect", depends_on=["task_dispatch"], timeout_seconds=30))

        # FusionAgent always last
        graph.add_task(AgentTaskNode("task_fusion", run_id, "FusionAgent", "fusion", depends_on=["task_conflict_detect"], timeout_seconds=30))

        try:
            graph.validate_dependencies()
        except ValueError as e:
            state.transition("failed")
            yield sse_event("run_failed", {"reason": str(e)}); return

        yield sse_event("task_graph_created", {"tasks": [t.to_dict() for t in graph.tasks.values()]})
        state.transition("running")

        # Execute all tasks in topological order with proper lifecycle events
        # Emit task_ready for all tasks first + save to SQLite
        for task in graph.tasks.values():
            yield _task_sse("task_ready", task, run_id)
            self.repo.save_task(run_id, task.to_dict())

        for _layer_idx in range(6):  # max 6 layers (domain, dispatch, detect, arbiter, fusion)
            ready = graph.get_ready_tasks()
            if not ready: break
            for task in ready:
                graph.mark_running(task.task_id)
                task.input_snapshot = project_context_for_agent(state.to_dict(), task.agent_name)
                self.repo.update_task(run_id, task.to_dict())
                yield _task_sse("task_started", task, run_id)

                if task.agent_name in ("ConflictDetector", "ConflictArbiter", "FusionAgent"):
                    # System agents — count once (not via executor)
                    budget.record_agent_call(task.agent_name)
                    graph.mark_succeeded(task.task_id)
                    if task.agent_name == "ConflictDetector":
                        state.transition("arbitrating")
                        conflicts = _detect_simple_conflicts(state)
                        state.conflicts = conflicts
                        yield sse_event("conflict_check_done", {"runId": run_id, "conflicts": conflicts, "conflictCount": len(conflicts)})
                        task.output_snapshot = {"conflicts": conflicts, "conflictCount": len(conflicts)}
                        self.repo.update_task(run_id, task.to_dict())

                        # === DYNAMIC INSERTION: ConflictArbiter ===
                        has_high = conflicts and any(c.get("severity") in ("high", "critical") for c in conflicts)
                        if has_high:
                            arbiter_task = AgentTaskNode("task_arbiter", run_id, "ConflictArbiter",
                                                         "arbitrate", depends_on=["task_conflict_detect"],
                                                         timeout_seconds=30)
                            graph.add_task(arbiter_task)
                            # Rewire: FusionAgent now depends on ConflictArbiter instead of ConflictDetector
                            graph.tasks["task_fusion"].depends_on = ["task_arbiter"]
                            try:
                                graph.validate_dependencies()
                            except ValueError:
                                # Rollback: keep original dependency
                                graph.tasks["task_fusion"].depends_on = ["task_conflict_detect"]
                            else:
                                # Emit task_ready for the dynamically inserted task
                                yield _task_sse("task_ready", arbiter_task, run_id)
                                self.repo.save_task(run_id, arbiter_task.to_dict())

                    elif task.agent_name == "ConflictArbiter":
                        # Execute arbitration for each conflict
                        from backend.agent.collaboration.agents import conflict_arbiter as _arbiter
                        arb_results = []
                        safety_first = "在学生过街安全与机动车通行效率冲突时，学生生命安全绝对优先。行人相位保障是第一原则；机动车绿灯延长必须在确保行人安全过街时间充足后方可实施。"
                        for c in state.conflicts:
                            arb = _arbiter(c)
                            arb["conflict_id"] = c.get("id", f"arb_{len(arb_results)}")
                            arb["safety_first_rule"] = safety_first
                            arb["limitations"] = [
                                "信号配时精确值需现场勘查确认",
                                "学生过街流量需学校提供统计数据",
                            ]
                            arb_results.append(arb)
                            yield sse_event("arbitration_result", {
                                "runId": run_id,
                                "conflictId": arb["conflict_id"],
                                "requiresHumanReview": arb.get("requires_human_review", False),
                                "safetyFirstRule": safety_first,
                                "resolution": arb.get("resolution", ""),
                                "limitations": arb.get("limitations", []),
                            })
                        state.arbitration_results = arb_results
                        task.output_snapshot = {"arbitrationResults": arb_results, "arbitrationCount": len(arb_results)}
                        self.repo.update_task(run_id, task.to_dict())
                        # Save conflicts with resolutions
                        for c, arb in zip(state.conflicts, arb_results):
                            self.repo.save_conflict({
                                "conflict_id": arb.get("conflict_id", ""),
                                "run_id": run_id,
                                "type": c.get("type", ""),
                                "field": c.get("field", ""),
                                "participants": c.get("agents", []),
                                "severity": c.get("severity", "low"),
                                "status": "resolved" if arb.get("resolved") else "open",
                                "resolution": arb.get("resolution", ""),
                                "resolved_by": "ConflictArbiter",
                                "requires_human_review": arb.get("requires_human_review", False),
                            })

                    elif task.agent_name == "FusionAgent":
                        state.transition("fusing")
                        yield sse_event("fusion_start", {"runId": run_id, "text": "正在调用大模型融合各 Agent 结论..."})
                        if LLM_ENABLED:
                            # Real streaming: forward DeepSeek deltas
                            agent_text = "\n".join(
                                f"[{a}] findings: {r.get('findings', [])} suggestion: {r.get('suggestion', '')}"
                                for a, r in state.task_results.items()
                            )
                            if state.arbitration_results:
                                arb_text = "；".join(
                                    f"仲裁{ar.get('conflict_id','')}: {ar.get('resolution','')}"
                                    for ar in state.arbitration_results
                                )
                                agent_text += f"\n\n仲裁结果: {arb_text}"
                            prompt = f"基于以下多Agent协同分析结果，生成一段自然语言融合决策总结（200字以内）：\n\n{agent_text}\n\n融合决策："
                            fusion = ""
                            try:
                                from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
                                from openai import OpenAI
                                client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
                                stream = client.chat.completions.create(model=DEEPSEEK_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.3, max_tokens=500, stream=True, timeout=20)
                                for chunk in stream:
                                    delta = chunk.choices[0].delta.content
                                    if delta:
                                        fusion += delta
                                        yield sse_event("fusion_delta", {"runId": run_id, "text": delta, "executionMode": "llm"})
                            except Exception as e:
                                print(f"[Fusion] LLM stream failed: {e}")
                                fusion = _build_fusion(state)
                                for chunk in _chunk_text(fusion):
                                    yield sse_event("fusion_delta", {"runId": run_id, "text": chunk, "executionMode": "template_fallback"})
                                    await asyncio.sleep(0.02)
                        else:
                            fusion = _build_fusion(state)
                            for chunk in _chunk_text(fusion):
                                yield sse_event("fusion_delta", {"runId": run_id, "text": chunk, "executionMode": "template_fallback"})
                                await asyncio.sleep(0.02)

                        # Build structured final_decision consuming arbitration results
                        has_high_conflict = state.conflicts and any(c.get("severity") in ("high", "critical") for c in state.conflicts)
                        unresolved = [a for a in state.arbitration_results if not a.get("resolved")]
                        final = {
                            "fusionSummary": fusion,
                            "generationMode": "llm" if LLM_ENABLED else "template_fallback",
                            "requiresHumanReview": bool(unresolved) or has_high_conflict,
                            "actionPlan": list(state.task_results.keys()),
                            "monitoringIndicators": [],
                            "limitations": [],
                            "confidence": 0.8,
                            "arbitration": {
                                "results": state.arbitration_results,
                                "totalConflicts": len(state.conflicts),
                                "resolvedCount": len(state.arbitration_results) - len(unresolved),
                                "unresolvedCount": len(unresolved),
                            },
                        }
                        if state.grounding_context:
                            from backend.grounding.rendering import grounding_audit_summary

                            final["groundingAudit"] = grounding_audit_summary(state.grounding_context)
                        yield sse_event("fusion_done", {"runId": run_id, "fusionSummary": fusion, "generationMode": "llm" if LLM_ENABLED else "template_fallback"})
                        state.final_decision = final
                        task.output_snapshot = {"fusionSummary": fusion, "generationMode": "llm" if LLM_ENABLED else "template_fallback", "agentResults": list(state.task_results.keys()), "arbitrationConsumed": len(state.arbitration_results) > 0}
                        if state.grounding_context:
                            task.output_snapshot["groundingAudit"] = final["groundingAudit"]
                        self.repo.update_task(run_id, task.to_dict())
                    yield _task_sse("task_succeeded", task, run_id)
                else:
                    # Domain/execution agents — count happens in executor
                    yield sse_event("budget_updated", {"runId": run_id, **budget.to_dict()})
                    try:
                        result = await asyncio.wait_for(execute_single_agent(task, state, budget), timeout=task.timeout_seconds)
                        if result.success and result.result:
                            graph.mark_succeeded(task.task_id)
                            state.record_agent_result(task.agent_name, result.result.model_dump())
                            # Save output_snapshot with agent result
                            task.output_snapshot = result.result.model_dump()
                            self.repo.update_task(run_id, task.to_dict())
                            self.repo.save_event(run_id, {"event_id": f"evt_agent_{task.agent_name}", "event_type": "agent_result", "agentName": task.agent_name, "status": "succeeded"}, len(bus.get_history(run_id)))
                            yield _agent_result_sse(task.agent_name, result.result)
                            yield _task_sse("task_succeeded", task, run_id)
                        else:
                            graph.mark_failed(task.task_id, result.error)
                            self.repo.save_event(run_id, {"event_id": f"evt_fail_{task.agent_name}", "event_type": "task_failed", "agentName": task.agent_name, "error": result.error}, len(bus.get_history(run_id)))
                            yield _task_sse("task_failed", task, run_id)
                    except asyncio.TimeoutError:
                        graph.mark_failed(task.task_id, "timeout")
                        yield _task_sse("task_failed", task, run_id)

        # Completion invariants
        has_agent_results = len(state.task_results) > 0
        fusion_ok = bool(state.final_decision) and "综合 0 个 Agent" not in str(state.final_decision)
        all_done = graph.is_completed()

        # --- SET ALL STATE FIELDS BEFORE SAVING ---
        from datetime import datetime as _dt
        state.updated_at = _dt.now().strftime("%Y-%m-%dT%H:%M:%S")
        state.budget_usage = budget.to_dict()
        state.failed_agents = list(set(t.agent_name for t in graph.tasks.values() if t.status == "failed" and t.agent_name != "FusionAgent")) if graph.has_failed_tasks() else []

        if has_agent_results and fusion_ok and all_done:
            state.transition("completed")
        elif has_agent_results and not fusion_ok:
            state.final_decision = _build_fusion(state) if not isinstance(state.final_decision, dict) else state.final_decision
            state.transition("completed")
        elif has_agent_results:
            state.transition("partial_success")
        else:
            state.transition("failed")

        # --- SAVE ALL FINAL STATE ---
        for task in graph.tasks.values():
            self.repo.update_task(run_id, task.to_dict())
        self.repo.update_run(state.to_dict())

        # --- SEND COMPLETION EVENTS AFTER SAVE ---
        if state.status == "completed":
            yield sse_event("run_completed", {"runId": run_id, "sessionId": session_id, "status": "completed"})
        elif state.status == "partial_success":
            yield sse_event("run_partial_success", {"reason": "部分任务未完成"})
        else:
            yield sse_event("run_failed", {"reason": "未能获取有效领域分析结果。请补充道路、速度、排队长度等信息后重试。"})
        # Single done — only here, not duplicated by wrapper


class AgentExecutionResult:
    def __init__(self, success, agent_name="", task_id="", result=None, error="", attempt=1):
        self.success = success; self.agent_name = agent_name; self.task_id = task_id
        self.result = result; self.error = error; self.attempt = attempt


def _detect_simple_conflicts(state: CollaborationRunState) -> List[Dict]:
    """检测 Agent 建议冲突。"""
    conflicts = []
    signal = state.task_results.get("SignalAgent", {})
    safety = state.task_results.get("PublicSafetyAgent", {})
    congestion = state.task_results.get("CongestionAgent", {})

    signal_findings = signal.get("findings", [])
    safety_findings = safety.get("findings", [])
    congestion_findings = congestion.get("findings", [])

    # signal vs safety: green time vs pedestrian crossing
    if signal and safety:
        sig_text = str(signal_findings)
        saf_text = str(safety_findings)
        if any(w in sig_text for w in ["信号", "配时", "绿", "周期"]) and any(w in saf_text for w in ["学校", "医院", "行人", "过街", "安全"]):
            conflicts.append({"type": "strategy_conflict", "description": "机动车通行效率优化与行人/安全需求存在资源冲突",
                              "agents": ["SignalAgent", "PublicSafetyAgent"], "severity": "high",
                              "field": "信号周期资源分配"})
            conflicts.append({"type": "priority_conflict", "description": "通行效率优先级与学生过街安全优先级冲突",
                              "agents": ["SignalAgent", "PublicSafetyAgent"], "severity": "high",
                              "field": "处置优先级"})
            conflicts.append({"type": "resource_conflict", "description": "同一信号周期内机动车绿灯时间与行人过街相位争抢",
                              "agents": ["SignalAgent", "PublicSafetyAgent"], "severity": "high",
                              "field": "信号周期时间"})

    # congestion vs safety: diversion vs pedestrian protection
    if congestion and safety:
        cong_text = str(congestion_findings)
        saf_text = str(safety_findings)
        if any(w in cong_text for w in ["分流", "放行", "通行"]) and any(w in saf_text for w in ["学校", "行人", "过街", "安全"]):
            conflicts.append({"type": "safety_conflict", "description": "分流/放行方案可能增加行人安全风险",
                              "agents": ["CongestionAgent", "PublicSafetyAgent"], "severity": "medium"})

    return conflicts


def _build_fusion(state: CollaborationRunState) -> str:
    agents = [name for name, r in state.task_results.items() if r.get("findings")]
    parts = [f"综合 {len(agents)} 个 Agent 的分析结果"]
    if state.conflicts:
        parts.append(f"，检测到 {len(state.conflicts)} 个建议冲突")
        resolved = [a for a in state.arbitration_results if a.get("resolved")]
        unresolved = [a for a in state.arbitration_results if not a.get("resolved")]
        if resolved:
            parts.append(f"，其中 {len(resolved)} 个已自动仲裁解决")
        if unresolved:
            parts.append(f"，{len(unresolved)} 个高风险冲突需人工审核")
        parts.append("，已按安全优先原则融合处理")
    parts.append("。")
    if state.arbitration_results:
        for ar in state.arbitration_results:
            if ar.get("safety_first_rule"):
                parts.append(f"[仲裁原则] {ar['safety_first_rule']}。")
                break
    for name, r in state.task_results.items():
        if r.get("suggestion"):
            parts.append(f"[{name}] {r['suggestion']}。")
    return "".join(parts)


def _task_sse(event: str, task, run_id: str) -> str:
    """生成 task 事件。"""
    return sse_event(event, {
        "runId": run_id, "taskId": task.task_id,
        "agentName": task.agent_name, "status": task.status,
        "attempt": task.attempt,
    })


def _agent_result_sse(agent_name: str, result) -> str:
    """生成 agent_result SSE 事件（camelCase 字段名）。"""
    from backend.agent.streaming import sse_event
    execution_mode = "rule"
    if agent_name in ("DispatchAgent", "FusionAgent") and LLM_ENABLED:
        execution_mode = "llm"
    elif agent_name in ("DispatchAgent", "FusionAgent"):
        execution_mode = "template_fallback"

    payload = {
        "agentName": agent_name,
        "taskId": result.task_id,
        "status": result.status,
        "attempt": getattr(result, "attempt", 1) or 1,
        "executionMode": execution_mode,
            "result": {
                "urgency": result.urgency,
                "findings": result.findings,
                "recommendation": result.suggestion,
                "confidence": result.confidence,
                "evidenceRefs": result.evidence_refs,
                "proposedActions": result.proposed_actions,
                "limitations": result.assumptions or [],
            }
        }
    return sse_event("agent_result", payload)


def _chunk_text(text: str, size: int = 8) -> list:
    if not text: return [""]
    chunks = []; start = 0
    for i, ch in enumerate(text):
        if ch in "。\n？！，；" and i - start >= size:
            chunks.append(text[start:i + 1]); start = i + 1
    if start < len(text): chunks.append(text[start:])
    return chunks if chunks else [text[i:i + size] for i in range(0, len(text), size)]
