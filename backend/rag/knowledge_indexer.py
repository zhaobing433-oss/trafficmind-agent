"""
知识库索引器
----------
将交通规则、历史事件报告、日报周报等文本内容切片并写入向量库。
"""

import json
from datetime import datetime
from typing import Dict, Any, List

from backend.rag.vector_store import (
    add_documents,
    rebuild_collection,
    _set_last_indexed_time,
    _CHROMA_AVAILABLE,
)
from backend.rag.embedding_tools import embed_texts, get_embedding_mode
from backend.tools.db_tools import get_connection, init_db
from backend.config import RULES_PATH


def _load_rules_text() -> List[str]:
    """从 Markdown 规则文件中提取各事件类型的预案文本。"""
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return []

    # 按 ## 分割得到各事件类型
    sections = content.split("\n## ")
    chunks = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        # 取事件类型名作为标题
        title = section.split("\n")[0].strip("# ").strip()
        chunks.append(f"交通处置预案 - {title}\n{section}")
    return chunks


def _load_history_reports() -> List[Dict[str, Any]]:
    """从 SQLite 加载历史事件报告。"""
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM event_records ORDER BY createdAt DESC")
    rows = cursor.fetchall()
    conn.close()

    reports = []
    for row in rows:
        event = dict(row)
        # 将 rawEvent JSON 还原
        raw = event.get("rawEvent", "{}")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {}

        text_parts = [
            f"事件编号: {event.get('eventId', '')}",
            f"事件类型: {event.get('eventTypeCn', event.get('eventType', ''))}",
            f"路段: {event.get('roadName', '')}",
            f"方向: {event.get('direction', '')}",
            f"风险等级: {event.get('riskLevel', '')} ({event.get('riskScore', 0)}分)",
            f"状态: {event.get('status', '')}",
            f"时间: {event.get('createdAt', '')}",
            "",
            event.get("report", ""),
        ]
        reports.append({
            "text": "\n".join(text_parts),
            "metadata": {
                "docType": "event_report",
                "eventId": event.get("eventId", ""),
                "eventType": event.get("eventTypeCn", event.get("eventType", "")),
                "roadName": event.get("roadName", ""),
                "riskLevel": event.get("riskLevel", ""),
                "createdAt": event.get("createdAt", ""),
            },
        })
    return reports


def _load_report_summaries() -> List[Dict[str, Any]]:
    """加载日报/周报文本（从已有报告汇总工具生成）。"""
    from backend.tools.report_summary_tools import generate_daily_report, generate_weekly_report

    reports = []
    try:
        daily = generate_daily_report()
        if daily.get("reportText"):
            reports.append({
                "text": daily["reportText"],
                "metadata": {
                    "docType": "daily_report",
                    "eventId": "",
                    "eventType": "",
                    "roadName": "",
                    "riskLevel": "",
                    "createdAt": daily.get("date", datetime.now().strftime("%Y-%m-%d")),
                },
            })
    except Exception as e:
        print(f"[Indexer] 日报加载失败: {e}")

    try:
        weekly = generate_weekly_report()
        if weekly.get("reportText"):
            reports.append({
                "text": weekly["reportText"],
                "metadata": {
                    "docType": "weekly_report",
                    "eventId": "",
                    "eventType": "",
                    "roadName": "",
                    "riskLevel": "",
                    "createdAt": f"{weekly.get('startDate', '')}~{weekly.get('endDate', '')}",
                },
            })
    except Exception as e:
        print(f"[Indexer] 周报加载失败: {e}")

    return reports


