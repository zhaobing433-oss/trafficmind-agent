"""
Workflow SSE 流式事件 — Phase 12

Workflow 执行过程中的标准 SSE 事件类型。

事件列表（与 Collaboration SSE 事件风格一致）：
  workflow_started    — Workflow 启动
  node_started        — 节点开始执行
  node_completed      — 节点成功完成
  node_failed         — 节点执行失败
  workflow_paused     — Workflow 暂停（等待条件）
  approval_required   — 需要人工审批
  workflow_resumed    — Workflow 恢复执行
  action_started      — 外部动作开始
  action_completed    — 外部动作完成
  workflow_completed  — Workflow 完成
  workflow_cancelled  — Workflow 取消
  error               — 一般错误
  done                — 流结束（恰好一次）
"""

from typing import Any, Dict

from backend.agent.streaming import sse_event as _sse_event


def workflow_started(run_id: str, definition_id: str, version: int,
                     session_id: str = "", entry_node_id: str = "") -> str:
    """Workflow 启动事件。"""
    return _sse_event("workflow_started", {
        "runId": run_id,
        "definitionId": definition_id,
        "version": version,
        "sessionId": session_id,
        "entryNodeId": entry_node_id,
    })


def node_started(run_id: str, node_id: str, node_type: str,
                 label: str = "") -> str:
    """节点开始事件。"""
    return _sse_event("node_started", {
        "runId": run_id,
        "nodeId": node_id,
        "nodeType": node_type,
        "label": label,
    })


def node_completed(run_id: str, node_id: str, node_type: str,
                   attempt: int = 1, result: Dict[str, Any] = None) -> str:
    """节点完成事件。"""
    return _sse_event("node_completed", {
        "runId": run_id,
        "nodeId": node_id,
        "nodeType": node_type,
        "attempt": attempt,
        "result": result or {},
    })


def node_failed(run_id: str, node_id: str, node_type: str,
                error: str = "", attempt: int = 1) -> str:
    """节点失败事件。"""
    return _sse_event("node_failed", {
        "runId": run_id,
        "nodeId": node_id,
        "nodeType": node_type,
        "error": error,
        "attempt": attempt,
    })


def workflow_paused(run_id: str, node_id: str, reason: str = "") -> str:
    """Workflow 暂停事件。"""
    return _sse_event("workflow_paused", {
        "runId": run_id,
        "currentNodeId": node_id,
        "reason": reason,
    })


def approval_required(run_id: str, approval_id: str, node_id: str,
                      proposed_actions: list = None) -> str:
    """需要人工审批事件。"""
    return _sse_event("approval_required", {
        "runId": run_id,
        "approvalId": approval_id,
        "nodeId": node_id,
        "proposedActions": proposed_actions or [],
    })


def workflow_resumed(run_id: str, node_id: str = "") -> str:
    """Workflow 恢复事件。"""
    return _sse_event("workflow_resumed", {
        "runId": run_id,
        "currentNodeId": node_id,
    })


def action_started(run_id: str, node_id: str, action_type: str,
                   action_id: str = "") -> str:
    """外部动作开始事件。"""
    return _sse_event("action_started", {
        "runId": run_id,
        "nodeId": node_id,
        "actionType": action_type,
        "actionId": action_id,
    })


def action_completed(run_id: str, node_id: str, action_type: str,
                     action_id: str = "", status: str = "succeeded") -> str:
    """外部动作完成事件。"""
    return _sse_event("action_completed", {
        "runId": run_id,
        "nodeId": node_id,
        "actionType": action_type,
        "actionId": action_id,
        "status": status,
    })


def workflow_completed(run_id: str, status: str = "completed") -> str:
    """Workflow 完成事件。"""
    return _sse_event("workflow_completed", {
        "runId": run_id,
        "status": status,
    })


def workflow_cancelled(run_id: str, reason: str = "") -> str:
    """Workflow 取消事件。"""
    return _sse_event("workflow_cancelled", {
        "runId": run_id,
        "reason": reason,
    })


def workflow_rejected(run_id: str, reason: str = "") -> str:
    """Workflow 人工驳回事件。"""
    return _sse_event("workflow_rejected", {
        "runId": run_id,
        "reason": reason or "人工审批驳回",
    })


def workflow_error(run_id: str, message: str, node_id: str = "") -> str:
    """Workflow 错误事件。"""
    return _sse_event("error", {
        "runId": run_id,
        "nodeId": node_id,
        "message": message,
    })


def workflow_done(run_id: str, status: str = "completed",
                  error: bool = False) -> str:
    """Workflow 流结束事件（恰好一次）。"""
    data: Dict[str, Any] = {"runId": run_id, "status": status}
    if error:
        data["error"] = True
    return _sse_event("done", data)
