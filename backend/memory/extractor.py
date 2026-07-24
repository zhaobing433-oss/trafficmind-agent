"""
Memory V2 结构化抽取器 — Phase 10 里程碑二

从协同 Run 结果中抽取结构化记忆候选。
以确定性规则为主，LLM 仅作为可选增强。
"""

import re
from typing import Any, Dict, List, Optional

from backend.memory.models import MemoryWriteCandidate
from backend.memory.constants import (
    MemoryType,
    MemoryStatus,
    MemorySourceType,
    AuthorityLevel,
    DYNAMIC_FIELD_BLOCKLIST,
)
from backend.memory.policy import DEFAULT_POLICY


# ================================================================
# Stable field whitelist (can be promoted to stable_fact)
# ================================================================

STABLE_FIELD_WHITELIST: Dict[str, str] = {
    "roadName": "road.name",
    "direction": "road.direction",
    "nearbySchool": "school.nearby",
    "nearbyHospital": "hospital.nearby",
    "isMainRoad": "road.is_main",
    "eventType": "route.event_type",
    "eventTypeCn": "route.event_type_cn",
}

# Values that should NOT be written (defaults/placeholders)
DEFAULT_PLACEHOLDERS = {
    "未知路段", "未命名", "未命名路段", "unknown", "", None,
}


# ================================================================
# Constraint keywords
# ================================================================

CONSTRAINT_KEYWORDS = [
    "必须", "不能", "不得", "优先", "至少", "最多",
    "保证", "限制", "避免", "禁止", "确保",
]


# ================================================================
# Confirmation keywords
# ================================================================

CONFIRMATION_KEYWORDS = [
    "采用", "同意", "确认", "执行", "就按这个方案",
    "选择第一种", "选择第二种", "选择第", "按第",
]


# ================================================================
# Correction keywords
# ================================================================

CORRECTION_KEYWORDS = [
    "刚才说错了", "不是X", "更正为", "应该是",
    "把X改成Y", "前面的信息有误", "不是", "而是",
    "纠正", "改一下", "修改为", "改成",
]


# ================================================================
# MemoryExtractionResult
# ================================================================

class MemoryExtractionResult:
    """抽取结果容器。"""

    def __init__(self):
        self.session_goals: List[MemoryWriteCandidate] = []
        self.stable_facts: List[MemoryWriteCandidate] = []
        self.constraints: List[MemoryWriteCandidate] = []
        self.confirmed_decisions: List[MemoryWriteCandidate] = []
        self.proposals: List[MemoryWriteCandidate] = []
        self.unresolved_issues: List[MemoryWriteCandidate] = []
        self.user_corrections: List[MemoryWriteCandidate] = []
        self.run_summaries: List[MemoryWriteCandidate] = []
        self.temporary_facts: List[MemoryWriteCandidate] = []
        self.rejected_dynamic_facts: List[Dict[str, Any]] = []

    def all_candidates(self) -> List[MemoryWriteCandidate]:
        """返回所有非空候选列表的合并。"""
        result = []
        for lst in [
            self.session_goals, self.stable_facts, self.constraints,
            self.confirmed_decisions, self.proposals, self.unresolved_issues,
            self.user_corrections, self.run_summaries, self.temporary_facts,
        ]:
            result.extend(lst)
        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sessionGoals": len(self.session_goals),
            "stableFacts": len(self.stable_facts),
            "constraints": len(self.constraints),
            "confirmedDecisions": len(self.confirmed_decisions),
            "proposals": len(self.proposals),
            "unresolvedIssues": len(self.unresolved_issues),
            "userCorrections": len(self.user_corrections),
            "runSummaries": len(self.run_summaries),
            "temporaryFacts": len(self.temporary_facts),
            "rejectedDynamicFacts": len(self.rejected_dynamic_facts),
        }


# ================================================================
# MemoryExtractor
# ================================================================

