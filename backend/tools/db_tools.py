"""
数据库工具模块
------------
使用 SQLite 持久化存储事件分析结果。
表结构：event_records
"""

import sqlite3
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from backend.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """获取数据库连接（自动创建目录）。"""
    import os
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 让查询结果支持按列名访问
    return conn


def init_db() -> None:
    """初始化数据库表结构。"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            eventId TEXT UNIQUE NOT NULL,
            eventType TEXT NOT NULL,
            eventTypeCn TEXT NOT NULL,
            roadName TEXT NOT NULL,
            direction TEXT DEFAULT '',
            riskScore INTEGER NOT NULL,
            riskLevel TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT '待派单',
            report TEXT DEFAULT '',
            rawEvent TEXT DEFAULT '{}',
            fullResult TEXT DEFAULT '{}',
            createdAt TEXT NOT NULL,
            updatedAt TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_event_analysis(result: Dict[str, Any]) -> bool:
    """
    保存事件分析结果到数据库。

    Args:
        result: 完整的分析结果字典（与 /analyze_event 返回结构一致）

    Returns:
        是否保存成功
    """
    try:
        init_db()  # 确保表存在
        conn = get_connection()
        cursor = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        standard_event = result.get("standardEvent", {})
        event_id = result.get("eventId", standard_event.get("eventId", ""))

        cursor.execute("""
            INSERT OR REPLACE INTO event_records
                (eventId, eventType, eventTypeCn, roadName, direction,
                 riskScore, riskLevel, status, report,
                 rawEvent, fullResult, createdAt, updatedAt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event_id,
            standard_event.get("eventType", ""),
            standard_event.get("eventTypeCn", ""),
            standard_event.get("roadName", ""),
            standard_event.get("direction", ""),
            result.get("riskScore", 0),
            result.get("riskLevel", ""),
            result.get("status", "待派单"),
            result.get("report", ""),
            json.dumps(standard_event, ensure_ascii=False),
            json.dumps(result, ensure_ascii=False),
            result.get("analyzedAt", now),
            now,
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] 保存失败: {e}")
        return False


def get_history(limit: int = 50) -> List[Dict[str, Any]]:
    """
    查询历史事件分析记录。

    Args:
        limit: 最大返回条数

    Returns:
        历史记录列表
    """
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT eventId, eventType, eventTypeCn, roadName, riskScore, "
        "riskLevel, status, createdAt, updatedAt "
        "FROM event_records ORDER BY updatedAt DESC LIMIT ?",
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_event_by_id(event_id: str) -> Optional[Dict[str, Any]]:
    """
    根据 eventId 查询单条事件详情。

    Args:
        event_id: 事件编号

    Returns:
        事件详情字典，不存在则返回 None
    """
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM event_records WHERE eventId = ?",
        (event_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return None

    record = dict(row)
    # 将 JSON 字符串还原为对象
    for field in ("rawEvent", "fullResult"):
        if field in record and isinstance(record[field], str):
            try:
                record[field] = json.loads(record[field])
            except json.JSONDecodeError:
                pass
    return record


def update_event_status(event_id: str, status: str) -> bool:
    """
    更新事件状态。

    Args:
        event_id: 事件编号
        status: 新状态（待研判/待派单/处置中/已处置/待复盘/已归档）

    Returns:
        是否更新成功
    """
    from backend.config import EVENT_STATUSES

    if status not in EVENT_STATUSES:
        return False

    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        "UPDATE event_records SET status = ?, updatedAt = ? WHERE eventId = ?",
        (status, now, event_id),
    )
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def get_stats() -> Dict[str, Any]:
    """
    获取仪表盘统计数据。

    Returns:
        {
            "totalEvents": int,
            "highRiskCount": int,
            "avgRiskScore": float,
            "pendingDispatch": int,
            "riskDistribution": [{"level": str, "count": int}, ...],
            "eventTypeDistribution": [{"type": str, "count": int}, ...],
            "statusDistribution": [{"status": str, "count": int}, ...],
            "dailyTrend": [{"date": str, "count": int}, ...],
        }
    """
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    # 总事件数
    cursor.execute("SELECT COUNT(*) FROM event_records")
    total_events = cursor.fetchone()[0]

    # 高风险及以上事件数
    cursor.execute(
        "SELECT COUNT(*) FROM event_records WHERE riskLevel IN ('高风险', '重大风险')"
    )
    high_risk_count = cursor.fetchone()[0]

    # 平均风险分数
    cursor.execute("SELECT AVG(riskScore) FROM event_records")
    avg_row = cursor.fetchone()
    avg_risk_score = round(avg_row[0], 1) if avg_row[0] else 0.0

    # 待派单数
    cursor.execute("SELECT COUNT(*) FROM event_records WHERE status = '待派单'")
    pending_dispatch = cursor.fetchone()[0]

    # 风险等级分布
    cursor.execute(
        "SELECT riskLevel, COUNT(*) as cnt FROM event_records GROUP BY riskLevel ORDER BY cnt DESC"
    )
    risk_distribution = [{"level": row["riskLevel"], "count": row["cnt"]} for row in cursor.fetchall()]

    # 事件类型分布
    cursor.execute(
        "SELECT eventTypeCn as type, COUNT(*) as cnt FROM event_records GROUP BY eventTypeCn ORDER BY cnt DESC"
    )
    event_type_distribution = [{"type": row["type"], "count": row["cnt"]} for row in cursor.fetchall()]

    # 状态分布
    cursor.execute(
        "SELECT status, COUNT(*) as cnt FROM event_records GROUP BY status ORDER BY cnt DESC"
    )
    status_distribution = [{"status": row["status"], "count": row["cnt"]} for row in cursor.fetchall()]

    # 近 7 天每日趋势
    cursor.execute("""
        SELECT DATE(createdAt) as date, COUNT(*) as cnt
        FROM event_records
        WHERE createdAt >= DATE('now', '-6 days')
        GROUP BY DATE(createdAt)
        ORDER BY date ASC
    """)
    daily_trend = [{"date": row["date"], "count": row["cnt"]} for row in cursor.fetchall()]

    conn.close()

    return {
        "totalEvents": total_events,
        "highRiskCount": high_risk_count,
        "avgRiskScore": avg_risk_score,
        "pendingDispatch": pending_dispatch,
        "riskDistribution": risk_distribution,
        "eventTypeDistribution": event_type_distribution,
        "statusDistribution": status_distribution,
        "dailyTrend": daily_trend,
    }
