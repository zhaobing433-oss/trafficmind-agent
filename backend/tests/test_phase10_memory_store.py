"""
Phase 10 Memory V2 专项测试

覆盖 MemoryItem CRUD、MemoryTrace、Policy 策略、幂等迁移、动态字段拦截。

DB_PATH 通过 module-scoped fixture 覆写，仅在测试执行期间生效，
不影响 pytest 收集阶段的 TestClient 初始化。
"""
import pytest
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

# Ensure backend is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

TEST_DB = os.path.join(tempfile.gettempdir(), f"test_phase10_memory_{os.getpid()}.db")

from backend.memory.models import MemoryItem, MemoryTrace, MemoryWriteCandidate
from backend.memory.store import MemoryRepository, init_memory_tables
from backend.memory.policy import MemoryPolicy, DEFAULT_POLICY
from backend.memory.constants import (
    MemoryType,
    MemoryStatus,
    MemorySourceType,
    AuthorityLevel,
    DYNAMIC_FIELD_BLOCKLIST,
    EXCLUDED_STATUSES,
)


@pytest.fixture(scope="module", autouse=True)
def patch_db_for_module():
    """模块级：仅在 Phase 10 测试执行期间覆写 DB_PATH。"""
    import backend.config as _cfg
    _original = _cfg.DB_PATH
    _cfg.DB_PATH = TEST_DB
    # 确保隔离：如果测试 DB 文件残留，删除它
    for suffix in ("", "-wal", "-shm"):
        path = TEST_DB + suffix
        if os.path.exists(path):
            os.remove(path)
    yield
    _cfg.DB_PATH = _original


@pytest.fixture(autouse=True)
def clean_db():
    """每个测试前重建干净数据库。"""
    # Clean up all SQLite files including WAL/SHM
    for suffix in ("", "-wal", "-shm"):
        path = TEST_DB + suffix
        if os.path.exists(path):
            os.remove(path)

    init_memory_tables()
    yield
    # Clean up after test
    for suffix in ("", "-wal", "-shm"):
        path = TEST_DB + suffix
        if os.path.exists(path):
            os.remove(path)


# ================================================================
# Test 1: 创建 MemoryItem
# ================================================================
class TestCreateMemoryItem:
    def test_create_basic_item(self):
        repo = MemoryRepository()
        item = repo.create_item(
            memory_type=MemoryType.STABLE_FACT.value,
            session_id="sess_test_001",
            memory_key="road.name",
            value={"name": "中山路", "direction": "南北"},
            text_content="中山路是南北向主干道",
            status=MemoryStatus.ACTIVE.value,
            source_type=MemorySourceType.USER_EXPLICIT.value,
            confidence=0.95,
            authority_level=AuthorityLevel.HUMAN_REVIEW,
        )
        assert item is not None
        assert item.id.startswith("mem_")
        assert item.memory_type == "stable_fact"
        assert item.session_id == "sess_test_001"
        assert item.memory_key == "road.name"
        assert item.value["name"] == "中山路"
        assert item.value["direction"] == "南北"
        assert item.status == "active"
        assert item.confidence == 0.95
        assert item.authority_level == AuthorityLevel.HUMAN_REVIEW
        assert item.created_at != ""

    def test_create_item_with_all_fields(self):
        repo = MemoryRepository()
        item = repo.create_item(
            memory_type=MemoryType.CONSTRAINT.value,
            session_id="sess_full",
            memory_key="constraint.speed_limit",
            value={"max_speed": 40, "unit": "km/h"},
            text_content="学校区域限速40",
            status=MemoryStatus.CONFIRMED.value,
            confidence=1.0,
            authority_level=AuthorityLevel.SYSTEM_RULE,
            source_type=MemorySourceType.SYSTEM_RULE.value,
            source_run_id="run_001",
            source_message_id="msg_001",
            valid_from="2026-01-01T00:00:00",
            valid_until="2026-12-31T23:59:59",
            scope_type="session",
            scope_id="sess_full",
        )
        assert item.source_run_id == "run_001"
        assert item.source_message_id == "msg_001"
        assert item.valid_from == "2026-01-01T00:00:00"
        assert item.valid_until == "2026-12-31T23:59:59"


