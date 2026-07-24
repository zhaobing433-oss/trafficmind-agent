"""
Memory V2 抽象存储接口 — Phase 10 可移植加固

所有业务代码（Extractor、WriteGate、Retriever、Coordinator）必须依赖
MemoryStore 接口，不得直接 import sqlite3 或依赖具体实现。

SQLite 实现见 sqlite_repository.py。
PostgreSQL 实现预留 Phase 11。
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional, Tuple

from backend.memory.models import MemoryItem, MemoryTrace


class MemoryTransaction:
    """事务句柄。

    SQLite 实现内部持有一个专用连接。
    业务代码在 with 块内操作，退出时自动提交或回滚。
    """

    def commit(self) -> None:
        """显式提交事务。"""
        raise NotImplementedError

    def rollback(self) -> None:
        """显式回滚事务。"""
        raise NotImplementedError


class MemoryStore(ABC):
    """Memory V2 抽象存储契约。

    定义所有业务操作必须实现的方法签名。
    具体实现（SQLite / PostgreSQL）各自提供持久化逻辑。
    """

    # ================================================================
    # 事务
    # ================================================================

    @abstractmethod
    @contextmanager
    def transaction(self) -> Generator[MemoryTransaction, None, None]:
        """返回一个事务上下文管理器。

        Usage:
            with repo.transaction() as tx:
                repo.create_item(...)
                repo.supersede_item(...)
                # 退出时自动提交；异常时自动回滚
        """
        ...

    # ================================================================
    # Create
    # ================================================================

    @abstractmethod
    def create_item(
        self,
        memory_type: str,
        session_id: str,
        memory_key: str = "",
        value: Optional[Dict[str, Any]] = None,
        text_content: str = "",
        status: str = "candidate",
        confidence: float = 1.0,
        authority_level: int = 0,
        source_type: str = "",
        source_id: str = "",
        source_run_id: str = "",
        source_message_id: str = "",
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        supersedes_id: str = "",
        scope_type: str = "session",
        scope_id: str = "",
        item_id: Optional[str] = None,
    ) -> MemoryItem:
        """创建一条新记忆。

        幂等性：相同 dedupKey 返回已有记录，不产生重复。
        """
        ...

    # ================================================================
    # Read
    # ================================================================

    @abstractmethod
    def get_item(self, item_id: str) -> Optional[MemoryItem]:
        """按 ID 查询单条记忆。"""
        ...

    @abstractmethod
    def list_session_items(
        self,
        session_id: str,
        memory_type: Optional[str] = None,
        memory_key: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_inactive: bool = False,
    ) -> List[MemoryItem]:
        """查询 Session 的记忆列表。默认排除 rejected/superseded/expired。"""
        ...

    @abstractmethod
    def find_active_by_key(
        self, session_id: str, memory_key: str
    ) -> Optional[MemoryItem]:
        """按 session_id + memory_key 查找当前活跃的记忆。"""
        ...

    @abstractmethod
    def find_items_by_run(
        self, session_id: str, source_run_id: str
    ) -> List[MemoryItem]:
        """查找某个 Run 产生的所有记忆。"""
        ...

    @abstractmethod
    def find_duplicate(
        self,
        session_id: str,
        memory_type: str,
        memory_key: str,
        source_type: str,
        text_content: str,
    ) -> Optional[MemoryItem]:
        """幂等去重查询。"""
        ...

    @abstractmethod
    def count_session_items(self, session_id: str) -> Dict[str, int]:
        """统计 Session 的记忆数量。"""
        ...

    # ================================================================
    # Update
    # ================================================================

    @abstractmethod
    def update_item(self, item_id: str, **kwargs) -> bool:
        """更新记忆字段。"""
        ...

    @abstractmethod
    def confirm_item(self, item_id: str) -> bool:
        """标记为 confirmed。"""
        ...

    @abstractmethod
    def reject_item(self, item_id: str) -> bool:
        """标记为 rejected。"""
        ...

    @abstractmethod
    def expire_item(self, item_id: str) -> bool:
        """标记为 expired。"""
        ...

    @abstractmethod
    def supersede_item(
        self, old_item_id: str, new_item: MemoryItem
    ) -> Tuple[MemoryItem, MemoryItem]:
        """取代旧记忆，创建新记忆。旧记录标记为 superseded。"""
        ...

    @abstractmethod
    def increment_access(self, item_id: str) -> bool:
        """增加访问计数并更新 last_accessed_at。"""
        ...

    # ================================================================
    # Expiry
    # ================================================================

    @abstractmethod
    def expire_due_items(self) -> int:
        """标记所有已过期的活跃/confirmed 记忆。"""
        ...

    @abstractmethod
    def expire_session_items(self, session_id: str) -> int:
        """标记 Session 中已过期的记忆。"""
        ...

    # ================================================================
    # Trace
    # ================================================================

    @abstractmethod
    def save_trace(self, trace: MemoryTrace) -> MemoryTrace:
        """保存一条 MemoryTrace。已存在则 UPDATE（不 INSERT OR REPLACE）。"""
        ...

    @abstractmethod
    def get_trace_by_run(self, run_id: str) -> Optional[MemoryTrace]:
        """按 run_id 查询追踪。"""
        ...

    @abstractmethod
    def list_traces(
        self, session_id: str, limit: int = 20
    ) -> List[MemoryTrace]:
        """查询 Session 的 Trace 列表。"""
        ...

    # ================================================================
    # Session 清理
    # ================================================================

    @abstractmethod
    def delete_session_memory(self, session_id: str) -> int:
        """删除 Session 的所有记忆和追踪。"""
        ...
