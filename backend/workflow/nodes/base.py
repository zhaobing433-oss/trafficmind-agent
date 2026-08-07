"""
Workflow 节点基类与注册表 — Phase 12

每个节点实现为标准接口：
  async def execute(state: TrafficWorkflowState, config: NodeConfig) -> Dict[str, Any]

节点通过 NodeRegistry 按 node_type 注册和查找。
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from backend.workflow.models import NodeConfig
from backend.workflow.state import TrafficWorkflowState

# 节点执行函数签名
NodeExecutor = Callable[
    [TrafficWorkflowState, NodeConfig],
    Any,  # 返回 Dict[str, Any]（异步函数的协程）
]


class NodeRegistry:
    """节点类型注册表。

    按 node_type 字符串查找对应的执行函数。
    """

    def __init__(self):
        self._executors: Dict[str, NodeExecutor] = {}

    def register(self, node_type: str, executor: NodeExecutor) -> None:
        """注册节点类型。

        Args:
            node_type: 节点类型字符串（如 "trigger", "agent_task"）
            executor: 节点执行函数
        """
        self._executors[node_type] = executor

    def get(self, node_type: str) -> NodeExecutor:
        """获取节点执行函数。

        Args:
            node_type: 节点类型字符串

        Returns:
            节点执行函数

        Raises:
            KeyError: 节点类型未注册
        """
        if node_type not in self._executors:
            raise KeyError(
                f"未注册的节点类型: '{node_type}'。"
                f"已注册: {list(self._executors.keys())}"
            )
        return self._executors[node_type]

    def has(self, node_type: str) -> bool:
        """检查节点类型是否已注册。"""
        return node_type in self._executors

    def list_types(self):
        """列出所有已注册的节点类型。"""
        return list(self._executors.keys())


# 全局单例
_registry: NodeRegistry | None = None


def get_node_registry() -> NodeRegistry:
    """获取全局节点注册表单例。"""
    global _registry
    if _registry is None:
        _registry = NodeRegistry()
    return _registry