# ================================================================
# Test 2: 查询同 Session 记忆
# ================================================================
class TestListSessionItems:
    def test_list_returns_active_items(self):
        repo = MemoryRepository()
        sid = "sess_list_001"
        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="road.name",
                         value={"name": "A路"}, status="active", source_type="user_explicit")
        repo.create_item(memory_type="constraint", session_id=sid, memory_key="rule.speed",
                         value={"max": 40}, status="confirmed", source_type="system_rule")
        repo.create_item(memory_type="proposal", session_id=sid, memory_key="proposal.1",
                         value={"idea": "test"}, status="candidate", source_type="agent_proposal")

        items = repo.list_session_items(sid)
        assert len(items) == 3

    def test_list_with_type_filter(self):
        repo = MemoryRepository()
        sid = "sess_type_filter"
        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="a",
                         value={}, source_type="user_explicit")
        repo.create_item(memory_type="constraint", session_id=sid, memory_key="b",
                         value={}, source_type="system_rule")
        repo.create_item(memory_type="constraint", session_id=sid, memory_key="c",
                         value={}, source_type="system_rule")

        items = repo.list_session_items(sid, memory_type="constraint")
        assert len(items) == 2
        for item in items:
            assert item.memory_type == "constraint"

    def test_list_with_key_filter(self):
        repo = MemoryRepository()
        sid = "sess_key_filter"
        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="road.name",
                         value={}, source_type="user_explicit")
        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="road.type",
                         value={}, source_type="user_explicit")

        items = repo.list_session_items(sid, memory_key="road.name")
        assert len(items) == 1
        assert items[0].memory_key == "road.name"


# ================================================================
# Test 3: 不同 Session 严格隔离
# ================================================================
class TestSessionIsolation:
    def test_sessions_isolated(self):
        repo = MemoryRepository()
        s1 = "sess_iso_a"
        s2 = "sess_iso_b"

        repo.create_item(memory_type="stable_fact", session_id=s1, memory_key="k1",
                         value={"v": 1}, source_type="user_explicit")
        repo.create_item(memory_type="stable_fact", session_id=s2, memory_key="k2",
                         value={"v": 2}, source_type="user_explicit")

        items_s1 = repo.list_session_items(s1)
        items_s2 = repo.list_session_items(s2)
        assert len(items_s1) == 1
        assert len(items_s2) == 1
        assert items_s1[0].session_id == s1
        assert items_s2[0].session_id == s2

    def test_find_active_by_key_scoped_to_session(self):
        repo = MemoryRepository()
        s1 = "sess_key_scope_a"
        s2 = "sess_key_scope_b"

        repo.create_item(memory_type="stable_fact", session_id=s1, memory_key="road.name",
                         value={"name": "A路"}, status="active", source_type="user_explicit")
        repo.create_item(memory_type="stable_fact", session_id=s2, memory_key="road.name",
                         value={"name": "B路"}, status="active", source_type="user_explicit")

        found_s1 = repo.find_active_by_key(s1, "road.name")
        found_s2 = repo.find_active_by_key(s2, "road.name")
        assert found_s1 is not None
        assert found_s2 is not None
        assert found_s1.value["name"] == "A路"
        assert found_s2.value["name"] == "B路"


# ================================================================
# Test 4: supersede 旧事实
# ================================================================
class TestSupersede:
    def test_supersede_marks_old_superseded(self):
        repo = MemoryRepository()
        sid = "sess_supersede"

        old = repo.create_item(
            memory_type="stable_fact", session_id=sid, memory_key="road.name",
            value={"name": "旧路名"}, status="active", source_type="user_explicit",
            authority_level=AuthorityLevel.DEFAULT,
        )

        new = MemoryItem(
            id=f"mem_new_{old.id}",
            memory_type="stable_fact",
            session_id=sid,
            memory_key="road.name",
            value={"name": "新路名"},
            text_content="路名已更新",
            status="active",
            authority_level=AuthorityLevel.USER_CORRECTION,
            source_type="user_correction",
            scope_type="session",
            scope_id=sid,
        )

        old_updated, new_created = repo.supersede_item(old.id, new)

        assert old_updated.status == "superseded"
        assert new_created.status == "active"
        assert new_created.supersedes_id == old.id
        assert new_created.value["name"] == "新路名"

        # Old should no longer appear in default queries
        items = repo.list_session_items(sid)
        names = [i.value.get("name") for i in items]
        assert "新路名" in names
        assert "旧路名" not in names


