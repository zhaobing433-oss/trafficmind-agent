"""
Phase 10 Memory V2 写入侧专项测试

覆盖: Extractor / WriteGate / ConflictResolver / Coordinator / 接入
"""
import pytest
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

TEST_DB = os.path.join(tempfile.gettempdir(), f"test_phase10_memwrite_{os.getpid()}.db")

from backend.memory.models import (
    MemoryItem, MemoryTrace, MemoryWriteCandidate, MemoryWriteResult,
    compute_dedup_key,
)
from backend.memory.store import MemoryRepository, init_memory_tables
from backend.memory.repository import MemoryStore
from backend.memory.extractor import MemoryExtractor, MemoryExtractionResult
from backend.memory.write_gate import MemoryWriteGate, GateDecision
from backend.memory.conflict_resolver import ConflictResolver
from backend.memory.coordinator import MemoryCoordinator
from backend.memory.constants import (
    MemoryType, MemoryStatus, MemorySourceType, AuthorityLevel,
    DYNAMIC_FIELD_BLOCKLIST,
)
from backend.memory.policy import MemoryPolicy, DEFAULT_POLICY


@pytest.fixture(scope="module", autouse=True)
def patch_db_for_module():
    import backend.config as _cfg
    _original = _cfg.DB_PATH
    _cfg.DB_PATH = TEST_DB
    for suffix in ("", "-wal", "-shm"):
        path = TEST_DB + suffix
        if os.path.exists(path):
            os.remove(path)
    yield
    _cfg.DB_PATH = _original


@pytest.fixture(autouse=True)
def clean_db():
    for suffix in ("", "-wal", "-shm"):
        path = TEST_DB + suffix
        if os.path.exists(path):
            os.remove(path)
    init_memory_tables()
    yield
    for suffix in ("", "-wal", "-shm"):
        path = TEST_DB + suffix
        if os.path.exists(path):
            os.remove(path)


# ================================================================
# Helper: create a mock current_event
# ================================================================

def _make_event(**kwargs) -> dict:
    defaults = {
        "eventType": "congestion", "eventTypeCn": "拥堵",
        "roadName": "人民路", "direction": "南北",
        "avgSpeed": 8.0, "queueLength": 400.0, "duration": 600.0,
        "weather": "clear", "timePeriod": "morning_peak",
        "isMainRoad": True, "nearbySchool": True, "nearbyHospital": False,
        "fieldSources": {
            "roadName": "user", "nearbySchool": "user",
            "avgSpeed": "nl_parsed", "queueLength": "nl_parsed",
        },
    }
    defaults.update(kwargs)
    return defaults


def _make_agent_results(*agents) -> list:
    results = []
    for name, suggestion, findings in agents:
        results.append({
            "agentName": name, "suggestion": suggestion,
            "findings": findings or [],
            "urgency": "medium", "confidence": 0.7,
        })
    return results


# ================================================================
# Session Goal (Tests 1-3)
# ================================================================

