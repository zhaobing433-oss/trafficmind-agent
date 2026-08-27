"""
Decision Context Assembler — Phase 19 Round 1

durable rows → normalize → SourceProjection[] → rank → budget → pack → DecisionContext。

关键不变量：
  - 纯函数：无 provider 调用、无 budget claim、无持久化写入、不改 run.status
  - 无 LLM 压缩：所有 summary 均为确定性字段投影 / 截断
  - collector 与 SourceSnapshotDigest 共用同一份 SourceProjection[]，
    因此「same digest ⇒ same normalized input ⇒ same selection ⇒ same context」
  - allowlist 优于事后 regex scrub：secret 字段从不进入 normalizedFields
  - T3 正文（RAG body）永不进入 prompt，只保留 ref + 短投影
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from backend.planning import evidence_refs as refs
from backend.planning.decision_context import (
    ASSEMBLER_VERSION,
    ContextBudget,
    DecisionContext,
    DecisionType,
    EvidenceRef,
    ObservationView,
    SourceProjection,
    TRUST_ORDINAL,
    TrustClass,
    compute_source_snapshot_digest,
    content_hash,
    empty_decision_context,
)

# ── 12 类 collector source ────────────────────────────────────────────────
SOURCE_NODE_RUN = "node_run"
SOURCE_NODE_OUTPUT = "node_output"
SOURCE_EVENT = "event"
SOURCE_ACTION = "action"
SOURCE_APPROVAL = "approval"
SOURCE_AGENT_OUTPUT = "agent_output"
SOURCE_RISK = "risk"
SOURCE_POLICY_AUDIT = "policy_audit"
SOURCE_RAG_TRACE = "rag_trace"
SOURCE_MEMORY = "memory"
SOURCE_SIMULATION = "simulation"
SOURCE_ERROR = "error"

ALL_SOURCE_TYPES: Tuple[str, ...] = (
    SOURCE_NODE_RUN, SOURCE_NODE_OUTPUT, SOURCE_EVENT, SOURCE_ACTION,
    SOURCE_APPROVAL, SOURCE_AGENT_OUTPUT, SOURCE_RISK, SOURCE_POLICY_AUDIT,
    SOURCE_RAG_TRACE, SOURCE_MEMORY, SOURCE_SIMULATION, SOURCE_ERROR,
)

#: 明确排除的 state/DB 字段（secret 边界 + T3 正文 + 已废弃字段）
EXCLUDED_FIELDS: Tuple[str, ...] = (
    "params_json",        # action 参数可能内嵌 webhook token
    "originalInput",      # 原始用户自由文本（T4），已由 currentEvent 归一化取代
    "content",            # RAG chunk 正文
    "contextual_content",  # RAG 带上下文正文
    "stableFacts",        # 声明但从未写入
    "dynamicObservations",  # 声明但从未写入
    "evidenceRefs",       # state_json.evidenceRefs —— R1 不读不写
)

#: state_json.auditEvents 中属于 ToolPolicy 决策痕迹的 eventType
POLICY_AUDIT_EVENT_TYPES = ("tool_denied", "tool_approval_required", "tool_allowed")

#: action_records.result_json 中允许携带**取值**的键。
#: 其余键（尤其通用 action 分支回填的 "params"）只保留键名。
ACTION_RESULT_ALLOWED_KEYS: Tuple[str, ...] = (
    "sent", "channel", "saved", "eventId", "status", "note",
    "simulation", "dispatched", "cancelled",
    "snapshotId", "simulationRunId", "error",
)

#: node_run 中被视为「已完成」的状态
_SUCCEEDED = "succeeded"

#: unknown-key 投影（otherKeys / outputKeys）的固定上限：
#: 1000 个未知键 → 只保留排序后的前 32 个键名，绝不收集全部键名。
MAX_OTHER_KEYS = 32


def _truncate(text: str, cap: int) -> Tuple[str, bool]:
    """确定性截断。返回 (文本, 是否被截断)。"""
    s = "" if text is None else str(text)
    if len(s) <= cap:
        return s, False
    return s[:cap], True


def _project(value: Any, cap: int) -> Tuple[str, bool]:
    """结构化值 → 有界字符串投影（无 LLM）。

    只允许用于**已经过 allowlist 的**结构；不得直接投影原始 durable 行，
    否则等同于「整体 dump 后截断」，无法构成 secret 边界。
    """
    from backend.planning.decision_context import canonical_json
    raw = value if isinstance(value, str) else canonical_json(value)
    return _truncate(raw, cap)


#: URL 中的凭据形态（webhook token / basic auth / 敏感 query 参数）
_CREDENTIAL_PATTERNS = (
    re.compile(r"://[^/\s:@]+:[^/\s@]+@"),                                   # user:pass@
    re.compile(r"(?i)\b(key|token|secret|access_token|password|pwd|sig)=[^\s&\"']+"),
    re.compile(r"(?i)https?://[^\s\"']*(?:hook|webhook|send)\?[^\s\"']*"),   # webhook URL
)


def _scrub_credentials(text: str) -> str:
    """对自由文本做确定性凭据脱敏（allowlist 之外的纵深防御，非替代品）。

    异常字符串常内嵌请求 URL（企微/钉钉 webhook 含 token），
    仅靠截断无法保证不泄漏，因此在入库前统一脱敏。
    """
    out = "" if text is None else str(text)
    for pattern in _CREDENTIAL_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


def _free_text(value: Any, cap: int) -> str:
    """自由文本字段的统一入口：脱敏 + 有界截断。"""
    scrubbed = _scrub_credentials("" if value is None else str(value))
    return _truncate(scrubbed, cap)[0]


def _allowlist(payload: Mapping[str, Any], allowed: Sequence[str],
               free_text_keys: Sequence[str] = ()) -> Dict[str, Any]:
    """字段级 allowlist 投影。

    allowed 之外的键**只保留键名**（`otherKeys`），其值绝不进入上下文 ——
    这样未知/新增的 payload 形态默认关闭，而不是默认泄漏。

    Args:
        payload: 原始结构化值
        allowed: 允许携带取值的键
        free_text_keys: allowed 中需要脱敏 + 截断的自由文本键

    Returns:
        投影后的字典（含 otherKeys 键名列表）
    """
    allowed_set = set(allowed)
    out: Dict[str, Any] = {}
    others: List[str] = []
    keys_truncated = False
    for key in sorted(payload.keys()):          # stable sort（词典序）
        if key not in allowed_set:
            others.append(key)
            continue
        value = payload[key]
        if key in free_text_keys:
            out[key] = _free_text(value, 200)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        else:
            # 结构化值不整体搬运，只记录形状（dict 键名同样封顶）
            if isinstance(value, dict):
                shape_keys = sorted(value.keys())
                out[key] = {"_shape": shape_keys[:MAX_OTHER_KEYS],
                            "_keysTruncated": len(shape_keys) > MAX_OTHER_KEYS}
            else:
                out[key] = {"_len": len(value) if isinstance(value, (list, tuple)) else 0}
    if len(others) > MAX_OTHER_KEYS:
        keys_truncated = True
        others = others[:MAX_OTHER_KEYS]        # 只保留键名，且固定上限
    if others:
        out["otherKeys"] = others
        if keys_truncated:
            out["keysTruncated"] = True
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# normalize —— 12 类 source，各自 allowlist
# ═══════════════════════════════════════════════════════════════════════════════


def _norm_node_runs(repo, run_id: str) -> List[SourceProjection]:
    """workflow_node_runs。无 error → T0（纯枚举/ID）；有 error → T1（携带执行文本）。"""
    out: List[SourceProjection] = []
    for nr in repo.get_node_runs(run_id):
        err = nr.error or ""
        fields = {
            "nodeId": nr.node_id,
            "nodeType": nr.node_type.value,
            "status": nr.status.value,
            "attempt": nr.attempt,
            "completedAt": nr.completed_at or "",
        }
        trust = TrustClass.T0_SYSTEM
        if err:
            # error 是异常字符串，可能内嵌 tool/agent 返回文本 → 非 T0
            fields["error"] = _free_text(err, 400)
            trust = TrustClass.T1_TOOL
        out.append(SourceProjection(
            sourceRef=refs.node_ref(run_id, nr.node_id),
            sourceType=SOURCE_NODE_RUN, trustClass=trust,
            normalizedFields=fields, timestamp=nr.completed_at or "",
            nodeId=nr.node_id,
        ))
    return out


def project_node_output(node_id: str, value: Any) -> Tuple[Dict[str, Any], TrustClass]:
    """nodeOutputs[nodeId] 的 **形状感知 allowlist 投影**。

    executor 把节点 handler 的原始返回值整体写入 state.nodeOutputs
    （executor.py:860），因此这里绝不能整体 dump 后截断：

      - rag_retrieve  → {"rag_context": {... "results":[{"content": <13k 正文>}]}}
      - memory_context→ {"memory_context": {...召回原文...}}
      - 通用 action   → {"params": <可能含 webhook token>, ...}

    上述三者都会绕过 T3 子预算 / T3 200 字投影 / params_json 排除。
    故按形状分类，只取计数与 ID；未知形状**只保留键名**。

    Returns:
        (normalizedFields, trustClass)
    """
    payload = value if isinstance(value, dict) else {}

    # RAG 检索输出 → T3，只留 ref 与计数，正文永不进入
    if "rag_context" in payload:
        ctx = payload.get("rag_context") or {}
        ctx = ctx if isinstance(ctx, dict) else {}
        results = ctx.get("results") or []
        return {"nodeId": node_id, "kind": "rag",
                "resultCount": int(ctx.get("resultCount", len(results)) or 0),
                "traceId": str(ctx.get("traceId", "") or ""),
                "degraded": bool(ctx.get("degraded", False))}, TrustClass.T3_KNOWLEDGE

    # Memory 召回输出 → T3，只留计数
    if "memory_context" in payload:
        ctx = payload.get("memory_context") or {}
        ctx = ctx if isinstance(ctx, dict) else {}
        return {"nodeId": node_id, "kind": "memory",
                "recallCount": int(ctx.get("recallCount", 0) or 0)}, TrustClass.T1_TOOL

    # action 节点输出 → T1；result 由 _norm_actions 以自己的 allowlist 承担
    if "action_id" in payload or "action_type" in payload:
        return {"nodeId": node_id, "kind": "action",
                "actionId": str(payload.get("action_id", "") or ""),
                "actionType": str(payload.get("action_type", "") or ""),
                "status": str(payload.get("status", "") or ""),
                "error": _free_text(payload.get("error", ""), 200)}, TrustClass.T1_TOOL

    # 未知形状 → 默认关闭：只记录键名（固定上限），不搬运任何取值
    keys = sorted(payload.keys())
    truncated = len(keys) > MAX_OTHER_KEYS
    out_fields = {"nodeId": node_id, "kind": "opaque",
                  "outputKeys": keys[:MAX_OTHER_KEYS]}
    if truncated:
        out_fields["keysTruncated"] = True
    return out_fields, TrustClass.T1_TOOL


def _norm_node_outputs(state: Mapping[str, Any], run_id: str) -> List[SourceProjection]:
    """state_json.nodeOutputs —— 按形状 allowlist 投影（见 project_node_output）。"""
    out: List[SourceProjection] = []
    for node_id, value in sorted((state.get("nodeOutputs") or {}).items()):
        fields, trust = project_node_output(node_id, value)
        out.append(SourceProjection(
            sourceRef=refs.node_output_ref(run_id, node_id),
            sourceType=SOURCE_NODE_OUTPUT, trustClass=trust,
            normalizedFields=fields, nodeId=node_id,
        ))
    return out


def _norm_events(repo, run_id: str) -> List[SourceProjection]:
    """workflow_events —— 只取 eventType/nodeId/sequence（枚举与 ID）→ T0。"""
    out: List[SourceProjection] = []
    for e in repo.list_events(run_id):
        out.append(SourceProjection(
            sourceRef=refs.event_ref(e.event_id),
            sourceType=SOURCE_EVENT, trustClass=TrustClass.T0_SYSTEM,
            normalizedFields={"eventType": e.event_type, "nodeId": e.node_id or "",
                              "sequence": e.sequence},
            timestamp=e.created_at or "", nodeId=e.node_id or "",
        ))
    return out


def _norm_actions(repo, run_id: str) -> List[SourceProjection]:
    """workflow_action_records —— **绝不读取 params_json**（secret 边界）→ T1。"""
    try:
        records = repo.list_action_records(run_id)
    except AttributeError:
        return []
    out: List[SourceProjection] = []
    for r in records:
        # result 必须走字段 allowlist：通用 action 分支会把整个 params 回填进
        # result（action.py:547-552），整体 dump + 截断等于绕过 params_json 排除。
        result = r.result if isinstance(r.result, dict) else {}
        out.append(SourceProjection(
            sourceRef=refs.action_ref(r.action_id),
            sourceType=SOURCE_ACTION, trustClass=TrustClass.T1_TOOL,
            normalizedFields={
                "actionId": r.action_id, "actionType": r.action_type,
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "error": _free_text(r.error, 200),
                "result": _allowlist(result, ACTION_RESULT_ALLOWED_KEYS,
                                     free_text_keys=("error", "note")),
                "idempotencyKey": r.idempotency_key,
            },
            timestamp=r.completed_at or r.created_at or "", nodeId=r.node_id or "",
        ))
    return out


def _norm_approvals(repo, run_id: str) -> List[SourceProjection]:
    """workflow_approvals —— 只取 decision（枚举）→ T0。

    reviewer / comment 为人工自由文本，Design Lock 规定 Critic 不得看到，
    因此完全不进入 normalizedFields。
    """
    try:
        approvals = repo.list_approvals(run_id)
    except AttributeError:
        return []
    out: List[SourceProjection] = []
    for a in approvals:
        out.append(SourceProjection(
            sourceRef=refs.approval_ref(a.approval_id),
            sourceType=SOURCE_APPROVAL, trustClass=TrustClass.T0_SYSTEM,
            normalizedFields={
                "approvalId": a.approval_id,
                "decision": a.decision.value if hasattr(a.decision, "value") else str(a.decision),
                "decidedAt": a.decided_at or "",
            },
            timestamp=a.decided_at or a.created_at or "", nodeId=a.node_id or "",
        ))
    return out


def _norm_agent_outputs(state: Mapping[str, Any], run_id: str) -> List[SourceProjection]:
    """state_json.agentOutputs —— agent 派生 summary → T2。"""
    out: List[SourceProjection] = []
    for agent, payload in sorted((state.get("agentOutputs") or {}).items()):
        d = payload if isinstance(payload, dict) else {}
        summary, _ = _truncate(d.get("summary", ""), 400)
        out.append(SourceProjection(
            sourceRef=refs.agent_ref(run_id, agent),
            sourceType=SOURCE_AGENT_OUTPUT, trustClass=TrustClass.T2_AGENT,
            normalizedFields={"agentName": agent, "summary": summary},
            timestamp=d.get("recordedAt", "") or "",
        ))
    return out


def _norm_risk(state: Mapping[str, Any], run_id: str) -> List[SourceProjection]:
    """state_json.riskAssessment —— 评分含规则文本 → T2。"""
    risk = state.get("riskAssessment") or {}
    if not risk:
        return []
    reasons = risk.get("riskReasons") or []
    joined, _ = _truncate("; ".join(str(r) for r in reasons), 400)
    return [SourceProjection(
        sourceRef=refs.risk_ref(run_id),
        sourceType=SOURCE_RISK, trustClass=TrustClass.T2_AGENT,
        normalizedFields={"riskLevel": risk.get("riskLevel", ""),
                          "riskScore": risk.get("riskScore", 0),
                          "riskReasons": joined},
    )]


def _norm_policy_audit(state: Mapping[str, Any], run_id: str) -> List[SourceProjection]:
    """state_json.auditEvents 中的 ToolPolicy 痕迹 → T0。

    ToolPolicy 决策本身不持久化，auditEvents 是其唯一 durable trace。
    只取枚举与 ID（不含 reason 文本），保持 T0「无自由文本」不变量。
    Evidence 只是 decision input —— 绝不改变 policy 结果。
    """
    out: List[SourceProjection] = []
    for idx, ev in enumerate(state.get("auditEvents") or []):
        if not isinstance(ev, dict):
            continue
        etype = ev.get("eventType", "")
        if etype not in POLICY_AUDIT_EVENT_TYPES:
            continue
        payload = ev.get("payload") or {}
        out.append(SourceProjection(
            sourceRef=refs.policy_ref(run_id, ev.get("nodeId", ""), etype),
            sourceType=SOURCE_POLICY_AUDIT, trustClass=TrustClass.T0_SYSTEM,
            normalizedFields={
                "eventType": etype,
                "nodeId": ev.get("nodeId", ""),
                "decision": payload.get("decision", ""),
                "riskLevel": payload.get("riskLevel", ""),
                "actionType": payload.get("actionType", ""),
                "sequence": idx,
            },
            timestamp=ev.get("timestamp", "") or "", nodeId=ev.get("nodeId", "") or "",
        ))
    return out


def _norm_rag_traces(state: Mapping[str, Any]) -> List[SourceProjection]:
    """RAG —— **只保留 ref + 计数**，正文（content/contextual_content）永不进入。"""
    out: List[SourceProjection] = []
    rag_ctx = state.get("ragContext") or {}
    results = rag_ctx.get("results") or []
    for trace_id in (state.get("ragTraceIds") or []):
        out.append(SourceProjection(
            sourceRef=refs.rag_trace_ref(str(trace_id)),
            sourceType=SOURCE_RAG_TRACE, trustClass=TrustClass.T3_KNOWLEDGE,
            normalizedFields={"traceId": str(trace_id), "acceptedTotal": len(results)},
        ))
    # 无 traceId 时，用 chunk id 作为稳定 ref（仍不含正文）
    if not out and results:
        for r in results:
            if not isinstance(r, dict):
                continue
            cid = r.get("chunk_id") or r.get("document_id") or ""
            if not cid:
                continue
            out.append(SourceProjection(
                sourceRef=refs.rag_trace_ref(str(cid)),
                sourceType=SOURCE_RAG_TRACE, trustClass=TrustClass.T3_KNOWLEDGE,
                normalizedFields={"chunkId": str(cid),
                                  "documentId": str(r.get("document_id", ""))},
            ))
    return out


def _norm_memory(state: Mapping[str, Any]) -> List[SourceProjection]:
    """state_json.memoryContext.provenance —— 只保留 id + 短投影 → T3。"""
    out: List[SourceProjection] = []
    mem = state.get("memoryContext") or {}
    for entry in (mem.get("provenance") or []):
        if not isinstance(entry, dict):
            continue
        mid = entry.get("memoryId") or entry.get("id") or ""
        if not mid:
            continue
        text, _ = _truncate(str(entry.get("summary", "") or entry.get("memoryKey", "")), 200)
        out.append(SourceProjection(
            sourceRef=refs.memory_ref(str(mid)),
            sourceType=SOURCE_MEMORY, trustClass=TrustClass.T3_KNOWLEDGE,
            normalizedFields={"memoryId": str(mid),
                              "memoryType": entry.get("memoryType", ""),
                              "textProjection": text},
        ))
    return out


def _norm_simulation(state: Mapping[str, Any]) -> List[SourceProjection]:
    """state_json.simulationRefs —— 结构化仿真引用 → T1。"""
    sim = state.get("simulationRefs") or {}
    if not sim:
        return []
    out: List[SourceProjection] = []
    sim_run = sim.get("simulationRunId", "")
    if sim_run:
        out.append(SourceProjection(
            sourceRef=refs.simulation_ref(str(sim_run)),
            sourceType=SOURCE_SIMULATION, trustClass=TrustClass.T1_TOOL,
            normalizedFields={"simulationRunId": str(sim_run),
                              "trafficEventId": str(sim.get("trafficEventId", ""))},
        ))
    snap = sim.get("latestSnapshotId") or sim.get("decisionSnapshotId") or ""
    if snap:
        out.append(SourceProjection(
            sourceRef=refs.sim_snapshot_ref(str(snap)),
            sourceType=SOURCE_SIMULATION, trustClass=TrustClass.T1_TOOL,
            normalizedFields={"snapshotId": str(snap)},
        ))
    return out


def _norm_errors(state: Mapping[str, Any], run_id: str) -> List[SourceProjection]:
    """state_json.errors —— 异常文本 → T1。ref 用 (nodeId, attempt) 而非 list index。"""
    out: List[SourceProjection] = []
    for err in (state.get("errors") or []):
        if not isinstance(err, dict):
            continue
        node_id = err.get("nodeId", "") or "unknown"
        attempt = int(err.get("attempt", 1) or 1)
        text = _free_text(err.get("error", ""), 400)
        out.append(SourceProjection(
            sourceRef=refs.error_ref(run_id, node_id, attempt),
            sourceType=SOURCE_ERROR, trustClass=TrustClass.T1_TOOL,
            normalizedFields={"nodeId": node_id, "attempt": attempt, "error": text},
            timestamp=err.get("timestamp", "") or "", nodeId=node_id,
        ))
    return out


def collect_source_projections(repo, run) -> List[SourceProjection]:
    """归一化收集全部 12 类 durable source（纯读，无写入）。"""
    state = run.state if isinstance(run.state, dict) else {}
    run_id = run.run_id
    projections: List[SourceProjection] = []
    projections.extend(_norm_node_runs(repo, run_id))
    projections.extend(_norm_node_outputs(state, run_id))
    projections.extend(_norm_events(repo, run_id))
    projections.extend(_norm_actions(repo, run_id))
    projections.extend(_norm_approvals(repo, run_id))
    projections.extend(_norm_agent_outputs(state, run_id))
    projections.extend(_norm_risk(state, run_id))
    projections.extend(_norm_policy_audit(state, run_id))
    projections.extend(_norm_rag_traces(state))
    projections.extend(_norm_memory(state))
    projections.extend(_norm_simulation(state))
    projections.extend(_norm_errors(state, run_id))
    return projections


# ═══════════════════════════════════════════════════════════════════════════════
# 确定性排名
# ═══════════════════════════════════════════════════════════════════════════════


def _relevance(p: SourceProjection, current_step_id: str, current_node_id: str,
               explicit_refs: Sequence[str]) -> float:
    """确定性相关度（不依赖 LLM；证据自身无法抬高自己的分数）。"""
    score = 0.0
    if p.sourceRef in explicit_refs:
        score += 100.0                      # explicit evidence ref
    if current_step_id and p.nodeId == current_step_id:
        score += 40.0                       # step locality
    elif current_node_id and p.nodeId == current_node_id:
        score += 30.0
    fields = dict(p.normalizedFields)
    if fields.get("error") or fields.get("status") in ("failed", "timed_out"):
        score += 20.0                       # failure relation
    if fields.get("eventType") in POLICY_AUDIT_EVENT_TYPES:
        score += 20.0
    score += float(4 - TRUST_ORDINAL[p.trustClass]) * 5.0   # trust
    return score


def rank_projections(projections: Sequence[SourceProjection], current_step_id: str,
                     current_node_id: str,
                     explicit_refs: Sequence[str]) -> List[SourceProjection]:
    """稳定全序排名 + source diversity 轮转。

    tie-break：(-relevance, trustOrdinal, timestamp ASC, sourceType ASC, sourceRef ASC)
    —— 末位 sourceRef 必然可判，因此不依赖 dict 迭代序或 DB 自然序。
    """
    explicit = list(explicit_refs)

    def sort_key(p: SourceProjection):
        return (
            -_relevance(p, current_step_id, current_node_id, explicit),
            TRUST_ORDINAL[p.trustClass],
            p.timestamp or "",
            p.sourceType,
            p.sourceRef,
        )

    ordered = sorted(projections, key=sort_key)

    # source diversity：先每类取 1，再按序补齐（保持类内相对顺序）
    seen: set = set()
    first_pass: List[SourceProjection] = []
    rest: List[SourceProjection] = []
    for p in ordered:
        if p.sourceType not in seen:
            seen.add(p.sourceType)
            first_pass.append(p)
        else:
            rest.append(p)
    return first_pass + rest


# ═══════════════════════════════════════════════════════════════════════════════
# 预算打包
# ═══════════════════════════════════════════════════════════════════════════════


def pack_evidence(ordered: Sequence[SourceProjection], budget: ContextBudget,
                  current_step_id: str, current_node_id: str,
                  explicit_refs: Sequence[str]) -> Tuple[List[EvidenceRef], bool, List[Dict[str, Any]]]:
    """按预算与子预算确定性打包。返回 (evidence, truncated, provenance)。"""
    used_total = 0
    used_by_trust: Dict[TrustClass, int] = {t: 0 for t in TrustClass}
    packed: List[EvidenceRef] = []
    truncated = False
    considered_by_type: Dict[str, int] = {}
    selected_by_type: Dict[str, int] = {}
    dropped: List[Dict[str, Any]] = []

    for p in ordered:
        considered_by_type[p.sourceType] = considered_by_type.get(p.sourceType, 0) + 1
        cap = (budget.t3ProjectionChars if p.trustClass == TrustClass.T3_KNOWLEDGE
               else budget.perEvidenceChars)
        summary, cut = _project(dict(p.normalizedFields), cap)
        if cut:
            truncated = True
        size = len(summary)
        trust_cap = budget.cap_for(p.trustClass)
        if used_total + size > budget.totalChars:
            truncated = True
            dropped.append({"sourceRef": p.sourceRef, "dropReason": "total_budget"})
            continue
        if p.trustClass != TrustClass.T0_SYSTEM and used_by_trust[p.trustClass] + size > trust_cap:
            truncated = True
            dropped.append({"sourceRef": p.sourceRef, "dropReason": "trust_subcap"})
            continue
        used_total += size
        used_by_trust[p.trustClass] += size
        selected_by_type[p.sourceType] = selected_by_type.get(p.sourceType, 0) + 1
        packed.append(EvidenceRef(
            evidenceId=p.sourceRef, sourceType=p.sourceType, sourceRef=p.sourceRef,
            trustClass=p.trustClass, summary=summary, timestamp=p.timestamp,
            relevance=_relevance(p, current_step_id, current_node_id, explicit_refs),
            contentHash=p.stableContentHash,
        ))

    provenance = [
        {"sourceType": st, "considered": considered_by_type.get(st, 0),
         "selected": selected_by_type.get(st, 0)}
        for st in ALL_SOURCE_TYPES
    ]
    provenance.append({"dropped": len(dropped)})
    return packed, truncated, provenance


# ═══════════════════════════════════════════════════════════════════════════════
# assemble
# ═══════════════════════════════════════════════════════════════════════════════


def _observation_view(observation) -> Optional[ObservationView]:
    if observation is None:
        return None
    output = observation.output or {}
    summary, _ = _project(output, 400) if output else ("", False)
    return ObservationView(
        type=observation.type.value,
        status=observation.status.value,
        stepId=observation.stepId or "",
        nodeId=(observation.metadata or {}).get("nodeId", ""),
        failureCode=observation.failureCode or "",
        # T1 文本（node error 可能内嵌 tool/agent 返回文本与 URL token）：
        # 模型可见视图先脱敏（persistence 不受影响）
        failureReason=_scrub_credentials(observation.failureReason or ""),
        outputSummary=_scrub_credentials(summary),
    )


def _completed_and_remaining(repo, run, plan) -> Tuple[List[Dict[str, Any]], List[str]]:
    """已完成步骤摘要 + 未达成目标（确定性投影）。"""
    done = {nr.node_id for nr in repo.get_node_runs(run.run_id)
            if nr.status.value == _SUCCEEDED}
    completed = [{"stepId": s.stepId, "stepType": s.stepType.value}
                 for s in plan.steps if s.stepId in done]
    remaining = [s.objective for s in plan.steps if s.stepId not in done]
    return completed, remaining


#: limit 字段 → usage 字段（用于计算 remaining）
_BUDGET_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("maxSteps", "stepsUsed"), ("maxReplans", "replansUsed"),
    ("maxRetries", "retriesUsed"), ("maxToolCalls", "toolCallsUsed"),
    ("maxLlmCalls", "llmCallsUsed"), ("maxCriticCalls", "criticCallsUsed"),
    ("maxAssessments", "assessmentCallsUsed"),
)


def _budget_snapshot(lineage) -> Dict[str, Any]:
    """{limits, usage, remaining} —— 与 master prompt 同源的真实预算状态。

    Design Lock V2.2 §2：不得为了 restart 稳定性让 fingerprint 与真实 prompt 脱钩。
    master 的 continuation.py 已把整个 budgetUsage（含 activeElapsedSeconds 浮点）
    渲染进 prompt，因此这里保持同样内容 —— 代价是 fingerprint 不跨崩溃稳定
    （Option B：契约只保证「同一 source snapshot 内 assembler 纯函数」）。
    """
    if lineage is None:
        return {}
    limits = lineage.budgetLimits.to_dict()
    usage = lineage.budgetUsage.to_dict()
    remaining = {
        usage_key: max(0, int(limits.get(limit_key, 0)) - int(usage.get(usage_key, 0)))
        for limit_key, usage_key in _BUDGET_PAIRS
    }
    return {"limits": limits, "usage": usage, "remaining": remaining}


def _trajectory_projection(repo, run_id: str) -> Dict[str, Any]:
    """compute_trajectory() 的 metrics 子集（只读；失败退化为空）。"""
    try:
        from backend.planning.trajectory import compute_trajectory
        t = compute_trajectory(repo, run_id) or {}
        m = t.get("metrics", {}) or {}
        return {
            "revisionCount": m.get("revisionCount"),
            "replanCount": m.get("replanCount"),
            "recoveryAttempts": m.get("recoveryAttempts"),
            "budgetExhaustions": m.get("budgetExhaustions"),
            "loopStops": m.get("loopStops"),
            "toolDenials": m.get("toolDenials"),
            "trajectoryLength": m.get("trajectoryLength"),
            "finalOutcome": t.get("finalOutcome"),
        }
    except Exception:
        return {}


def assemble_decision_context(
    repo,
    run,
    plan,
    observation,
    decision_type: DecisionType,
    lineage=None,
    critic_recommendation: Optional[Mapping[str, Any]] = None,
    critic_boundary_key: Optional[str] = None,
) -> DecisionContext:
    """装配 DecisionContext（纯函数：无 provider / 无 claim / 无持久化写入）。

    Args:
        repo: WorkflowRepository（只读使用）
        run: WorkflowRun
        plan: Plan
        observation: Observation 或 None
        decision_type: DecisionType
        lineage: ExecutionLineage（可选，用于 budgetSnapshot）
        critic_recommendation: 仅 SEMANTIC_REPLAN 使用（R1 不接线 production）
        critic_boundary_key: 绑定证明（记入 provenance，不进 fingerprint）

    Returns:
        DecisionContext（含 sourceSnapshotDigest）
    """
    state = run.state if isinstance(run.state, dict) else {}
    obs_view = _observation_view(observation)
    current_step_id = obs_view.stepId if obs_view else ""
    current_node_id = (obs_view.nodeId if obs_view else "") or state.get("currentNode", "") or ""
    explicit = [r.get("ref", "") if isinstance(r, dict) else str(r)
                for r in (getattr(observation, "evidenceRefs", None) or [])]

    projections = collect_source_projections(repo, run)
    ordered = rank_projections(projections, current_step_id, current_node_id, explicit)
    budget = ContextBudget.for_decision(decision_type)
    packed, truncated, provenance = pack_evidence(
        ordered, budget, current_step_id, current_node_id, explicit)

    completed, remaining = _completed_and_remaining(repo, run, plan)
    rec_hash = content_hash(dict(critic_recommendation)) if critic_recommendation else None

    system_state = {
        "decisionType": decision_type.value,
        "runId": run.run_id,
        "rootRunId": (getattr(lineage, "rootRunId", "") or run.run_id),
        "planId": plan.planId,
        "planVersion": plan.version,
        "runStatus": run.status.value,
        "goalHash": content_hash(plan.goal or ""),
        "planGoalType": plan.goalType.value,
        "currentStepId": current_step_id,
        "currentNodeId": current_node_id,
        "explicitRefs": sorted(explicit),
        "boundCriticRecommendationHash": rec_hash,
        "budgetState": _budget_snapshot(lineage),
    }
    digest = compute_source_snapshot_digest(projections, system_state)

    return DecisionContext(
        decisionType=decision_type,
        rootRunId=system_state["rootRunId"],
        runId=run.run_id,
        planId=plan.planId,
        planVersion=plan.version,
        goal=plan.goal,
        goalType=plan.goalType.value,
        currentStepId=current_step_id,
        currentNodeId=current_node_id,
        observation=obs_view,
        executionEvidence=tuple(packed),
        trajectorySummary=_trajectory_projection(repo, run.run_id),
        criticRecommendation=dict(critic_recommendation) if critic_recommendation else None,
        criticBoundaryKey=critic_boundary_key,
        completedWorkSummary=tuple(completed),
        remainingObjectives=tuple(remaining),
        budgetSnapshot=_budget_snapshot(lineage),
        contextProvenance=tuple(provenance),
        sourceSnapshotDigest=digest,
        assemblerVersion=ASSEMBLER_VERSION,
        truncated=truncated,
    )


def assemble_or_empty(repo, run, plan, observation, decision_type: DecisionType,
                      **kwargs) -> DecisionContext:
    """安全装配：任何异常 → 空上下文（等价 Phase18），绝不 fail workflow。"""
    try:
        return assemble_decision_context(repo, run, plan, observation, decision_type, **kwargs)
    except Exception:
        return empty_decision_context(
            decision_type,
            run_id=getattr(run, "run_id", ""),
            plan_id=getattr(plan, "planId", ""),
            plan_version=getattr(plan, "version", 1),
        )
