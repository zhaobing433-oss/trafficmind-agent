"""
未闭环事件提醒工具模块
------------------
找出仍未完成处置闭环的事件，生成提醒信息和处置建议。
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List
from backend.tools.db_tools import get_connection, init_db


# 未闭环状态集合
UNCLOSED_STATUSES = {"待研判", "待派单", "处置中", "待复盘"}

# 风险等级排序映射
RISK_ORDER = {"低风险": 1, "中风险": 2, "高风险": 3, "重大风险": 4}


def build_alert_reason(event: Dict[str, Any]) -> str:
    """
    根据事件状态和风险等级生成提醒原因。

    Args:
        event: 事件记录字典

    Returns:
        提醒原因文本
    """
    risk_level = event.get("riskLevel", "")
    status = event.get("status", "")
    risk_score = event.get("riskScore", 0)
    created_at = event.get("createdAt", "")

    parts = []

    # 风险等级提醒
    if risk_level in ("高风险", "重大风险"):
        status_cn = {"待派单": "尚未派单", "处置中": "仍在处置中"}.get(status, "")
        if status_cn:
            parts.append(f"{risk_level}事件{status_cn}（{risk_score}分），请优先关注。")

    # 时间提醒
    if created_at:
        try:
            created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
            elapsed = datetime.now() - created_dt
            minutes = int(elapsed.total_seconds() / 60)

            if risk_level == "重大风险" and minutes > 10:
                parts.insert(0, f"重大风险事件已持续 {minutes} 分钟未闭环，需要紧急介入！")
            elif minutes > 1440:  # 超过 24 小时
                parts.append(f"事件已超过 {minutes // 60} 小时未闭环，请尽快完成处置。")
            elif minutes > 30:
                parts.append(f"事件已持续 {minutes} 分钟，建议加快处置进度。")
        except (ValueError, TypeError):
            pass

    # 状态特定提醒
    if status == "待复盘":
        parts.append("事件待复盘已超时，请尽快组织复盘并归档。")
    elif status == "待研判":
        parts.append("事件尚未完成研判，请尽快安排分析。")
    elif status == "待派单":
        parts.append("事件已完成研判但尚未派单，请尽快下发处置任务。")

    return "；".join(parts) if parts else "请关注事件处置进度"


def build_recommended_action(event: Dict[str, Any]) -> str:
    """
    根据事件信息生成建议处置动作。

    Args:
        event: 事件记录字典

    Returns:
        建议动作文本
    """
    risk_level = event.get("riskLevel", "")
    status = event.get("status", "")
    event_type = event.get("eventTypeCn", event.get("eventType", ""))

    if risk_level == "重大风险":
        return "立即启动应急预案，通知相关单位负责人，优先调配资源处置。"

    if risk_level == "高风险":
        if status in ("待派单", "待研判"):
            return "尽快完成研判并派单，通知辖区交警大队关注。"
        return "跟踪处置进度，确保在 30 分钟内完成闭环。"

    if status == "待复盘":
        return "安排复盘会议，总结处置经验，更新预案库后归档。"

    if status == "待研判":
        return f"请在系统中完成「{event_type}」事件的研判分析。"

    return "按常规流程推进处置，做好记录。"


def get_unclosed_events(hours: int = 24, min_risk: str = "中风险") -> Dict[str, Any]:
    """
    获取未闭环的事件列表。

    Args:
        hours: 查询最近多少小时内的事件
        min_risk: 最低风险等级筛选

    Returns:
        {"count": int, "alerts": [...]}
    """
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    # 计算时间范围
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    # 风险等级阈值
    min_risk_order = RISK_ORDER.get(min_risk, 2)

    # 查询未闭环事件
    placeholders = ",".join("?" for _ in UNCLOSED_STATUSES)
    cursor.execute(
        f"SELECT * FROM event_records WHERE status IN ({placeholders}) AND createdAt >= ? ORDER BY "
        "CASE riskLevel WHEN '重大风险' THEN 0 WHEN '高风险' THEN 1 WHEN '中风险' THEN 2 ELSE 3 END, "
        "createdAt DESC",
        list(UNCLOSED_STATUSES) + [since],
    )
    rows = cursor.fetchall()
    conn.close()

    alerts = []
    for row in rows:
        event = dict(row)
        risk_level = event.get("riskLevel", "")
        risk_order = RISK_ORDER.get(risk_level, 0)

        # 按 min_risk 过滤
        if risk_order < min_risk_order:
            continue

        # 计算持续时长
        created_at = event.get("createdAt", "")
        duration_since = ""
        try:
            created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
            elapsed = datetime.now() - created_dt
            mins = int(elapsed.total_seconds() / 60)
            if mins < 60:
                duration_since = f"{mins} 分钟"
            elif mins < 1440:
                duration_since = f"{mins // 60} 小时 {mins % 60} 分钟"
            else:
                duration_since = f"{mins // 1440} 天 {mins % 1440 // 60} 小时"
        except (ValueError, TypeError):
            duration_since = "未知"

        alerts.append({
            "eventId": event.get("eventId", ""),
            "eventType": event.get("eventTypeCn", event.get("eventType", "")),
            "roadName": event.get("roadName", ""),
            "direction": event.get("direction", ""),
            "riskLevel": risk_level,
            "riskScore": event.get("riskScore", 0),
            "status": event.get("status", ""),
            "createdAt": created_at,
            "durationSinceCreated": duration_since,
            "alertReason": build_alert_reason(event),
            "recommendedAction": build_recommended_action(event),
        })

    return {
        "count": len(alerts),
        "alerts": alerts,
    }