# ================================================================
# Test 5: expired 记忆不被默认查询
# ================================================================
class TestExpiredExclusion:
    def test_expired_not_in_default_list(self):
        repo = MemoryRepository()
        sid = "sess_expired"

        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="k1",
                         value={}, status="active", source_type="user_explicit")
        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="k2",
                         value={}, status="expired", source_type="user_explicit")

        items = repo.list_session_items(sid)
        assert len(items) == 1
        assert items[0].memory_key == "k1"

    def test_rejected_not_in_default_list(self):
        repo = MemoryRepository()
        sid = "sess_rejected"

        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="k1",
                         value={}, status="active", source_type="user_explicit")
        repo.create_item(memory_type="proposal", session_id=sid, memory_key="k2",
                         value={}, status="rejected", source_type="agent_proposal")

        items = repo.list_session_items(sid)
        assert len(items) == 1
        assert items[0].memory_key == "k1"

    def test_superseded_not_in_default_list(self):
        repo = MemoryRepository()
        sid = "sess_superseded_excl"

        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="k1",
                         value={}, status="active", source_type="user_explicit")
        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="k2",
                         value={}, status="superseded", source_type="user_explicit")

        items = repo.list_session_items(sid)
        assert len(items) == 1
        assert items[0].memory_key == "k1"


# ================================================================
# Test 6: valid_until 自动过期
# ================================================================
class TestValidUntilAutoExpiry:
    def test_valid_until_auto_expire(self):
        repo = MemoryRepository()
        sid = "sess_valid_until"

        # Create item with past valid_until
        past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        repo.create_item(
            memory_type="temporary_fact", session_id=sid, memory_key="temp.old",
            value={"info": "old"}, status="active", source_type="event_parser",
            valid_until=past,
        )
        # Create item with future valid_until
        future = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        repo.create_item(
            memory_type="temporary_fact", session_id=sid, memory_key="temp.new",
            value={"info": "new"}, status="active", source_type="event_parser",
            valid_until=future,
        )

        # Before expire_due_items, both should show (past item still has status "active" in DB)
        count = repo.expire_due_items()
        assert count == 1  # Only the past one expired

        items = repo.list_session_items(sid)
        assert len(items) == 1
        assert items[0].memory_key == "temp.new"

    def test_memory_item_is_valid_method(self):
        """Test MemoryItem.is_valid() checks valid_until."""
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")

        item_future = MemoryItem(id="m1", memory_type="temporary_fact",
                                 valid_until=future, status="active")
        assert item_future.is_valid(now) is True

        item_past = MemoryItem(id="m2", memory_type="temporary_fact",
                               valid_until=past, status="active")
        assert item_past.is_valid(now) is False

        item_expired_status = MemoryItem(id="m3", memory_type="temporary_fact",
                                         valid_until=future, status="expired")
        assert item_expired_status.is_valid(now) is False


# ================================================================
# Test 7: rejected 不被召回
# ================================================================
class TestRejectedNotRecalled:
    def test_rejected_excluded_from_find_active_by_key(self):
        repo = MemoryRepository()
        sid = "sess_reject_recall"

        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="road.name",
                         value={"name": "被拒绝的路"}, status="rejected", source_type="agent_proposal")
        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="road.name",
                         value={"name": "活跃的路"}, status="active", source_type="user_explicit")

        found = repo.find_active_by_key(sid, "road.name")
        assert found is not None
        assert found.value["name"] == "活跃的路"

    def test_reject_then_confirm_flow(self):
        repo = MemoryRepository()
        sid = "sess_reject_confirm"

        item = repo.create_item(memory_type="proposal", session_id=sid, memory_key="test.p",
                                value={"idea": "x"}, status="candidate", source_type="agent_proposal")
        assert repo.reject_item(item.id) is True
        rejected = repo.get_item(item.id)
        assert rejected.status == "rejected"

        # Can still confirm another item
        item2 = repo.create_item(memory_type="proposal", session_id=sid, memory_key="test.p2",
                                 value={"idea": "y"}, status="candidate", source_type="agent_proposal")
        assert repo.confirm_item(item2.id) is True
        confirmed = repo.get_item(item2.id)
        assert confirmed.status == "confirmed"


# ================================================================
# Test 8: JSON 字段正确序列化
# ================================================================
class TestJsonSerialization:
    def test_value_json_roundtrip(self):
        repo = MemoryRepository()
        sid = "sess_json"

        complex_value = {
            "name": "测试路段",
            "coordinates": {"lat": 31.23, "lng": 121.47},
            "tags": ["主干道", "学校周边"],
            "nested": {"a": [1, 2, 3], "b": {"c": "d"}},
            "unicode": "中文测试 🚦",
        }
        item = repo.create_item(
            memory_type="stable_fact", session_id=sid, memory_key="complex",
            value=complex_value, source_type="user_explicit",
        )

        retrieved = repo.get_item(item.id)
        assert retrieved.value["name"] == "测试路段"
        assert retrieved.value["coordinates"]["lat"] == 31.23
        assert retrieved.value["tags"] == ["主干道", "学校周边"]
        assert retrieved.value["nested"]["b"]["c"] == "d"
        assert retrieved.value["unicode"] == "中文测试 🚦"

    def test_empty_value_defaults(self):
        repo = MemoryRepository()
        sid = "sess_empty_val"
        item = repo.create_item(memory_type="stable_fact", session_id=sid,
                                memory_key="empty", source_type="user_explicit")
        assert item.value == {}


