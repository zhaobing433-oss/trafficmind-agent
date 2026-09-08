"""Paths and environment for the isolated Qiantang Pilot demo runtime."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEMO_PACK_DIR = BACKEND_DIR / "data" / "pilot_demo" / "qt_by_xiasha_pilot_001"
DEFAULT_RUNTIME_DIR = DEMO_PACK_DIR / "runtime"


def demo_environment(runtime_dir: Path = DEFAULT_RUNTIME_DIR) -> Dict[str, str]:
    root = runtime_dir.resolve()
    return {
        "QIANTANG_DEMO": "1",
        "TRAFFICMIND_DB_PATH": str(root / "trafficmind_demo.db"),
        "RAG_V2_DB_PATH": str(root / "rag" / "rag_v2.db"),
        "RAG_V2_FTS_PATH": str(root / "rag" / "rag_v2_fts.db"),
        "RAG_V2_VECTOR_DB_PATH": str(root / "vector"),
        "RAG_V2_COLLECTION_NAME": "trafficmind_qiantang_demo",
        "RAG_EMBEDDING_MODEL": "Qwen/Qwen3-Embedding-0.6B",
        "RAG_ALLOW_HASH_FALLBACK": "false",
        "DEEPSEEK_API_KEY": "",
        "WECHAT_WEBHOOK_URL": "",
        "DINGTALK_WEBHOOK_URL": "",
        "SMTP_HOST": "",
        "SMTP_TO": "",
    }


def configure_demo_environment(runtime_dir: Path = DEFAULT_RUNTIME_DIR) -> Dict[str, str]:
    values = demo_environment(runtime_dir)
    for key, value in values.items():
        os.environ[key] = value
    return values


def ensure_isolated_runtime(runtime_dir: Path) -> Path:
    root = runtime_dir.resolve()
    demo_parent = DEMO_PACK_DIR.resolve()
    if root != demo_parent and demo_parent not in root.parents:
        raise ValueError(f"demo runtime must remain under {demo_parent}")
    production_db = (BACKEND_DIR / "data" / "trafficmind.db").resolve()
    if (root / "trafficmind_demo.db").resolve() == production_db:
        raise ValueError("demo runtime cannot use the production database")
    return root
