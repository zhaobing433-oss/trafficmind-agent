"""
action 节点 — 外部动作执行。

执行经批准的外部动作（通知、信号调整、派单等）。

幂等性保证：
  - 使用 idempotency_key = {runId}:{nodeId}:{actionType}
  - 重复 resume 或 retry 不重复执行已成功动作
  - 通过 WorkflowActionRecord 表做幂等检查

未经 human_approval 批准不得执行 action 节点。
"""

from typing import Any, Dict

from backend.workflow.models import (
    ActionStatus,
    NodeConfig,
    WorkflowActionRecord,
    compute_action_idempotency_key,
    generate_action_id,
)
from backend.workflow.state import TrafficWorkflowState


async def execute_action(
    state: TrafficWorkflowState, config: NodeConfig, repository=None
) -> Dict[str, Any]:
    """执行外部动作。

    执行前检查：
      1. 是否已经过审批（如有 approval 节点）
      2. 幂等键是否已存在成功记录

    Args:
        state: 工作流状态
        config: 节点配置
          - config.action_type: 动作类型（"notify_wechat", "adjust_signal" 等）
          - config.action_params: 动作参数
        repository: Workflow 持久化仓库（用于幂等检查）

    Returns:
        执行结果
    """
    action_type = config.config.get("action_type", "")
    if not action_type:
        return {"error": "action 节点缺少 action_type 配置"}

    # 检查是否有待审批但未批准的审批
    pending = state.pending_approval
    if pending:
        return {
            "error": "存在未处理的审批，不能执行外部动作",
            "approval_id": pending.get("approvalId"),
        }

    # ── 优先使用审批后的 edited_actions，否则用节点配置 ──────────
    action_params = config.config.get("action_params", {})
    if state.approved_actions:
        # 查找匹配当前 action_type 的已批准动作
        for approved in state.approved_actions:
            if isinstance(approved, dict) and approved.get("actionType") == action_type:
                action_params = approved.get("params", approved.get("action_params", approved))
                break
            # Phase 13: 结构化 proposal 直接使用自身作为 params
            if isinstance(approved, dict) and approved.get("actionType"):
                # 映射 agent proposal 格式到 action 格式
                action_params = {
                    "targetIds": approved.get("sourceRoadId", approved.get("targetRoadIds", [])),
                    "parameters": {
                        "diversionRatio": approved.get("diversionRatio", 0.35),
                    },
                }
                if isinstance(action_params["targetIds"], str):
                    action_params["targetIds"] = [action_params["targetIds"]]
                # 添加 targetRoadIds
                tr = approved.get("targetRoadIds", [])
                if tr:
                    action_params["targetIds"] = [approved.get("sourceRoadId", tr[0])] + tr
                break

    # 幂等键
    idempotency_key = compute_action_idempotency_key(
        state.workflow_run_id, config.node_id, action_type
    )

    # 幂等检查（如果提供了 repository）
    if repository:
        try:
            existing = repository.get_action_record_by_idempotency_key(idempotency_key)
            if existing and existing.status == ActionStatus.SUCCEEDED:
                state.add_audit_event("action_idempotent_skip", config.node_id, {
                    "actionType": action_type,
                    "idempotencyKey": idempotency_key,
                    "reason": "已成功执行，幂等跳过",
                })
                return {
                    "action_type": action_type,
                    "status": "skipped",
                    "reason": "idempotent_skip",
                    "previous_result": existing.result,
                }
        except Exception:
            pass  # 幂等检查失败不影响执行

    # 创建动作记录
    action_id = generate_action_id()
    record = WorkflowActionRecord(
        action_id=action_id,
        run_id=state.workflow_run_id,
        node_id=config.node_id,
        action_type=action_type,
        idempotency_key=idempotency_key,
        params=action_params,
        status=ActionStatus.EXECUTING,
    )

    # 执行具体动作
    result_data: Dict[str, Any] = {}
    error = ""
    status = ActionStatus.SUCCEEDED

    try:
        result_data = await _dispatch_action(action_type, action_params, state)
    except Exception as e:
        error = str(e)[:500]
        status = ActionStatus.FAILED
        state.record_error(config.node_id, f"action 执行失败: {error}")

    # 更新动作记录
    record.status = status
    record.result = result_data
    record.error = error
    record.completed_at = record.created_at  # 简化时间戳

    # 持久化（如果提供了 repository）
    # DB 层有 UNIQUE(idempotency_key) 约束，提供数据库级别的幂等保护
    if repository:
        try:
            repository.save_action_record(record)
        except Exception as e:
            # 检查是否为 IntegrityError（幂等键冲突）
            err_str = str(e).lower()
            if "unique" in err_str or "integrity" in err_str:
                # 数据库级别幂等保护：重新读取已有记录
                try:
                    existing = repository.get_action_record_by_idempotency_key(
                        idempotency_key
                    )
                    if existing:
                        state.add_audit_event("action_idempotent_db_protect", config.node_id, {
                            "actionType": action_type,
                            "idempotencyKey": idempotency_key,
                            "reason": "DB UNIQUE 约束触发，幂等跳过",
                        })
                        return {
                            "action_id": existing.action_id,
                            "action_type": action_type,
                            "status": "skipped",
                            "reason": "idempotent_db_protect",
                            "previous_result": existing.result,
                        }
                except Exception:
                    pass
            # 其他持久化错误：记录但不阻止返回结果

    # 跟踪
    state.action_record_ids.append(action_id)
    if isinstance(state.action_results, dict):
        state.action_results[action_type] = {
            "actionId": action_id,
            "status": status.value,
            "result": result_data,
            "error": error,
        }

    state.add_audit_event("action_executed", config.node_id, {
        "actionType": action_type,
        "actionId": action_id,
        "status": status.value,
        "idempotencyKey": idempotency_key,
    })

    return {
        "action_id": action_id,
        "action_type": action_type,
        "status": status.value,
        "result": result_data,
        "error": error,
    }


