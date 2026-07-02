"""Knowledge indexer — build vector index from rules, reports, experience"""
import json
from datetime import datetime
from typing import Dict, Any, List
from backend.rag.vector_store import add_documents, rebuild_collection, _set_last_indexed_time, _CHROMA_AVAILABLE
from backend.rag.embedding_tools import get_embedding_mode
from backend.tools.db_tools import get_connection, init_db
from backend.config import RULES_PATH

def _load_rules_text():
    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f: content = f.read()
    except: return []
    chunks = [f"交通处置预案 - {s.split(chr(10))[0].strip('# ').strip()}\n{s}" for s in content.split("\n## ") if s.strip()]
    return chunks

def _load_history_reports():
    init_db(); conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT * FROM event_records ORDER BY createdAt DESC")
    rows = cursor.fetchall(); conn.close()
    reports = []
    for row in rows:
        event = dict(row)
        raw = event.get("rawEvent", "{}")
        if isinstance(raw, str):
            try: raw = json.loads(raw)
            except: raw = {}
        text = f"事件编号: {event.get('eventId', '')}\n事件类型: {event.get('eventTypeCn', event.get('eventType', ''))}\n路段: {event.get('roadName', '')}\n风险: {event.get('riskLevel', '')} ({event.get('riskScore', 0)}分)\n状态: {event.get('status', '')}\n\n{event.get('report', '')}"
        reports.append({"text": text, "metadata": {"docType": "event_report", "eventId": event.get("eventId", ""), "eventType": event.get("eventTypeCn", event.get("eventType", "")), "roadName": event.get("roadName", ""), "riskLevel": event.get("riskLevel", ""), "createdAt": event.get("createdAt", "")}})
    return reports

def _load_dispatch_experience():
    return [
        {"text": "交通调度经验 - 雨天早高峰拥堵处置\n当雨天叠加早高峰发生主干道拥堵时：\n1. 优先通知交警大队和信号控制中心\n2. 上游路口增加绿灯时间，引导车辆分流\n3. 通过交通广播、诱导屏发布拥堵和绕行信息\n4. 如排队长度持续增长（>300米），在上游关键路口实施强制分流\n5. 关注积水路段，必要时通知市政排水部门", "metadata": {"docType": "dispatch_experience", "eventType": "拥堵", "riskLevel": "高风险"}},
        {"text": "交通调度经验 - 事故应急处置\n当发生交通事故时：\n1. 立即通知122事故处理中心和120急救中心\n2. 交警第一时间到达现场，划定警戒区域\n3. 调取事发前5分钟监控录像固定证据\n4. 安排拖车快速清理事故车辆\n5. 通过诱导屏提示后方车辆减速变道\n6. 如有人员伤亡，通知就近医院开通绿色通道", "metadata": {"docType": "dispatch_experience", "eventType": "事故", "riskLevel": "重大风险"}},
        {"text": "交通调度经验 - 信号灯异常处置\n当信号灯出现异常时：\n1. 通知信号灯运维单位立即派员检修\n2. 交警到达路口进行人工指挥\n3. 在信号灯修复前持续派人值守\n4. 通过诱导屏告知周边驾驶员路口信号灯异常\n5. 若为早晚高峰，增加人员配置", "metadata": {"docType": "dispatch_experience", "eventType": "信号灯异常", "riskLevel": "高风险"}},
        {"text": "交通调度经验 - 行人闯入快速路\n行人闯入机动车道/快速路时：\n1. 通知就近交警或巡查人员前往劝离\n2. 通过广播诱导屏提示过往车辆减速避让\n3. 若发生在高速或快速路，立即通知高速交警\n4. 评估是否需要增设隔离护栏或过街设施", "metadata": {"docType": "dispatch_experience", "eventType": "行人闯入", "riskLevel": "高风险"}},
        {"text": "交通调度经验 - 施工占道管理\n施工占道事件处置流程：\n1. 核查施工审批手续是否齐全\n2. 检查施工现场安全防护是否符合规范\n3. 若造成严重拥堵，要求施工单位调整施工时间\n4. 安排交警在关键点位疏导交通\n5. 对违规施工的责令停工并上报主管部门", "metadata": {"docType": "dispatch_experience", "eventType": "施工占道", "riskLevel": "中风险"}},
    ]

def build_knowledge_index():
    if not _CHROMA_AVAILABLE: return {"success": False, "indexedDocuments": 0, "collectionName": "", "message": "ChromaDB 未安装，请: pip install chromadb"}
    collection = rebuild_collection()
    if collection is None: return {"success": False, "indexedDocuments": 0, "collectionName": "", "message": "向量库初始化失败"}
    all_docs, all_metas, all_ids, idx = [], [], [], 0
    for chunk in _load_rules_text():
        all_docs.append(chunk); all_metas.append({"docType": "rule"}); all_ids.append(f"rule_{idx}"); idx += 1
    for r in _load_history_reports():
        all_docs.append(r["text"]); all_metas.append(r["metadata"]); all_ids.append(f"event_{idx}"); idx += 1
    for e in _load_dispatch_experience():
        all_docs.append(e["text"]); all_metas.append(e["metadata"]); all_ids.append(f"exp_{idx}"); idx += 1
    if not all_docs: return {"success": False, "indexedDocuments": 0, "collectionName": collection.name, "message": "无文档"}
    ok = add_documents(all_docs, all_metas, all_ids)
    _set_last_indexed_time()
    return {"success": ok, "indexedDocuments": len(all_docs) if ok else 0, "collectionName": collection.name, "embeddingMode": get_embedding_mode(), "message": f"索引 {len(all_docs)} 条文档" if ok else "写入失败"}
