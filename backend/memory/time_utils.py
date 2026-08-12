"""
Memory V2 UTC 时间工具 — Phase 10 可移植加固

所有 Memory 模块内新时间必须使用 UTC timezone-aware datetime。
兼容已有无时区测试数据，但新写入必须带 +00:00。
TTL 比较统一为 UTC。
"""

from datetime import datetime, timezone, timedelta
from typing import Optional


def utc_now() -> datetime:
    """返回当前 UTC timezone-aware datetime。"""
    return datetime.now(timezone.utc)


def to_iso_utc(dt: Optional[datetime] = None) -> str:
    """将 datetime 转换为 ISO 8601 UTC 字符串（含 +00:00 offset）。

    Args:
        dt: datetime 对象，为 None 时使用当前 UTC 时间。

    Returns:
        如 "2026-07-24T12:15:13+00:00"
    """
    dt = dt or utc_now()
    if dt.tzinfo is None:
        # 无时区视为 UTC（兼容已有数据）
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def parse_iso_datetime(s: str) -> datetime:
    """解析 ISO 时间字符串为 UTC timezone-aware datetime。

    支持格式：
    - "2026-07-24T12:15:13+00:00"
    - "2026-07-24T12:15:13Z"
    - "2026-07-24T12:15:13"  (视为 UTC)
    - "2026-07-24 12:15:13"  (旧格式，视为 UTC)

    Args:
        s: ISO 时间字符串。

    Returns:
        UTC timezone-aware datetime。
    """
    if not s:
        return utc_now()

    s = s.strip()

    # Already ISO 8601 with timezone
    if s.endswith("+00:00") or s.endswith("Z"):
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)

    # Old format "YYYY-MM-DD HH:MM:SS"
    if " " in s:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)

    # ISO without timezone
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_expired(valid_until: Optional[str], reference: Optional[str] = None) -> bool:
    """判断 valid_until 是否已过期（统一 UTC 比较）。

    Args:
        valid_until: ISO 时间字符串。
        reference: 参考时间，None 使用当前 UTC。

    Returns:
        True 表示已过期。
    """
    if not valid_until:
        return False
    ref = parse_iso_datetime(reference) if reference else utc_now()
    deadline = parse_iso_datetime(valid_until)
    return deadline <= ref
