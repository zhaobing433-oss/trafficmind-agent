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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
