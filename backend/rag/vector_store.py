import os, json
from datetime import datetime
from typing import Dict, Any, List, Optional
from backend.config import _BACKEND_DIR

VECTOR_DB_PATH = str(_BACKEND_DIR / "data" / "vector_db")
_CHROMA_AVAILABLE = False
try:
    import chromadb
    _CHROMA_AVAILABLE = True
except: pass

def get_chroma_client():
    if not _CHROMA_AVAILABLE: return None
    import chromadb; os.makedirs(VECTOR_DB_PATH, exist_ok=True)
    return chromadb.PersistentClient(path=VECTOR_DB_PATH)

def get_collection(name="trafficmind_knowledge"):
    if not _CHROMA_AVAILABLE: return None
    try: return get_chroma_client().get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})
    except: return None

def rebuild_collection(name="trafficmind_knowledge"):
    if not _CHROMA_AVAILABLE: return None
    try: get_chroma_client().delete_collection(name)
    except: pass
    return get_collection(name)

def add_documents(docs, metas, ids, collection_name="trafficmind_knowledge"):
    c = get_collection(collection_name)
    if c is None: return False
    try: c.add(documents=docs, metadatas=metas, ids=ids); return True
    except Exception as e: print(f"[VS] add err: {e}"); return False

def search_similar(query, limit=5, where=None, collection_name="trafficmind_knowledge"):
    c = get_collection(collection_name)
    if c is None: return []
    try:
        results = c.query(query_texts=[query], n_results=limit, where=where)
        if not results.get("ids") or not results["ids"][0]: return []
        return [{"id": results["ids"][0][i], "content": results["documents"][0][i],
                 "metadata": results["metadatas"][0][i],
                 "score": round(1.0 - results["distances"][0][i], 4)} for i in range(len(results["ids"][0]))]
    except: return []

def get_collection_stats(collection_name="trafficmind_knowledge"):
    if not _CHROMA_AVAILABLE: return {"enabled": False, "reason": "ChromaDB not installed"}
    c = get_collection(collection_name)
    if c is None: return {"enabled": False, "reason": "Collection unavailable"}
    try: return {"enabled": True, "collectionName": collection_name, "documentCount": c.count(),
                  "lastIndexedAt": None, "embeddingMode": "sentence_transformers"}
    except: return {"enabled": False}

def _set_last_indexed_time():
    try: open(str(_BACKEND_DIR / "data" / "vector_db" / ".last_indexed"), "w").write(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except: pass
