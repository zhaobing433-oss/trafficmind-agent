"""
TrafficMind Agent 测试脚本
--------------------------
使用 FastAPI TestClient 进行端到端测试。
启动应用后运行：pytest backend/tests/test_sample_request.py -v
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


# 示例请求体（与需求文档一致）
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


class TestAnalyzeEvent:
    """测试 /analyze_event 接口"""

    def test_analyze_returns_200(self):
        """正常事件应返回 200"""
        response = client.post("/analyze_event", json=SAMPLE_EVENT)
        assert response.status_code == 200, f"期望 200，实际 {response.status_code}: {response.text}"

    def test_analyze_has_all_fields(self):
        """返回结果应包含所有必要字段"""
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
        """风险分数应在 0-100 之间"""
        response = client.post("/analyze_event", json=SAMPLE_EVENT)
        data = response.json()
        assert 0 <= data["riskScore"] <= 100, f"风险分数 {data['riskScore']} 超出范围"

    def test_analyze_risk_level_valid(self):
        """风险等级应为合法值"""
        response = client.post("/analyze_event", json=SAMPLE_EVENT)
        data = response.json()
        valid_levels = ["低风险", "中风险", "高风险", "重大风险"]
        assert data["riskLevel"] in valid_levels, f"无效风险等级: {data['riskLevel']}"

    def test_missing_required_fields(self):
        """缺少核心字段时应返回 422（Pydantic 校验层拦截）"""
        incomplete_event = {"eventId": "E001"}
        response = client.post("/analyze_event", json=incomplete_event)
        assert response.status_code == 422

    def test_congestion_risk_score(self):
        """拥堵事件应返回合理的风险分数"""
        response = client.post("/analyze_event", json=SAMPLE_EVENT)
        data = response.json()
        # base=20 + speed=15 + queue=15 + duration(>600)=10 + rain=10 + peak=10 + mainRoad=10 + hospital=10 = 100
        # 但 max 是 100，所以应该是 100
        assert data["riskScore"] == 100
        assert data["riskLevel"] == "重大风险"


class TestHistory:
    """测试 /history 接口"""

    def test_history_returns_200(self):
        """应正常返回历史记录"""
        # 先确保有一条记录
        client.post("/analyze_event", json=SAMPLE_EVENT)
        response = client.get("/history")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "records" in data
        assert isinstance(data["records"], list)


class TestGetEvent:
    """测试 /event/{event_id} 接口"""

    def test_get_existing_event(self):
        """查询已保存的事件应返回详情"""
        client.post("/analyze_event", json=SAMPLE_EVENT)
        response = client.get(f"/event/{SAMPLE_EVENT['eventId']}")
        assert response.status_code == 200
        assert response.json()["eventId"] == SAMPLE_EVENT["eventId"]

    def test_get_nonexistent_event(self):
        """查询不存在的事件应返回 404"""
        response = client.get("/event/NONEXISTENT")
        assert response.status_code == 404


class TestUpdateStatus:
    """测试 /event/{event_id}/status 接口"""

    def test_update_status_valid(self):
        """合法状态更新应成功"""
        client.post("/analyze_event", json=SAMPLE_EVENT)
        response = client.post(
            f"/event/{SAMPLE_EVENT['eventId']}/status",
            json={"status": "处置中"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "处置中"

    def test_update_status_invalid(self):
        """非法状态值应返回 400"""
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
