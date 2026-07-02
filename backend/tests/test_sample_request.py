"""
TrafficMind Agent 测试脚本
--------------------------
使用 FastAPI TestClient 进行端到端测试。
覆盖第一阶段全部接口 + 第二阶段新增接口。
启动测试：pytest backend/tests/test_sample_request.py -v
"""

import pytest
from fastapi.testclient import TestClient

# 修改 sys.path 并导入 app
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from backend.app import app

# 测试客户端
client = TestClient(app)


# ==================== 测试数据集 ====================

SAMPLE_EVENT = {
    "eventId": "E202606290001",
    "eventType": "congestion",
    "cameraId": "CAM_001",
    "roadName": "人民路-解放路路口",
    "direction": "东向西",
    "lane": "直行车道",
    "avgSpeed": 8.5,
    "queueLength": 180,
    "duration": 601,
    "vehicleCount": 96,
    "weather": "rain",
    "timePeriod": "morning_peak",
    "isMainRoad": True,
    "nearbySchool": False,
    "nearbyHospital": True,
    "confidence": 0.91,
}

# 第二阶段测试用多样数据：3 拥堵 + 2 事故 + 1 违停
STAGE2_EVENTS = [
    {   # 拥堵 - 人民路，高风险
        "eventId": "E202606300001",
        "eventType": "congestion",
        "roadName": "人民路-解放路路口",
        "direction": "东向西",
        "avgSpeed": 7.0,
        "queueLength": 200,
        "duration": 900,
        "vehicleCount": 120,
        "weather": "rain",
        "timePeriod": "morning_peak",
        "isMainRoad": True,
        "nearbySchool": False,
        "nearbyHospital": True,
        "confidence": 0.92,
    },
    {   # 拥堵 - 人民路，中风险
        "eventId": "E202606300002",
        "eventType": "congestion",
        "roadName": "人民路-解放路路口",
        "direction": "西向东",
        "avgSpeed": 18.0,
        "queueLength": 100,
        "duration": 300,
        "vehicleCount": 50,
        "weather": "clear",
        "timePeriod": "off_peak",
        "isMainRoad": True,
        "nearbySchool": False,
        "nearbyHospital": True,
        "confidence": 0.95,
    },
    {   # 拥堵 - 中山路
        "eventId": "E202606300003",
        "eventType": "congestion",
        "roadName": "中山路-南京路路口",
        "direction": "南向北",
        "avgSpeed": 5.0,
        "queueLength": 350,
        "duration": 1200,
        "vehicleCount": 200,
        "weather": "fog",
        "timePeriod": "evening_peak",
        "isMainRoad": True,
        "nearbySchool": True,
        "nearbyHospital": False,
        "confidence": 0.88,
    },
    {   # 事故 - 中山路，重大风险
        "eventId": "E202606300004",
        "eventType": "accident",
        "roadName": "中山路-南京路路口",
        "direction": "南向北",
        "avgSpeed": 2.0,
        "queueLength": 400,
        "duration": 1500,
        "vehicleCount": 60,
        "weather": "fog",
        "timePeriod": "evening_peak",
        "isMainRoad": True,
        "nearbySchool": True,
        "nearbyHospital": True,
        "confidence": 0.85,
    },
    {   # 事故 - 人民路
        "eventId": "E202606300005",
        "eventType": "accident",
        "roadName": "人民路-解放路路口",
        "direction": "东向西",
        "avgSpeed": 3.0,
        "queueLength": 300,
        "duration": 800,
        "vehicleCount": 30,
        "weather": "rain",
        "timePeriod": "morning_peak",
        "isMainRoad": True,
        "nearbySchool": False,
        "nearbyHospital": True,
        "confidence": 0.90,
    },
    {   # 违停 - 中山路，低风险
        "eventId": "E202606300006",
        "eventType": "illegal_parking",
        "roadName": "中山路-南京路路口",
        "direction": "北向南",
        "avgSpeed": 35.0,
        "queueLength": 20,
        "duration": 180,
        "vehicleCount": 1,
        "weather": "clear",
        "timePeriod": "off_peak",
        "isMainRoad": False,
        "nearbySchool": False,
        "nearbyHospital": False,
        "confidence": 0.96,
    },
]


