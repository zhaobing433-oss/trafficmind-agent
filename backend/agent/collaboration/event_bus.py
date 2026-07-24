"""
本地事件总线 — Phase 9.1
内存实现，设计为后续可替换为 Redis Streams / RabbitMQ。
"""

from typing import Any, Callable, Dict, List
from datetime import datetime


class InMemoryEventBus:
    """内存事件总线。后续可替换为 Redis Streams 实现。"""

    def __init__(self):
        self._history: List[Dict[str, Any]] = []
        self._subscribers: Dict[str, List[Callable]] = {}
        self._idempotency_keys: set = set()

    def publish(self, message: Dict[str, Any]):
        """发布消息。相同 message_id 的幂等保护。"""
        msg_id = message.get("message_id", "")
        if msg_id and msg_id in self._idempotency_keys:
            return  # 重复消息，跳过

        if msg_id:
            self._idempotency_keys.add(msg_id)

        # Add timestamp if missing
        if "created_at" not in message:
            message["created_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        self._history.append(message)

        # Notify subscribers
        msg_type = message.get("message_type", "*")
        for pattern, handlers in self._subscribers.items():
            if pattern == "*" or pattern == msg_type:
                for handler in handlers:
                    try:
                        handler(message)
                    except Exception as e:
                        print(f"[EventBus] handler error for {msg_type}: {e}")

    def subscribe(self, message_type: str, handler: Callable):
        """订阅特定消息类型。"""
        if message_type not in self._subscribers:
            self._subscribers[message_type] = []
        self._subscribers[message_type].append(handler)

    def get_history(self, run_id: str = "") -> List[Dict[str, Any]]:
        """获取消息历史。可按 run_id 过滤。"""
        if not run_id:
            return list(self._history)
        return [m for m in self._history if m.get("run_id") == run_id]

    def clear(self):
        """清空历史（测试用）。"""
        self._history.clear()
        self._idempotency_keys.clear()
        self._subscribers.clear()


# 全局单例（后续可替换为分布式实现）
_bus_instance: InMemoryEventBus | None = None


def get_event_bus() -> InMemoryEventBus:
    global _bus_instance
    if _bus_instance is None:
        _bus_instance = InMemoryEventBus()
    return _bus_instance