# ================================================================
# Test 9: Session 删除能删除记忆
# ================================================================
class TestSessionDelete:
    def test_delete_session_cleans_memory(self):
        repo = MemoryRepository()
        sid = "sess_to_delete"

        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="k1",
                         value={}, source_type="user_explicit")
        repo.create_item(memory_type="constraint", session_id=sid, memory_key="k2",
                         value={}, source_type="system_rule")

        trace = MemoryTrace(trace_id="trace_del", run_id="run_del", session_id=sid)
        repo.save_trace(trace)

        # Verify items exist
        assert len(repo.list_session_items(sid)) == 2
        assert repo.get_trace_by_run("run_del") is not None

        # Delete
        deleted = repo.delete_session_memory(sid)
        assert deleted >= 3  # 2 items + 1 trace (could have cascade from other tests)

        # Verify cleaned
        assert len(repo.list_session_items(sid)) == 0
        assert repo.get_trace_by_run("run_del") is None

    def test_delete_only_targets_one_session(self):
        repo = MemoryRepository()
        s1 = "sess_del_a"
        s2 = "sess_del_b"

        repo.create_item(memory_type="stable_fact", session_id=s1, memory_key="a1",
                         value={}, source_type="user_explicit")
        repo.create_item(memory_type="stable_fact", session_id=s2, memory_key="b1",
                         value={}, source_type="user_explicit")

        repo.delete_session_memory(s1)
        assert len(repo.list_session_items(s1)) == 0
        assert len(repo.list_session_items(s2)) == 1


# ================================================================
# Test 10: Trace 保存和读取
# ================================================================
class TestMemoryTrace:
    def test_save_and_read_trace(self):
        repo = MemoryRepository()
        sid = "sess_trace"
        trace = MemoryTrace(
            trace_id="trace_001",
            run_id="run_001",
            session_id=sid,
            recall_intent="测试召回",
            candidates_json=json.dumps([{"id": "m1", "score": 0.9}]),
            selected_json=json.dumps(["m1"]),
            token_estimate=150,
            recall_latency_ms=5,
            write_latency_ms=3,
        )
        repo.save_trace(trace)

        loaded = repo.get_trace_by_run("run_001")
        assert loaded is not None
        assert loaded.trace_id == "trace_001"
        assert loaded.run_id == "run_001"
        assert loaded.recall_intent == "测试召回"
        assert loaded.token_estimate == 150
        assert loaded.recall_latency_ms == 5
        assert loaded.write_latency_ms == 3

    def test_trace_upsert(self):
        repo = MemoryRepository()
        sid = "sess_trace_upsert"
        t1 = MemoryTrace(trace_id="t1", run_id="r1", session_id=sid,
                         recall_intent="v1", token_estimate=100)
        repo.save_trace(t1)

        t2 = MemoryTrace(trace_id="t1", run_id="r1", session_id=sid,
                         recall_intent="v2", token_estimate=200)
        repo.save_trace(t2)

        loaded = repo.get_trace_by_run("r1")
        assert loaded.recall_intent == "v2"
        assert loaded.token_estimate == 200

    def test_list_traces_by_session(self):
        repo = MemoryRepository()
        sid = "sess_trace_list"
        for i in range(3):
            trace = MemoryTrace(trace_id=f"t{i}", run_id=f"r{i}", session_id=sid)
            repo.save_trace(trace)

        traces = repo.list_traces(sid, limit=10)
        assert len(traces) == 3


# ================================================================
# Test 11: SQL 迁移可重复执行
# ================================================================
class TestMigrationIdempotent:
    def test_init_called_multiple_times(self):
        """验证 init_memory_tables() 可反复调用不报错。"""
        for _ in range(5):
            init_memory_tables()
        # If we reach here without exceptions, the test passes

    def test_init_preserves_existing_data(self):
        """验证重复 init 不破坏已有数据。"""
        repo = MemoryRepository()
        sid = "sess_migrate_preserve"
        item = repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="k",
                                value={"x": 1}, source_type="user_explicit")

        # Re-init
        init_memory_tables()
        init_memory_tables()

        loaded = repo.get_item(item.id)
        assert loaded is not None
        assert loaded.value["x"] == 1


