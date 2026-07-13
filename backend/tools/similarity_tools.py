"""
相似案例检索工具模块
------------------
基于规则相似度从历史事件中检索相似案例。
第一阶段使用规则相似度，预留向量检索扩展接口。
"""

from typing import Dict, Any, List, Optional
from backend.tools.db_tools import get_connection, init_db


def calculate_similarity(current_event: Dict[str, Any], history_event: Dict[str, Any]) -> Dict[str, Any]:
    """
    基于规则计算当前事件与历史事件的相似度。

    相似度规则（总分上限 1.0）：
      - eventType 相同：+0.35
      - roadName 相同：+0.25
      - direction 相同：+0.10
      - weather 相同：+0.05
      - timePeriod 相同：+0.10
      - riskLevel 相同：+0.10
      - avgSpeed 差距 < 5：+0.05
      - queueLength 差距 < 50：+0.05
      - nearbySchool / nearbyHospital / isMainRoad 相同：各 +0.03

    Args:
        current_event: 当前事件字典
        history_event: 历史事件字典

    Returns:
        {"similarityScore": float, "similarityReasons": [str]}
    """
    score = 0.0
    reasons: List[str] = []

    # 辅助函数：安全获取字段值
    def get_val(event, key, default=None):
        if key in event:
            return event[key]
        # 尝试从 rawEvent JSON 中获取
        raw = event.get("rawEvent", {})
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                raw = {}
        if isinstance(raw, dict):
            return raw.get(key, default)
        return default

    def get_val_full(event, key, default=None):
        """从 fullResult 或 rawEvent 中获取字段"""
        # 先尝试直接从 event dict 获取
        if key in event and event[key] is not None and event[key] != "":
            return event[key]
        # 尝试 rawEvent
        raw = event.get("rawEvent", {})
        if isinstance(raw, str):
            import json
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                raw = {}
        if isinstance(raw, dict) and key in raw and raw[key] is not None and raw[key] != "":
            return raw[key]
        # 尝试 fullResult
        full = event.get("fullResult", {})
        if isinstance(full, str):
            import json
            try:
                full = json.loads(full)
            except (json.JSONDecodeError, TypeError):
                full = {}
        if isinstance(full, dict):
            se = full.get("standardEvent", {})
            if isinstance(se, dict) and key in se:
                return se[key]
        return default

    # --- 核心相似度规则 ---

    # 1. 事件类型相同 +0.35
    cur_type = get_val_full(current_event, "eventTypeCn") or get_val_full(current_event, "eventType")
    hist_type = get_val_full(history_event, "eventTypeCn") or get_val_full(history_event, "eventType")
    if cur_type and hist_type and cur_type == hist_type:
        score += 0.35
        reasons.append(f"事件类型相同：{cur_type}")

    # 2. 路段名称相同 +0.25
    cur_road = get_val_full(current_event, "roadName")
    hist_road = get_val_full(history_event, "roadName")
    if cur_road and hist_road and cur_road == hist_road:
        score += 0.25
        reasons.append(f"发生位置相同：{cur_road}")

    # 3. 方向相同 +0.10
    cur_dir = get_val_full(current_event, "direction")
    hist_dir = get_val_full(history_event, "direction")
    if cur_dir and hist_dir and cur_dir == hist_dir:
        score += 0.10
        reasons.append(f"方向相同：{cur_dir}")

    # 4. 天气相同 +0.05
    cur_weather = get_val_full(current_event, "weather")
    hist_weather = get_val_full(history_event, "weather")
    if cur_weather and hist_weather and cur_weather == hist_weather:
        score += 0.05
        weather_cn = {"rain": "雨", "snow": "雪", "fog": "雾", "clear": "晴"}.get(cur_weather, cur_weather)
        reasons.append(f"天气状况相同：{weather_cn}")

    # 5. 时段相同 +0.10
    cur_period = get_val_full(current_event, "timePeriod")
    hist_period = get_val_full(history_event, "timePeriod")
    if cur_period and hist_period and cur_period == hist_period:
        score += 0.10
        period_cn = {"morning_peak": "早高峰", "evening_peak": "晚高峰", "off_peak": "平峰"}.get(cur_period, cur_period)
        reasons.append(f"均发生在{period_cn}")

    # 6. 风险等级相同 +0.10
    cur_level = get_val_full(current_event, "riskLevel")
    hist_level = get_val_full(history_event, "riskLevel")
    if cur_level and hist_level and cur_level == hist_level:
        score += 0.10
        reasons.append(f"风险等级相同：{cur_level}")

    # 7. 平均车速差距 < 5 +0.05
    cur_speed = float(get_val_full(current_event, "avgSpeed") or 0)
    hist_speed = float(get_val_full(history_event, "avgSpeed") or 0)
    if abs(cur_speed - hist_speed) < 5:
        score += 0.05
        reasons.append(f"平均车速接近（{cur_speed} vs {hist_speed} km/h）")

    # 8. 排队长度差距 < 50 +0.05
    cur_queue = float(get_val_full(current_event, "queueLength") or 0)
    hist_queue = float(get_val_full(history_event, "queueLength") or 0)
    if abs(cur_queue - hist_queue) < 50:
        score += 0.05
        reasons.append(f"排队长度接近（{cur_queue} vs {hist_queue} 米）")

    # 9. 周边特征相同
    for field, label in [("nearbySchool", "邻近学校"), ("nearbyHospital", "邻近医院"), ("isMainRoad", "主干道")]:
        cur_val = get_val_full(current_event, field)
        hist_val = get_val_full(history_event, field)
        if cur_val is not None and hist_val is not None and bool(cur_val) == bool(hist_val):
            score += 0.03
            if bool(cur_val):
                reasons.append(f"均为{label}路段")

    # 上限 1.0
    score = min(score, 1.0)

    return {
        "similarityScore": round(score, 2),
        "similarityReasons": reasons,
    }