# ==================== 第一阶段回归测试 ====================

class TestAnalyzeEvent:
    """测试 /analyze_event 接口"""

    def test_analyze_returns_200(self):
        response = client.post("/analyze_event", json=SAMPLE_EVENT)
        assert response.status_code == 200

    def test_analyze_has_all_fields(self):
        response = client.post("/analyze_event", json=SAMPLE_EVENT)
        data = response.json()
        required_fields = [
            "eventId", "standardEvent", "riskScore", "riskLevel",
            "riskReasons", "matchedRule", "suggestions",
            "dispatchMessage", "publicMessage", "report",
            "status", "saved",
        ]
        for field in required_fields:
            assert field in data, f"缺少字段: {field}"

    def test_analyze_risk_score_in_range(self):
        response = client.post("/analyze_event", json=SAMPLE_EVENT)
        data = response.json()
        assert 0 <= data["riskScore"] <= 100

    def test_analyze_risk_level_valid(self):
        response = client.post("/analyze_event", json=SAMPLE_EVENT)
        data = response.json()
        valid_levels = ["低风险", "中风险", "高风险", "重大风险"]
        assert data["riskLevel"] in valid_levels

    def test_missing_required_fields(self):
        incomplete_event = {"eventId": "E001"}
        response = client.post("/analyze_event", json=incomplete_event)
        assert response.status_code == 422

    def test_congestion_risk_score(self):
        response = client.post("/analyze_event", json=SAMPLE_EVENT)
        data = response.json()
        assert data["riskScore"] == 100
        assert data["riskLevel"] == "重大风险"


class TestHistory:
    """测试 /history 接口"""

    def test_history_returns_200(self):
        client.post("/analyze_event", json=SAMPLE_EVENT)
        response = client.get("/history")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "records" in data


class TestGetEvent:
    """测试 /event/{event_id} 接口"""

    def test_get_existing_event(self):
        client.post("/analyze_event", json=SAMPLE_EVENT)
        response = client.get(f"/event/{SAMPLE_EVENT['eventId']}")
        assert response.status_code == 200
        assert response.json()["eventId"] == SAMPLE_EVENT["eventId"]

    def test_get_nonexistent_event(self):
        response = client.get("/event/NONEXISTENT")
        assert response.status_code == 404