# ================================================================
# Test 12: 动态字段不能写为 stable_fact
# ================================================================
class TestDynamicFieldBlocking:
    def test_stable_fact_rejects_avg_speed(self):
        policy = DEFAULT_POLICY
        violations = policy.validate_stable_fact_value({"avgSpeed": 8.5, "roadName": "中山路"})
        assert "avgSpeed" in violations

    def test_stable_fact_rejects_queue_length(self):
        policy = DEFAULT_POLICY
        violations = policy.validate_stable_fact_value({"queueLength": 200})
        assert "queueLength" in violations

    def test_stable_fact_rejects_multiple_dynamic(self):
        policy = DEFAULT_POLICY
        violations = policy.validate_stable_fact_value({
            "avgSpeed": 10, "queueLength": 150, "duration": 600, "weather": "rain"
        })
        assert len(violations) == 4
        assert "avgSpeed" in violations
        assert "queueLength" in violations
        assert "duration" in violations
        assert "weather" in violations

    def test_stable_fact_allows_safe_fields(self):
        policy = DEFAULT_POLICY
        violations = policy.validate_stable_fact_value({
            "roadName": "中山路",
            "eventType": "congestion",
            "nearbySchool": True,
            "isMainRoad": True,
        })
        assert len(violations) == 0

    def test_policy_validate_write_candidate_rejects_dynamic(self):
        policy = DEFAULT_POLICY
        reason = policy.validate_write_candidate(
            memory_type="stable_fact",
            memory_key="road.info",
            value={"avgSpeed": 10, "roadName": "中山路"},
            source_type="agent_fusion",
        )
        assert reason is not None
        assert "avgSpeed" in reason

    def test_policy_validate_write_candidate_accepts_safe(self):
        policy = DEFAULT_POLICY
        reason = policy.validate_write_candidate(
            memory_type="stable_fact",
            memory_key="road.info",
            value={"roadName": "中山路", "isMainRoad": True},
            source_type="agent_fusion",
        )
        assert reason is None

    def test_memory_key_with_dynamic_field_rejected(self):
        policy = DEFAULT_POLICY
        reason = policy.validate_stable_fact_key("road.avgSpeed_info")
        assert reason is not None
        assert "avgSpeed" in reason

    def test_memory_key_without_safe_prefix_rejected(self):
        policy = DEFAULT_POLICY
        reason = policy.validate_stable_fact_key("random_key")
        assert reason is not None
        assert "安全前缀" in reason

    def test_memory_key_with_safe_prefix_accepted(self):
        policy = DEFAULT_POLICY
        for prefix in ["road.name", "route.id", "school.info", "hospital.nearby",
                        "intersection.main", "rule.speed_limit", "policy.override",
                        "decision.final", "constraint.time", "goal.primary"]:
            reason = policy.validate_stable_fact_key(prefix)
            assert reason is None, f"Expected {prefix} to be accepted, got: {reason}"


# ================================================================
# Test 13: temporary_fact 无 valid_until 被拒绝
# ================================================================
class TestTemporaryFactValidation:
    def test_temporary_fact_without_valid_until_rejected(self):
        policy = DEFAULT_POLICY
        reason = policy.validate_write_candidate(
            memory_type="temporary_fact",
            memory_key="temp.closure",
            value={"info": "道路施工"},
            source_type="event_parser",
            valid_until=None,
        )
        assert reason is not None
        assert "valid_until" in reason

    def test_temporary_fact_with_valid_until_accepted(self):
        policy = DEFAULT_POLICY
        reason = policy.validate_write_candidate(
            memory_type="temporary_fact",
            memory_key="temp.closure",
            value={"info": "道路施工"},
            source_type="event_parser",
            valid_until="2026-12-31T23:59:59",
        )
        assert reason is None

    def test_user_correction_wrong_source_rejected(self):
        policy = DEFAULT_POLICY
        reason = policy.validate_write_candidate(
            memory_type="user_correction",
            memory_key="correction.1",
            value={"fix": "something"},
            source_type="agent_proposal",  # 只能是 user_correction
        )
        assert reason is not None


