"""
统计工具模块
----------
高风险路口 TopN 统计等扩展统计功能。
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List
from backend.tools.db_tools import get_connection, init_db


RISK_ORDER = {"低风险": 1, "中风险": 2, "高风险": 3, "重大风险": 4}


def get_high_risk_roads(limit: int = 10, days: int = 7, min_risk: str = "高风险") -> Dict[str, Any]:
    """
    统计高风险事件多发的路口 TopN。

    Args:
        limit: 返回数量上限
        days: 统计最近多少天
        min_risk: 最低风险等级筛选

    Returns:
        {"range": str, "topRoads": [...]}
    """
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    # 时间范围
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    min_risk_order = RISK_ORDER.get(min_risk, 3)

    # 查询指定时间范围内的事件
    cursor.execute(
        "SELECT * FROM event_records WHERE createdAt >= ? ORDER BY createdAt DESC",
        (since,),
    )
    rows = cursor.fetchall()
    conn.close()

    # 按 roadName 聚合
    road_stats: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        event = dict(row)
        road = event.get("roadName", "未知路段")
        risk_level = event.get("riskLevel", "")
        risk_score = event.get("riskScore", 0)
        event_type = event.get("eventTypeCn", event.get("eventType", ""))
        status = event.get("status", "")

        if road not in road_stats:
            road_stats[road] = {
                "roadName": road,
                "totalEvents": 0,
                "highRiskCount": 0,
                "majorRiskCount": 0,
                "totalRiskScore": 0,
                "eventTypes": {},
                "unclosedCount": 0,
            }

        rs = road_stats[road]
        rs["totalEvents"] += 1
        rs["totalRiskScore"] += risk_score

        if risk_level == "高风险":
            rs["highRiskCount"] += 1
        elif risk_level == "重大风险":
            rs["majorRiskCount"] += 1

        rs["eventTypes"][event_type] = rs["eventTypes"].get(event_type, 0) + 1

        if status not in ("已处置", "已归档"):
            rs["unclosedCount"] += 1

    # 筛选满足 min_risk 的路口并计算指标
    result_roads = []
    for road, rs in road_stats.items():
        # 只统计包含指定风险等级及以上事件的路口
        if min_risk_order >= 3 and rs["highRiskCount"] + rs["majorRiskCount"] == 0:
            continue
        if min_risk_order >= 4 and rs["majorRiskCount"] == 0:
            continue

        rs["avgRiskScore"] = round(rs["totalRiskScore"] / rs["totalEvents"], 1) if rs["totalEvents"] > 0 else 0

        # 最常见事件类型
        if rs["eventTypes"]:
            rs["mostCommonEventType"] = max(rs["eventTypes"], key=rs["eventTypes"].get)
        else:
            rs["mostCommonEventType"] = "无"

        # 生成建议
        suggestions = []
        if rs["majorRiskCount"] > 0:
            suggestions.append("建议纳入重点巡查路口，优先安排交警值守。")
        if rs["highRiskCount"] + rs["majorRiskCount"] >= 3:
            suggestions.append("建议复核信号配时方案，排查交通组织隐患。")
        if rs["unclosedCount"] > 0:
            suggestions.append(f"仍有 {rs['unclosedCount']} 起事件未闭环，请跟踪处置。")
        if rs["totalEvents"] >= 5:
            suggestions.append("建议排查违停、施工或事故诱因，制定综合治理方案。")
        if not suggestions:
            suggestions.append("持续关注该路口交通运行状态。")

        rs["suggestedAction"] = "；".join(suggestions)

        # 清理内部字段
        del rs["totalRiskScore"]
        del rs["eventTypes"]

        result_roads.append(rs)

    # 按高风险+重大风险数量降序排列
    result_roads.sort(key=lambda x: x["highRiskCount"] + x["majorRiskCount"], reverse=True)

    return {
        "range": f"最近 {days} 天",
        "topRoads": result_roads[:limit],
    }