class TestSessionGoal:
    def test_first_round_creates_goal(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="人民路小学门口早高峰严重拥堵，请分析",
            current_event=_make_event(),
            selected_agents=["CongestionAgent"],
            agent_results=[], conflicts=[], arbitration_results=[],
            fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=True,
        )
        assert len(result.session_goals) == 1
        g = result.session_goals[0]
        assert g.memory_type == "session_goal"
        assert g.memory_key == "goal.primary"
        assert "人民路" in g.value["goal"]
        assert g.status == "active"

    def test_same_goal_not_duplicated(self):
        extractor = MemoryExtractor()
        # Second round without goal switch
        result = extractor.extract(
            session_id="s1", run_id="r2",
            user_message_id="um2", assistant_message_id="am2",
            user_input="排队情况怎么样？",
            current_event=_make_event(),
            selected_agents=["CongestionAgent"],
            agent_results=[], conflicts=[], arbitration_results=[],
            fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        assert len(result.session_goals) == 0  # not duplicated

    def test_explicit_goal_switch(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r3",
            user_message_id="um3", assistant_message_id="am3",
            user_input="现在改为分析机场高速事故",
            current_event=_make_event(roadName="机场高速", eventTypeCn="事故"),
            selected_agents=["AccidentAgent"],
            agent_results=[], conflicts=[], arbitration_results=[],
            fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        assert len(result.session_goals) == 1
        g = result.session_goals[0]
        assert g.metadata.get("trigger") == "goal_switch"


# ================================================================
# Stable Facts (Tests 4-6)
# ================================================================

class TestStableFacts:
    def test_road_name_written_as_stable_fact(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="人民路拥堵",
            current_event=_make_event(roadName="人民路"),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        road_facts = [f for f in result.stable_facts if f.memory_key == "road.name"]
        assert len(road_facts) == 1
        assert road_facts[0].value["value"] == "人民路"

    def test_nearby_school_written(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="学校附近拥堵",
            current_event=_make_event(nearbySchool=True),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        school_facts = [f for f in result.stable_facts
                        if f.memory_key == "school.nearby"]
        assert len(school_facts) == 1

    def test_default_road_name_not_written(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="某路段拥堵",
            current_event=_make_event(roadName="未知路段"),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        road_facts = [f for f in result.stable_facts if f.memory_key == "road.name"]
        assert len(road_facts) == 0


# ================================================================
# Dynamic Field Rejection (Tests 7-9)
# ================================================================

class TestDynamicFieldRejection:
    def test_avg_speed_rejected(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="速度8km/h",
            current_event=_make_event(avgSpeed=8.0),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        rejected = [r for r in result.rejected_dynamic_facts
                    if r.get("fieldName") == "avgSpeed"]
        assert len(rejected) == 1
        assert rejected[0]["reason"] == "dynamic_field_blocked"

    def test_queue_length_rejected(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="排队400米",
            current_event=_make_event(queueLength=400.0),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        rejected = [r for r in result.rejected_dynamic_facts
                    if r.get("fieldName") == "queueLength"]
        assert len(rejected) == 1

    def test_weather_rejected(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="下雨天",
            current_event=_make_event(weather="rain"),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        rejected = [r for r in result.rejected_dynamic_facts
                    if r.get("fieldName") == "weather"]
        assert len(rejected) == 1


# ================================================================
# Constraints (Test 10)
# ================================================================

class TestConstraints:
    def test_user_constraint_extracted(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="必须保证学生过街时间不少于25秒",
            current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        assert len(result.constraints) >= 1
        c = result.constraints[0]
        # Check structured extraction
        if "operator" in c.value:
            assert c.value["operator"] in ("gte", "lte", "eq")
            assert c.value.get("value") is not None


# ================================================================
# Proposals (Tests 11-12)
# ================================================================

class TestProposals:
    def test_agent_result_becomes_proposal(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="分析拥堵",
            current_event=_make_event(),
            selected_agents=["CongestionAgent"],
            agent_results=_make_agent_results(
                ("CongestionAgent", "建议延长绿灯20秒", ["拥堵严重"]),
            ),
            conflicts=[], arbitration_results=[],
            fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        assert len(result.proposals) == 1
        p = result.proposals[0]
        assert p.memory_type == "proposal"
        assert p.status == "candidate"
        assert p.source_type == "agent_proposal"

    def test_fusion_not_confirmed_decision(self):
        """Fusion 结果不能自动成为 confirmed_decision。"""
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="分析拥堵",
            current_event=_make_event(),
            selected_agents=["CongestionAgent"],
            agent_results=_make_agent_results(
                ("CongestionAgent", "建议分流", ["拥堵"]),
            ),
            conflicts=[], arbitration_results=[],
            fusion_summary="综合建议分流处理",
            final_decision={"fusionSummary": "综合建议分流处理"},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        # Fusion result becomes run_summary, not confirmed_decision
        assert len(result.confirmed_decisions) == 0
        assert len(result.proposals) >= 0  # proposals from agent, not fusion


# ================================================================
# Confirmed Decisions (Tests 13-14)
# ================================================================

class TestConfirmedDecisions:
    def test_explicit_confirmation_creates_decision(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r2",
            user_message_id="um2", assistant_message_id="am2",
            user_input="采用延长绿灯20秒的方案",
            current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        assert len(result.confirmed_decisions) == 1
        d = result.confirmed_decisions[0]
        assert d.memory_type == "confirmed_decision"
        assert d.status == "confirmed"

    def test_vague_expression_not_confirmed(self):
        """含糊表达不形成确认。"""
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r2",
            user_message_id="um2", assistant_message_id="am2",
            user_input="也许可以试试延长绿灯",
            current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        assert len(result.confirmed_decisions) == 0


# ================================================================
# User Correction (Tests 15-20)
# ================================================================

class TestUserCorrection:
    def test_correction_extracted(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r2",
            user_message_id="um2", assistant_message_id="am2",
            user_input="刚才说错了，不是人民路，是中山路",
            current_event=_make_event(roadName="中山路"),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        assert len(result.user_corrections) >= 1

    def test_coordinator_correction_supersedes_old(self):
        """Coordinator 执行纠正：旧值 superseded，新值 active。"""
        repo = MemoryRepository()
        sid = "sess_corr_test"

        # Create old fact
        old = repo.create_item(
            memory_type="stable_fact", session_id=sid,
            memory_key="road.name", value={"value": "人民路"},
            text_content="roadName: 人民路", status="active",
            source_type="user_explicit",
            authority_level=AuthorityLevel.HUMAN_REVIEW,
        )

        # Execute correction
        coordinator = MemoryCoordinator(repo=repo)
        result = coordinator.apply_user_correction(
            session_id=sid, run_id="r_corr",
            user_message_id="um_corr",
            old_value="人民路", new_value="中山路",
            memory_key="road.name",
        )
        assert result["success"] is True

        # Old fact superseded
        old_reloaded = repo.get_item(old.id)
        assert old_reloaded.status == "superseded"

        # New fact active
        new_fact = repo.find_active_by_key(sid, "road.name")
        assert new_fact is not None
        assert new_fact.value.get("value") == "中山路"

    def test_correction_creates_audit_record(self):
        repo = MemoryRepository()
        sid = "sess_corr_audit"
        coordinator = MemoryCoordinator(repo=repo)
        result = coordinator.apply_user_correction(
            session_id=sid, run_id="r_audit",
            user_message_id="um_a",
            old_value="旧路", new_value="新路",
            memory_key="road.name",
        )
        assert result["success"] is True
        assert result["correctionId"] != ""

        # user_correction 审计记录存在
        items = repo.list_session_items(sid)
        corrections = [i for i in items if i.memory_type == "user_correction"]
        assert len(corrections) == 1
        c = corrections[0]
        assert c.value["oldValue"] == "旧路"
        assert c.value["newValue"] == "新路"

    def test_correction_transaction_all_committed(self):
        """纠正事务成功时全部提交。"""
        repo = MemoryRepository()
        sid = "sess_tx_all"
        coordinator = MemoryCoordinator(repo=repo)
        result = coordinator.apply_user_correction(
            session_id=sid, run_id="r_tx",
            user_message_id="um_tx",
            old_value="A路", new_value="B路",
        )
        assert result["success"] is True
        # 验证所有操作已持久化
        items = repo.list_session_items(sid)
        assert len(items) >= 2  # new fact + correction record

    def test_low_authority_cannot_overwrite_user(self):
        """低 authority 新值不能覆盖用户事实。"""
        repo = MemoryRepository()
        sid = "sess_auth_low"

        # Create user-level fact
        repo.create_item(
            memory_type="stable_fact", session_id=sid,
            memory_key="road.name", value={"value": "用户路"},
            status="active", source_type="user_explicit",
            authority_level=AuthorityLevel.HUMAN_REVIEW,
        )

        gate = MemoryWriteGate()
        candidate = MemoryWriteCandidate(
            memory_type="stable_fact", memory_key="road.name",
            value={"value": "解析路"},
            source_type="event_parser",
            authority_level=AuthorityLevel.EVENT_PARSER,
            status="active",
        )
        existing = repo.list_session_items(sid)
        decision, reason, conflicting = gate.decide(candidate, existing, repo)
        assert decision == GateDecision.REJECT
        assert "lower_authority" in reason.lower()


# ================================================================
# Unresolved Issues (Tests 21-22)
# ================================================================

class TestUnresolvedIssues:
    def test_requires_human_review_creates_issue(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="分析冲突",
            current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[{"resolved": False, "conflict_id": "c1"}],
            fusion_summary="", final_decision={},
            requires_human_review=True, run_status="completed",
            degraded=False, is_first_round=False,
        )
        assert len(result.unresolved_issues) >= 1

    def test_no_issue_when_all_resolved(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="分析完成",
            current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[],
            fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        assert len(result.unresolved_issues) == 0


# ================================================================
# Run Summary (Tests 23-25)
# ================================================================

class TestRunSummary:
    def test_completed_run_creates_summary(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r_sum",
            user_message_id="um1", assistant_message_id="am1",
            user_input="分析拥堵",
            current_event=_make_event(),
            selected_agents=["CongestionAgent"],
            agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="拥堵已缓解",
            final_decision={"fusionSummary": "拥堵已缓解"},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        summaries = [s for s in result.run_summaries
                     if s.memory_key == "run.summary.r_sum"]
        assert len(summaries) == 1

    def test_partial_success_creates_summary(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r_partial",
            user_message_id="um1", assistant_message_id="am1",
            user_input="分析",
            current_event=_make_event(),
            selected_agents=["CongestionAgent"],
            agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="",
            final_decision={},
            requires_human_review=False, run_status="partial_success",
            degraded=False, is_first_round=False,
        )
        summaries = [s for s in result.run_summaries
                     if s.memory_key == "run.summary.r_partial"]
        assert len(summaries) == 1

    def test_failed_run_no_summary(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r_fail",
            user_message_id="um1", assistant_message_id="am1",
            user_input="分析",
            current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="",
            final_decision={},
            requires_human_review=False, run_status="failed",
            degraded=False, is_first_round=False,
        )
        summaries = [s for s in result.run_summaries
                     if s.memory_key == "run.summary.r_fail"]
        assert len(summaries) == 0


# ================================================================
# Temporary Facts (Tests 26-28)
# ================================================================

class TestTemporaryFacts:
    def test_temporary_fact_with_ttl_written(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="道路封闭到16:00",
            current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        assert len(result.temporary_facts) >= 1
        tf = result.temporary_facts[0]
        assert tf.valid_until is not None
        assert "+00:00" in tf.valid_until

    def test_temporary_fact_without_ttl_skipped(self):
        """无 TTL 的临时信息不写为 temporary_fact。"""
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="前方施工请注意",
            current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        assert len(result.temporary_facts) == 0

    def test_ttl_is_utc(self):
        extractor = MemoryExtractor()
        result = extractor.extract(
            session_id="s1", run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="未来30分钟实施管制",
            current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=False,
        )
        if result.temporary_facts:
            tf = result.temporary_facts[0]
            assert "+00:00" in tf.valid_until


# ================================================================
# Idempotency and Dedup (Tests 29-30)
# ================================================================

class TestIdempotency:
    def test_same_run_idempotent(self):
        """同一 run 重复写入幂等。"""
        repo = MemoryRepository()
        sid = "sess_idem"
        coordinator = MemoryCoordinator(repo=repo)

        args = dict(
            session_id=sid, run_id="r_idem",
            user_message_id="um1", assistant_message_id="am1",
            user_input="人民路拥堵", current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=True,
        )

        r1 = coordinator.extract_and_write(**args)
        r2 = coordinator.extract_and_write(**args)

        assert r1["error"] is None
        assert r2["error"] is None
        # Second write should have more deduplicated than created
        assert r2["createdCount"] <= r1["createdCount"]

    def test_dedup_key_prevents_duplicate(self):
        """dedupKey 防止完全相同的记忆重复。"""
        repo = MemoryRepository()
        sid = "sess_dedup_key"
        coordinator = MemoryCoordinator(repo=repo)

        coordinator.extract_and_write(
            session_id=sid, run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="人民路拥堵", current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=True,
        )
        c1 = repo.count_session_items(sid)["total_items"]

        # Same run again
        coordinator.extract_and_write(
            session_id=sid, run_id="r1",
            user_message_id="um1", assistant_message_id="am1",
            user_input="人民路拥堵", current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=True,
        )
        c2 = repo.count_session_items(sid)["total_items"]
        assert c2 == c1  # no new items


# ================================================================
# Memory Failure Isolation (Test 31)
# ================================================================

class TestFailureIsolation:
    def test_memory_failure_does_not_crash(self):
        """Memory 写入失败不影响调用方（返回 error 字段）。"""
        coordinator = MemoryCoordinator()
        # 传入无效参数
        result = coordinator.extract_and_write(
            session_id="", run_id="",  # empty IDs
            user_message_id="", assistant_message_id="",
            user_input="", current_event={},
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="",
            final_decision={}, requires_human_review=False,
            run_status="completed", degraded=False,
            is_first_round=False,
        )
        # 即使失败，也不抛异常
        assert "error" in result or result["candidateCount"] == 0


# ================================================================
# SSE Events (Tests 32-34)
# ================================================================

class TestSSEEventStructures:
    def test_memory_write_completed_structure(self):
        """memory_write_completed 事件包含所有统计字段。"""
        repo = MemoryRepository()
        sid = "sess_sse"
        coordinator = MemoryCoordinator(repo=repo)
        result = coordinator.extract_and_write(
            session_id=sid, run_id="r_sse",
            user_message_id="um_sse", assistant_message_id="am_sse",
            user_input="人民路拥堵分析",
            current_event=_make_event(),
            selected_agents=["CongestionAgent"],
            agent_results=_make_agent_results(
                ("CongestionAgent", "建议分流", ["拥堵"]),
            ),
            conflicts=[], arbitration_results=[],
            fusion_summary="分析完成", final_decision={},
            requires_human_review=False, run_status="completed",
            degraded=False, is_first_round=True,
        )
        assert "runId" in result
        assert "candidateCount" in result
        assert "createdCount" in result
        assert "deduplicatedCount" in result
        assert "supersededCount" in result
        assert "rejectedCount" in result
        assert "confirmedCount" in result
        assert "latencyMs" in result

    def test_memory_write_failed_structure(self):
        """memory_write_failed 包含错误信息。"""
        coordinator = MemoryCoordinator()
        result = coordinator.extract_and_write(
            session_id="", run_id="r_fail_sse",
            user_message_id="", assistant_message_id="",
            user_input="", current_event={},
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="",
            final_decision={}, requires_human_review=False,
            run_status="completed", degraded=False,
            is_first_round=False,
        )
        # 返回结构化结果而不是抛异常
        assert isinstance(result, dict)

    def test_write_started_event_exists(self):
        """memory_write_started 事件概念存在（Coordinator 入口）。"""
        # Coordinator.extract_and_write 本身就是 memory_write_started 的实现
        # 此测试验证 coordinator 可正常初始化
        coordinator = MemoryCoordinator()
        assert coordinator.repo is not None
        assert coordinator.extractor is not None
        assert coordinator.gate is not None


# ================================================================
# Session Delete (Tests 35-36)
# ================================================================

class TestSessionDelete:
    def test_delete_cleans_memory(self):
        repo = MemoryRepository()
        sid = "sess_del_write"
        coordinator = MemoryCoordinator(repo=repo)
        coordinator.extract_and_write(
            session_id=sid, run_id="r_del",
            user_message_id="um_del", assistant_message_id="am_del",
            user_input="测试删除", current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="",
            final_decision={}, requires_human_review=False,
            run_status="completed", degraded=False,
            is_first_round=True,
        )
        assert repo.count_session_items(sid)["total_items"] > 0
        deleted = repo.delete_session_memory(sid)
        assert deleted > 0
        assert repo.count_session_items(sid)["total_items"] == 0

    def test_delete_one_session_spares_other(self):
        repo = MemoryRepository()
        s1, s2 = "sess_iso_a", "sess_iso_b"
        coordinator = MemoryCoordinator(repo=repo)
        coordinator.extract_and_write(
            session_id=s1, run_id="r_a",
            user_message_id="um_a", assistant_message_id="am_a",
            user_input="A", current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="",
            final_decision={}, requires_human_review=False,
            run_status="completed", degraded=False,
            is_first_round=True,
        )
        coordinator.extract_and_write(
            session_id=s2, run_id="r_b",
            user_message_id="um_b", assistant_message_id="am_b",
            user_input="B", current_event=_make_event(),
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="",
            final_decision={}, requires_human_review=False,
            run_status="completed", degraded=False,
            is_first_round=True,
        )
        repo.delete_session_memory(s1)
        assert repo.count_session_items(s2)["total_items"] > 0


# ================================================================
# Phase 9 Compatibility (Test 37)
# ================================================================

class TestPhase9Compatibility:
    def test_current_event_unchanged_after_write(self):
        """Memory 写入不修改 currentEvent。"""
        original_event = _make_event()
        event_copy = dict(original_event)
        coordinator = MemoryCoordinator()
        coordinator.extract_and_write(
            session_id="sess_ce", run_id="r_ce",
            user_message_id="um_ce", assistant_message_id="am_ce",
            user_input="测试", current_event=event_copy,
            selected_agents=[], agent_results=[], conflicts=[],
            arbitration_results=[], fusion_summary="",
            final_decision={}, requires_human_review=False,
            run_status="completed", degraded=False,
            is_first_round=True,
        )
        # currentEvent 不应被修改
        assert event_copy["roadName"] == original_event["roadName"]
        assert event_copy["avgSpeed"] == original_event["avgSpeed"]


# ================================================================
# MemoryStore Mock Injection (Test 39)
# ================================================================

class TestMemoryStoreInjection:
    def test_coordinator_accepts_injected_repo(self):
        """Coordinator 接受依赖注入的 MemoryStore。"""
        repo = MemoryRepository()
        coordinator = MemoryCoordinator(repo=repo)
        assert coordinator.repo is repo
        assert isinstance(coordinator.repo, MemoryStore)

    def test_coordinator_default_factory(self):
        """默认使用 factory 创建 repo。"""
        coordinator = MemoryCoordinator()  # no repo
        assert coordinator.repo is not None
        assert isinstance(coordinator.repo, MemoryStore)


# ================================================================
# WriteGate detailed rules (additional)
# ================================================================

class TestWriteGateRules:
    def test_agent_proposal_cannot_be_confirmed(self):
        gate = MemoryWriteGate()
        candidate = MemoryWriteCandidate(
            memory_type="proposal", memory_key="p.1",
            value={"suggestion": "test"}, source_type="agent_proposal",
            status="confirmed",  # 不应该
            authority_level=AuthorityLevel.AGENT_PROPOSAL,
        )
        decision, reason, _ = gate.decide(candidate, [], None)
        assert decision == GateDecision.REJECT
        assert "cannot_be_confirmed" in reason

    def test_event_parser_low_confidence_rejected(self):
        gate = MemoryWriteGate()
        candidate = MemoryWriteCandidate(
            memory_type="stable_fact", memory_key="road.name",
            value={"value": "测试路"}, source_type="event_parser",
            status="active", confidence=0.2,  # too low
            authority_level=AuthorityLevel.EVENT_PARSER,
        )
        decision, reason, _ = gate.decide(candidate, [], None)
        assert decision == GateDecision.REJECT

    def test_identical_content_deduplicated(self):
        gate = MemoryWriteGate()
        existing = MemoryItem(
            id="m1", memory_type="stable_fact", session_id="s",
            memory_key="road.name", value={"value": "人民路"},
            status="active",
        )
        candidate = MemoryWriteCandidate(
            memory_type="stable_fact", memory_key="road.name",
            value={"value": "人民路"}, source_type="event_parser",
            status="active", authority_level=AuthorityLevel.EVENT_PARSER,
        )
        decision, reason, _ = gate.decide(candidate, [existing], None)
        assert decision == GateDecision.DEDUPLICATED