# ================================================================
# Test 14: 相同 source 和内容可幂等去重
# ================================================================
class TestIdempotentDedup:
    def test_find_duplicate_detects_same_content(self):
        repo = MemoryRepository()
        sid = "sess_dedup"

        item1 = repo.create_item(
            memory_type="stable_fact", session_id=sid, memory_key="road.name",
            value={"name": "中山路"}, text_content="中山路主干道",
            source_type="agent_fusion", status="active",
        )

        dup = repo.find_duplicate(
            session_id=sid,
            memory_type="stable_fact",
            memory_key="road.name",
            source_type="agent_fusion",
            text_content="中山路主干道",
        )
        assert dup is not None
        assert dup.id == item1.id

    def test_different_content_no_duplicate(self):
        repo = MemoryRepository()
        sid = "sess_no_dup"

        repo.create_item(
            memory_type="stable_fact", session_id=sid, memory_key="road.name",
            value={"name": "中山路"}, text_content="中山路主干道",
            source_type="agent_fusion", status="active",
        )

        dup = repo.find_duplicate(
            session_id=sid,
            memory_type="stable_fact",
            memory_key="road.name",
            source_type="agent_fusion",
            text_content="不同的内容",
        )
        assert dup is None

    def test_rejected_duplicate_not_returned(self):
        repo = MemoryRepository()
        sid = "sess_dup_rejected"

        repo.create_item(
            memory_type="stable_fact", session_id=sid, memory_key="road.name",
            value={"name": "A路"}, text_content="A路信息",
            source_type="agent_fusion", status="rejected",
        )

        dup = repo.find_duplicate(
            session_id=sid,
            memory_type="stable_fact",
            memory_key="road.name",
            source_type="agent_fusion",
            text_content="A路信息",
        )
        assert dup is None


# ================================================================
# Test: Access tracking
# ================================================================
class TestAccessTracking:
    def test_increment_access(self):
        repo = MemoryRepository()
        sid = "sess_access"
        item = repo.create_item(memory_type="stable_fact", session_id=sid,
                                memory_key="k", value={}, source_type="user_explicit")
        assert item.access_count == 0
        assert item.last_accessed_at is None

        repo.increment_access(item.id)
        updated = repo.get_item(item.id)
        assert updated.access_count == 1
        assert updated.last_accessed_at is not None

        repo.increment_access(item.id)
        repo.increment_access(item.id)
        updated2 = repo.get_item(item.id)
        assert updated2.access_count == 3


# ================================================================
# Test: find_items_by_run
# ================================================================
class TestFindByRun:
    def test_find_by_source_run(self):
        repo = MemoryRepository()
        sid = "sess_by_run"
        run_a = "run_aaa"
        run_b = "run_bbb"

        repo.create_item(memory_type="run_summary", session_id=sid, memory_key="sum.a",
                         value={"r": "a"}, source_type="agent_fusion", source_run_id=run_a)
        repo.create_item(memory_type="run_summary", session_id=sid, memory_key="sum.b",
                         value={"r": "b"}, source_type="agent_fusion", source_run_id=run_b)

        items_a = repo.find_items_by_run(sid, run_a)
        items_b = repo.find_items_by_run(sid, run_b)
        assert len(items_a) == 1
        assert len(items_b) == 1
        assert items_a[0].source_run_id == run_a
        assert items_b[0].source_run_id == run_b


# ================================================================
# Test: count_session_items + stats
# ================================================================
class TestStats:
    def test_count_session_items(self):
        repo = MemoryRepository()
        sid = "sess_stats"

        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="k1",
                         value={}, status="active", source_type="user_explicit")
        repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="k2",
                         value={}, status="confirmed", source_type="agent_fusion")
        repo.create_item(memory_type="proposal", session_id=sid, memory_key="k3",
                         value={}, status="rejected", source_type="agent_proposal")
        repo.create_item(memory_type="constraint", session_id=sid, memory_key="k4",
                         value={}, status="superseded", source_type="system_rule")

        stats = repo.count_session_items(sid)
        assert stats["total_items"] == 4
        assert stats["active_items"] == 1
        assert stats["confirmed_items"] == 1
        assert stats["rejected_items"] == 1
        assert stats["superseded_items"] == 1
        assert stats["by_type"]["stable_fact"] == 2
        assert stats["by_type"]["proposal"] == 1
        assert stats["by_type"]["constraint"] == 1


# ================================================================
# Test: Authority comparison
# ================================================================
class TestAuthority:
    def test_should_supersede_higher_wins(self):
        policy = DEFAULT_POLICY
        assert policy.should_supersede(40, 80) is True   # higher authority supersedes
        assert policy.should_supersede(80, 40) is False  # lower cannot
        assert policy.should_supersede(60, 60) is False  # equal does not supersede

    def test_get_authority_for_source(self):
        policy = DEFAULT_POLICY
        assert policy.get_authority_for_source("user_correction") == 100
        assert policy.get_authority_for_source("human_review") == 80
        assert policy.get_authority_for_source("agent_fusion") == 60
        assert policy.get_authority_for_source("agent_proposal") == 40
        assert policy.get_authority_for_source("event_parser") == 20
        assert policy.get_authority_for_source("system_rule") == 10
        assert policy.get_authority_for_source("unknown") == 0


