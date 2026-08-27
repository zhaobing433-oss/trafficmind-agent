"""
Decision Provenance — Phase19 Round4-Lite read model

critic / semantic_replan / assessment 三个决策的 provenance 只读投影。
从 durable state 确定性派生：
  - criticInvocations / semanticReplanInvocations / assessment 注册表
    （workflow_runs.state_json，Phase19 R2/R3 claim/complete tx 写入）
  - executionLineage（rootRunId）
  - replannedToRunId（child 指针）
  - observation_recorded events（evidenceRefs 白名单）
  - exact-version 定义快照（durable Plan flag）

R4 契约（§3）：READ-ONLY —— 0 provider call / 0 持久化写 / 0 状态变更。
本模块绝不 import llm_client，绝不调用任何 claim/complete/save 方法。

不可伪造原则（§4，R4 契约 v2 —— actual mode 与 claim 语义分离）：
  - groundedMode 表达 actual provider prompt mode。durable 层不记录
    kill-switch 决策时取值 / assembler 成败，因此 provider 路径的 actual
    mode 不可恢复 → 恒 "unknown"；唯一可证明的是 deterministic 硬事实
    路径（无 LLM，provider 不可能被调用）→ "deterministic"；
    无 prompt 决策（fallback / 无 result）→ None。
    绝不把 durable Plan flag 或 goalResolved 推导成 actual grounded mode。
  - groundedPlanEnabled 表达 durable Plan 能力旗标
    （Plan.groundedDecisionContextEnabled，identity 来源），true/false/
    None（快照缺失）。它只说明 plan 侧资格，不说明 runtime 实际模式。
  - providerClaimed 表达 durable claim 事实（registry entry 由 claim tx
    创建；assessment 无 claim 路径 / 白名单 fallback reason 可证明
    未 claim）。
  - providerCall 表达 actual provider 调用：True 仅当 durable 层存在
    provider 产出物（critic recommendation / semantic proposal / assessment
    assessed 结果——complete 只在 provider 成功返回后写入，失败保持
    STARTED）；False 仅当可证明无 provider 路径（deterministic /
    无 claim 白名单 fallback）；其余（claim 后 crash / claim 后异常 /
    无产出物）→ None。claim ≠ call。
  - created/completed 时间戳：per-invocation 未持久化 → 不提供。
  - contextFingerprint / sourceSnapshotDigest：决策时未持久化 → 不提供，
    绝不 read-time 重算当前 context 冒充历史 decision fingerprint。
  - evidenceRefs：由同 (type, stepId) 边界的 observation_recorded
    事件派生，只取 {"ref"} 白名单，绝不携带 failureReason / output / 正文；
    'unknown' stepId（legacy 边界）→ None，绝不用 run 级 refs 冒充。

排序（§10）：decisionType 稳定秩（critic < semantic_replan < assessment）
→ boundaryKey 字典序。不依赖 dict 插入序，restart 前后字节一致。
注意：该顺序是 deterministic stable ordering，**不是 chronological** ——
per-invocation 时间戳未持久化，Phase20 消费方不得将其解读为决策时间线。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_DECISION_TYPE_RANK = {"critic": 0, "semantic_replan": 1, "assessment": 2}
_RECOMMENDATION_VALUES = ("replan", "abort", "escalate_human")
_ACHIEVEMENT_VALUES = ("achieved", "not_achieved", "unknown")
# assessment fallback 的 claim 未发生原因（durable fallbackReason 白名单值，
# 代码语义保证这些路径从未触达 claim/provider）
_NO_CLAIM_FALLBACK_REASONS = ("client_unavailable", "not_eligible",
                              "budget_exhausted")
# claim 已存在（本次被拒）→ 之前的 attempt 是否真实调用过 provider 不可知
_CLAIM_HELD_FALLBACK_REASONS = ("already_started",)


def _plan_grounded_flag(repo, run) -> Optional[bool]:
    """run 绑定的 durable plan flag（版本语义与 continuation._load_plan_from_run 一致）。

    versioned child（version>1）snapshot 缺失/malformed → fail-closed None；
    legacy base v1 → 回退 base definition metadata.plan；拿不到 → None。
    """
    try:
        plan_raw = None
        ver = repo.get_definition_version(run.definition_id, run.version)
        if ver is not None:
            dj = ver.definition_json if isinstance(ver.definition_json, dict) else {}
            metadata = dj.get("metadata", {}) or {}
            plan_raw = metadata.get("plan")
            if not plan_raw:
                # versioned snapshot 存在但 plan 缺失 → fail-closed
                return None
        elif run.version <= 1:
            definition = repo.get_definition(run.definition_id)
            if definition is not None and isinstance(definition.metadata, dict):
                plan_raw = definition.metadata.get("plan")
        if not plan_raw:
            return None
        if isinstance(plan_raw, str):
            import json as _json
            plan_raw = _json.loads(plan_raw)
        if not isinstance(plan_raw, dict):
            return None
        return bool(plan_raw.get("groundedDecisionContextEnabled", False))
    except Exception:
        return None


def _root_run_id(state: Dict[str, Any], run_id: str) -> str:
    lineage = state.get("executionLineage", {}) or {}
    return lineage.get("rootRunId") or run_id


def _key_tail(key: str) -> tuple:
    """key 末尾两个组件（critic: type,sid；semantic: stepId,type）。

    rsplit 从右取 2 段：type/sid/stepId 均为枚举值或 compiler canonical
    stepId（固定字面量或 {kind}_{slug}_{n:02d}，slug 来自 capability
    固定映射），不含 ':'，与 root/run id 是否含 ':' 无关。格式不符 →
    (None, None)。
    """
    parts = key.rsplit(":", 2)
    if len(parts) != 3:
        return None, None
    return parts[1], parts[2]


def _observation_evidence_refs(repo, run_id: str, obs_type: Optional[str],
                               step_id: Optional[str]) -> Optional[List[str]]:
    """同 (type, stepId) 边界的 observation 事件 evidenceRefs（ref 白名单，去重保序）。

    stepId 缺失/unknown（legacy 边界）→ 不派生（无法安全关联，返回 None）。
    绝不携带 failureReason / output / metadata / 正文（§5）。
    """
    if not obs_type or step_id in ("", None, "unknown"):
        return None
    try:
        refs: List[str] = []
        seen = set()
        for e in repo.list_events(run_id):
            if e.event_type != "observation_recorded":
                continue
            p = e.payload if isinstance(e.payload, dict) else {}
            if p.get("type") != obs_type or p.get("stepId") != step_id:
                continue
            for r in p.get("evidenceRefs") or []:
                if isinstance(r, dict) and isinstance(r.get("ref"), str) and r["ref"]:
                    if r["ref"] not in seen:
                        seen.add(r["ref"])
                        refs.append(r["ref"])
        return refs or None
    except Exception:
        return None


def _critic_entries(repo, run, state: Dict[str, Any],
                    grounded_flag: Optional[bool], root_run_id: str) -> List[Dict[str, Any]]:
    """criticInvocations 注册表 → provenance entries（不暴露 reasonSummary 等自由文本）。"""
    entries: List[Dict[str, Any]] = []
    registry = state.get("criticInvocations") or {}
    if not isinstance(registry, dict):
        return entries
    for key, entry in registry.items():
        if not isinstance(key, str) or not key or not isinstance(entry, dict):
            continue
        status = entry.get("status")
        decision_status = status if status in ("STARTED", "COMPLETED") else "unknown"
        obs_type, step_id = _key_tail(key)
        # provider 产出物 = complete 时写入的 recommendation（complete 只在
        # provider 成功返回后调用；失败/crash → registry 恒 STARTED）
        provider_output = (isinstance(entry.get("recommendation"), dict)
                           and bool(entry.get("recommendation")))
        item: Dict[str, Any] = {
            "decisionType": "critic",
            "runId": run.run_id,
            "rootRunId": root_run_id,
            "planVersion": run.version,
            "boundaryKey": key,
            "decisionStatus": decision_status,
            # actual prompt mode（grounded/legacy）由 kill-switch + assembler
            # 成败决定，durable 层未记录 → 不可恢复，恒 unknown（§4 不伪造）
            "groundedMode": "unknown",
            # durable Plan 能力旗标（identity 来源）；拿不到 → None
            "groundedPlanEnabled": grounded_flag,
            # claim ≠ call：仅 durable provider 产出物能证明 actual call
            "providerCall": True if decision_status == "COMPLETED" and provider_output else None,
            # registry entry 由 claim tx 创建 → claim 是 durable 事实
            "providerClaimed": True,
            "evidenceRefs": _observation_evidence_refs(repo, run.run_id, obs_type, step_id),
            "runStatus": run.status.value,
            "recommendation": None,
            "confidence": None,
        }
        if decision_status == "COMPLETED":
            rec = entry.get("recommendation")
            if isinstance(rec, dict):
                rv = rec.get("recommendation")
                item["recommendation"] = rv if rv in _RECOMMENDATION_VALUES else None
                try:
                    item["confidence"] = float(rec.get("confidence"))
                except (TypeError, ValueError):
                    item["confidence"] = None
        entries.append(item)
    return entries


def _semantic_replan_entries(repo, run, state: Dict[str, Any],
                             grounded_flag: Optional[bool],
                             root_run_id: str) -> List[Dict[str, Any]]:
    """semanticReplanInvocations → provenance（criticBoundaryKey 由 key 组件精确派生）。

    R3 exact binding 语义不变：只做同字节级派生 + COMPLETED 精确 lookup；
    绝不读取 proposal.raw（raw provider response，§5 禁止暴露）。
    """
    entries: List[Dict[str, Any]] = []
    registry = state.get("semanticReplanInvocations") or {}
    if not isinstance(registry, dict):
        return entries
    for key, entry in registry.items():
        if not isinstance(key, str) or not key or not isinstance(entry, dict):
            continue
        step_id, obs_type = _key_tail(key)
        if not step_id or not obs_type:
            # key 格式不符 → 无法派生 exact boundary，跳过（不伪造）
            continue
        status = entry.get("status")
        decision_status = status if status in ("STARTED", "COMPLETED") else "unknown"
        bound = None
        critic_rec = None
        try:
            from backend.planning.critic import (
                derive_critic_boundary_key,
                lookup_bound_critic_recommendation,
            )
            # 与 R3 决策时同源函数，字节级一致（§6）
            bound = derive_critic_boundary_key(
                root_run_id, run.run_id, run.version, obs_type, step_id)
            found = lookup_bound_critic_recommendation(state, bound)
            rv = found.get("recommendation")
            critic_rec = rv if rv in _RECOMMENDATION_VALUES else None
        except Exception:
            bound, critic_rec = None, None
        child_id = state.get("replannedToRunId")
        child_version = None
        if child_id:
            try:
                child = repo.get_run(child_id)
                child_version = child.version if child is not None else None
            except Exception:
                child_version = None
        # provider 产出物 = complete 时写入的 proposal（含 provider raw 输出；
        # complete 只在 provider 成功返回后调用）
        provider_output = (isinstance(entry.get("proposal"), dict)
                           and bool(entry.get("proposal")))
        entries.append({
            "decisionType": "semantic_replan",
            "runId": run.run_id,
            "rootRunId": root_run_id,
            "planVersion": run.version,
            "boundaryKey": key,
            "decisionStatus": decision_status,
            "groundedMode": "unknown",
            "groundedPlanEnabled": grounded_flag,
            "providerCall": True if decision_status == "COMPLETED" and provider_output else None,
            "providerClaimed": True,
            "evidenceRefs": _observation_evidence_refs(repo, run.run_id, obs_type, step_id),
            "runStatus": run.status.value,
            "criticBoundaryKey": bound,
            "criticRecommendation": critic_rec,
            "resultStatus": "child_created" if child_id else None,
            "childRunId": child_id or None,
            "childVersion": child_version,
        })
    return entries


def _fallback_claim_status(reason: Optional[str]) -> tuple:
    """assessment FALLBACK 的 (providerClaimed, providerCall)（不暴露 reason 原文）。

    白名单无 claim 原因（client_unavailable / not_eligible / budget_exhausted）
      → claim 未发生、provider 不可能被调用（可证明）→ (False, False)；
    already_started → claim 已存在（本次被拒），之前 attempt 是否真实调用
      provider 不可知 → (True, None)；
    其余非空 reason（claim 后异常）→ claim 发生、actual call 不可证明 → (True, None)；
    空 → (None, None)。
    """
    if not reason:
        return None, None
    if reason in _NO_CLAIM_FALLBACK_REASONS:
        return False, False
    if reason in _CLAIM_HELD_FALLBACK_REASONS:
        return True, None
    return True, None


def _assessment_entries(repo, run, state: Dict[str, Any],
                        grounded_flag: Optional[bool],
                        root_run_id: str) -> List[Dict[str, Any]]:
    """assessment 注册表 → provenance（assessmentMode/Status 是 durable 决策模式事实）。"""
    entries: List[Dict[str, Any]] = []
    registry = state.get("assessment") or {}
    if not isinstance(registry, dict):
        return entries
    for key, entry in registry.items():
        if not isinstance(key, str) or not key or not isinstance(entry, dict):
            continue
        result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
        status = entry.get("status")
        assess_status = result.get("assessmentStatus")
        mode = result.get("assessmentMode")

        if status == "STARTED":
            # claim 后 crash 窗口：无 result，call 不可证明（§5）
            decision_status, grounded_mode, claimed, call, result_status = (
                "STARTED", None, True, None, None)
        elif status == "COMPLETED":
            if assess_status == "fallback":
                claimed, call = _fallback_claim_status(result.get("assessmentFallbackReason"))
                decision_status, grounded_mode, result_status = "COMPLETED", None, "fallback"
            elif mode == "deterministic":
                # hard-fact / 无 LLM 路径（complete 无 claim）—— 可证明
                decision_status, grounded_mode, claimed, call, result_status = (
                    "deterministic", "deterministic", False, False, None)
            elif mode == "llm":
                # goalResolved=true 只证明 exact Plan.goal 解析成功，不证明
                # grounded assessment prompt 实际使用（kill-switch /
                # assembler 成败未持久化）→ groundedMode 不得推导（§4）
                decision_status, grounded_mode, claimed, result_status = (
                    "COMPLETED", "unknown", True, None)
                # assessed = provider 产出物（goalAchievement 等）已 durable 写入
                call = True if assess_status == "assessed" else None
            else:
                decision_status, grounded_mode, claimed, call, result_status = (
                    "COMPLETED", None, None, None, None)
        else:
            decision_status, grounded_mode, claimed, call, result_status = (
                "unknown", None, None, None, None)

        verdict = result.get("goalAchievement")
        entries.append({
            "decisionType": "assessment",
            "runId": run.run_id,
            "rootRunId": root_run_id,
            "planVersion": run.version,
            "boundaryKey": key,
            "decisionStatus": decision_status,
            "groundedMode": grounded_mode,
            "groundedPlanEnabled": grounded_flag,
            "providerCall": call,
            "providerClaimed": claimed,
            # assessment 决策级 evidenceRefs 未持久化 → 不派生（§4 不伪造）
            "evidenceRefs": None,
            "runStatus": run.status.value,
            "verdict": verdict if verdict in _ACHIEVEMENT_VALUES else None,
            "goalResolved": (bool(result.get("goalResolved", False))
                             if "goalResolved" in result else None),
            "resultStatus": result_status,
        })
    return entries


def build_decision_provenance(run, repo) -> List[Dict[str, Any]]:
    """run 的 decision provenance 只读投影（R4 契约）。

    Args:
        run: WorkflowRun（含 state_json）
        repo: SQLiteWorkflowRepository（只调用 SELECT 类方法）

    Returns:
        稳定排序的 provenance entries；任何异常 / legacy 无数据 → []。
        0 provider call / 0 持久化写 / 0 状态变更。
    """
    if run is None:
        return []
    try:
        state = run.state if isinstance(run.state, dict) else {}
        root_run_id = _root_run_id(state, run.run_id)
        grounded_flag = _plan_grounded_flag(repo, run)
        entries: List[Dict[str, Any]] = []
        entries.extend(_critic_entries(repo, run, state, grounded_flag, root_run_id))
        entries.extend(_semantic_replan_entries(repo, run, state, grounded_flag, root_run_id))
        entries.extend(_assessment_entries(repo, run, state, grounded_flag, root_run_id))
        entries.sort(key=lambda d: (_DECISION_TYPE_RANK.get(d["decisionType"], 99),
                                    d["boundaryKey"]))
        return entries
    except Exception:
        return []
