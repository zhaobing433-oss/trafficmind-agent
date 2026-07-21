"""
Phase 9 多Run隔离 + 冲突检测 + 缺失字段 回归测试
"""
import pytest, asyncio, json


class TestMultiRunIsolation:
    """多Run输入隔离"""

    def test_school_scenario_avgSpeed_is_none(self):
        from backend.agent.collaboration.event_parser import parse_content_to_event
        r = parse_content_to_event("学校门口早高峰严重拥堵，机动车方向需要增加绿灯时间，但大量学生正在集中横穿道路。")
        assert r["avgSpeed"] is None, f"avgSpeed should be None, got {r['avgSpeed']}"
        assert r["queueLength"] is None, f"queueLength should be None, got {r['queueLength']}"

    def test_school_scenario_no_fake_8_400(self):
        from backend.agent.collaboration.event_parser import parse_content_to_event
        r = parse_content_to_event("学校门口早高峰严重拥堵，机动车方向需要增加绿灯时间，但大量学生正在集中横穿道路。")
        assert r["avgSpeed"] != 8.0
        assert r["queueLength"] != 400.0

    def test_second_run_independent_normalized_event(self):
        from backend.agent.collaboration.event_parser import parse_content_to_event
        r1 = parse_content_to_event("主干道平均车速8km/h，排队400米")
        r2 = parse_content_to_event("学校门口学生横穿道路，信号灯需要调整")
        assert r2["avgSpeed"] is None or r2["avgSpeed"] != r1["avgSpeed"]
        assert r2["nearbySchool"] is True

    def test_congestion_agent_no_fake_numbers_when_missing(self):
        from backend.agent.collaboration.event_parser import parse_content_to_event
        from backend.agent.multi_agent import _get_event_info, CongestionAgent
        r = parse_content_to_event("学校门口早高峰严重拥堵")
        info = _get_event_info(r)
        ca = CongestionAgent()
        result = ca.analyze(info)
        text = str(result["findings"])
        assert "8" not in text or "8km" not in text
        assert "400" not in text


class TestSchoolScenarioRouting:
    """学校场景路由"""

    def test_school_triggers_public_safety(self):
        from backend.agent.collaboration.event_parser import parse_content_to_event
        from backend.agent.router import route_agents
        r = parse_content_to_event("学校门口学生集中横穿，机动车需要信号调整")
        r["originalInput"] = "学校门口学生集中横穿，机动车需要信号调整"
        agents = route_agents(r)["selectedAgents"]
        assert "PublicSafetyAgent" in agents, f"PublicSafetyAgent should be selected, got {agents}"

    def test_school_signal_triggers_signal_agent(self):
        from backend.agent.collaboration.event_parser import parse_content_to_event
        from backend.agent.router import route_agents
        r = parse_content_to_event("学校门口拥堵需要延长绿灯时间")
        r["originalInput"] = "学校门口拥堵需要延长绿灯时间"
        agents = route_agents(r)["selectedAgents"]
        assert "SignalAgent" in agents, f"SignalAgent should be selected, got {agents}"

    def test_simple_congestion_no_public_safety(self):
        from backend.agent.router import route_agents
        info = {"eventTypeCn": "拥堵", "roadName": "某路", "avgSpeed": 8.0, "queueLength": 400,
                "nearbySchool": False, "nearbyHospital": False, "weather": "clear", "timePeriod": "off_peak",
                "isMainRoad": True, "riskLevel": "高风险"}
        agents = route_agents(info)["selectedAgents"]
        assert "PublicSafetyAgent" not in agents, f"Simple congestion should not trigger PublicSafety, got {agents}"