def find_similar_cases(event_id: str, limit: int = 5, min_score: float = 0.4) -> Dict[str, Any]:
    """
    查找与指定事件相似的历史案例。

    Args:
        event_id: 当前事件编号
        limit: 返回的最大案例数
        min_score: 最低相似度阈值

    Returns:
        {
            "currentEvent": {...},
            "similarCases": [...],
        }
    """
    from backend.tools.db_tools import get_event_by_id, get_all_events_for_similarity

    # 获取当前事件
    current = get_event_by_id(event_id)
    if not current:
        return {"currentEvent": None, "similarCases": [], "error": f"事件 {event_id} 不存在"}

    # 构建当前事件摘要
    current_summary = {
        "eventId": current.get("eventId", ""),
        "eventType": current.get("eventTypeCn", current.get("eventType", "")),
        "roadName": current.get("roadName", ""),
        "direction": current.get("direction", ""),
        "riskScore": current.get("riskScore", 0),
        "riskLevel": current.get("riskLevel", ""),
        "status": current.get("status", ""),
        "createdAt": current.get("createdAt", ""),
    }

    # 获取所有历史事件（排除当前事件）
    all_events = get_all_events_for_similarity()
    candidates = [e for e in all_events if e.get("eventId") != event_id]

    # 计算相似度
    scored = []
    for hist in candidates:
        sim = calculate_similarity(current, hist)
        if sim["similarityScore"] >= min_score:
            scored.append({
                "eventId": hist.get("eventId", ""),
                "eventType": hist.get("eventTypeCn", hist.get("eventType", "")),
                "roadName": hist.get("roadName", ""),
                "direction": hist.get("direction", ""),
                "riskScore": hist.get("riskScore", 0),
                "riskLevel": hist.get("riskLevel", ""),
                "status": hist.get("status", ""),
                "similarityScore": sim["similarityScore"],
                "similarityReasons": sim["similarityReasons"],
                "report": hist.get("report", "")[:500],  # 截取前500字
                "createdAt": hist.get("createdAt", ""),
            })

    # 按相似度降序排列
    scored.sort(key=lambda x: x["similarityScore"], reverse=True)

    return {
        "currentEvent": current_summary,
        "similarCases": scored[:limit],
    }


# ========== 向量检索扩展接口（第三阶段） ==========

def vector_based_similarity(event_id: str, limit: int = 5, min_score: float = 0.4) -> Dict[str, Any]:
    """
    基于向量数据库的语义相似度检索（预留接口）。

    第三阶段计划：
      - 使用 Chroma / FAISS 存储事件嵌入向量
      - 通过 embedding 模型计算语义相似度
      - 支持 RAG 增强的事件案例检索

    Args:
        event_id: 当前事件编号
        limit: 返回的最大案例数
        min_score: 最低相似度阈值

    Returns:
        与 find_similar_cases 格式相同；向量库不可用时返回空列表
    """
    from backend.tools.db_tools import get_event_by_id
    from backend.rag.vector_store import _CHROMA_AVAILABLE
    from backend.rag.vector_store import search_similar as chroma_search

    current = get_event_by_id(event_id)
    if not current:
        return {"currentEvent": None, "similarCases": [], "error": f"事件 {event_id} 不存在"}
    if not _CHROMA_AVAILABLE:
        return {"currentEvent": _build_summary(current), "similarCases": [], "error": "向量库不可用"}

    query_text = (
        f"事件类型: {current.get('eventTypeCn', current.get('eventType', ''))} "
        f"路段: {current.get('roadName', '')} "
        f"风险等级: {current.get('riskLevel', '')} "
        f"天气: {current.get('weather', 'clear')} "
        f"时段: {current.get('timePeriod', 'off_peak')}"
    )
    try:
        vector_results = chroma_search(query_text, limit=limit * 2, where={"docType": "event_report"})
    except Exception as e:
        return {"currentEvent": _build_summary(current), "similarCases": [], "error": str(e)}

    scored = []
    for r in vector_results:
        meta = r.get("metadata", {})
        ev_id = meta.get("eventId", "")
        if ev_id == event_id: continue
        score = r.get("score", 0.0)
        if score >= min_score:
            scored.append({"eventId": ev_id, "eventType": meta.get("eventType", ""),
                "roadName": meta.get("roadName", ""), "riskLevel": meta.get("riskLevel", ""),
                "similarityScore": round(score, 2),
                "similarityReasons": [r.get("reason", "语义相似")],
                "matchedEvidence": r.get("content", "")[:300],
                "report": r.get("content", "")[:500], "createdAt": meta.get("createdAt", ""),})
    scored.sort(key=lambda x: x["similarityScore"], reverse=True)
    return {"currentEvent": _build_summary(current), "similarCases": scored[:limit]}


