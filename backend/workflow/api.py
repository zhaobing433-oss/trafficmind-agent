"""
Workflow V1 API — Phase 12

FastAPI Router，提供 Workflow 相关的 REST + SSE 接口。

端点：
  GET    /workflow/definitions                        — 列出所有 Definition
  GET    /workflow/definitions/{definitionId}          — 获取单个 Definition
  POST   /workflow/runs                               — 创建并启动 Run（SSE 流式）
  GET    /workflow/runs/{runId}                        — 查询 Run 详情
  GET    /workflow/runs/{runId}/trace                  — 查询 Run Trace
  POST   /workflow/runs/{runId}/resume                 — 恢复暂停的 Run（SSE 流式）
  POST   /workflow/runs/{runId}/cancel                 — 取消 Run
  POST   /workflow/runs/{runId}/retry                  — 重试失败节点
  POST   /workflow/runs/{runId}/approvals/{approvalId} — 处理审批
  GET    /workflow/runs/{runId}/stream                 — SSE 状态流
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from backend.agent.streaming import sse_event, sse_error
from backend.workflow.models import (
    ApprovalDecision,
    DefinitionStatus,
    WorkflowApproval,
    WorkflowRunStatus,
)
from backend.workflow.state import TrafficWorkflowState
from backend.workflow.definition import DefinitionManager
from backend.workflow.repository import SQLiteWorkflowRepository, init_workflow_tables
from backend.workflow.executor import get_executor

# ═══════════════════════════════════════════════════════════════════════════════
# Router
# ═══════════════════════════════════════════════════════════════════════════════

router = APIRouter(prefix="/workflow", tags=["Workflow V1"])

# 确保表已初始化
init_workflow_tables()

# 全局 Repository 和 Manager
_repo = SQLiteWorkflowRepository()
_def_manager = DefinitionManager(_repo)


# ═══════════════════════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════════════════════


class StartRunRequest(BaseModel):
    """启动 Workflow Run 请求。"""
    definitionId: str
    sessionId: Optional[str] = ""
    eventThreadId: Optional[str] = ""
    event: Dict[str, Any] = {}
    triggeredBy: Optional[str] = "api"

    model_config = ConfigDict(extra="allow")


class ResumeRunRequest(BaseModel):
    """恢复 Workflow Run 请求。"""
    pass  # 当前不需要额外参数


class RetryNodeRequest(BaseModel):
    """重试失败节点请求。"""
    nodeId: str


class ApprovalRequest(BaseModel):
    """审批请求。"""
    action: str  # "approve", "reject", "edit_and_approve"
    reviewer: Optional[str] = ""
    comment: Optional[str] = ""
    editedActions: Optional[List[Dict[str, Any]]] = None

    model_config = ConfigDict(extra="allow")


# ═══════════════════════════════════════════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/definitions", summary="列出 Workflow 定义")
async def list_definitions(
    status: Optional[str] = Query(None, description="按状态筛选: draft/active/deprecated"),
):
    """列出所有 WorkflowDefinition。可按状态筛选。"""
    definitions = _repo.list_definitions(status=status)
    return {
        "total": len(definitions),
        "definitions": [d.to_dict() for d in definitions],
    }


@router.get("/definitions/{definition_id}", summary="获取 Workflow 定义详情")
async def get_definition(definition_id: str):
    """获取单个 WorkflowDefinition 详情，包含所有版本。"""
    definition = _repo.get_definition(definition_id)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Definition '{definition_id}' 不存在")

    versions = _repo.list_definition_versions(definition_id)
    return {
        "definition": definition.to_dict(),
        "versions": [v.to_dict() for v in versions],
        "versionCount": len(versions),
    }


@router.post("/runs", summary="创建并启动 Workflow Run（SSE 流式）")
async def start_run(body: StartRunRequest):
    """创建 Workflow Run 并以 SSE 流式执行。

    返回 SSE 事件流：
      workflow_started → node_started* → node_completed* →
      [approval_required] → [workflow_paused] →
      workflow_completed → done
    """
    executor = get_executor()

    # 获取 definition 名称（用于 SSE）
    definition = _repo.get_definition(body.definitionId)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Definition '{body.definitionId}' 不存在")

    async def _stream():
        try:
            async for sse_str in executor.start(
                definition_id=body.definitionId,
                session_id=body.sessionId or "",
                event_thread_id=body.eventThreadId or "",
                initial_event=body.event,
                triggered_by=body.triggeredBy or "api",
            ):
                yield sse_str
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield sse_event("error", {
                "message": str(e).split("\n")[0][:200],
                "details": "An internal error occurred during workflow execution."
            })
            yield sse_event("done", {"error": True})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs/{run_id}", summary="查询 Workflow Run 详情")
async def get_run(run_id: str):
    """查询单个 Workflow Run 的完整详情，包含状态、节点执行记录和 Trace。"""
    run = _repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")

    node_runs = _repo.get_node_runs(run_id)
    events = _repo.list_events(run_id)
    action_records = _repo.list_action_records(run_id)

    # 解析 state
    state = run.state
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except Exception:
            state = {}

    return {
        "run": run.to_dict(),
        "state": state,
        "nodeRuns": [nr.to_dict() for nr in node_runs],
        "events": [e.to_dict() for e in events],
        "actionRecords": [a.to_dict() for a in action_records],
        "nodeCount": len(node_runs),
        "eventCount": len(events),
    }


@router.get("/runs/{run_id}/trace", summary="查询 Workflow Run Trace")
async def get_run_trace(run_id: str):
    """查询 Workflow Run 的完整 Trace：节点、事件、审批、动作记录。"""
    run = _repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")

    node_runs = _repo.get_node_runs(run_id)
    events = _repo.list_events(run_id)
    action_records = _repo.list_action_records(run_id)

    # 构建时间线
    timeline = []
    for e in sorted(events, key=lambda x: x.sequence):
        timeline.append({
            "sequence": e.sequence,
            "eventType": e.event_type,
            "nodeId": e.node_id,
            "payload": e.payload,
            "createdAt": e.created_at,
        })

    return {
        "runId": run_id,
        "definitionId": run.definition_id,
        "version": run.version,
        "status": run.status.value,
        "currentNodeId": run.current_node_id,
        "timeline": timeline,
        "nodeRuns": [
            {
                "nodeId": nr.node_id,
                "nodeType": nr.node_type.value,
                "status": nr.status.value,
                "attempt": nr.attempt,
                "error": nr.error,
                "startedAt": nr.started_at,
                "completedAt": nr.completed_at,
            }
            for nr in node_runs
        ],
        "actionRecords": [a.to_dict() for a in action_records],
        "ragTraceIds": [],
        "agentRunIds": [],
        "approvalIds": [],
        "actionRecordIds": [a.action_id for a in action_records],
    }


@router.post("/runs/{run_id}/resume", summary="恢复 Workflow Run（SSE 流式）")
async def resume_run(run_id: str, body: ResumeRunRequest = None):
    """恢复暂停的 Workflow Run 执行（SSE 流式）。

    仅在 Run 状态为 paused 或 awaiting_approval 时可恢复。
    """
    run = _repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")

    executor = get_executor()

    async def _stream():
        try:
            async for sse_str in executor.resume(run_id=run_id):
                yield sse_str
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield sse_event("error", {
                "message": str(e).split("\n")[0][:200],
            })
            yield sse_event("done", {"error": True})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/runs/{run_id}/cancel", summary="取消 Workflow Run")
async def cancel_run(run_id: str):
    """取消正在执行的 Workflow Run。"""
    executor = get_executor()
    result = await executor.cancel(run_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/runs/{run_id}/retry", summary="重试失败节点")
async def retry_node(run_id: str, body: RetryNodeRequest):
    """重试 Workflow Run 中失败的节点。"""
    executor = get_executor()
    result = await executor.retry_node(run_id, body.nodeId)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/runs/{run_id}/approvals/{approval_id}", summary="处理审批")
async def process_approval(run_id: str, approval_id: str, body: ApprovalRequest):
    """处理人工审批。

    action 可选值:
      - approve: 批准，继续执行后续节点
      - reject: 驳回，Workflow 终止
      - edit_and_approve: 编辑后批准
    """
    executor = get_executor()

    action = body.action
    if action == "approve":
        result = await executor.approve(
            run_id,
            reviewer=body.reviewer or "",
            comment=body.comment or "",
        )
    elif action == "reject":
        result = await executor.reject(
            run_id,
            reviewer=body.reviewer or "",
            comment=body.comment or "",
        )
    elif action == "edit_and_approve":
        result = await executor.edit_and_approve(
            run_id,
            edited_actions=body.editedActions or [],
            reviewer=body.reviewer or "",
            comment=body.comment or "",
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"无效的审批动作 '{action}'。有效值: approve, reject, edit_and_approve",
        )

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/runs/{run_id}/stream", summary="Workflow Run SSE 状态流")
@router.post("/runs/{run_id}/stream", summary="Workflow Run SSE 状态流 (POST)")
async def get_run_stream(run_id: str):
    """获取 Workflow Run 的当前状态 SSE 流。

    用于前端获取 Run 的实时状态更新。
    如果 Run 已完成，返回一个 done 事件后关闭。
    """
    run = _repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")

    async def _stream():
        # 发送当前状态
        yield sse_event("run_status", {
            "runId": run_id,
            "status": run.status.value,
            "currentNodeId": run.current_node_id,
            "definitionId": run.definition_id,
            "version": run.version,
        })

        # 发送节点执行记录
        node_runs = _repo.get_node_runs(run_id)
        for nr in node_runs:
            yield sse_event("node_status", nr.to_dict())

        # 发送 action 记录
        action_records = _repo.list_action_records(run_id)
        for ar in action_records:
            yield sse_event("action_status", ar.to_dict())

        yield sse_event("done", {"runId": run_id})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