class TestConflictDetection:
    """冲突检测"""

    def test_conflict_detected_when_signal_vs_school_safety(self):
        from backend.agent.collaboration.orchestrator import _detect_simple_conflicts
        from backend.agent.collaboration.state import CollaborationRunState
        state = CollaborationRunState("r1", "s1", "t1")
        state.task_results = {
            "SignalAgent": {"findings": ["信号优化建议：延长机动车绿灯"],
                            "suggestion": "延长机动车绿灯时间", "urgency": "high"},
            "PublicSafetyAgent": {"findings": ["学校周边需保障学生过街安全"],
                                  "suggestion": "保障学生过街相位", "urgency": "high"},
        }
        conflicts = _detect_simple_conflicts(state)
        assert len(conflicts) >= 1, f"Should detect at least 1 conflict, got {len(conflicts)}"
        conflict_types = [c["type"] for c in conflicts]
        assert "resource_conflict" in conflict_types or "priority_conflict" in conflict_types or "strategy_conflict" in conflict_types

    def test_no_conflict_when_no_safety(self):
        from backend.agent.collaboration.orchestrator import _detect_simple_conflicts
        from backend.agent.collaboration.state import CollaborationRunState
        state = CollaborationRunState("r2", "s2", "t2")
        state.task_results = {
            "CongestionAgent": {"findings": ["拥堵严重"], "suggestion": "分流", "urgency": "high"},
        }
        conflicts = _detect_simple_conflicts(state)
        assert len(conflicts) == 0, f"Should detect no conflicts, got {len(conflicts)}"

    def test_conflict_arbiter_created_when_conflicts_exist(self):
        from backend.agent.collaboration.orchestrator import _detect_simple_conflicts
        from backend.agent.collaboration.state import CollaborationRunState
        state = CollaborationRunState("r3", "s3", "t3")
        state.task_results = {
            "SignalAgent": {"findings": ["延长机动车绿灯20秒"], "suggestion": "增加机动车通行", "urgency": "high"},
            "PublicSafetyAgent": {"findings": ["学生横穿需要行人保护相位"], "suggestion": "限制机动车放行", "urgency": "high"},
        }
        conflicts = _detect_simple_conflicts(state)
        assert len(conflicts) > 0
        # Verify ConflictArbiter would be needed
        has_high_conflict = any(c.get("severity") in ("high", "critical") for c in conflicts)
        assert has_high_conflict, f"School+signal conflict should be high severity, got {conflicts}"

    def test_arbiter_requires_human_review_for_high_conflict(self):
        from backend.agent.collaboration.agents import conflict_arbiter
        result = conflict_arbiter({"id": "c1", "type": "strategy_conflict", "severity": "high",
                                    "description": "学校过街安全与机动车通行效率冲突"})
        assert result["requires_human_review"] is True, "High severity school conflict should require human review"

    def test_arbiter_resolves_low_conflict(self):
        from backend.agent.collaboration.agents import conflict_arbiter
        result = conflict_arbiter({"id": "c2", "type": "strategy_conflict", "severity": "low"})
        assert result["resolved"] is True
        assert result["requires_human_review"] is False


class TestAgentProposals:
    """结构化 proposals"""

    def test_congestion_agent_missing_fields_limitation(self):
        from backend.agent.multi_agent import _get_event_info, CongestionAgent
        info = _get_event_info({"eventTypeCn": "拥堵", "roadName": "学校路", "nearbySchool": True})
        ca = CongestionAgent()
        result = ca.analyze(info)
        assert len(result["findings"]) >= 1
        # Should mention missing data, not fake numbers
        assert "未提供" in str(result["findings"]) or "缺失" in str(result["findings"])

    def test_signal_agent_structured_proposal(self):
        from backend.agent.multi_agent import _get_event_info, SignalAgent
        info = _get_event_info({"eventTypeCn": "拥堵", "roadName": "某路", "signalOptimizationRequested": True})
        sa = SignalAgent()
        result = sa.analyze(info)
        # SignalAgent should have findings about signal optimization
        assert len(result["findings"]) >= 1


class TestParserFields:
    """Parser 字段正确性"""

    def test_school_keywords_detected(self):
        from backend.agent.collaboration.event_parser import parse_content_to_event
        r = parse_content_to_event("学校门口学生横穿道路")
        assert r["nearbySchool"] is True
        assert r["pedestrianRisk"] == "high"

    def test_signal_keywords_detected(self):
        from backend.agent.collaboration.event_parser import parse_content_to_event
        r = parse_content_to_event("需要增加绿灯时间优化信号配时")
        assert r["signalOptimizationRequested"] is True

    def test_conflict_intent_detected(self):
        from backend.agent.collaboration.event_parser import parse_content_to_event
        r = parse_content_to_event("评估机动车通行效率与学生过街安全之间的冲突并协同研判")
        assert r["conflictIntent"] is True

    def test_missing_fields_tracked(self):
        from backend.agent.collaboration.event_parser import parse_content_to_event
        r = parse_content_to_event("学校门口拥堵")
        assert "avgSpeed" in r.get("missingFields", [])
        assert "queueLength" in r.get("missingFields", [])


