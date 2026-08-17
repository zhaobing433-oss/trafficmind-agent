"""
事件归一化器 — Phase 16 Round 3

统一处理 malformed / None / missing / 非法字符串 字段。

核心原则：
  UNKNOWN ≠ ZERO
  - None / missing / "" / "null" / "N/A" → 保留为 None（unknown），不伪造成 0
  - 字符串数字（"123"、"123.4"）→ 转 float
  - 非法字符串（"abc"）→ None（unknown）+ warning

归一化结果附加：
  - unknownFields: 哪些字段为 unknown（None）
  - normalizationWarnings: 哪些字段原始值非法无法解析

Agent 做算术时安全，但回答中不能把 unknown 说成 0。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.tools.event_tools import normalize_event_type


# 需要数值归一化的字段
NUMERIC_FIELDS = [
    "avgSpeed", "queueLength", "duration",
    "vehicleCount", "riskScore", "confidence",
]

# 视为 unknown 的字符串
_UNKNOWN_STRINGS = {"", "null", "none", "n/a", "na", "-", "unknown", "未知", "无"}


def _coerce_numeric(value: Any) -> Optional[float]:
    """安全转换数值。

    Returns:
        数值（int/float/合法字符串）→ float
        None / missing / 空字符串 / "null" / "N/A" / 非法字符串 → None（unknown）

    不抛异常。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None  # bool 不是数值
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in _UNKNOWN_STRINGS:
            return None
        try:
            return float(s)
        except (ValueError, TypeError):
            return None
    return None


def normalize_event(raw_event: Dict[str, Any]) -> Dict[str, Any]:
    """归一化事件。

    Args:
        raw_event: 原始事件 dict（可能含 standardEvent 包装）。

    Returns:
        归一化后的 dict：
          - 原字段全部保留
          - 数值字段被安全转换（unknown → None）
          - eventTypeCn 补全
          - unknownFields: 值为 None 的字段列表
          - normalizationWarnings: 非法值无法解析的警告列表
    """
    if not isinstance(raw_event, dict):
        raw_event = {}

    # 兼容 standardEvent 包装
    se = raw_event.get("standardEvent", raw_event)
    if not isinstance(se, dict):
        se = {}

    warnings: List[str] = []
    unknown_fields: List[str] = []

    # 从原始事件复制（保留全部字段）
    normalized = dict(raw_event)

    # 数值归一化
    for field in NUMERIC_FIELDS:
        raw_value = se.get(field)
        value = _coerce_numeric(raw_value)
        normalized[field] = value
        if value is None:
            unknown_fields.append(field)
            # 只有非空非法值才产生 warning（区分 truly missing vs malformed）
            if raw_value is not None and raw_value != "":
                warnings.append(f"{field}: 无法解析 '{raw_value}'，按未知处理")

    # 事件类型归一化
    et_raw = se.get("eventType", "")
    et_cn = se.get("eventTypeCn", "")
    if not et_cn:
        et_cn = normalize_event_type(et_raw)
    normalized["eventType"] = et_raw
    normalized["eventTypeCn"] = et_cn

    # 字符串字段去空白（保留原始用于 trace）
    road_name = se.get("roadName", "")
    if isinstance(road_name, str):
        normalized["roadName"] = road_name.strip()

    # 布尔字段安全转换
    for field in ("isMainRoad", "nearbySchool", "nearbyHospital"):
        normalized[field] = _coerce_bool(se.get(field, False))

    # 附加归一化元数据
    normalized["normalizationWarnings"] = warnings
    normalized["unknownFields"] = unknown_fields

    return normalized


def _coerce_bool(value: Any) -> bool:
    """安全转换布尔。None / 非法 → False。"""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "是")
    if isinstance(value, (int, float)):
        return bool(value)
    return False