# ================================================================
# Test: Agent injection whitelist
# ================================================================
class TestAgentInjection:
    def test_filter_items_for_agent(self):
        policy = DEFAULT_POLICY
        items = [
            MemoryItem(id="m1", memory_type="stable_fact", session_id="s", memory_key="k1",
                       value={}, status="active"),
            MemoryItem(id="m2", memory_type="constraint", session_id="s", memory_key="k2",
                       value={}, status="active"),
            MemoryItem(id="m3", memory_type="proposal", session_id="s", memory_key="k3",
                       value={}, status="active"),
        ]
        # ConflictDetector gets NO memory (empty whitelist)
        filtered = policy.filter_items_for_agent(items, "ConflictDetector")
        assert len(filtered) == 0

        # CongestionAgent gets stable_fact + constraint + confirmed_decision + session_goal
        filtered = policy.filter_items_for_agent(items, "CongestionAgent")
        assert len(filtered) == 2  # stable_fact, constraint (not proposal)
        types = {i.memory_type for i in filtered}
        assert "stable_fact" in types
        assert "constraint" in types
        assert "proposal" not in types

    def test_unknown_agent_gets_nothing(self):
        policy = DEFAULT_POLICY
        items = [MemoryItem(id="m1", memory_type="stable_fact", session_id="s",
                            memory_key="k1", value={}, status="active")]
        filtered = policy.filter_items_for_agent(items, "NonExistentAgent")
        assert len(filtered) == 0


# ================================================================
# Test: update_item
# ================================================================
class TestUpdateItem:
    def test_update_status_and_content(self):
        repo = MemoryRepository()
        sid = "sess_update"
        item = repo.create_item(memory_type="proposal", session_id=sid, memory_key="p1",
                                value={"idea": "old"}, status="candidate",
                                source_type="agent_proposal", confidence=0.5)

        repo.update_item(item.id, status="confirmed", confidence=0.9,
                         text_content="updated text")
        updated = repo.get_item(item.id)
        assert updated.status == "confirmed"
        assert updated.confidence == 0.9
        assert updated.text_content == "updated text"

    def test_update_value(self):
        repo = MemoryRepository()
        sid = "sess_update_val"
        item = repo.create_item(memory_type="stable_fact", session_id=sid, memory_key="k",
                                value={"old": 1}, source_type="user_explicit")

        repo.update_item(item.id, value={"new": 2})
        updated = repo.get_item(item.id)
        assert updated.value == {"new": 2}


# ================================================================
# Test: expire_item + expire_session_items
# ================================================================
class TestExpireMethods:
    def test_expire_single_item(self):
        repo = MemoryRepository()
        sid = "sess_expire_one"
        item = repo.create_item(memory_type="proposal", session_id=sid, memory_key="p",
                                value={}, status="active", source_type="agent_proposal")
        assert repo.expire_item(item.id) is True
        loaded = repo.get_item(item.id)
        assert loaded.status == "expired"

    def test_expire_session_items(self):
        repo = MemoryRepository()
        sid = "sess_expire_many"
        past = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")

        repo.create_item(memory_type="temporary_fact", session_id=sid, memory_key="t1",
                         value={}, status="active", source_type="event_parser", valid_until=past)
        repo.create_item(memory_type="temporary_fact", session_id=sid, memory_key="t2",
                         value={}, status="active", source_type="event_parser", valid_until=future)
        repo.create_item(memory_type="temporary_fact", session_id=sid, memory_key="t3",
                         value={}, status="confirmed", source_type="agent_fusion", valid_until=past)

        count = repo.expire_session_items(sid)
        assert count == 2  # t1 + t3 (past valid_until), t2 stays (future)
        active = repo.list_session_items(sid)
        assert len(active) == 1
        assert active[0].memory_key == "t2"


