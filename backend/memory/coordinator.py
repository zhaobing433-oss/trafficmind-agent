"""
Memory V2 协调器 — Phase 10 里程碑二

编排完整的 Memory 写入流程：
Extractor → Policy → WriteGate → ConflictResolver → Store(tx) → Trace
"""

import time
import logging
from typing import Any, Dict, List, Optional

from backend.memory.models import (
    MemoryItem,
    MemoryTrace,
    MemoryWriteCandidate,
    MemoryWriteResult,
)
from backend.memory.repository import MemoryStore
from backend.memory.extractor import MemoryExtractor, MemoryExtractionResult
from backend.memory.write_gate import MemoryWriteGate, GateDecision
from backend.memory.conflict_resolver import ConflictResolver
from backend.memory.constants import (
    MemoryType,
    MemoryStatus,
    MemorySourceType,
    AuthorityLevel,
)
from backend.memory.policy import DEFAULT_POLICY

logger = logging.getLogger(__name__)


class MemoryCoordinator:
    """Memory V2 写入协调器。

    协调 Extractor → Policy → WriteGate → ConflictResolver → Store → Trace
    的完整流程。

    Repository 通过依赖注入获得，默认使用 factory。
    """

    def __init__(self, repo: Optional[MemoryStore] = None):
        """
        Args:
            repo: MemoryStore 实现。为 None 时使用默认 factory。
        """
        if repo is None:
            from backend.memory.factory import create_memory_repository
            repo = create_memory_repository()
        self.repo: MemoryStore = repo
        self.extractor = MemoryExtractor()
        self.gate = MemoryWriteGate()
        self.resolver = ConflictResolver()

    def extract_and_write(
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
    ) -> Dict[str, Any]:
        """执行完整的 Memory 抽取和写入流程。

        Returns:
            {
                "runId": str,
                "sessionId": str,
                "candidateCount": int,
                "createdCount": int,
                "deduplicatedCount": int,
                "supersededCount": int,
                "rejectedCount": int,
                "confirmedCount": int,
                "latencyMs": int,
                "traceId": str,
                "writeResults": List[Dict],
                "error": Optional[str],
            }
        """
        start_time = time.time()
        trace_id = f"memtrace_{run_id}"
        write_results: List[Dict[str, Any]] = []

        try:
            # ============ Step 1: Extract ============
            extraction: MemoryExtractionResult = self.extractor.extract(
                session_id=session_id,
                run_id=run_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                user_input=user_input,
                current_event=current_event,
                selected_agents=selected_agents,
                agent_results=agent_results,
                conflicts=conflicts,
                arbitration_results=arbitration_results,
                fusion_summary=fusion_summary,
                final_decision=final_decision,
                requires_human_review=requires_human_review,
                run_status=run_status,
                degraded=degraded,
                is_first_round=is_first_round,
            )

            candidates = extraction.all_candidates()
            if not candidates:
                return self._empty_result(run_id, session_id, trace_id,
                                          int((time.time() - start_time) * 1000))

            # ============ Step 2: Load existing items for conflict check ============
            existing_items = self.repo.list_session_items(session_id, limit=500)

            # ============ Step 3: Gate decisions ============
            gate_decisions = []
            for candidate in candidates:
                decision = self.gate.decide(candidate, existing_items, self.repo)
                gate_decisions.append(decision)

            # ============ Step 4: Conflict resolve ============
            resolved = self.resolver.resolve(candidates, gate_decisions,
                                             existing_items)

            # ============ Step 5: Transactional write ============
            counts = {"created": 0, "deduplicated": 0, "superseded": 0,
                      "rejected": 0, "confirmed": 0, "no_op": 0}

            with self.repo.transaction() as tx:
                for candidate, action, reason, superseded_id in resolved:
                    wr = self._execute_action(
                        candidate, action, reason, superseded_id,
                        session_id, run_id,
                    )
                    write_results.append(wr)
                    if action in counts:
                        counts[action] += 1

                # Save trace
                trace = MemoryTrace(
                    trace_id=trace_id,
                    run_id=run_id,
                    session_id=session_id,
                    recall_intent="write_phase",
                    candidates_json="[]",  # JSON handled at repo boundary
                    selected_json="[]",
                    rejected_json="[]",
                    injection_map_json="{}",
                    write_candidates_json="[]",
                    write_results_json="[]",
                    token_estimate=0,
                    recall_latency_ms=0,
                    write_latency_ms=0,
                )
                self.repo.save_trace(trace)

                tx.commit()

            latency_ms = int((time.time() - start_time) * 1000)

            return {
                "runId": run_id,
                "sessionId": session_id,
                "candidateCount": len(candidates),
                "createdCount": counts.get("created", 0),
                "deduplicatedCount": counts.get("deduplicated", 0),
                "supersededCount": counts.get("superseded", 0),
                "rejectedCount": counts.get("rejected", 0),
                "confirmedCount": counts.get("confirmed", 0),
                "latencyMs": latency_ms,
                "traceId": trace_id,
                "writeResults": write_results,
                "error": None,
            }

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Memory write failed for run {run_id}: {e}", exc_info=True)
            return {
                "runId": run_id,
                "sessionId": session_id,
                "candidateCount": 0,
                "createdCount": 0,
                "deduplicatedCount": 0,
                "supersededCount": 0,
                "rejectedCount": 0,
                "confirmedCount": 0,
                "latencyMs": latency_ms,
                "traceId": trace_id,
                "writeResults": write_results,
                "error": str(e),
            }

    def _execute_action(
        self,
        candidate: MemoryWriteCandidate,
        action: str,
        reason: Optional[str],
        superseded_id: Optional[str],
        session_id: str,
        run_id: str,
    ) -> Dict[str, Any]:
        """执行单个写入操作。"""
        result = {
            "memoryType": candidate.memory_type,
            "memoryKey": candidate.memory_key,
            "action": action,
            "reason": reason or "",
        }

        try:
            if action == "create":
                item = self.repo.create_item(
                    memory_type=candidate.memory_type,
                    session_id=session_id,
                    memory_key=candidate.memory_key,
                    value=candidate.value,
                    text_content=candidate.text_content,
                    status=candidate.status,
                    confidence=candidate.confidence,
                    authority_level=candidate.authority_level,
                    source_type=candidate.source_type,
                    source_id=candidate.source_id,
                    source_run_id=candidate.source_run_id,
                    source_message_id=candidate.source_message_id,
                    valid_until=candidate.valid_until,
                )
                result["itemId"] = item.id

            elif action == "supersede" and superseded_id:
                new_item = MemoryItem(
                    id="",  # auto-generated
                    memory_type=candidate.memory_type,
                    session_id=session_id,
                    memory_key=candidate.memory_key,
                    value=candidate.value,
                    text_content=candidate.text_content,
                    status=candidate.status,
                    confidence=candidate.confidence,
                    authority_level=candidate.authority_level,
                    source_type=candidate.source_type,
                    source_id=candidate.source_id,
                    source_run_id=candidate.source_run_id,
                    source_message_id=candidate.source_message_id,
                    valid_until=candidate.valid_until,
                    scope_type="session",
                    scope_id=session_id,
                )
                old_item, new_created = self.repo.supersede_item(
                    superseded_id, new_item
                )
                result["itemId"] = new_created.id
                result["supersededId"] = superseded_id

            elif action == "confirm":
                # Find existing item with same key and type, confirm it
                existing = self.repo.find_active_by_key(
                    session_id, candidate.memory_key
                )
                if existing and existing.memory_type == candidate.memory_type:
                    self.repo.confirm_item(existing.id)
                    result["itemId"] = existing.id
                else:
                    # Create as confirmed
                    item = self.repo.create_item(
                        memory_type=candidate.memory_type,
                        session_id=session_id,
                        memory_key=candidate.memory_key,
                        value=candidate.value,
                        text_content=candidate.text_content,
                        status=MemoryStatus.CONFIRMED.value,
                        confidence=1.0,
                        authority_level=candidate.authority_level,
                        source_type=candidate.source_type,
                        source_id=candidate.source_id,
                        source_run_id=run_id,
                        source_message_id=candidate.source_message_id,
                    )
                    result["itemId"] = item.id

            elif action == "deduplicated":
                result["action"] = "deduplicated"

            elif action == "reject":
                result["action"] = "rejected"

            elif action == "no_op":
                result["action"] = "no_op"

        except Exception as e:
            result["action"] = "error"
            result["error"] = str(e)
            logger.error(f"Memory action '{action}' failed for "
                         f"{candidate.memory_key}: {e}")

        return result

    # ================================================================
    # User Correction (atomic transaction)
    # ================================================================

    def apply_user_correction(
        self,
        session_id: str,
        run_id: str,
        user_message_id: str,
        old_value: str,
        new_value: str,
        memory_key: str = "road.name",
        field_name: str = "roadName",
    ) -> Dict[str, Any]:
        """在单个事务中执行用户纠正：

        1. 查询并 supersede 旧事实
        2. 创建新事实
        3. 创建 user_correction 审计记录
        4. 保存 MemoryTrace

        Returns:
            {
                "success": bool,
                "supersededId": str,
                "newItemId": str,
                "correctionId": str,
                "traceId": str,
                "error": Optional[str],
            }
        """
        trace_id = f"memtrace_correction_{run_id}"
        result = {
            "success": False,
            "supersededId": "",
            "newItemId": "",
            "correctionId": "",
            "traceId": trace_id,
            "error": None,
        }

        try:
            with self.repo.transaction() as tx:
                # 1. Find old active fact
                old_item = self.repo.find_active_by_key(session_id, memory_key)

                if old_item and old_item.memory_type == MemoryType.STABLE_FACT.value:
                    # 2. Supersede old + create new
                    new_value_dict = {"value": new_value}
                    new_item = MemoryItem(
                        id="",
                        memory_type=MemoryType.STABLE_FACT.value,
                        session_id=session_id,
                        memory_key=memory_key,
                        value=new_value_dict,
                        text_content=f"{field_name}: {new_value}",
                        status=MemoryStatus.ACTIVE.value,
                        confidence=1.0,
                        authority_level=AuthorityLevel.USER_CORRECTION,
                        source_type=MemorySourceType.USER_CORRECTION.value,
                        source_id=user_message_id,
                        source_run_id=run_id,
                        source_message_id=user_message_id,
                        scope_type="session",
                        scope_id=session_id,
                    )
                    old_upd, new_created = self.repo.supersede_item(
                        old_item.id, new_item
                    )
                    result["supersededId"] = old_item.id
                    result["newItemId"] = new_created.id
                else:
                    # No old fact to supersede — just create
                    new_value_dict = {"value": new_value}
                    new_created = self.repo.create_item(
                        memory_type=MemoryType.STABLE_FACT.value,
                        session_id=session_id,
                        memory_key=memory_key,
                        value=new_value_dict,
                        text_content=f"{field_name}: {new_value}",
                        status=MemoryStatus.ACTIVE.value,
                        confidence=1.0,
                        authority_level=AuthorityLevel.USER_CORRECTION,
                        source_type=MemorySourceType.USER_CORRECTION.value,
                        source_id=user_message_id,
                        source_run_id=run_id,
                        source_message_id=user_message_id,
                    )
                    result["newItemId"] = new_created.id

                # 3. Create user_correction audit record
                correction = self.repo.create_item(
                    memory_type=MemoryType.USER_CORRECTION.value,
                    session_id=session_id,
                    memory_key=memory_key,
                    value={"oldValue": old_value, "newValue": new_value},
                    text_content=f"纠正: {old_value} → {new_value}",
                    status=MemoryStatus.CONFIRMED.value,
                    confidence=1.0,
                    authority_level=AuthorityLevel.USER_CORRECTION,
                    source_type=MemorySourceType.USER_CORRECTION.value,
                    source_id=user_message_id,
                    source_run_id=run_id,
                    source_message_id=user_message_id,
                )
                result["correctionId"] = correction.id

                # 4. Save trace
                trace = MemoryTrace(
                    trace_id=trace_id,
                    run_id=run_id,
                    session_id=session_id,
                    recall_intent=f"user_correction: {old_value} → {new_value}",
                )
                self.repo.save_trace(trace)

                tx.commit()
                result["success"] = True

        except Exception as e:
            logger.error(f"User correction failed for {memory_key}: {e}",
                         exc_info=True)
            result["error"] = str(e)

        return result

    @staticmethod
    def _empty_result(
        run_id: str, session_id: str, trace_id: str, latency_ms: int,
    ) -> Dict[str, Any]:
        return {
            "runId": run_id,
            "sessionId": session_id,
            "candidateCount": 0,
            "createdCount": 0,
            "deduplicatedCount": 0,
            "supersededCount": 0,
            "rejectedCount": 0,
            "confirmedCount": 0,
            "latencyMs": latency_ms,
            "traceId": trace_id,
            "writeResults": [],
            "error": None,
        }