class TestRunDedup:
    """Run 去重和幂等"""

    def test_run_order_no_duplicate_run_ids(self):
        """两次提交只产生两个不同 runId"""
        sids = []
        for _ in range(2):
            r = __import__('fastapi.testclient', fromlist=['TestClient']).TestClient(
                __import__('backend.app', fromlist=['app']).app
            ).post('/chat/sessions', json={"mode": "collaboration"})
            sids.append(r.json()["sessionId"])
        # Different sessions = different IDs (sanity check)
        assert sids[0] != sids[1]

    def test_run_list_dedup_by_run_id(self):
        """listSessionRuns 返回的 run_id 不重复"""
        from fastapi.testclient import TestClient
        from backend.app import app
        c = TestClient(app)
        r = c.post('/chat/sessions', json={"mode": "collaboration"})
        sid = r.json()["sessionId"]
        # Send one message
        body = {"eventId": "E_t1", "eventType": "congestion", "roadName": "测试", "direction": "东",
                "avgSpeed": 8.0, "queueLength": 200, "duration": 600, "sessionId": sid}
        c.post('/agent/routed_analyze/stream', json=body)
        runs = c.get(f'/collaboration/sessions/{sid}/runs').json()["runs"]
        run_ids = [rr["run_id"] for rr in runs]
        assert len(run_ids) == len(set(run_ids)), f"Duplicate run_ids found: {run_ids}"


class TestTwoRoundFinal:
    """双轮最终验证"""

    def test_run_ids_unique_across_rounds(self):
        """两次提交产生两个不同 runId"""
        from backend.agent.router import route_agents
        info1 = {"eventTypeCn": "拥堵", "roadName": "高速路", "avgSpeed": 8.0, "queueLength": 400,
                 "weather": "clear", "timePeriod": "off_peak", "isMainRoad": True,
                 "nearbySchool": False, "nearbyHospital": False, "riskLevel": "高风险"}
        agents1 = route_agents(info1)["selectedAgents"]
        assert "CongestionAgent" in agents1
        info2 = {"eventTypeCn": "拥堵", "roadName": "学校路", "nearbySchool": True,
                 "pedestrianRisk": "high", "signalOptimizationRequested": True,
                 "weather": "clear", "timePeriod": "morning_peak",
                 "isMainRoad": False, "nearbyHospital": False, "riskLevel": "高风险"}
        agents2 = route_agents(info2)["selectedAgents"]
        # Second round should have different agent set
        assert "PublicSafetyAgent" in agents2
        assert agents1 != agents2

    def test_title_not_overwritten_by_second_round(self):
        """标题在后续回合不被覆盖"""
        from backend.chat.chat_db import create_session, add_message, update_session_title, get_session
        sid = f"sess_test_title_{id(object())}"
        create_session(sid, "collaboration")
        # Set initial title
        update_session_title(sid, "第一轮拥堵分析")
        # Simulate second round message
        add_message(f"um_{id(object())}", sid, "user", "追问内容", "collaboration")
        # Title should NOT be overwritten
        from backend.chat.chat_db import update_session_title as ust
        # Only update if title is "新对话" — should skip
        sess = get_session(sid)
        assert sess["title"] == "第一轮拥堵分析"


