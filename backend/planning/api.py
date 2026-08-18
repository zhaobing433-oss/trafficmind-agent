"""
Adaptive Planning V1 API — Phase 17 Round 1

FastAPI Router（prefix="/planning"）。

端点：
  POST /planning/plans/preview      — 纯函数：build + validate，零持久化零副作用
  POST /planning/plans              — validate + materialize definition + persist（不执行）
  POST /planning/plans/{planId}/run — 创建 workflow run + 委托 WorkflowExecutor（SSE）
  GET  /planning/plans/{planId}     — frozen plan definition + runs[] execution projection

ToolPolicy / Approval 仍是唯一执行门禁。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from backend.agent.streaming import sse_event
from backend.planning.adapter import plan_to_definition
from backend.planning.context import build_planning_context
from backend.planning.models import Plan, PlanDefinitionStatus
from backend.planning.planner import build_plan
from backend.planning.status_projection import project_step_statuses
from backend.planning.validator import has_errors, validate_plan
from backend.workflow.executor import get_executor
from backend.workflow.repository import SQLiteWorkflowRepository

router = APIRouter(prefix="/planning", tags=["Adaptive Planning V1"])

# 惰性仓库：repository 方法内部会 init_workflow_tables()，避免 import 时触碰真实 DB
_repo = SQLiteWorkflowRepository()


# ═══════════════════════════════════════════════════════════════════════════════
# 请求模型
# ═══════════════════════════════════════════════════════════════════════════════


class PlanPreviewRequest(BaseModel):
    """计划构建请求（preview / create 共用）。"""
    goal: Optional[str] = ""
    event: Dict[str, Any] = {}
    ragEvidence: Optional[Dict[str, Any]] = None
    memoryContext: Optional[Dict[str, Any]] = None
    constraints: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(extra="allow")


class PlanRunRequest(BaseModel):
    """计划执行请求。"""
    event: Dict[str, Any] = {}
    sessionId: Optional[str] = ""
    eventThreadId: Optional[str] = ""
    triggeredBy: Optional[str] = "api"

    model_config = ConfigDict(extra="allow")


def _build_context(body: PlanPreviewRequest):
    return build_planning_context(
        raw_event=body.event,
        user_goal=body.goal or "",
        rag_evidence=body.ragEvidence,
        memory_context=body.memoryContext,
        constraints=body.constraints,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 端点
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/plans/preview", summary="构建并校验计划（纯函数，零持久化）")
async def preview_plan(body: PlanPreviewRequest):
    """只 build context + build Plan + validate + return，不写任何 DB / workflow 记录。"""
    ctx = _build_context(body)
    plan = build_plan(ctx)
    issues = validate_plan(plan)
    return {
        "plan": plan.to_dict(),
        "validationIssues": [i.to_dict() for i in issues],
        "valid": not has_errors(issues),
    }


@router.post("/plans", summary="物化计划为 WorkflowDefinition（不执行）")
async def create_plan(body: PlanPreviewRequest):
    """validate → materialize WorkflowDefinition → persist metadata。不执行。"""
    ctx = _build_context(body)
    plan = build_plan(ctx)
    plan.definitionStatus = PlanDefinitionStatus.VALIDATED

    issues = validate_plan(plan)
    if has_errors(issues):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "计划校验失败",
                "validationIssues": [i.to_dict() for i in issues],
            },
        )

    plan.definitionStatus = PlanDefinitionStatus.ACTIVE
    definition = plan_to_definition(plan)
    definition.metadata["validation"] = {
        "valid": True,
        "issueCount": len(issues),
        "issues": [i.to_dict() for i in issues],
    }
    _repo.save_definition(definition)

    return {
        "planId": plan.planId,
        "version": plan.version,
        "fingerprint": plan.planFingerprint,
        "definitionStatus": plan.definitionStatus.value,
    }


@router.post("/plans/{plan_id}/run", summary="执行物化计划（SSE）")
async def run_plan(plan_id: str, body: PlanRunRequest):
    """lookup materialized plan → revalidate 必要安全条件 → 委托 WorkflowExecutor。"""
    definition = _repo.get_definition(plan_id)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' 不存在（未物化）")

    plan = _load_plan_from_metadata(definition.metadata)
    if plan is None:
        raise HTTPException(status_code=400, detail="definition 缺少 plan 元数据")

    # revalidate 安全条件（ToolPolicy / 校验仍唯一权威）
    issues = validate_plan(plan)
    if has_errors(issues):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "计划安全校验失败，拒绝执行",
                "validationIssues": [i.to_dict() for i in issues],
            },
        )

    # Phase17 Round3: 创建 durable planning run（PENDING + driver_managed），
    # RunDriver 异步执行；HTTP/SSE 只 observe。
    run_id = _create_planning_run_record(plan_id, body)
    if run_id is None:
        raise HTTPException(status_code=400, detail="创建 planning run 失败")

    return StreamingResponse(
        _observe_run(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/plans/{plan_id}", summary="查询计划定义 + 执行投影")
async def get_plan(plan_id: str):
    """返回 frozen plan definition + runs[] execution projection。不 mutate plan 元数据。"""
    definition = _repo.get_definition(plan_id)
    if definition is None:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' 不存在")

    plan = _load_plan_from_metadata(definition.metadata)
    if plan is None:
        raise HTTPException(status_code=400, detail="definition 缺少 plan 元数据")

    runs = _repo.list_runs(definition_id=plan_id, limit=50)
    run_projections = []
    for run in runs:
        state = run.state if isinstance(run.state, dict) else {}
        pending = state.get("pendingApproval") or state.get("pending_approval")
        node_runs = _repo.get_node_runs(run.run_id)
        step_statuses = project_step_statuses(
            plan,
            node_runs,
            run_status=run.status.value,
            pending_approval=pending,
        )
        lineage = (state.get("executionLineage") or {})
        run_projections.append({
            "runId": run.run_id,
            "status": run.status.value,
            "version": run.version,
            "rootRunId": lineage.get("rootRunId"),
            "replannedFromRunId": state.get("replannedFromRunId"),
            "replannedFromVersion": state.get("replannedFromVersion"),
            "replannedToRunId": state.get("replannedToRunId"),
            "terminationReason": state.get("terminationReason"),
            "startedAt": run.started_at or None,
            "completedAt": run.completed_at or None,
            "budgetUsage": (lineage.get("budgetUsage") or {}),
            "budgetLimits": (lineage.get("budgetLimits") or {}),
            "stepStatuses": {k: v.value for k, v in step_statuses.items()},
        })

    # 返回 canonical 最新 revision 的 plan（latestVersion），而非 definition.metadata 的原始 v1
    latest_version = _repo.get_latest_version_number(plan_id)
    latest_plan = _get_plan_at_version(plan_id, latest_version) or plan

    return {
        "plan": latest_plan.to_dict(),
        "latestVersion": latest_version,
        "definitionId": definition.id,
        "runs": run_projections,
    }


@router.post("/runs/{run_id}/replan", summary="显式 deterministic replan（child continuation）")
async def replan_run(run_id: str):
    """对失败/拒绝的 run 发起 deterministic revision。幂等（已 replan 返回既有 child）。"""
    from backend.planning.continuation import PlanningContinuationCoordinator
    coordinator = PlanningContinuationCoordinator(_repo)
    result = coordinator.explicit_replan(run_id)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/runs/{run_id}/observations", summary="查询 run 的 observation audit")
async def list_observations(run_id: str):
    """从 durable workflow_events 重建 observation audit log（返回 observation payload）。"""
    run = _repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")
    events = _repo.list_observations(run_id)
    return {
        "runId": run_id,
        "observations": [e.payload if isinstance(e.payload, dict) else {} for e in events],
    }


@router.get("/plans", summary="列出 planning plans（分页）")
async def list_plans(
    page: int = 1,
    pageSize: int = 20,
    goalType: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
):
    """plan discovery。只返回 planning definitions。filter 在 SQL 侧先于分页。"""
    page = max(1, page)
    pageSize = min(100, max(1, pageSize))
    offset = (page - 1) * pageSize

    # filter（goalType/status/search）在 SQL 侧生效；只加载当前页，无 1000 硬上限
    total, definitions = _repo.list_planning_definitions_filtered(
        goal_type=goalType, status=status, search=search,
        limit=pageSize, offset=offset,
    )
    aggregates = _repo.batch_get_run_aggregates([d.id for d in definitions])

    items = []
    for d in definitions:
        plan = _load_plan_from_metadata(d.metadata)
        agg = aggregates.get(d.id, {})
        latest = agg.get("latest")
        # latestVersion = canonical 最新 revision（workflow_definition_versions MAX(version)），非最新 run 的 version
        latest_version = _repo.get_latest_version_number(d.id) or (plan.version if plan else 1)
        latest_plan = _get_plan_at_version(d.id, latest_version) or plan
        items.append({
            "planId": d.id,
            "goal": plan.goal if plan else d.name,
            "goalType": plan.goalType.value if plan else "",
            "latestVersion": latest_version,
            "latestFingerprint": latest_plan.planFingerprint if latest_plan else "",
            "createdAt": d.created_at or None,
            "updatedAt": d.updated_at or None,
            "executionCount": agg.get("executionCount", 0),
            "latestExecutionStatus": latest.get("status") if latest else None,
            "latestRootRunId": latest.get("rootRunId") if latest else None,
            "replanCount": agg.get("replanCount", 0),
        })

    return {"total": total, "page": page, "pageSize": pageSize, "plans": items}


@router.get("/plans/{plan_id}/diff", summary="版本 diff（deterministic）")
async def diff_plan(plan_id: str, fromVersion: int, toVersion: int):
    from_plan = _get_plan_at_version(plan_id, fromVersion)
    to_plan = _get_plan_at_version(plan_id, toVersion)
    if from_plan is None or to_plan is None:
        raise HTTPException(status_code=404, detail="版本不存在")
    from backend.planning.diff import compute_diff
    diff = compute_diff(from_plan, to_plan)
    return {"planId": plan_id, "fromVersion": fromVersion, "toVersion": toVersion, **diff}


@router.get("/runs/{run_id}/trajectory", summary="execution lineage trajectory metrics")
async def run_trajectory(run_id: str):
    run = _repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' 不存在")
    from backend.planning.trajectory import compute_trajectory
    return compute_trajectory(_repo, run_id)


def _get_plan_at_version(plan_id: str, version: int) -> Optional[Plan]:
    """从 version snapshot 提取 frozen Plan。"""
    ver = _repo.get_definition_version(plan_id, int(version))
    if ver is None:
        return None
    dj = ver.definition_json if isinstance(ver.definition_json, dict) else {}
    metadata = dj.get("metadata", {})
    if not metadata:
        metadata = dj
    return _load_plan_from_metadata(metadata)


# ═══════════════════════════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════════════════════════


def _load_plan_from_metadata(metadata: Dict[str, Any]) -> Optional[Plan]:
    """从 definition.metadata 反序列化 frozen plan。"""
    plan_raw = metadata.get("plan")
    if not plan_raw:
        return None
    if isinstance(plan_raw, str):
        try:
            plan_raw = json.loads(plan_raw)
        except Exception:
            return None
    try:
        return Plan.from_dict(plan_raw)
    except Exception:
        return None


def _auto_replan_if_needed(run_id: str) -> None:
    """machine failure 自动 replan（仅 planning-generated run；deny/reject 不自动）。"""
    try:
        from backend.planning.continuation import PlanningContinuationCoordinator
        coordinator = PlanningContinuationCoordinator(_repo)
        coordinator.auto_continue(run_id)
    except Exception:
        pass  # 自动 replan 失败不阻断主流程


def _create_planning_run_record(plan_id: str, body) -> Optional[str]:
    """创建 durable planning run（PENDING + driver_managed=1），不执行。

    返回 run_id；RunDriver 随后 claim + execute_created_run。
    """
    import copy

    from backend.planning.budget import new_lineage, set_lineage
    from backend.workflow.definition import DefinitionManager
    from backend.workflow.models import WorkflowRun, WorkflowRunStatus, generate_run_id
    from backend.workflow.state import TrafficWorkflowState

    try:
        mgr = DefinitionManager(_repo)
        definition = mgr.get_latest_definition(plan_id)
        if definition is None:
            return None
        issues = mgr.validate_for_execution(definition)
        if issues:
            return None
        version = mgr.create_version(definition, changelog="planning run")
        run_id = generate_run_id()
        state = TrafficWorkflowState(
            workflow_run_id=run_id, workflow_definition_id=plan_id,
            workflow_version=version.version,
            session_id=body.sessionId or "", event_thread_id=body.eventThreadId or "",
            current_event=body.event or {}, original_input=copy.deepcopy(body.event or {}),
            status=WorkflowRunStatus.PENDING, current_node=definition.entry_node_id,
        )
        run = WorkflowRun(
            run_id=run_id, definition_id=plan_id, version=version.version,
            session_id=body.sessionId or "", event_thread_id=body.eventThreadId or "",
            status=WorkflowRunStatus.PENDING, current_node_id=definition.entry_node_id,
            state=state.to_dict(), triggered_by=body.triggeredBy or "api",
        )
        set_lineage(run.state, new_lineage(run_id))
        # 原子创建 driver-managed run（driver_managed=1 单次落库，无 post-save mark 窗口）
        _repo.save_driver_managed_run(run)
        return run_id
    except Exception:
        import traceback
        traceback.print_exc()
        return None


async def _observe_run(run_id: str):
    """观察 run 状态直到 terminal（不拥有 execution lifecycle）。"""
    import asyncio

    yield sse_event("run_created", {"runId": run_id})
    last_status = ""
    for _ in range(1200):  # 最多 600s
        run = _repo.get_run(run_id)
        if run is None:
            break
        if run.status.value != last_status:
            last_status = run.status.value
            yield sse_event("run_status", {"runId": run_id, "status": run.status.value})
        if run.is_terminal():
            yield sse_event("done", {"runId": run_id, "status": run.status.value})
            return
        await asyncio.sleep(0.5)
    yield sse_event("done", {"runId": run_id, "status": last_status})


def _extract_run_id(sse_str: str) -> str:
    """从 SSE 字符串提取 workflow_started 的 runId。"""
    for line in sse_str.split("\n"):
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            try:
                data = json.loads(payload)
                if isinstance(data, dict) and data.get("runId"):
                    return data["runId"]
            except Exception:
                pass
    return ""


def _record_plan_lifecycle_events(run_id: str) -> None:
    """补写 plan_started + plan_completed/plan_failed 事件（run 已持久化后）。"""
    from datetime import datetime, timezone

    from backend.workflow.models import WorkflowEvent

    run = _repo.get_run(run_id)
    if run is None:
        return

    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    existing = _repo.list_events(run_id)
    seq = len(existing)

    start_evt = WorkflowEvent(
        event_id=f"wfevent_plan_{run_id}_start",
        run_id=run_id,
        event_type="plan_started",
        payload={"runId": run_id, "startedAt": run.started_at or ""},
        sequence=seq,
        created_at=run.started_at or _now(),
    )
    _repo.save_event(start_evt)

    evt_type = {
        "completed": "plan_completed",
        "failed": "plan_failed",
        "rejected": "plan_rejected",
        "cancelled": "plan_cancelled",
    }.get(run.status.value)
    if evt_type:
        end_evt = WorkflowEvent(
            event_id=f"wfevent_plan_{run_id}_end",
            run_id=run_id,
            event_type=evt_type,
            payload={"runId": run_id, "status": run.status.value},
            sequence=seq + 1,
        )
        _repo.save_event(end_evt)