async def _dispatch_action(
    action_type: str,
    params: Dict[str, Any],
    state: TrafficWorkflowState,
) -> Dict[str, Any]:
    """调度具体的外部动作。

    Args:
        action_type: 动作类型
        params: 动作参数
        state: 工作流状态

    Returns:
        执行结果
    """
    event = state.current_event or {}
    risk = state.risk_assessment or {}

    if action_type == "notify_wechat":
        # 企业微信通知
        try:
            from backend.tools.notify_tools import send_wechat_work
            event_summary = (
                f"## TrafficMind 交通事件通知\n"
                f"事件类型：{event.get('eventTypeCn', '')}\n"
                f"路段：{event.get('roadName', '')}\n"
                f"风险等级：{risk.get('riskLevel', '未知')}（{risk.get('riskScore', 0)}分）\n"
            )
            send_wechat_work(event_summary)
            return {"sent": True, "channel": "wechat"}
        except Exception as e:
            return {"sent": False, "channel": "wechat", "error": str(e)[:200]}

    elif action_type == "notify_dingtalk":
        # 钉钉通知
        try:
            from backend.tools.notify_tools import send_dingtalk
            event_summary = (
                f"## TrafficMind 交通事件通知\n"
                f"事件：{event.get('eventTypeCn', '')} | {event.get('roadName', '')}\n"
                f"风险：{risk.get('riskLevel', '未知')}（{risk.get('riskScore', 0)}分）\n"
            )
            send_dingtalk(event_summary)
            return {"sent": True, "channel": "dingtalk"}
        except Exception as e:
            return {"sent": False, "channel": "dingtalk", "error": str(e)[:200]}

    elif action_type == "save_result":
        # 持久化分析结果
        try:
            from backend.tools.db_tools import save_event_analysis
            result_data = {
                "eventId": event.get("eventId", f"evt_{state.workflow_run_id}"),
                "eventType": event.get("eventType", ""),
                "eventTypeCn": event.get("eventTypeCn", ""),
                "roadName": event.get("roadName", ""),
                "riskScore": risk.get("riskScore", 0),
                "riskLevel": risk.get("riskLevel", "低风险"),
                "status": "待派单",
            }
            save_event_analysis(result_data)
            return {"saved": True, "eventId": result_data.get("eventId", "")}
        except Exception as e:
            return {"saved": False, "error": str(e)[:200]}

    # ── Phase 13: Simulation Actions ──────────────────────────────────
    # 所有 simulation action 必须标记 simulation=true
    # Agent 不得直接调用，必须经过 Workflow Risk Gate → Human Approval

    elif action_type == "simulation_traffic_diversion":
        return await _execute_simulation_action(action_type, params, state,
            "分流动作：将指定道路流量分流到目标道路")

    elif action_type == "simulation_signal_adjustment":
        return await _execute_simulation_action(action_type, params, state,
            "信号调整：调整指定路口信号配时")

    elif action_type == "simulation_lane_control":
        return await _execute_simulation_action(action_type, params, state,
            "车道控制：调整指定路段车道使用")

    elif action_type == "simulation_dispatch_coordination":
        return await _execute_simulation_action(action_type, params, state,
            "调度协调：发送模拟调度指令")

    elif action_type == "simulation_monitor":
        return await _execute_simulation_action(action_type, params, state,
            "监控：检查交通状态改善情况")

    elif action_type == "simulation_close":
        return await _execute_simulation_action(action_type, params, state,
            "关闭：标记事件已处置完成")

    else:
        # 通用动作：记录日志
        return {
            "action_type": action_type,
            "params": params,
            "status": "executed",
            "note": "通用动作已记录",
        }