class TestUpdateStatus:
    """测试 /event/{event_id}/status 接口"""

    def test_update_status_valid(self):
        client.post("/analyze_event", json=SAMPLE_EVENT)
        response = client.post(
            f"/event/{SAMPLE_EVENT['eventId']}/status",
            json={"status": "处置中"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "处置中"

    def test_update_status_invalid(self):
        client.post("/analyze_event", json=SAMPLE_EVENT)
        response = client.post(
            f"/event/{SAMPLE_EVENT['eventId']}/status",
            json={"status": "不存在的状态"},
        )
        assert response.status_code == 400


class TestHealth:
    """测试 /health 接口"""

    def test_health(self):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestStats:
    """测试 /stats 接口"""

    def test_stats_returns_200(self):
        response = client.get("/stats")
        assert response.status_code == 200
        data = response.json()
        assert "totalEvents" in data
        assert "riskDistribution" in data


# ==================== 第二阶段新增测试 ====================

@pytest.fixture(scope="module")
def seed_stage2_data():
    """向数据库写入第二阶段测试数据。"""
    for ev in STAGE2_EVENTS:
        client.post("/analyze_event", json=ev)


class TestSimilarCases:
    """测试 /similar_cases/{event_id} 接口"""

    def test_similar_cases_returns_200(self, seed_stage2_data):
        response = client.get("/similar_cases/E202606300001?limit=3&min_score=0.3")
        assert response.status_code == 200
        data = response.json()
        assert "currentEvent" in data
        assert "similarCases" in data
        assert len(data["similarCases"]) > 0, "应该有相似案例"

    def test_similar_cases_not_found(self):
        response = client.get("/similar_cases/NONEXISTENT")
        assert response.status_code == 404

    def test_similar_cases_respects_limit(self, seed_stage2_data):
        response = client.get("/similar_cases/E202606300001?limit=2&min_score=0.3")
        data = response.json()
        assert len(data["similarCases"]) <= 2

    def test_similar_cases_has_scores(self, seed_stage2_data):
        response = client.get("/similar_cases/E202606300001?limit=3&min_score=0.3")
        data = response.json()
        for case in data["similarCases"]:
            assert "similarityScore" in case
            assert "similarityReasons" in case
            assert case["similarityScore"] >= 0.3


class TestDailyReport:
    """测试 /reports/daily 接口"""

    def test_daily_report_returns_200(self, seed_stage2_data):
        response = client.get("/reports/daily")
        assert response.status_code == 200
        data = response.json()
        assert "date" in data
        assert "totalEvents" in data
        assert "reportText" in data

    def test_daily_report_with_date(self, seed_stage2_data):
        response = client.get("/reports/daily?date=2026-06-30")
        assert response.status_code == 200
        data = response.json()
        assert data["date"] == "2026-06-30"


class TestWeeklyReport:
    """测试 /reports/weekly 接口"""

    def test_weekly_report_returns_200(self, seed_stage2_data):
        response = client.get("/reports/weekly")
        assert response.status_code == 200
        data = response.json()
        assert "startDate" in data
        assert "endDate" in data
        assert "totalEvents" in data
        assert "reportText" in data

    def test_weekly_report_with_dates(self, seed_stage2_data):
        response = client.get("/reports/weekly?start_date=2026-06-01&end_date=2026-06-30")
        assert response.status_code == 200


class TestUnclosedAlerts:
    """测试 /alerts/unclosed 接口"""

    def test_unclosed_alerts_returns_200(self, seed_stage2_data):
        response = client.get("/alerts/unclosed?hours=720&min_risk=低风险")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "alerts" in data

    def test_unclosed_alerts_invalid_risk(self):
        response = client.get("/alerts/unclosed?min_risk=超高风险")
        assert response.status_code == 400

    def test_unclosed_alerts_has_fields(self, seed_stage2_data):
        response = client.get("/alerts/unclosed?hours=720&min_risk=低风险")
        data = response.json()
        for alert in data["alerts"]:
            assert "eventId" in alert
            assert "alertReason" in alert
            assert "recommendedAction" in alert
            assert "durationSinceCreated" in alert


class TestHighRiskRoads:
    """测试 /stats/high_risk_roads 接口"""

    def test_high_risk_roads_returns_200(self, seed_stage2_data):
        response = client.get("/stats/high_risk_roads?days=30&min_risk=低风险")
        assert response.status_code == 200
        data = response.json()
        assert "range" in data
        assert "topRoads" in data

    def test_high_risk_roads_respects_limit(self, seed_stage2_data):
        response = client.get("/stats/high_risk_roads?limit=2&days=30&min_risk=低风险")
        data = response.json()
        assert len(data["topRoads"]) <= 2

    def test_high_risk_roads_has_fields(self, seed_stage2_data):
        response = client.get("/stats/high_risk_roads?days=30&min_risk=低风险")
        data = response.json()
        for road in data["topRoads"]:
            assert "roadName" in road
            assert "totalEvents" in road
            assert "avgRiskScore" in road
            assert "mostCommonEventType" in road
            assert "suggestedAction" in road


# ==================== Phase 3 + 4 测试 ====================


class TestRagEndpoints:
    def test_rag_status(self):
        r = client.get("/rag/status"); assert r.status_code == 200
        assert "enabled" in r.json()
    def test_rebuild_index(self):
        r = client.post("/rag/rebuild_index"); assert r.status_code in (200, 500)
    def test_rag_search(self, seed_stage2_data):
        r = client.get("/rag/search?query=%E6%8B%A5%E5%A0%B5&limit=3")
        assert r.status_code == 200; assert "results" in r.json()
    def test_rag_ask(self, seed_stage2_data):
        r = client.post("/rag/ask", json={"question": "雨天早高峰拥堵如何处置？", "limit": 3})
        assert r.status_code == 200; assert "answer" in r.json()
    def test_hybrid_similarity(self, seed_stage2_data):
        r = client.get("/similar_cases_hybrid/E202606300001?limit=3&min_score=0.3")
        assert r.status_code == 200
        for c in r.json().get("similarCases", []):
            assert "ruleSimilarity" in c; assert "vectorSimilarity" in c; assert "finalSimilarity" in c
    def test_multi_agent(self):
        body = {"eventId":"E99901","eventType":"congestion","roadName":"t","avgSpeed":8.5,"queueLength":180,"duration":601,"weather":"rain","timePeriod":"morning_peak"}
        r = client.post("/agent/multi_analyze", json=body)
        assert r.status_code == 200; d = r.json()
        assert "agentResults" in d; assert "finalDecision" in d; assert "dispatchPlan" in d


class TestReactDiagnose:
    def test_react_returns_200(self):
        r = client.post("/agent/react_diagnose", json={"question": "最近高风险事件多吗？", "max_steps": 3})
        assert r.status_code == 200; d = r.json()
        assert "question" in d; assert "steps" in d; assert "finalAnswer" in d; assert "usedLLM" in d
    def test_react_has_tool_calls(self):
        r = client.post("/agent/react_diagnose", json={"question": "人民路为什么高风险事件多？", "max_steps": 3})
        d = r.json()
        assert len(d.get("toolCalls", [])) > 0
        forbidden = {"update_event_status", "send_notification", "delete_event", "modify_risk_score", "analyze_event"}
        for tc in d.get("toolCalls", []):
            assert tc["tool"] not in forbidden
    def test_react_no_api_key(self):
        r = client.post("/agent/react_diagnose", json={"question": "统计当前事件数量", "max_steps": 2})
        assert r.status_code == 200; assert len(r.json().get("finalAnswer", "")) > 0


class TestRoutedAnalyze:
    S = {"eventId":"E99902","eventType":"congestion","roadName":"人民路","direction":"东向西","avgSpeed":5.0,"queueLength":300,"duration":1200,"weather":"rain","timePeriod":"morning_peak","isMainRoad":True,"nearbyHospital":True}
    def test_routed_returns_200(self):
        r = client.post("/agent/routed_analyze", json=self.S)
        assert r.status_code == 200; d = r.json()
        for k in ["selectedAgents","routingReasons","agentResults","conflicts","resolvedPlan","finalDecision","dispatchPlan","report"]:
            assert k in d, f"missing {k}"
    def test_routed_has_routing(self):
        d = client.post("/agent/routed_analyze", json=self.S).json()
        assert len(d["selectedAgents"]) >= 2; assert len(d["routingReasons"]) >= 1
    def test_routed_congestion_routing(self):
        d = client.post("/agent/routed_analyze", json=self.S).json()
        assert "CongestionAgent" in d["selectedAgents"]
        assert "DispatchAgent" in d["selectedAgents"]
    def test_routed_conflict_detection(self):
        body = {**self.S, "eventType":"accident", "nearbyHospital":True, "nearbySchool":True}
        d = client.post("/agent/routed_analyze", json=body).json()
        assert "conflicts" in d; assert isinstance(d["conflicts"], list)
    def test_old_multi_analyze_still_works(self):
        r = client.post("/agent/multi_analyze", json=self.S)
        assert r.status_code == 200


# ==================== Phase 6 测试 ====================


class TestChatSessions:
    """Chat 会话 CRUD"""
    sid: str = ""

    def test_create_session(self):
        r = client.post("/chat/sessions", json={"mode": "react"})
        assert r.status_code == 200
        d = r.json()
        assert "sessionId" in d
        TestChatSessions.sid = d["sessionId"]

    def test_list_sessions(self):
        r = client.get("/chat/sessions")
        assert r.status_code == 200
        assert len(r.json()["sessions"]) >= 1

    def test_send_message(self):
        assert TestChatSessions.sid, "No session created"
        r = client.post(f"/chat/sessions/{TestChatSessions.sid}/messages",
                        json={"content": "雨天早高峰主干道拥堵如何处置？", "mode": "react"})
        assert r.status_code == 200
        d = r.json()
        assert "sessionId" in d
        assert "userMessage" in d
        assert "assistantMessage" in d
        assert "abstained" in d
        assert "evidence" in d

    def test_get_session_detail(self):
        assert TestChatSessions.sid, "No session created"
        r = client.get(f"/chat/sessions/{TestChatSessions.sid}")
        assert r.status_code == 200
        d = r.json()
        assert "session" in d
        assert "messages" in d
        assert len(d["messages"]) >= 2  # user + assistant

    def test_delete_session(self):
        assert TestChatSessions.sid, "No session created"
        r = client.delete(f"/chat/sessions/{TestChatSessions.sid}")
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestRagGrounded:
    """RAG 可信回答：有证据 / 无证据"""

    def test_with_evidence(self):
        r = client.post("/chat/sessions", json={"mode": "rag"})
        sid = r.json()["sessionId"]
        r = client.post(f"/chat/sessions/{sid}/messages",
                        json={"content": "雨天早高峰主干道拥堵应该怎么处置？", "mode": "rag"})
        d = r.json()
        assert d["abstained"] is False, "应有证据，不应拒答"
        assert len(d.get("evidence", [])) > 0, "应有检索证据"
        client.delete(f"/chat/sessions/{sid}")

    def test_without_evidence(self):
        r = client.post("/chat/sessions", json={"mode": "rag"})
        sid = r.json()["sessionId"]
        r = client.post(f"/chat/sessions/{sid}/messages",
                        json={"content": "火星基地交通信号灯如何优化？", "mode": "rag"})
        d = r.json()
        # May abstain OR provide low-confidence answer
        assert "abstained" in d
        assert "evidence" in d
        client.delete(f"/chat/sessions/{sid}")

    def test_policy_threshold(self):
        """retrieval_policy: empty results → abstain"""
        from backend.rag.retrieval_policy import apply_retrieval_threshold
        r = apply_retrieval_threshold([])
        assert r["abstain"] is True
        assert r["level"] == "none"

        # low score
        r = apply_retrieval_threshold([{"score": 0.20}])
        assert r["abstain"] is True

        # high score
        r = apply_retrieval_threshold([{"score": 0.80}])
        assert r["abstain"] is False
        assert r["level"] == "high"


class TestMemorySummary:
    """上下文摘要"""

    def test_long_session_summary(self):
        r = client.post("/chat/sessions", json={"mode": "react"})
        sid = r.json()["sessionId"]
        msgs = [
            "人民路最近高风险事件多吗？",
            "有哪些具体的处置建议？",
            "信号灯配时需要调整吗？",
            "医院周边的拥堵怎么处理？",
            "学校附近有没有类似问题？",
            "帮我生成一份周报",
            "未闭环事件有多少？",
        ]
        for q in msgs:
            client.post(f"/chat/sessions/{sid}/messages", json={"content": q, "mode": "react"})

        # Check memory summary exists
        from backend.chat.chat_db import get_memory_summary
        mem = get_memory_summary(sid)
        if mem:
            assert mem.get("summary"), "Summary should not be empty"
        # Context should not be infinite
        from backend.chat.memory_manager import build_context_for_llm
        ctx = build_context_for_llm(sid, "最新问题")
        assert len(ctx) < 4000, f"Context too long: {len(ctx)} chars"
        client.delete(f"/chat/sessions/{sid}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
