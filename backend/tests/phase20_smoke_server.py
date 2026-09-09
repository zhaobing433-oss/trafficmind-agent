"""Phase 20 Round 1 — 隔离运行时冒烟服务器

以临时存储（temp 主 DB / temp RAG DB / temp Chroma / FakeEmbedding）启动
独立 uvicorn 实例（127.0.0.1:8091），用于运行时冒烟，绝不触碰生产
trafficmind.db / rag_v2.db / vector_db。

用法：
    backend/.venv/bin/python backend/tests/phase20_smoke_server.py
"""
import os
import sys
import tempfile

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(_BACKEND))

TMP = tempfile.mkdtemp(prefix="phase20_smoke_")
print(f"[smoke] temp dir: {TMP}")

# ── 1. 主 DB 隔离（必须在 import app 之前）──
import backend.config as cfg
cfg.DB_PATH = os.path.join(TMP, "trafficmind_smoke.db")

# ── 2. RAG V2 隔离 ──
import backend.rag.v2.config as v2_config
import backend.rag.v2.document_repository as doc_repo
v2_config.RAG_V2_DB_PATH = os.path.join(TMP, "rag_v2_smoke.db")
doc_repo.RAG_V2_DB_PATH = v2_config.RAG_V2_DB_PATH

# ── 3. Chroma 隔离 ──
import backend.rag.v2.dense_index as dense_idx
dense_idx._VECTOR_DB_PATH = os.path.join(TMP, "chroma")
dense_idx._get_vector_db_path = lambda: dense_idx._VECTOR_DB_PATH

# ── 4. Fake embedding（避免加载真实模型）──
from backend.rag.v2.providers import FakeEmbeddingProvider
_fake = FakeEmbeddingProvider(dimension=384)
import backend.rag.v2.providers as providers
providers.get_embedding_provider = lambda: _fake
import backend.knowledge.service as ks
ks.get_embedding_provider = lambda: _fake

doc_repo.init_db()

# ── 5. 导入 app（此时 import 的模块全部捕获 temp 路径）──
from backend.app import app  # noqa: E402

if __name__ == "__main__":
    import uvicorn
    print("[smoke] listening on http://127.0.0.1:8091 (isolated stores)")
    uvicorn.run(app, host="127.0.0.1", port=8091, log_level="warning")