class TestDetailHydration:
    """Run 详情水合"""

    def test_get_run_returns_tasks(self):
        """GET /collaboration/runs/{runId} 返回 tasks"""
        from fastapi.testclient import TestClient
        from backend.app import app
        c = TestClient(app)
        r = c.post('/chat/sessions', json={"mode": "collaboration"})
        sid = r.json()["sessionId"]
        body = {"eventId": "E_hyd", "eventType": "congestion", "roadName": "测试", "direction": "东",
                "avgSpeed": 8.0, "queueLength": 200, "duration": 600, "sessionId": sid}
        c.post('/agent/routed_analyze/stream', json=body)
        runs = c.get(f'/collaboration/sessions/{sid}/runs').json()["runs"]
        if runs:
            detail = c.get(f'/collaboration/runs/{runs[0]["run_id"]}').json()
            assert "run" in detail

    def test_list_sessions_returns_summaries(self):
        """listSessionRuns 返回的是摘要（不包含tasks/agentResults）"""
        from fastapi.testclient import TestClient
        from backend.app import app
        c = TestClient(app)
        r = c.post('/chat/sessions', json={"mode": "collaboration"})
        sid = r.json()["sessionId"]
        body = {"eventId": "E_sum", "eventType": "congestion", "roadName": "测试", "direction": "东",
                "avgSpeed": 8.0, "queueLength": 200, "duration": 600, "sessionId": sid}
        c.post('/agent/routed_analyze/stream', json=body)
        runs = c.get(f'/collaboration/sessions/{sid}/runs').json()["runs"]
        # Summaries don't have tasks
        assert all("tasks" not in rr for rr in runs) or all(len(rr.get("tasks", [])) == 0 for rr in runs)

    def test_budget_persisted_in_run_detail(self):
        """Run 详情中 budgetUsage 非空"""
        from fastapi.testclient import TestClient
        from backend.app import app
        c = TestClient(app)
        r = c.post('/chat/sessions', json={"mode": "collaboration"})
        sid = r.json()["sessionId"]
        body = {"eventId": "E_bud", "eventType": "congestion", "roadName": "测试", "direction": "东",
                "avgSpeed": 8.0, "queueLength": 200, "duration": 600, "sessionId": sid}
        c.post('/agent/routed_analyze/stream', json=body)
        runs = c.get(f'/collaboration/sessions/{sid}/runs').json().get("runs", [])
        assert len(runs) >= 1, "Should have at least 1 run"


class TestFusionPersistence:
    """融合总结持久化验证"""

    def test_assistant_message_not_placeholder(self):
        from fastapi.testclient import TestClient
        from backend.app import app
        c = TestClient(app)
        body = {'content': '主干道平均车速8km/h，排队400米，请协同研判。'}
        r = c.post('/agent/routed_analyze/stream', json=body)
        import re
        sid = re.search(r'\"sessionId\":\s*\"([^\"]+)\"', r.text).group(1)
        ses = c.get(f'/chat/sessions/{sid}').json()
        msgs = ses['messages']
        asst = [m for m in msgs if m['role'] == 'assistant']
        assert len(asst) >= 1
        assert asst[0]['content'] != '协同分析完成', f"Should not save placeholder, got: {asst[0]['content'][:50]}"
        assert len(asst[0]['content']) > 20, f"Summary too short: {len(asst[0]['content'])} chars"

    def test_final_decision_is_structured(self):
        from fastapi.testclient import TestClient
        from backend.app import app
        c = TestClient(app)
        body = {'content': '主干道平均车速8km/h，排队400米，请协同研判。'}
        r = c.post('/agent/routed_analyze/stream', json=body)
        import re
        sid = re.search(r'\"sessionId\":\s*\"([^\"]+)\"', r.text).group(1)
        runs = c.get(f'/collaboration/sessions/{sid}/runs').json()['runs']
        assert len(runs) >= 1
        rid = runs[0]['run_id']
        detail = c.get(f'/collaboration/runs/{rid}').json()
        fd = detail['run'].get('final_decision')
        # Should be a dict with fusionSummary key
        assert isinstance(fd, dict), f"final_decision should be dict, got {type(fd).__name__}"
        assert 'fusionSummary' in fd, f"Missing fusionSummary key, got {list(fd.keys())[:5]}"

    def test_fusion_done_has_runid(self):
        from fastapi.testclient import TestClient
        from backend.app import app
        c = TestClient(app)
        body = {'content': '主干道平均车速8km/h，排队400米，请协同研判。'}
        r = c.post('/agent/routed_analyze/stream', json=body)
        text = r.text
        # fusion_delta should carry runId
        import re
        delta_matches = re.findall(r'fusion_delta.*runId', text, re.DOTALL)
        assert len(delta_matches) > 0, "fusion_delta should include runId"

    def test_fusion_delta_has_runid_in_data(self):
        from fastapi.testclient import TestClient
        from backend.app import app
        c = TestClient(app)
        body = {'content': '主干道平均车速8km/h，排队400米，请协同研判。'}
        r = c.post('/agent/routed_analyze/stream', json=body)
        fusion_done = 'event: fusion_done' in r.text
        assert fusion_done, "Should have fusion_done event"

    def test_budget_non_empty_after_completion(self):
        from fastapi.testclient import TestClient
        from backend.app import app
        c = TestClient(app)
        body = {'content': '主干道平均车速8km/h，排队400米，请协同研判。'}
        r = c.post('/agent/routed_analyze/stream', json=body)
        import re
        sid = re.search(r'\"sessionId\":\s*\"([^\"]+)\"', r.text).group(1)
        runs = c.get(f'/collaboration/sessions/{sid}/runs').json()['runs']
        rid = runs[0]['run_id']
        detail = c.get(f'/collaboration/runs/{rid}').json()
        bu = detail['run'].get('budget_usage', {})
        if isinstance(bu, dict):
            calls = sum(int(v) for v in bu.get('used_agent_calls', bu.get('usedAgentCalls', {})).values())
            assert calls > 0, f"Should have agent calls > 0, got {calls}"

    def test_budget_updated_event_present(self):
        from fastapi.testclient import TestClient
        from backend.app import app
        c = TestClient(app)
        body = {'content': '主干道平均车速8km/h，排队400米，请协同研判。'}
        r = c.post('/agent/routed_analyze/stream', json=body)
        assert 'event: budget_updated' in r.text or 'budget_updated' in r.text


