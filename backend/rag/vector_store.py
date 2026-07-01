"""
向量数据库封装
-----------
基于 ChromaDB 实现本地向量存储与检索。
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from backend.config import _BACKEND_DIR

# 向量库路径
VECTOR_DB_PATH = str(_BACKEND_DIR / "data" / "vector_db")

# Chroma 是否可用
_CHROMA_AVAILABLE = False
_CHROMA_CLIENT = None
_COLLECTION = None

try:
    import chromadb
    from chromadb.config import Settings

    _CHROMA_AVAILABLE = True
except ImportError:
    print("[VectorStore] ChromaDB 未安装，向量检索不可用。安装: pip install chromadb")


def get_chroma_client():
    """获取 ChromaDB 客户端（惰性初始化）。"""
    global _CHROMA_CLIENT
    if not _CHROMA_AVAILABLE:
        return None
    if _CHROMA_CLIENT is None:
        os.makedirs(VECTOR_DB_PATH, exist_ok=True)
        _CHROMA_CLIENT = chromadb.PersistentClient(path=VECTOR_DB_PATH)
    return _CHROMA_CLIENT


def get_collection(name: str = "trafficmind_knowledge"):
    """获取或创建 collection。"""
    global _COLLECTION
    if not _CHROMA_AVAILABLE:
        return None
    client = get_chroma_client()
    if client is None:
        return None
    try:
        _COLLECTION = client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        print(f"[VectorStore] 获取 collection 失败: {e}")
        _COLLECTION = None
    return _COLLECTION


def rebuild_collection(name: str = "trafficmind_knowledge"):
    """删除并重建 collection。"""
    global _COLLECTION
    if not _CHROMA_AVAILABLE:
        return None
    client = get_chroma_client()
    if client is None:
        return None
    try:
        client.delete_collection(name)
    except Exception:
        pass
    _COLLECTION = None
    return get_collection(name)


def add_documents(
    documents: List[str],
    metadatas: List[Dict[str, Any]],
    ids: List[str],
    collection_name: str = "trafficmind_knowledge",
):
    """批量添加文档到向量库。"""
    collection = get_collection(collection_name)
    if collection is None:
        return False
    try:
        collection.add(
            documents=documents,
            metadatas=metadatas,
            ids=ids,
        )
        return True
    except Exception as e:
        print(f"[VectorStore] 添加文档失败: {e}")
        return False


def search_similar(
    query: str,
    limit: int = 5,
    where: Optional[Dict[str, Any]] = None,
    collection_name: str = "trafficmind_knowledge",
) -> List[Dict[str, Any]]:
    """语义检索相似文档。"""
    collection = get_collection(collection_name)
    if collection is None:
        return []

    try:
        results = collection.query(
            query_texts=[query],
            n_results=limit,
            where=where,
        )
    except Exception as e:
        print(f"[VectorStore] 检索失败: {e}")
        return []

    if not results or not results.get("ids") or not results["ids"][0]:
        return []

    docs = []
    for i, doc_id in enumerate(results["ids"][0]):
        docs.append({
            "id": doc_id,
            "content": results["documents"][0][i] if results.get("documents") else "",
            "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
            "score": round(1.0 - results["distances"][0][i], 4) if results.get("distances") else 0.0,
        })
    return docs


def get_collection_stats(collection_name: str = "trafficmind_knowledge") -> Dict[str, Any]:
    """获取向量库状态信息。"""
    if not _CHROMA_AVAILABLE:
        return {"enabled": False, "reason": "ChromaDB 未安装"}

    collection = get_collection(collection_name)
    if collection is None:
        return {"enabled": False, "reason": "Collection 不可用"}

    try:
        count = collection.count()
        return {
            "enabled": True,
            "collectionName": collection_name,
            "documentCount": count,
            "lastIndexedAt": _get_last_indexed_time(),
            "embeddingMode": "local (sentence-transformers)",
        }
    except Exception as e:
        return {"enabled": False, "reason": str(e)}


_LAST_INDEXED_FILE = str(_BACKEND_DIR / "data" / "vector_db" / ".last_indexed")


def _get_last_indexed_time() -> Optional[str]:
    try:
        if os.path.exists(_LAST_INDEXED_FILE):
            with open(_LAST_INDEXED_FILE, "r") as f:
                return f.read().strip()
    except Exception:
        pass
    return None


def _set_last_indexed_time():
    try:
        os.makedirs(os.path.dirname(_LAST_INDEXED_FILE), exist_ok=True)
        with open(_LAST_INDEXED_FILE, "w") as f:
            f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass
