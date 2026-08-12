"""
预设场景定义 — Phase 13 V1

第一轮完整实现 Scenario C（道路事故导致主干道拥堵）。

Scenario A: 早高峰匝道拥堵 (后续)
Scenario B: 学校周边短时拥堵 (后续)
Scenario C: 道路事故导致主干道拥堵 (当前)
"""

from backend.simulation.models import TrafficMapScenario

SCENARIOS: dict[str, TrafficMapScenario] = {
    "scenario_c_accident": TrafficMapScenario(
        scenario_id="scenario_c_accident",
        name="Scenario C: 演示大道交通事故",
        description=(
            "演示大道（R01）发生交通事故，导致主干道严重拥堵。"
            "流程：Normal → Inject Accident → Severe Congestion → "
            "Agent Analyze → Workflow → Approval → Apply Diversion → Traffic Improves"
        ),
        category="accident",
        initial_events=[
            {
                "event_type": "accident",
                "severity": "high",
                "road_id": "R01",
                "intersection_id": "",
                "longitude": 116.397,
                "latitude": 39.907,
                "description": "演示大道（北→南）中段发生两车追尾事故，占用一条车道",
            },
        ],
    ),
    "scenario_a_peak_hour": TrafficMapScenario(
        scenario_id="scenario_a_peak_hour",
        name="Scenario A: 早高峰创新路拥堵",
        description=(
            "早高峰期间创新路（R03）出现严重拥堵，需要信号配时优化和分流。"
        ),
        category="peak_hour",
        initial_events=[
            {
                "event_type": "congestion",
                "severity": "high",
                "road_id": "R03",
                "intersection_id": "",
                "longitude": 116.3975,
                "latitude": 39.906,
                "description": "早高峰创新路（西→东）严重拥堵，排队超过 300m",
            },
        ],
    ),
    "scenario_b_school_zone": TrafficMapScenario(
        scenario_id="scenario_b_school_zone",
        name="Scenario B: 学校周边短时拥堵",
        description=(
            "演示北路口（I01）附近学校放学，周边道路出现短时拥堵。"
        ),
        category="school_zone",
        initial_events=[
            {
                "event_type": "congestion",
                "severity": "medium",
                "road_id": "R11",
                "intersection_id": "I01",
                "longitude": 116.397,
                "latitude": 39.908,
                "description": "演示北路学校放学，接送车辆集中，短时拥堵",
            },
        ],
    ),
}