# ================================================================
# Test: MemoryItem from_row with safe JSON parsing
# ================================================================
class TestFromRow:
    def test_from_row_with_string_json(self):
        row = {
            "id": "mem_test", "memory_type": "stable_fact", "scope_type": "session",
            "scope_id": "s", "session_id": "s", "memory_key": "k",
            "value_json": '{"name": "test", "count": 42}',
            "text_content": "text", "status": "active", "confidence": 0.9,
            "authority_level": 50, "source_type": "user_explicit",
            "source_id": "", "source_run_id": "", "source_message_id": "",
            "valid_from": None, "valid_until": None, "supersedes_id": "",
            "created_at": "2026-01-01", "updated_at": "2026-01-01",
            "last_accessed_at": None, "access_count": 0,
        }
        item = MemoryItem.from_row(row)
        assert item.value == {"name": "test", "count": 42}

    def test_from_row_with_dict_value(self):
        row = {
            "id": "mem_test2", "memory_type": "constraint", "scope_type": "session",
            "scope_id": "s", "session_id": "s", "memory_key": "k",
            "value_json": {"limit": 40},
            "text_content": "", "status": "active", "confidence": 1.0,
            "authority_level": 10, "source_type": "system_rule",
            "source_id": "", "source_run_id": "", "source_message_id": "",
            "valid_from": None, "valid_until": None, "supersedes_id": "",
            "created_at": "", "updated_at": "",
            "last_accessed_at": None, "access_count": 0,
        }
        item = MemoryItem.from_row(row)
        assert item.value == {"limit": 40}

    def test_from_row_with_malformed_json(self):
        row = {
            "id": "mem_test3", "memory_type": "stable_fact", "scope_type": "session",
            "scope_id": "s", "session_id": "s", "memory_key": "k",
            "value_json": "not valid json!!!",
            "text_content": "", "status": "active", "confidence": 1.0,
            "authority_level": 0, "source_type": "",
            "source_id": "", "source_run_id": "", "source_message_id": "",
            "valid_from": None, "valid_until": None, "supersedes_id": "",
            "created_at": "", "updated_at": "",
            "last_accessed_at": None, "access_count": 0,
        }
        item = MemoryItem.from_row(row)
        assert item.value == {}  # Safe fallback to empty dict


# ================================================================
# Test: source type rules
# ================================================================
class TestSourceTypeRules:
    def test_agent_proposal_cannot_create_confirmed_decision(self):
        policy = DEFAULT_POLICY
        reason = policy.validate_write_candidate(
            memory_type="confirmed_decision",
            memory_key="decision.final",
            value={"action": "分流"},
            source_type="agent_proposal",  # NOT allowed for confirmed_decision
        )
        assert reason is not None

    def test_agent_fusion_can_create_confirmed_decision(self):
        policy = DEFAULT_POLICY
        reason = policy.validate_write_candidate(
            memory_type="confirmed_decision",
            memory_key="decision.final",
            value={"action": "分流"},
            source_type="agent_fusion",
        )
        assert reason is None

    def test_human_review_can_create_confirmed_decision(self):
        policy = DEFAULT_POLICY
        reason = policy.validate_write_candidate(
            memory_type="confirmed_decision",
            memory_key="decision.final",
            value={"action": "分流"},
            source_type="human_review",
        )
        assert reason is None


# ================================================================
# Test: MemoryType enum coverage
# ================================================================
class TestMemoryTypeEnum:
    def test_all_types_valid(self):
        all_types = {
            "session_goal", "stable_fact", "constraint",
            "confirmed_decision", "unresolved_issue", "user_correction",
            "run_summary", "proposal", "temporary_fact",
        }
        for t in all_types:
            assert MemoryType(t) is not None  # Should not raise

    def test_all_statuses_valid(self):
        all_statuses = {"candidate", "active", "confirmed", "rejected", "superseded", "expired"}
        for s in all_statuses:
            assert MemoryStatus(s) is not None


# ================================================================
# Test: DYNAMIC_FIELD_BLOCKLIST contents
# ================================================================
class TestBlocklistContents:
    def test_blocklist_contains_critical_fields(self):
        assert "avgSpeed" in DYNAMIC_FIELD_BLOCKLIST
        assert "queueLength" in DYNAMIC_FIELD_BLOCKLIST
        assert "duration" in DYNAMIC_FIELD_BLOCKLIST
        assert "weather" in DYNAMIC_FIELD_BLOCKLIST
        assert "signalState" in DYNAMIC_FIELD_BLOCKLIST
        assert "trafficFlow" in DYNAMIC_FIELD_BLOCKLIST
        assert "pedestrianCount" in DYNAMIC_FIELD_BLOCKLIST
        assert "laneAvailability" in DYNAMIC_FIELD_BLOCKLIST
        assert "accidentStatus" in DYNAMIC_FIELD_BLOCKLIST

    def test_policy_uses_blocklist(self):
        policy = DEFAULT_POLICY
        for field in DYNAMIC_FIELD_BLOCKLIST:
            assert policy.is_dynamic_field(field) is True
            assert policy.is_dynamic_field(field.upper()) is True  # case insensitive
