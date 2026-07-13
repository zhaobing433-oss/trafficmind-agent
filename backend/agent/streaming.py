"""
SSE 流式工具 — 生成标准 Server-Sent Events 格式
"""
import json
from typing import Dict, Any


def sse_event(event: str, data: Dict[str, Any]) -> str:
    """生成标准 SSE 事件字符串。"""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def sse_heartbeat() -> str:
    """心跳事件，防止长连接超时。"""
    return ": heartbeat\n\n"


def sse_error(message: str) -> str:
    """错误事件。"""
    return sse_event("error", {"message": message})