async def _execute_simulation_action(
    action_type: str,
    params: Dict[str, Any],
    state: TrafficWorkflowState,
    description: str,
) -> Dict[str, Any]:
    """执行模拟交通动作（Phase 13 Bridge）。

    约束：
      - simulation ALWAYS True
      - 必须通过 Workflow Risk Gate + Human Approval 后才能调用
      - 调用 DemoSimulationProvider.apply_action()
      - 记录 before/after snapshot 对比
    """
    from backend.simulation.demo_provider import get_demo_provider
    from backend.simulation.models import (
        TrafficSimulationAction as SimAction,
        ActionType,
        generate_action_id,
    )

    sim_refs = state.simulation_refs or {}
    simulation_run_id = sim_refs.get("simulationRunId", "") or sim_refs.get(
        "simulation_run_id", ""
    )
    decision_snapshot_id = sim_refs.get("decisionSnapshotId", "") or sim_refs.get(
        "decision_snapshot_id", ""
    )
    if not simulation_run_id:
        return {
            "error": "simulation_refs 缺少 simulationRunId，无法执行模拟动作",
            "simulation": True,
        }

    # 映射 workflow action_type → simulation ActionType
    action_type_map = {
        "simulation_traffic_diversion": ActionType.TRAFFIC_DIVERSION,
        "simulation_signal_adjustment": ActionType.SIGNAL_ADJUSTMENT,
        "simulation_lane_control": ActionType.LANE_CONTROL,
        "simulation_dispatch_coordination": ActionType.DISPATCH_COORDINATION,
        "simulation_monitor": ActionType.MONITOR,
        "simulation_close": ActionType.CLOSE,
    }
    sim_action_type = action_type_map.get(action_type, ActionType.MONITOR)

    provider = get_demo_provider()

    # 构建模拟动作
    sim_action = SimAction(
        action_id=generate_action_id(),
        action_type=sim_action_type,
        target_ids=params.get("targetIds", params.get("target_ids", [])),
        parameters=params.get("parameters", params.get("params", {})),
        source="workflow",
        workflow_run_id=state.workflow_run_id,
        simulation=True,
    )

    try:
        # 获取 before snapshot
        before_snap = provider.get_snapshot(simulation_run_id)
        sim_action.before_snapshot_id = before_snap.snapshot_id

        # 执行动作
        new_snap = provider.apply_action(simulation_run_id, sim_action)

        # 构建改善指标
        affected_roads = sim_action.target_ids
        improvements = {}
        for rid in affected_roads:
            before_rs = before_snap.road_states.get(rid)
            after_rs = new_snap.road_states.get(rid)
            if before_rs and after_rs:
                improvements[rid] = {
                    "speedBefore": before_rs.avg_speed,
                    "speedAfter": after_rs.avg_speed,
                    "speedDelta": round(after_rs.avg_speed - before_rs.avg_speed, 1),
                    "queueBefore": before_rs.queue_length,
                    "queueAfter": after_rs.queue_length,
                    "queueDelta": round(after_rs.queue_length - before_rs.queue_length, 0),
                    "congestionBefore": before_rs.congestion_level.value,
                    "congestionAfter": after_rs.congestion_level.value,
                }

        # 更新 simulation_refs: latestSnapshotId → after
        state.simulation_refs["latestSnapshotId"] = new_snap.snapshot_id

        return {
            "action_id": sim_action.action_id,
            "action_type": action_type,
            "simulation": True,
            "status": "succeeded",
            "description": description,
            "decisionSnapshotId": decision_snapshot_id,
            "beforeSnapshotId": before_snap.snapshot_id,
            "afterSnapshotId": new_snap.snapshot_id,
            "improvements": improvements,
        }

    except Exception as e:
        return {
            "action_id": sim_action.action_id,
            "action_type": action_type,
            "simulation": True,
            "status": "failed",
            "error": str(e)[:500],
            "description": description,
            "decisionSnapshotId": decision_snapshot_id,
        }