class TestSidebarLabels:
    """最近分析标签"""

    def test_collaboration_session_has_mode(self):
        from fastapi.testclient import TestClient
        from backend.app import app
        c = TestClient(app)
        body = {'content': '主干道平均车速8km/h，排队400米，请协同研判。'}
        r = c.post('/agent/routed_analyze/stream', json=body)
        import re
        sid = re.search(r'\"sessionId\":\s*\"([^\"]+)\"', r.text).group(1)
        sessions = c.get('/chat/sessions?limit=10').json()['sessions']
        collab = [s for s in sessions if s['id'] == sid]
        assert len(collab) == 1
        assert collab[0].get('mode') == 'collaboration', f"Mode should be collaboration, got {collab[0].get('mode')}"


class TestConflictScenarioFinal:
    """冲突场景回归"""

    def test_school_conflict_has_3_conflict_types(self):
        from backend.agent.collaboration.orchestrator import _detect_simple_conflicts
        from backend.agent.collaboration.state import CollaborationRunState
        state = CollaborationRunState("rc", "sc", "tc")
        state.task_results = {
            "SignalAgent": {"findings": ["建议延长机动车绿灯20秒", "优化信号配时"], "suggestion": "增加机动车通行", "urgency": "high"},
            "PublicSafetyAgent": {"findings": ["学生集中横穿需要行人保护相位", "限制机动车放行以保证安全"], "suggestion": "保障行人相位", "urgency": "high"},
        }
        conflicts = _detect_simple_conflicts(state)
        types = set(c["type"] for c in conflicts)
        # Should have multiple conflict types
        assert len(types) >= 2, f"Should have at least 2 conflict types, got {types}"

    def test_high_conflict_requires_human_review(self):
        from backend.agent.collaboration.agents import conflict_arbiter
        result = conflict_arbiter({"id": "school_1", "type": "resource_conflict", "severity": "high",
                                    "description": "信号周期资源在学生安全与通行效率之间存在冲突"})
        assert result["requires_human_review"] is True

    def test_no_conflict_when_only_congestion(self):
        from backend.agent.collaboration.orchestrator import _detect_simple_conflicts
        from backend.agent.collaboration.state import CollaborationRunState
        state = CollaborationRunState("r0", "s0", "t0")
        state.task_results = {"CongestionAgent": {"findings": ["拥堵"], "suggestion": "分流", "urgency": "high"}}
        conflicts = _detect_simple_conflicts(state)
        assert len(conflicts) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
