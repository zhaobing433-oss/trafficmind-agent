"""
报告汇总工具模块
--------------
生成交通事件日报和周期报告。
支持 LLM 润色（可选），未配置时降级为本地模板。
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from backend.tools.db_tools import get_connection, init_db
from backend.config import LLM_ENABLED


def _query_events_by_date_range(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    """查询指定日期范围内的事件列表。"""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM event_records WHERE createdAt >= ? AND createdAt < ? ORDER BY createdAt DESC",
        (start_date, end_date + " 23:59:59"),
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _build_summary_data(events: List[Dict[str, Any]], date_label: str) -> Dict[str, Any]:
    """根据事件列表构建汇总数据。"""
    total = len(events)
    high_risk = sum(1 for e in events if e.get("riskLevel") in ("高风险", "重大风险"))
    major_risk = sum(1 for e in events if e.get("riskLevel") == "重大风险")

    # 未闭环事件
    closed_statuses = {"已处置", "已归档"}
    unclosed = [e for e in events if e.get("status") not in closed_statuses]

    # 高发路口 Top5
    road_counter: Dict[str, int] = {}
    for e in events:
        road = e.get("roadName", "未知")
        road_counter[road] = road_counter.get(road, 0) + 1
    top_roads = sorted(road_counter.items(), key=lambda x: x[1], reverse=True)[:5]
    top_roads_list = [{"roadName": r, "count": c} for r, c in top_roads]

    # 事件类型分布
    type_counter: Dict[str, int] = {}
    for e in events:
        t = e.get("eventTypeCn", e.get("eventType", "未知"))
        type_counter[t] = type_counter.get(t, 0) + 1
    event_type_dist = [{"type": t, "count": c} for t, c in sorted(type_counter.items(), key=lambda x: x[1], reverse=True)]

    # 风险等级分布
    level_counter: Dict[str, int] = {}
    for e in events:
        lv = e.get("riskLevel", "未知")
        level_counter[lv] = level_counter.get(lv, 0) + 1
    risk_level_dist = [{"level": lv, "count": c} for lv, c in level_counter.items()]

    # 状态分布
    status_counter: Dict[str, int] = {}
    for e in events:
        st = e.get("status", "未知")
        status_counter[st] = status_counter.get(st, 0) + 1
    status_dist = [{"status": st, "count": c} for st, c in status_counter.items()]

    # 关键发现
    findings = []
    if high_risk > 0:
        findings.append(f"报告期内共发生 {high_risk} 起高风险及以上事件，需重点关注。")
    if major_risk > 0:
        findings.append(f"其中 {major_risk} 起为重大风险事件，建议立即核查处置进度。")
    if unclosed:
        findings.append(f"仍有 {len(unclosed)} 起事件未完成闭环处置。")
    if top_roads:
        findings.append(f"高发路段为 {top_roads[0][0]}（{top_roads[0][1]}起），建议加强巡查。")

    # 管理建议
    suggestions = []
    if high_risk > 0:
        suggestions.append("对高风险事件涉及的信号配时、道路设施进行专项排查。")
    if unclosed:
        suggestions.append("督促未闭环事件责任单位加快处置进度，确保按时归档。")
    if top_roads:
        suggestions.append(f"建议将 {top_roads[0][0]} 纳入重点巡查路段，增加巡查频次。")
    suggestions.append("持续监测交通事件趋势，重点关注早晚高峰时段的路口通行状态。")

    return {
        "totalEvents": total,
        "highRiskEvents": high_risk,
        "majorRiskEvents": major_risk,
        "unclosedEvents": len(unclosed),
        "topRoads": top_roads_list,
        "eventTypeDistribution": event_type_dist,
        "riskLevelDistribution": risk_level_dist,
        "statusDistribution": status_dist,
        "keyFindings": findings,
        "suggestions": suggestions,
    }


def _build_report_text(summary: Dict[str, Any], report_type: str, date_label: str) -> str:
    """
    构建报告文本（本地模板，无 LLM 时使用）。

    Args:
        summary: 汇总数据
        report_type: "daily" 或 "weekly"
        date_label: 日期标签
    """
    lines = [
        "=" * 50,
        f"   TrafficMind Agent 交通事件{'日报' if report_type == 'daily' else '周报'}",
        f"   统计周期：{date_label}",
        "=" * 50,
        "",
        "一、总体概况",
        "-" * 30,
        f"报告期内共发生交通事件 {summary['totalEvents']} 起。",
        f"其中高风险及以上事件 {summary['highRiskEvents']} 起",
        f"（含重大风险事件 {summary['majorRiskEvents']} 起）。",
        f"当前仍有 {summary['unclosedEvents']} 起事件未完成闭环处置。",
        "",
        "二、高风险事件情况",
        "-" * 30,
    ]

    if summary['highRiskEvents'] > 0:
        lines.append(f"高风险/重大风险事件共 {summary['highRiskEvents']} 起，")
        lines.append("建议逐案核查处置进度，确保闭环管理。")
    else:
        lines.append("本报告期内无高风险事件。")

    lines += [
        "",
        "三、高发路口分析",
        "-" * 30,
    ]
    if summary['topRoads']:
        for i, road in enumerate(summary['topRoads'], 1):
            lines.append(f"  {i}. {road['roadName']} — 发生 {road['count']} 起事件")
    else:
        lines.append("暂无数据。")

    lines += [
        "",
        "四、事件类型分布",
        "-" * 30,
    ]
    for item in summary['eventTypeDistribution']:
        lines.append(f"  {item['type']}: {item['count']} 起")

    lines += [
        "",
        "五、处置状态分析",
        "-" * 30,
    ]
    for item in summary['statusDistribution']:
        lines.append(f"  {item['status']}: {item['count']} 起")

    lines += [
        "",
        "六、未闭环事件提醒",
        "-" * 30,
    ]
    if summary['unclosedEvents'] > 0:
        lines.append(f"当前有 {summary['unclosedEvents']} 起事件尚未闭环，请关注：")
    else:
        lines.append("所有事件均已闭环，无遗留问题。")

    lines += [
        "",
        "七、管理建议",
        "-" * 30,
    ]
    for i, s in enumerate(summary['suggestions'], 1):
        lines.append(f"  {i}. {s}")

    lines += [
        "",
        "=" * 50,
        f"报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "TrafficMind Agent 自动生成",
    ]

    return "\n".join(lines)


def _polish_with_llm(raw_text: str) -> Optional[str]:
    """使用 LLM 润色报告文本。"""
    if not LLM_ENABLED:
        return None

    try:
        from backend.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        from openai import OpenAI

        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": "你是智慧交通系统的报告分析员。请将以下交通事件报告润色为专业的管理报告。"},
                {"role": "user", "content": f"请润色以下报告，保持原有结构和关键数据，语言更专业简洁：\n\n{raw_text}"},
            ],
            temperature=0.3,
            max_tokens=2048,
            timeout=30,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Report] LLM 润色失败: {e}")
        return None


def generate_daily_report(date: Optional[str] = None) -> Dict[str, Any]:
    """
    生成某一天的交通事件日报。

    Args:
        date: 日期字符串 YYYY-MM-DD，默认今天

    Returns:
        日报数据字典
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    start = date
    end = date
    events = _query_events_by_date_range(start, end)
    summary = _build_summary_data(events, date)
    summary["date"] = date

    # 添加趋势摘要（日报无趋势，仅当日数据）
    summary["trendSummary"] = f"{date} 共发生 {summary['totalEvents']} 起交通事件"

    # 生成报告文本
    raw_report = _build_report_text(summary, "daily", date)
    polished = _polish_with_llm(raw_report)
    summary["reportText"] = polished if polished else raw_report

    return summary


def generate_weekly_report(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    """
    生成交通事件周报。

    Args:
        start_date: 开始日期 YYYY-MM-DD，默认 7 天前
        end_date: 结束日期 YYYY-MM-DD，默认今天

    Returns:
        周报数据字典
    """
    if not end_date:
        end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date:
        start_dt = datetime.now() - timedelta(days=7)
        start_date = start_dt.strftime("%Y-%m-%d")

    events = _query_events_by_date_range(start_date, end_date)
    summary = _build_summary_data(events, f"{start_date} ~ {end_date}")
    summary["startDate"] = start_date
    summary["endDate"] = end_date

    # 每日趋势
    day_counter: Dict[str, int] = {}
    for e in events:
        day = e.get("createdAt", "")[:10]
        if day:
            day_counter[day] = day_counter.get(day, 0) + 1
    trend = [{"date": d, "count": c} for d, c in sorted(day_counter.items())]
    summary["trendSummary"] = trend

    # 生成报告文本
    raw_report = _build_report_text(summary, "weekly", f"{start_date} ~ {end_date}")
    polished = _polish_with_llm(raw_report)
    summary["reportText"] = polished if polished else raw_report

    return summary
