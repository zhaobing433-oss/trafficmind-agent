"""
事件解析工具模块
--------------
负责校验、标准化交通事件数据。
"""

from typing import Dict, Any, Optional, Tuple

# -------------------- 中英文事件类型映射 --------------------

EVENT_TYPE_MAP = {
    # 英文 -> 中文
    "congestion": "拥堵",
    "accident": "事故",
    "illegal_parking": "违停",
    "wrong_way": "逆行",
    "pedestrian_intrusion": "行人闯入",
    "signal_fault": "信号灯异常",
    "vehicle_stopped": "车辆滞留",
    "construction_block": "施工占道",
    # 中文 -> 中文（归一化）
    "拥堵": "拥堵",
    "事故": "事故",
    "违停": "违停",
    "逆行": "逆行",
    "行人闯入": "行人闯入",
    "信号灯异常": "信号灯异常",
    "车辆滞留": "车辆滞留",
    "施工占道": "施工占道",
}

# 核心必填字段（缺一个就报错）
REQUIRED_FIELDS = [
    "eventType",
    "roadName",
    "avgSpeed",
    "queueLength",
    "duration",
    "confidence",
]


def validate_event(event: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    校验事件必要字段是否齐全。

    Args:
        event: 原始事件字典

    Returns:
        (是否通过校验, 错误信息)
          - 通过时返回 (True, None)
          - 失败时返回 (False, "错误描述")
    """
    if not isinstance(event, dict):
        return False, "事件数据必须为 JSON 对象（dict）"

    missing = []
    for field in REQUIRED_FIELDS:
        if field not in event or event[field] is None or event[field] == "":
            missing.append(field)

    if missing:
        return False, f"缺少核心字段: {', '.join(missing)}"

    # 类型校验
    try:
        float(event.get("avgSpeed", 0))
        float(event.get("queueLength", 0))
        float(event.get("duration", 0))
        float(event.get("confidence", 0))
    except (ValueError, TypeError):
        return False, "avgSpeed、queueLength、duration、confidence 必须为数值类型"

    return True, None


def normalize_event_type(event_type: str) -> str:
    """
    将事件类型统一映射为中文名称。

    Args:
        event_type: 原始事件类型（中英文均可）

    Returns:
        中文事件类型；若无法识别，返回原值
    """
    if not event_type:
        return "未知事件"
    return EVENT_TYPE_MAP.get(event_type, event_type)


def safe_float(value: Any, default: float = 0.0) -> float:
    """
    安全转换为 float，None / missing / 空串 / 非法值 → default。

    与 event_normalizer 的 UNKNOWN ≠ ZERO 语义区分：
      这里用于「输出/持久化」路径，缺失值按字段语义回落到默认值，
      绝不抛出 TypeError。判断逻辑需保留 unknown 的地方请勿使用本函数。

    Args:
        value: 任意值（int/float/合法字符串/None/非法字符串）
        default: 回落默认值

    Returns:
        float 数值
    """
    if value is None:
        return float(default)
    if isinstance(value, bool):
        return float(default)
    try:
        return float(value)
    except (ValueError, TypeError):
        return float(default)


def safe_int(value: Any, default: int = 0) -> int:
    """
    安全转换为 int，None / missing / 非法值 → default。

    Args:
        value: 任意值
        default: 回落默认值

    Returns:
        int 数值
    """
    if value is None:
        return int(default)
    if isinstance(value, bool):
        return int(default)
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return int(default)


def standardize_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    标准化事件对象：补全中文类型名和默认字段。

    Args:
        event: 原始事件字典

    Returns:
        标准化后的事件字典
    """
    event_type_raw = event.get("eventType", "")
    cn_type = normalize_event_type(event_type_raw)

    standardized = {
        # --- 基本信息 ---
        "eventId": event.get("eventId", ""),
        "eventType": event_type_raw,
        "eventTypeCn": cn_type,
        "cameraId": event.get("cameraId", ""),
        "roadName": event.get("roadName", ""),
        "direction": event.get("direction", ""),
        "lane": event.get("lane", ""),

        # --- 量化指标（None/非法值安全回落，不抛 TypeError）---
        "avgSpeed": safe_float(event.get("avgSpeed"), 0.0),
        "queueLength": safe_float(event.get("queueLength"), 0.0),
        "duration": safe_float(event.get("duration"), 0.0),
        "vehicleCount": safe_int(event.get("vehicleCount"), 0),
        "confidence": safe_float(event.get("confidence"), 0.9),

        # --- 环境与场景（补充默认值） ---
        "weather": event.get("weather", "clear"),
        "timePeriod": event.get("timePeriod", "off_peak"),
        "isMainRoad": event.get("isMainRoad", False),
        "nearbySchool": event.get("nearbySchool", False),
        "nearbyHospital": event.get("nearbyHospital", False),
    }

    return standardized