class MemoryExtractor:
    """从协同 Run 结果中抽取结构化记忆。

    所有核心规则是确定性的，不依赖 LLM。
    LLM 只作为可选增强（extract_with_llm 预留）。
    """

    def __init__(self, policy=None):
        self.policy = policy or DEFAULT_POLICY

    def extract(
        self,
        session_id: str,
        run_id: str,
        user_message_id: str,
        assistant_message_id: str,
        user_input: str,
        current_event: Dict[str, Any],
        selected_agents: List[str],
        agent_results: List[Dict[str, Any]],
        conflicts: List[Dict[str, Any]],
        arbitration_results: List[Dict[str, Any]],
        fusion_summary: str,
        final_decision: Any,
        requires_human_review: bool,
        run_status: str,
        degraded: bool = False,
        is_first_round: bool = False,
    ) -> MemoryExtractionResult:
        """执行完整抽取。"""
        result = MemoryExtractionResult()

        # --- Session Goal ---
        self._extract_session_goal(result, user_input, session_id, run_id,
                                   user_message_id, is_first_round)

        # --- Stable Facts ---
        self._extract_stable_facts(result, current_event, user_input,
                                   session_id, run_id, user_message_id)

        # --- Constraints ---
        self._extract_constraints(result, user_input, session_id, run_id,
                                  user_message_id)

        # --- Proposals (from Agent results) ---
        self._extract_proposals(result, agent_results, session_id, run_id,
                                user_message_id)

        # --- Confirmed Decisions ---
        self._extract_confirmed_decisions(result, user_input, session_id,
                                          run_id, user_message_id)

        # --- User Corrections ---
        self._extract_user_corrections(result, user_input, current_event,
                                       session_id, run_id, user_message_id)

        # --- Unresolved Issues ---
        self._extract_unresolved_issues(result, conflicts, arbitration_results,
                                        requires_human_review, final_decision,
                                        session_id, run_id, user_message_id)

        # --- Run Summary ---
        if run_status in ("completed", "partial_success"):
            self._extract_run_summary(result, run_id, session_id, user_input,
                                      current_event, selected_agents,
                                      conflicts, final_decision,
                                      requires_human_review, degraded,
                                      user_message_id)

        # --- Temporary Facts ---
        self._extract_temporary_facts(result, user_input, session_id, run_id,
                                      user_message_id)

        return result

    # ================================================================
    # Session Goal
    # ================================================================

    def _extract_session_goal(
        self, result: MemoryExtractionResult, user_input: str,
        session_id: str, run_id: str, user_message_id: str,
        is_first_round: bool,
    ):
        """第一轮或明确切换目标时生成 session_goal。"""
        if not is_first_round:
            # Check for explicit goal switch
            switch_patterns = [
                r"改为分析", r"换一个", r"另外研判", r"现在分析",
                r"切换.*目标", r"转.*研判",
            ]
            is_switch = any(re.search(p, user_input) for p in switch_patterns)
            if not is_switch:
                return

        goal_text = user_input[:200].strip()
        if not goal_text:
            return

        candidate = MemoryWriteCandidate(
            memory_type=MemoryType.SESSION_GOAL.value,
            memory_key="goal.primary",
            value={"goal": goal_text},
            text_content=goal_text,
            status=MemoryStatus.ACTIVE.value,
            confidence=1.0,
            authority_level=AuthorityLevel.HUMAN_REVIEW,
            source_type=MemorySourceType.USER_EXPLICIT.value,
            source_id=user_message_id,
            source_run_id=run_id,
            source_message_id=user_message_id,
        )
        if is_first_round:
            candidate.metadata = {"trigger": "first_round"}
        else:
            candidate.metadata = {"trigger": "goal_switch", "reason": "用户明确切换目标"}

        result.session_goals.append(candidate)

    # ================================================================
    # Stable Facts
    # ================================================================

    def _extract_stable_facts(
        self, result: MemoryExtractionResult, current_event: Dict[str, Any],
        user_input: str, session_id: str, run_id: str, user_message_id: str,
    ):
        """从 currentEvent 提取稳定事实，跳过动态字段和占位值。"""
        field_sources = current_event.get("fieldSources", {})

        # First: explicitly reject dynamic fields present in current_event
        for field_name in DYNAMIC_FIELD_BLOCKLIST:
            if field_name in current_event and current_event[field_name] not in DEFAULT_PLACEHOLDERS:
                result.rejected_dynamic_facts.append({
                    "action": "rejected",
                    "reason": "dynamic_field_blocked",
                    "fieldName": field_name,
                    "sourceRunId": run_id,
                })

        for field_name, memory_key in STABLE_FIELD_WHITELIST.items():
            value = current_event.get(field_name)
            if value in DEFAULT_PLACEHOLDERS:
                continue
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue

            # Check dynamic field blocklist
            if field_name in DYNAMIC_FIELD_BLOCKLIST:
                result.rejected_dynamic_facts.append({
                    "action": "rejected",
                    "reason": "dynamic_field_blocked",
                    "memoryKey": memory_key,
                    "fieldName": field_name,
                    "sourceRunId": run_id,
                })
                continue

            # Determine source type and authority
            source = field_sources.get(field_name, "")
            if source == "user":
                src_type = MemorySourceType.USER_EXPLICIT.value
                authority = AuthorityLevel.HUMAN_REVIEW
            elif source == "event_parser" or source == "nl_parsed":
                src_type = MemorySourceType.EVENT_PARSER.value
                authority = AuthorityLevel.EVENT_PARSER
            else:
                # Check if user explicitly mentioned in input
                if isinstance(value, str) and value in user_input:
                    src_type = MemorySourceType.USER_EXPLICIT.value
                    authority = AuthorityLevel.HUMAN_REVIEW
                else:
                    src_type = MemorySourceType.EVENT_PARSER.value
                    authority = AuthorityLevel.EVENT_PARSER

            # Convert bool to readable format
            if isinstance(value, bool):
                display_value = {"value": value}
            elif isinstance(value, (int, float)):
                display_value = {"value": value}
            else:
                display_value = {"value": str(value)}

            candidate = MemoryWriteCandidate(
                memory_type=MemoryType.STABLE_FACT.value,
                memory_key=memory_key,
                value=display_value,
                text_content=f"{field_name}: {value}",
                status=MemoryStatus.ACTIVE.value,
                confidence=0.9 if src_type == MemorySourceType.EVENT_PARSER.value else 1.0,
                authority_level=authority,
                source_type=src_type,
                source_id=user_message_id,
                source_run_id=run_id,
                source_message_id=user_message_id,
            )
            result.stable_facts.append(candidate)

    # ================================================================
    # Constraints
    # ================================================================

    def _extract_constraints(
        self, result: MemoryExtractionResult, user_input: str,
        session_id: str, run_id: str, user_message_id: str,
    ):
        """从用户输入识别明确约束。"""
        for keyword in CONSTRAINT_KEYWORDS:
            if keyword not in user_input:
                continue

            # Find the sentence containing this keyword
            sentences = re.split(r'[。！？\n]', user_input)
            for sent in sentences:
                if keyword not in sent:
                    continue
                sent = sent.strip()
                if len(sent) < 3:
                    continue

                # Try to structure the constraint
                constraint_value = self._parse_constraint_sentence(sent, keyword)
                if not constraint_value:
                    constraint_value = {"text": sent}

                # Generate a key from the subject
                key_suffix = re.sub(r'[^\w]', '_', sent[:30]).strip('_').lower()
                if not key_suffix:
                    key_suffix = f"c{len(result.constraints) + 1}"

                candidate = MemoryWriteCandidate(
                    memory_type=MemoryType.CONSTRAINT.value,
                    memory_key=f"constraint.{key_suffix}",
                    value=constraint_value,
                    text_content=sent,
                    status=MemoryStatus.ACTIVE.value,
                    confidence=1.0,
                    authority_level=AuthorityLevel.HUMAN_REVIEW,
                    source_type=MemorySourceType.USER_EXPLICIT.value,
                    source_id=user_message_id,
                    source_run_id=run_id,
                    source_message_id=user_message_id,
                )
                result.constraints.append(candidate)

    def _parse_constraint_sentence(
        self, sentence: str, keyword: str
    ) -> Optional[Dict[str, Any]]:
        """尝试将约束句子结构化。"""
        # Pattern: "不少于X秒", "至少X分钟", "最多X", "保证X"
        duration_match = re.search(
            r'(\d+\.?\d*)\s*(秒|分钟|分|小时|米|公里|km|m|h|min|s)',
            sentence,
        )
        if duration_match:
            number = float(duration_match.group(1))
            unit = duration_match.group(2)
            # Map unit
            unit_map = {"秒": "seconds", "分": "minutes", "分钟": "minutes",
                        "小时": "hours", "米": "meters", "公里": "km",
                        "s": "seconds", "min": "minutes", "h": "hours",
                        "m": "meters", "km": "km"}
            unit_en = unit_map.get(unit, unit)

            op_map = {"至少": "gte", "不少于": "gte", "保证": "gte",
                      "最多": "lte", "不超过": "lte", "限制": "lte",
                      "禁止": "eq", "必须": "eq", "不能": "neq",
                      "不得": "neq", "避免": "neq"}
            operator = op_map.get(keyword, "gte")

            # Extract subject before keyword
            subject = sentence.split(keyword)[0].strip() if keyword in sentence else ""
            if len(subject) > 50:
                subject = subject[-50:]

            return {
                "operator": operator,
                "value": number,
                "unit": unit_en,
                "subject": subject or "constraint",
            }
        return None

    # ================================================================
    # Proposals
    # ================================================================

    def _extract_proposals(
        self, result: MemoryExtractionResult,
        agent_results: List[Dict[str, Any]],
        session_id: str, run_id: str, user_message_id: str,
    ):
        """从 Agent 结果提取 proposal（不得自动成为 confirmed_decision）。"""
        for ar in agent_results:
            agent_name = ar.get("agentName", ar.get("agent_name", "unknown"))
            suggestion = ar.get("suggestion", "")
            findings = ar.get("findings", [])

            if suggestion:
                candidate = MemoryWriteCandidate(
                    memory_type=MemoryType.PROPOSAL.value,
                    memory_key=f"proposal.{agent_name}.{run_id}",
                    value={
                        "agentName": agent_name,
                        "suggestion": suggestion,
                        "findings": findings[:5],  # top 5
                        "urgency": ar.get("urgency", "low"),
                        "confidence": ar.get("confidence", 0),
                    },
                    text_content=suggestion[:300],
                    status=MemoryStatus.CANDIDATE.value,
                    confidence=ar.get("confidence", 0.5),
                    authority_level=AuthorityLevel.AGENT_PROPOSAL,
                    source_type=MemorySourceType.AGENT_PROPOSAL.value,
                    source_id=user_message_id,
                    source_run_id=run_id,
                    source_message_id=user_message_id,
                )
                result.proposals.append(candidate)

    # ================================================================
    # Confirmed Decisions
    # ================================================================

    def _extract_confirmed_decisions(
        self, result: MemoryExtractionResult, user_input: str,
        session_id: str, run_id: str, user_message_id: str,
    ):
        """用户明确确认时才创建 confirmed_decision。

        含糊表达不形成确认。
        必须能唯一匹配 active proposal，否则不确认。
        """
        has_confirmation = any(kw in user_input for kw in CONFIRMATION_KEYWORDS)

        # 排除含糊模式
        vague_patterns = [
            r"也许", r"可能", r"大概", r"应该可以", r"试试",
            r"不一定", r"再说", r"看看",
        ]
        is_vague = any(re.search(p, user_input) for p in vague_patterns)

        if not has_confirmation or is_vague:
            return

        # 提取被确认的内容
        confirmed_content = user_input[:300]

        # Try to match a specific proposal
        matched_proposal_id = None
        matched_proposal_run_id = None
        agent_name_match = re.search(
            r'(CongestionAgent|SignalAgent|PublicSafetyAgent|DispatchAgent|AccidentAgent)',
            user_input,
        )
        has_ambiguous_ref = bool(re.search(r'这个方案|那个方案|第一种|第二种', user_input))

        if has_ambiguous_ref and not agent_name_match:
            # Ambiguous reference without specific agent → reject, don't confirm
            result.rejected_dynamic_facts.append({
                "action": "rejected",
                "reason": "ambiguous_proposal_reference",
                "memoryType": "confirmed_decision",
                "sourceRunId": run_id,
                "text": confirmed_content,
            })
            return

        if agent_name_match:
            matched_agent = agent_name_match.group(1)
            # Look through extracted proposals for a match
            for p in result.proposals:
                p_agent = p.value.get("agentName", "")
                if p_agent == matched_agent:
                    matched_proposal_run_id = p.source_run_id
                    break

        candidate = MemoryWriteCandidate(
            memory_type=MemoryType.CONFIRMED_DECISION.value,
            memory_key=f"decision.confirmed.{run_id}",
            value={
                "decision": confirmed_content,
                "confirmedProposalId": matched_proposal_id or "",
                "proposalSourceRunId": matched_proposal_run_id or "",
                "confirmationMessageId": user_message_id,
                "confirmationText": confirmed_content,
                "confirmedAt": "",  # filled by writer
            },
            text_content=confirmed_content,
            status=MemoryStatus.CONFIRMED.value,
            confidence=1.0,
            authority_level=AuthorityLevel.HUMAN_REVIEW,
            source_type=MemorySourceType.USER_EXPLICIT.value,
            source_id=user_message_id,
            source_run_id=run_id,
            source_message_id=user_message_id,
        )
        result.confirmed_decisions.append(candidate)

    # ================================================================
    # User Corrections
    # ================================================================

    def _extract_user_corrections(
        self, result: MemoryExtractionResult, user_input: str,
        current_event: Dict[str, Any],
        session_id: str, run_id: str, user_message_id: str,
    ):
        """识别用户纠正模式。"""
        has_correction = any(kw in user_input for kw in CORRECTION_KEYWORDS)
        if not has_correction:
            return

        # Pattern: "不是X，是Y" / "不是X而是Y"
        correction_patterns = [
            r'不是\s*(\S+?)\s*[,，]?\s*而是?\s*(\S+)',
            r'不是\s*(\S+?)[，,]\s*是\s*(\S+)',
            r'(\S+?)\s*改成\s*(\S+)',
            r'(\S+?)\s*更正为\s*(\S+)',
            r'应该是\s*(\S+)',
            r'修改为\s*(\S+)',
        ]

        for pattern in correction_patterns:
            match = re.search(pattern, user_input)
            if match:
                groups = match.groups()
                if len(groups) == 2:
                    old_val, new_val = groups[0], groups[1]
                else:
                    # "应该是X" / "修改为X"
                    old_val = ""
                    new_val = groups[0]

                # Try to detect which field is being corrected
                field_hints = {
                    "路": "road.name", "街": "road.name", "道": "road.name",
                    "学校": "school.nearby", "医院": "hospital.nearby",
                    "路口": "intersection.id",
                }
                memory_key = "correction.general"
                for hint, key in field_hints.items():
                    if hint in old_val or hint in new_val:
                        memory_key = key
                        break

                candidate = MemoryWriteCandidate(
                    memory_type=MemoryType.USER_CORRECTION.value,
                    memory_key=memory_key,
                    value={"oldValue": old_val, "newValue": new_val},
                    text_content=user_input[:300],
                    status=MemoryStatus.CONFIRMED.value,
                    confidence=1.0,
                    authority_level=AuthorityLevel.USER_CORRECTION,
                    source_type=MemorySourceType.USER_CORRECTION.value,
                    source_id=user_message_id,
                    source_run_id=run_id,
                    source_message_id=user_message_id,
                )
                result.user_corrections.append(candidate)
                return

    # ================================================================
    # Unresolved Issues
    # ================================================================

    def _extract_unresolved_issues(
        self, result: MemoryExtractionResult,
        conflicts: List[Dict[str, Any]],
        arbitration_results: List[Dict[str, Any]],
        requires_human_review: bool,
        final_decision: Any,
        session_id: str, run_id: str, user_message_id: str,
    ):
        """提取未解决问题。"""
        reasons = []

        # 1. requires_human_review flag
        if requires_human_review:
            reasons.append("requires_human_review")

        # 2. Unresolved conflicts
        for c in conflicts:
            if c.get("severity") in ("high", "critical"):
                resolved = any(
                    ar.get("conflict_id") == c.get("id", "")
                    and ar.get("resolved")
                    for ar in arbitration_results
                )
                if not resolved:
                    reasons.append(f"high_severity_conflict_unresolved:{c.get('description', '')[:80]}")

        # 3. Arbitration无法确定结果
        for ar in arbitration_results:
            if not ar.get("resolved"):
                reasons.append(f"arbitration_unresolved:{ar.get('conflict_id', '')}")

        # 4. Fusion 明确包含待确认标记
        fusion_text = ""
        if isinstance(final_decision, dict):
            fusion_text = str(final_decision.get("fusionSummary", ""))
        elif isinstance(final_decision, str):
            fusion_text = final_decision

        uncertainty_markers = ["待确认", "需人工复核", "信息不足", "建议人工"]
        for marker in uncertainty_markers:
            if marker in fusion_text:
                reasons.append(f"fusion_uncertainty:{marker}")
                break

        if not reasons:
            return

        for i, reason in enumerate(reasons[:5]):  # Cap at 5
            candidate = MemoryWriteCandidate(
                memory_type=MemoryType.UNRESOLVED_ISSUE.value,
                memory_key=f"unresolved.{run_id}.{i}",
                value={
                    "reason": reason,
                    "runId": run_id,
                    "requiresHumanReview": requires_human_review,
                },
                text_content=f"Unresolved: {reason}",
                status=MemoryStatus.ACTIVE.value,
                confidence=0.8,
                authority_level=AuthorityLevel.AGENT_FUSION,
                source_type=MemorySourceType.AGENT_FUSION.value,
                source_id=user_message_id,
                source_run_id=run_id,
                source_message_id=user_message_id,
            )
            result.unresolved_issues.append(candidate)

    # ================================================================
    # Run Summary
    # ================================================================

    def _extract_run_summary(
        self, result: MemoryExtractionResult, run_id: str,
        session_id: str, user_input: str,
        current_event: Dict[str, Any],
        selected_agents: List[str],
        conflicts: List[Dict[str, Any]],
        final_decision: Any, requires_human_review: bool,
        degraded: bool, user_message_id: str,
    ):
        """为已完成的 Run 创建摘要。"""
        fusion_text = ""
        if isinstance(final_decision, dict):
            fusion_text = str(final_decision.get("fusionSummary", ""))[:300]
        elif isinstance(final_decision, str):
            fusion_text = final_decision[:300]

        conflict_types = list(set(
            c.get("type", c.get("field", "unknown"))
            for c in (conflicts or [])
        ))

        candidate = MemoryWriteCandidate(
            memory_type=MemoryType.RUN_SUMMARY.value,
            memory_key=f"run.summary.{run_id}",
            value={
                "runId": run_id,
                "userQuery": user_input[:200],
                "currentEvent": {
                    "roadName": current_event.get("roadName", ""),
                    "eventTypeCn": current_event.get("eventTypeCn", ""),
                },
                "selectedAgents": selected_agents[:6],
                "conflictCount": len(conflicts or []),
                "conflictTypes": conflict_types[:5],
                "fusionSummary": fusion_text,
                "requiresHumanReview": requires_human_review,
                "degraded": degraded,
            },
            text_content=fusion_text[:300],
            status=MemoryStatus.ACTIVE.value,
            confidence=0.85,
            authority_level=AuthorityLevel.AGENT_FUSION,
            source_type=MemorySourceType.AGENT_FUSION.value,
            source_id=user_message_id,
            source_run_id=run_id,
            source_message_id=user_message_id,
        )
        result.run_summaries.append(candidate)

    # ================================================================
    # Temporary Facts
    # ================================================================

    def _extract_temporary_facts(
        self, result: MemoryExtractionResult, user_input: str,
        session_id: str, run_id: str, user_message_id: str,
    ):
        """提取用户明确给出有效期的临时事实。"""
        # Patterns: "到16:00", "未来30分钟", "今天早高峰", "封闭到X"
        time_patterns = [
            (r'[封关禁].*?到\s*(\d{1,2}[:：]\d{2})', None),
            (r'未来\s*(\d+)\s*分钟', lambda m: int(m.group(1))),
            (r'未来\s*(\d+)\s*小时', lambda m: int(m.group(1)) * 60),
            (r'预计.*?到\s*(\d{1,2}[:：]\d{2})', None),
        ]

        from backend.memory.time_utils import utc_now, to_iso_utc
        from datetime import timedelta

        for pattern, duration_fn in time_patterns:
            match = re.search(pattern, user_input)
            if not match:
                continue

            now = utc_now()
            if duration_fn:
                minutes = duration_fn(match)
                valid_until = to_iso_utc(now + timedelta(minutes=minutes))
            else:
                # Time-of-day pattern — assume today
                time_str = match.group(1).replace("：", ":")
                try:
                    hour, minute = map(int, time_str.split(":"))
                    deadline = now.replace(hour=hour, minute=minute, second=0)
                    if deadline <= now:
                        deadline += timedelta(days=1)
                    valid_until = to_iso_utc(deadline)
                except Exception:
                    continue

            candidate = MemoryWriteCandidate(
                memory_type=MemoryType.TEMPORARY_FACT.value,
                memory_key=f"temporary.{run_id}.restriction",
                value={
                    "restriction": user_input[:200],
                    "sourceRunId": run_id,
                },
                text_content=user_input[:300],
                status=MemoryStatus.ACTIVE.value,
                confidence=0.9,
                authority_level=AuthorityLevel.HUMAN_REVIEW,
                source_type=MemorySourceType.USER_EXPLICIT.value,
                source_id=user_message_id,
                source_run_id=run_id,
                source_message_id=user_message_id,
                valid_until=valid_until,
            )
            result.temporary_facts.append(candidate)
            return

        # No valid TTL found — explicitly reject
        result.rejected_dynamic_facts.append({
            "action": "rejected",
            "reason": "temporary_fact_missing_ttl",
            "memoryType": "temporary_fact",
            "memoryKey": "temporary.restriction",
            "sourceRunId": run_id,
        })