def _load_dispatch_experience() -> List[Dict[str, Any]]:
    """加载调度经验知识库（内置文本）。"""
    experiences = [
        {
            "text": """交通调度经验 - 雨天早高峰拥堵处置
当雨天叠加早高峰发生主干道拥堵时：
1. 优先通知交警大队和信号控制中心
2. 上游路口增加绿灯时间，引导车辆分流
3. 通过交通广播、诱导屏发布拥堵和绕行信息
4. 如排队长度持续增长（>300米），在上游关键路口实施强制分流
5. 关注积水路段，必要时通知市政排水部门
6. 每15分钟更新一次路况状态""",
            "metadata": {
                "docType": "dispatch_experience",
                "eventId": "",
                "eventType": "拥堵",
                "roadName": "",
                "riskLevel": "高风险",
                "createdAt": "",
            },
        },
        {
            "text": """交通调度经验 - 事故应急处置
当发生交通事故时：
1. 立即通知122事故处理中心和120急救中心
2. 交警第一时间到达现场，划定警戒区域
3. 调取事发前5分钟监控录像固定证据
4. 安排拖车快速清理事故车辆
5. 通过诱导屏提示后方车辆减速变道
6. 如有人员伤亡，通知就近医院开通绿色通道
7. 事故处置完毕确认车道恢复通行后归档""",
            "metadata": {
                "docType": "dispatch_experience",
                "eventId": "",
                "eventType": "事故",
                "roadName": "",
                "riskLevel": "重大风险",
                "createdAt": "",
            },
        },
        {
            "text": """交通调度经验 - 信号灯异常处置
当信号灯出现异常时：
1. 通知信号灯运维单位立即派员检修
2. 交警到达路口进行人工指挥
3. 在信号灯修复前持续派人值守
4. 通过诱导屏告知周边驾驶员路口信号灯异常
5. 若为早晚高峰，增加人员配置
6. 记录故障时间和修复时间，评估设备老化情况""",
            "metadata": {
                "docType": "dispatch_experience",
                "eventId": "",
                "eventType": "信号灯异常",
                "roadName": "",
                "riskLevel": "高风险",
                "createdAt": "",
            },
        },
        {
            "text": """交通调度经验 - 行人闯入快速路
行人闯入机动车道/快速路时：
1. 通知就近交警或巡查人员前往劝离
2. 通过广播诱导屏提示过往车辆减速避让
3. 若发生在高速或快速路，立即通知高速交警
4. 评估是否需要增设隔离护栏或过街设施
5. 若行人为老人或儿童，联系辖区派出所协助
6. 事后分析是否有护栏损坏缺口""",
            "metadata": {
                "docType": "dispatch_experience",
                "eventId": "",
                "eventType": "行人闯入",
                "roadName": "",
                "riskLevel": "高风险",
                "createdAt": "",
            },
        },
        {
            "text": """交通调度经验 - 施工占道管理
施工占道事件处置流程：
1. 核查施工审批手续是否齐全
2. 检查施工现场安全防护是否符合规范
3. 若造成严重拥堵，要求施工单位调整施工时间
4. 安排交警在关键点位疏导交通
5. 通过诱导屏、广播发布施工信息引导绕行
6. 对违规施工的责令停工并上报主管部门""",
            "metadata": {
                "docType": "dispatch_experience",
                "eventId": "",
                "eventType": "施工占道",
                "roadName": "",
                "riskLevel": "中风险",
                "createdAt": "",
            },
        },
    ]
    return experiences


def build_knowledge_index() -> Dict[str, Any]:
    """
    重建知识库索引。
    将所有知识来源（规则、报告、经验）向量化写入 Chroma。

    Returns:
        索引构建结果
    """
    if not _CHROMA_AVAILABLE:
        return {
            "success": False,
            "indexedDocuments": 0,
            "collectionName": "",
            "message": "ChromaDB 未安装，无法构建索引。请安装: pip install chromadb",
        }

    # 重建 collection
    collection = rebuild_collection()
    if collection is None:
        return {
            "success": False,
            "indexedDocuments": 0,
            "collectionName": "",
            "message": "向量库初始化失败",
        }

    all_docs = []
    all_metas = []
    all_ids = []
    idx = 0

    # 1. 交通规则
    for chunk in _load_rules_text():
        all_docs.append(chunk)
        all_metas.append({
            "docType": "rule",
            "eventId": "",
            "eventType": "",
            "roadName": "",
            "riskLevel": "",
            "createdAt": "",
        })
        all_ids.append(f"rule_{idx}")
        idx += 1

    # 2. 历史事件报告
    for report in _load_history_reports():
        all_docs.append(report["text"])
        all_metas.append(report["metadata"])
        all_ids.append(f"event_{idx}")
        idx += 1

    # 3. 日报/周报
    for report in _load_report_summaries():
        all_docs.append(report["text"])
        all_metas.append(report["metadata"])
        all_ids.append(f"report_{idx}")
        idx += 1

    # 4. 调度经验
    for exp in _load_dispatch_experience():
        all_docs.append(exp["text"])
        all_metas.append(exp["metadata"])
        all_ids.append(f"exp_{idx}")
        idx += 1

    if not all_docs:
        return {
            "success": False,
            "indexedDocuments": 0,
            "collectionName": collection.name,
            "message": "没有可索引的文档",
        }

    # 批量写入
    ok = add_documents(all_docs, all_metas, all_ids)
    _set_last_indexed_time()

    return {
        "success": ok,
        "indexedDocuments": len(all_docs),
        "collectionName": collection.name,
        "embeddingMode": get_embedding_mode(),
        "message": f"成功索引 {len(all_docs)} 条文档（embedding: {get_embedding_mode()}）" if ok else "索引写入失败",
    }
