"""
ExecutionBudget / ExecutionLineage — Phase 17 Round 2

预算属于 execution lineage（rootRunId），非 revision/child。child 继承 parent
cumulative usage；独立新 root run 初始化全新 budget。

持久化 source-of-truth：workflow_runs.state_json["executionLineage"]。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

LINEAGE_KEY = "executionLineage"

# stepsUsed 只计算 semantic PlanStep；结构节点不计
from backend.workflow.models import NodeType  # noqa: E402

BUDGETED_NODE_TYPES = frozenset({
    NodeType.VALIDATE_EVENT,
    NodeType.RULE_ROUTER,
    NodeType.RAG_RETRIEVE,
    NodeType.MEMORY_CONTEXT,
    NodeType.AGENT_TASK,
    NodeType.EVIDENCE_EVALUATE,
    NodeType.RISK_GATE,
    NodeType.ACTION,
})


def should_count_step(node_type) -> bool:
    """判断节点是否计入 stepsUsed（semantic PlanStep）。"""
    return node_type in BUDGETED_NODE_TYPES


class ActiveTimeTracker:
    """active execution time 累计（不含 awaiting/暂停/离线 idle）。

    维护一个 open segment：open_segment 后到 close_segment 之间计 active。
    """

    def __init__(self, active_elapsed: float = 0.0):
        self.active_elapsed = float(active_elapsed)
        self._segment_start: Optional[float] = None

    def open_segment(self, now_unix: float) -> None:
        self._segment_start = now_unix

    def close_segment(self, now_unix: float) -> None:
        if self._segment_start is not None:
            self.active_elapsed += max(0.0, now_unix - self._segment_start)
            self._segment_start = None

    @property
    def is_active(self) -> bool:
        return self._segment_start is not None

    def to_dict(self) -> Dict[str, Any]:
        return {"activeElapsed": self.active_elapsed, "segmentStart": self._segment_start}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ActiveTimeTracker":
        if not d:
            return cls()
        t = cls(float(d.get("activeElapsed", 0.0)))
        t._segment_start = d.get("segmentStart")
        return t


@dataclass
class ExecutionBudgetLimits:
    maxSteps: int = 100
    maxReplans: int = 3
    maxRetries: int = 2
    maxToolCalls: int = 5
    maxLlmCalls: int = 5
    maxTotalSeconds: int = 300

    def to_dict(self) -> Dict[str, Any]:
        return {
            "maxSteps": self.maxSteps,
            "maxReplans": self.maxReplans,
            "maxRetries": self.maxRetries,
            "maxToolCalls": self.maxToolCalls,
            "maxLlmCalls": self.maxLlmCalls,
            "maxTotalSeconds": self.maxTotalSeconds,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExecutionBudgetLimits":
        return cls(
            maxSteps=int(d.get("maxSteps", 100)),
            maxReplans=int(d.get("maxReplans", 3)),
            maxRetries=int(d.get("maxRetries", 2)),
            maxToolCalls=int(d.get("maxToolCalls", 5)),
            maxLlmCalls=int(d.get("maxLlmCalls", 5)),
            maxTotalSeconds=int(d.get("maxTotalSeconds", 300)),
        )


@dataclass
class ExecutionBudgetUsage:
    stepsUsed: int = 0
    replansUsed: int = 0
    retriesUsed: int = 0
    toolCallsUsed: int = 0
    llmCallsUsed: int = 0
    activeElapsedSeconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stepsUsed": self.stepsUsed,
            "replansUsed": self.replansUsed,
            "retriesUsed": self.retriesUsed,
            "toolCallsUsed": self.toolCallsUsed,
            "llmCallsUsed": self.llmCallsUsed,
            "activeElapsedSeconds": self.activeElapsedSeconds,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExecutionBudgetUsage":
        return cls(
            stepsUsed=int(d.get("stepsUsed", 0)),
            replansUsed=int(d.get("replansUsed", 0)),
            retriesUsed=int(d.get("retriesUsed", 0)),
            toolCallsUsed=int(d.get("toolCallsUsed", 0)),
            llmCallsUsed=int(d.get("llmCallsUsed", 0)),
            activeElapsedSeconds=float(d.get("activeElapsedSeconds", 0.0)),
        )


@dataclass
class ExecutionLineage:
    rootRunId: str
    budgetLimits: ExecutionBudgetLimits = field(default_factory=ExecutionBudgetLimits)
    budgetUsage: ExecutionBudgetUsage = field(default_factory=ExecutionBudgetUsage)
    loopGuard: Dict[str, Any] = field(default_factory=dict)
    rejectionConstraints: List[Dict[str, Any]] = field(default_factory=list)
    policyDenyConstraints: List[Dict[str, Any]] = field(default_factory=list)
    activeSegmentStart: Optional[float] = None  # 当前 active execution segment 起点（unix）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rootRunId": self.rootRunId,
            "budgetLimits": self.budgetLimits.to_dict(),
            "budgetUsage": self.budgetUsage.to_dict(),
            "loopGuard": self.loopGuard,
            "rejectionConstraints": list(self.rejectionConstraints),
            "policyDenyConstraints": list(self.policyDenyConstraints),
            "activeSegmentStart": self.activeSegmentStart,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExecutionLineage":
        if not d:
            return cls(rootRunId="")
        return cls(
            rootRunId=d.get("rootRunId", ""),
            budgetLimits=ExecutionBudgetLimits.from_dict(d.get("budgetLimits", {})),
            budgetUsage=ExecutionBudgetUsage.from_dict(d.get("budgetUsage", {})),
            loopGuard=dict(d.get("loopGuard", {})),
            rejectionConstraints=list(d.get("rejectionConstraints", [])),
            policyDenyConstraints=list(d.get("policyDenyConstraints", [])),
            activeSegmentStart=d.get("activeSegmentStart"),
        )


def new_lineage(root_run_id: str, limits: Optional[ExecutionBudgetLimits] = None) -> ExecutionLineage:
    """初始化新 execution lineage（独立 root run）。"""
    return ExecutionLineage(rootRunId=root_run_id, budgetLimits=limits or ExecutionBudgetLimits())


def inherit_lineage(parent: ExecutionLineage) -> ExecutionLineage:
    """child 继承 parent：同 rootRunId + 同 cumulative usage/constraints/loop。"""
    return ExecutionLineage(
        rootRunId=parent.rootRunId,
        budgetLimits=ExecutionBudgetLimits(**parent.budgetLimits.to_dict()),
        budgetUsage=ExecutionBudgetUsage(**parent.budgetUsage.to_dict()),
        loopGuard=dict(parent.loopGuard),
        rejectionConstraints=list(parent.rejectionConstraints),
        policyDenyConstraints=list(parent.policyDenyConstraints),
    )


# ── pure reservation（不落库，操作 ExecutionLineage）────────────────────────

def _exhausted(limits: ExecutionBudgetLimits, usage: ExecutionBudgetUsage) -> bool:
    return (
        usage.stepsUsed >= limits.maxSteps
        or usage.toolCallsUsed >= limits.maxToolCalls
        or usage.llmCallsUsed >= limits.maxLlmCalls
        or usage.replansUsed >= limits.maxReplans
        or usage.activeElapsedSeconds >= limits.maxTotalSeconds
    )


def reserve_step(lineage: ExecutionLineage) -> bool:
    if _exhausted(lineage.budgetLimits, lineage.budgetUsage):
        return False
    lineage.budgetUsage.stepsUsed += 1
    return True


def reserve_tool_call(lineage: ExecutionLineage) -> bool:
    if lineage.budgetUsage.toolCallsUsed >= lineage.budgetLimits.maxToolCalls:
        return False
    lineage.budgetUsage.toolCallsUsed += 1
    return True


def reserve_llm_call(lineage: ExecutionLineage) -> bool:
    if lineage.budgetUsage.llmCallsUsed >= lineage.budgetLimits.maxLlmCalls:
        return False
    lineage.budgetUsage.llmCallsUsed += 1
    return True


def reserve_retry(lineage: ExecutionLineage) -> bool:
    if lineage.budgetUsage.retriesUsed >= lineage.budgetLimits.maxRetries:
        return False
    lineage.budgetUsage.retriesUsed += 1
    return True


def reserve_replan(lineage: ExecutionLineage) -> bool:
    if lineage.budgetUsage.replansUsed >= lineage.budgetLimits.maxReplans:
        return False
    lineage.budgetUsage.replansUsed += 1
    return True


# ── durable reservation（repository 集成，dispatch 前落库）───────────────────

def get_lineage(run_state: Dict[str, Any]) -> ExecutionLineage:
    return ExecutionLineage.from_dict(run_state.get(LINEAGE_KEY, {}) if run_state else {})


def set_lineage(run_state: Dict[str, Any], lineage: ExecutionLineage) -> None:
    run_state[LINEAGE_KEY] = lineage.to_dict()


def _reserve_durable(repository, run_id: str, reserve_fn) -> bool:
    """通用 durable reservation：读 run → reserve → save_run。"""
    run = repository.get_run(run_id)
    if run is None:
        return False
    state = run.state if isinstance(run.state, dict) else {}
    lineage = get_lineage(state)
    if not lineage.rootRunId:
        return False  # 未初始化 lineage → 不保留（fail-closed）
    if not reserve_fn(lineage):
        return False
    set_lineage(state, lineage)
    run.state = state
    try:
        repository.save_run(run)
    except Exception:
        return False
    return True


def reserve_tool_call_durable(repository, run_id: str) -> bool:
    """dispatch 前 durable reservation。返回 True 表示已保留（可 dispatch）。"""
    return _reserve_durable(repository, run_id, reserve_tool_call)


def reserve_step_durable(repository, run_id: str) -> bool:
    """stepsUsed durable reservation（semantic PlanStep 执行后）。"""
    return _reserve_durable(repository, run_id, reserve_step)


def reserve_retry_durable(repository, run_id: str) -> bool:
    """retriesUsed durable reservation。"""
    return _reserve_durable(repository, run_id, reserve_retry)


def reserve_llm_call_durable(repository, run_id: str) -> bool:
    """llmCallsUsed durable reservation。"""
    return _reserve_durable(repository, run_id, reserve_llm_call)


def open_active_segment(lineage: ExecutionLineage, now_unix: float) -> None:
    """打开 active execution segment（不计 wait/offline idle）。"""
    lineage.activeSegmentStart = now_unix


def close_active_segment(lineage: ExecutionLineage, now_unix: float) -> None:
    """关闭 active segment，累加到 activeElapsedSeconds。"""
    if lineage.activeSegmentStart is not None:
        lineage.budgetUsage.activeElapsedSeconds += max(0.0, now_unix - lineage.activeSegmentStart)
        lineage.activeSegmentStart = None


def active_budget_exhausted(lineage: ExecutionLineage) -> bool:
    """activeElapsedSeconds 是否已达 maxTotalSeconds。"""
    return lineage.budgetUsage.activeElapsedSeconds >= lineage.budgetLimits.maxTotalSeconds