def rule_based_similarity(current_event, history_event):
    """规则相似度（calculate_similarity 别名）。"""
    return calculate_similarity(current_event, history_event)


def hybrid_similarity(event_id: str, limit: int = 5, min_score: float = 0.4,
                      rule_weight: float = None, vector_weight: float = None) -> Dict[str, Any]:
    """混合相似度：规则 + 向量。权重可配置，默认从 similarity_config 读取。"""
    from backend.tools.similarity_config import get_weights, get_weight_reason
    from backend.rag.intent_router import classify_traffic_intent

    # Determine weights
    current = None
    from backend.tools.db_tools import get_event_by_id
    ev = get_event_by_id(event_id)
    if ev:
        intent = classify_traffic_intent(ev.get("eventTypeCn", ev.get("eventType", "")))
    else:
        intent = "general_qa"

    w = get_weights(intent)
    rw = rule_weight if rule_weight is not None else w["rule"]
    vw = vector_weight if vector_weight is not None else w["vector"]

    rule_result = find_similar_cases(event_id, limit=limit * 2, min_score=0.2)
    vector_result = vector_based_similarity(event_id, limit=limit * 2, min_score=0.2)
    current = rule_result.get("currentEvent") or vector_result.get("currentEvent")
    combined: Dict[str, Dict[str, Any]] = {}
    for case in rule_result.get("similarCases", []):
        eid = case["eventId"]
        combined[eid] = {"eventId": eid, "eventType": case.get("eventType", ""),
            "roadName": case.get("roadName", ""), "riskLevel": case.get("riskLevel", ""),
            "ruleSimilarity": case.get("similarityScore", 0.0), "vectorSimilarity": 0.0,
            "finalSimilarity": round(case.get("similarityScore", 0.0) * rw, 2),
            "weightsUsed": {"rule": rw, "vector": vw},
            "weightReason": get_weight_reason(intent),
            "similarityReasons": case.get("similarityReasons", []),
            "matchedEvidence": "", "report": case.get("report", ""), "createdAt": case.get("createdAt", ""),}
    for case in vector_result.get("similarCases", []):
        eid = case["eventId"]
        if eid in combined:
            combined[eid]["vectorSimilarity"] = case.get("similarityScore", 0.0)
            combined[eid]["finalSimilarity"] = round(combined[eid]["ruleSimilarity"] * rw + case.get("similarityScore", 0.0) * vw, 2)
            if case.get("matchedEvidence"): combined[eid]["matchedEvidence"] = case["matchedEvidence"]
        else:
            combined[eid] = {"eventId": eid, "eventType": case.get("eventType", ""),
                "roadName": case.get("roadName", ""), "riskLevel": case.get("riskLevel", ""),
                "ruleSimilarity": 0.0, "vectorSimilarity": case.get("similarityScore", 0.0),
                "finalSimilarity": round(case.get("similarityScore", 0.0) * vw, 2),
                "weightsUsed": {"rule": rw, "vector": vw},
                "weightReason": get_weight_reason(intent),
                "similarityReasons": case.get("similarityReasons", []),
                "matchedEvidence": case.get("matchedEvidence", ""),
                "report": case.get("report", ""), "createdAt": case.get("createdAt", ""),}
    results = sorted(combined.values(), key=lambda x: x["finalSimilarity"], reverse=True)
    return {"currentEvent": current, "similarCases": [r for r in results if r["finalSimilarity"] >= min_score][:limit]}


def _build_summary(event):
    return {"eventId": event.get("eventId", ""), "eventType": event.get("eventTypeCn", event.get("eventType", "")),
            "roadName": event.get("roadName", ""), "direction": event.get("direction", ""),
            "riskScore": event.get("riskScore", 0), "riskLevel": event.get("riskLevel", ""),
            "status": event.get("status", ""), "createdAt": event.get("createdAt", ""),}
