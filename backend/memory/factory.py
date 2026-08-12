"""
Memory V2 Repository Factory — Phase 10 可移植加固

根据配置选择存储后端。
当前仅支持 SQLite，PostgreSQL 预留 Phase 11。

Usage:
    from backend.memory.factory import create_memory_repository
    repo = create_memory_repository()
"""

import os
from backend.memory.repository import MemoryStore


def create_memory_repository() -> MemoryStore:
    """根据 MEMORY_STORAGE_BACKEND 配置创建 MemoryStore 实例。

    环境变量：
        MEMORY_STORAGE_BACKEND: 存储后端 (sqlite | postgres)
        MEMORY_DATABASE_URL:     数据库连接串（PostgreSQL 需要）

    Returns:
        MemoryStore 实现实例。

    Raises:
        NotImplementedError: 当 backend=postgres 且尚未实现时。
        ValueError: 当 backend 值不合法时。
    """
    backend = os.getenv("MEMORY_STORAGE_BACKEND", "sqlite").lower().strip()

    if backend == "sqlite":
        from backend.memory.sqlite_repository import SQLiteMemoryRepository
        return SQLiteMemoryRepository()

    elif backend == "postgres":
        raise NotImplementedError(
            "PostgreSQL Memory backend will be implemented in Phase 11"
        )

    else:
        raise ValueError(
            f"不支持的 MEMORY_STORAGE_BACKEND: '{backend}'。"
            f"可选值: sqlite, postgres"
        )
