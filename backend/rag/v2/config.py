"""
RAG V2 配置 — 所有可配置项通过环境变量覆盖。
"""
import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_RAG_DATA_DIR = _BACKEND_DIR / "data" / "rag_v2"

# --- Feature flags ---
RAG_V2_ENABLED = os.getenv("RAG_V2_ENABLED", "true").lower() == "true"

# --- Embedding ---
RAG_EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
RAG_EMBEDDING_DEVICE = os.getenv("RAG_DEVICE", "auto")  # "cpu", "cuda", "auto"
RAG_EMBEDDING_BATCH_SIZE = int(os.getenv("RAG_BATCH_SIZE", "32"))

# --- Reranker ---
RAG_RERANKER_MODEL = os.getenv("RAG_RERANKER_MODEL", "Qwen/Qwen3-Reranker-0.6B")
RAG_RERANKER_DEVICE = os.getenv("RAG_DEVICE", "auto")

# --- Model download ---
RAG_ALLOW_MODEL_DOWNLOAD = os.getenv("RAG_ALLOW_MODEL_DOWNLOAD", "true").lower() == "true"
RAG_ALLOW_HASH_FALLBACK = os.getenv("RAG_ALLOW_HASH_FALLBACK", "false").lower() == "true"
RAG_MODEL_CACHE_DIR = os.getenv("RAG_MODEL_CACHE_DIR", "")

# --- Retrieval ---
RAG_DENSE_TOP_K = int(os.getenv("RAG_DENSE_TOP_K", "30"))
RAG_SPARSE_TOP_K = int(os.getenv("RAG_SPARSE_TOP_K", "30"))
RAG_STRUCTURED_TOP_K = int(os.getenv("RAG_STRUCTURED_TOP_K", "15"))
RAG_RERANK_TOP_K = int(os.getenv("RAG_RERANK_TOP_K", "25"))
RAG_EVIDENCE_TOP_K = int(os.getenv("RAG_EVIDENCE_TOP_K", "6"))

# --- RRF ---
RAG_RRF_K = int(os.getenv("RAG_RRF_K", "60"))
RAG_RRF_WINDOW = int(os.getenv("RAG_RRF_WINDOW", "40"))

# --- Context ---
RAG_MAX_CONTEXT_TOKENS = int(os.getenv("RAG_MAX_CONTEXT_TOKENS", "4096"))

# --- Timeout (Phase 16 Round 2: guarantee RAG termination) ---
RAG_STAGE_TIMEOUT_SECONDS = int(os.getenv("RAG_STAGE_TIMEOUT_SECONDS", "60"))
RAG_OVERALL_TIMEOUT_SECONDS = int(os.getenv("RAG_OVERALL_TIMEOUT_SECONDS", "120"))
# Reranker 是 optional quality-enhancement stage：超时即 fallback retrieval ranking
RAG_RERANK_TIMEOUT_SECONDS = int(os.getenv("RAG_RERANK_TIMEOUT_SECONDS", "15"))

# --- Chunking ---
RAG_CHILD_MIN_CHARS = int(os.getenv("RAG_CHILD_MIN_CHARS", "250"))
RAG_CHILD_MAX_CHARS = int(os.getenv("RAG_CHILD_MAX_CHARS", "450"))
RAG_PARENT_MIN_CHARS = int(os.getenv("RAG_PARENT_MIN_CHARS", "800"))
RAG_PARENT_MAX_CHARS = int(os.getenv("RAG_PARENT_MAX_CHARS", "1500"))
RAG_CHUNK_OVERLAP_CHARS = int(os.getenv("RAG_CHUNK_OVERLAP_CHARS", "80"))

# --- Chroma ---
RAG_V2_COLLECTION_NAME = os.getenv("RAG_V2_COLLECTION_NAME", "trafficmind_knowledge_v2")
RAG_V2_V1_COLLECTION_NAME = "trafficmind_knowledge"  # Legacy V1 collection, never deleted

# --- SQLite paths ---
RAG_V2_DB_PATH = str(_RAG_DATA_DIR / "rag_v2.db")
RAG_V2_FTS_PATH = str(_RAG_DATA_DIR / "rag_v2_fts.db")

# --- Agent ---
RAG_AGENT_MAX_EVIDENCE = int(os.getenv("RAG_AGENT_MAX_EVIDENCE", "4"))

# --- Evaluation ---
RAG_EVAL_ENABLED = os.getenv("RAG_EVAL_ENABLED", "true").lower() == "true"

# Ensure data dir exists
_RAG_DATA_DIR.mkdir(parents=True, exist_ok=True)
