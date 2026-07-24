"""
Memory V2 兼容导出层 — Phase 10 可移植加固

此模块保留原有导入路径兼容：
    from backend.memory.store import MemoryRepository
    from backend.memory.store import init_memory_tables

新业务代码应使用工厂：
    from backend.memory.factory import create_memory_repository
    repo = create_memory_repository()

底层实现已迁移至 sqlite_repository.py。
"""

# Re-export from new module structure for backward compatibility
from backend.memory.sqlite_repository import (
    SQLiteMemoryRepository as MemoryRepository,
    init_memory_tables,
)

__all__ = ["MemoryRepository", "init_memory_tables"]
