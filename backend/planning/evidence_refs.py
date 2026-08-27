"""
Evidence Reference — Phase 19 Round 1

namespaced durable reference：`namespace:key`。

关键不变量：
  - 只引用 durable primary key / stable logical key
  - 绝不引用 prompt 内临时数组下标（restart 后会错位）
  - ref 本身不含正文、不含 secret，只是指针
"""

from __future__ import annotations

from typing import Optional, Tuple

# ── namespace 常量（与 durable 存储一一对应）──────────────────────────────
NS_NODE = "node"            # workflow_node_runs（logical key = runId+nodeId）
NS_NODE_OUTPUT = "nodeout"  # state_json.nodeOutputs[nodeId]
NS_EVENT = "event"          # workflow_events.event_id
NS_OBSERVATION = "obs"      # workflow_events(observation_recorded).payload.observationId
NS_ACTION = "action"        # workflow_action_records.action_id
NS_IDEMPOTENCY = "idem"     # workflow_action_records.idempotency_key（UNIQUE）
NS_APPROVAL = "approval"    # workflow_approvals.approval_id
NS_AGENT = "agent"          # state_json.agentOutputs[agentName]
NS_RAG_TRACE = "ragtrace"   # rag_traces.trace_id
NS_MEMORY = "mem"           # memory_items.id
NS_SIMULATION = "sim"       # simulation_runs.run_id
NS_SIM_SNAPSHOT = "simsnap"  # simulation_snapshots.snapshot_id
NS_RISK = "risk"            # state_json.riskAssessment
NS_ERROR = "err"            # state_json.errors（key = nodeId+attempt，非 list index）
NS_POLICY = "policy"        # state_json.auditEvents 中 ToolPolicy 决策痕迹

ALL_NAMESPACES = (
    NS_NODE, NS_NODE_OUTPUT, NS_EVENT, NS_OBSERVATION, NS_ACTION, NS_IDEMPOTENCY,
    NS_APPROVAL, NS_AGENT, NS_RAG_TRACE, NS_MEMORY, NS_SIMULATION, NS_SIM_SNAPSHOT,
    NS_RISK, NS_ERROR, NS_POLICY,
)


def make_ref(namespace: str, *parts: str) -> str:
    """构造 `namespace:key`（多段 key 用 ':' 连接）。

    Args:
        namespace: ALL_NAMESPACES 之一
        *parts: 组成 durable key 的片段（不得为空）

    Returns:
        namespaced reference 字符串

    Raises:
        ValueError: namespace 非法或 parts 为空
    """
    if namespace not in ALL_NAMESPACES:
        raise ValueError(f"未知 evidence namespace: {namespace}")
    cleaned = [str(p) for p in parts if str(p) != ""]
    if not cleaned:
        raise ValueError(f"evidence ref '{namespace}' 缺少 key")
    return namespace + ":" + ":".join(cleaned)


def parse_ref(ref: str) -> Tuple[str, str]:
    """拆分为 (namespace, key)。非法 ref 抛 ValueError。"""
    if ":" not in ref:
        raise ValueError(f"非法 evidence ref（缺少 namespace）: {ref}")
    ns, key = ref.split(":", 1)
    if ns not in ALL_NAMESPACES:
        raise ValueError(f"未知 evidence namespace: {ns}")
    if not key:
        raise ValueError(f"evidence ref '{ref}' 缺少 key")
    return ns, key


def is_valid_ref(ref: str) -> bool:
    """是否为合法 namespaced ref（不抛异常）。"""
    try:
        parse_ref(ref)
        return True
    except ValueError:
        return False


# ── 具体构造器（避免各处手拼字符串）────────────────────────────────────────

def node_ref(run_id: str, node_id: str) -> str:
    return make_ref(NS_NODE, run_id, node_id)


def node_output_ref(run_id: str, node_id: str) -> str:
    return make_ref(NS_NODE_OUTPUT, run_id, node_id)


def event_ref(event_id: str) -> str:
    return make_ref(NS_EVENT, event_id)


def observation_ref(observation_id: str) -> str:
    return make_ref(NS_OBSERVATION, observation_id)


def action_ref(action_id: str) -> str:
    return make_ref(NS_ACTION, action_id)


def idempotency_ref(idempotency_key: str) -> str:
    return make_ref(NS_IDEMPOTENCY, idempotency_key)


def approval_ref(approval_id: str) -> str:
    return make_ref(NS_APPROVAL, approval_id)


def agent_ref(run_id: str, agent_name: str) -> str:
    return make_ref(NS_AGENT, run_id, agent_name)


def rag_trace_ref(trace_id: str) -> str:
    return make_ref(NS_RAG_TRACE, trace_id)


def memory_ref(memory_item_id: str) -> str:
    return make_ref(NS_MEMORY, memory_item_id)


def simulation_ref(sim_run_id: str) -> str:
    return make_ref(NS_SIMULATION, sim_run_id)


def sim_snapshot_ref(snapshot_id: str) -> str:
    return make_ref(NS_SIM_SNAPSHOT, snapshot_id)


def risk_ref(run_id: str) -> str:
    return make_ref(NS_RISK, run_id)


def error_ref(run_id: str, node_id: str, attempt: int) -> str:
    """state_json.errors 引用（key = nodeId+attempt，restart-safe，非 list index）。"""
    return make_ref(NS_ERROR, run_id, node_id or "unknown", str(attempt))


def policy_ref(run_id: str, node_id: str, event_type: str) -> str:
    """ToolPolicy 决策痕迹引用（state_json.auditEvents）。"""
    return make_ref(NS_POLICY, run_id, node_id or "unknown", event_type)


def ref_namespace(ref: str) -> Optional[str]:
    """返回 ref 的 namespace；非法 ref 返回 None。"""
    try:
        return parse_ref(ref)[0]
    except ValueError:
        return None
