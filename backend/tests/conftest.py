"""Shared pytest fixtures for backend test isolation."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def isolated_phase11_rag_v2_env(tmp_path_factory):
    """Keep Phase 11 RAG tests out of all runtime SQLite/Chroma stores."""
    from backend import config as backend_config
    from backend.agent.collaboration import db_repository as collaboration_repository
    from backend.chat import chat_db
    from backend.rag.v2 import config as rag_config
    from backend.tools import db_tools

    temp_root = tmp_path_factory.mktemp("phase11_rag_v2")
    traffic_db = temp_root / "trafficmind.db"
    rag_db = temp_root / "rag_v2.db"
    fts_db = temp_root / "rag_v2_fts.db"
    vector_db = temp_root / "data" / "vector_db"
    vector_db.mkdir(parents=True)

    backend_root = Path(__file__).resolve().parents[1]
    production_rag_db = (backend_root / "data" / "rag_v2" / "rag_v2.db").resolve()
    production_fts_db = (backend_root / "data" / "rag_v2" / "rag_v2_fts.db").resolve()
    production_vector_db = (backend_root / "data" / "vector_db").resolve()
    production_traffic_db = (backend_root / "data" / "trafficmind.db").resolve()

    assert traffic_db.resolve() != production_traffic_db
    assert rag_db.resolve() != production_rag_db
    assert fts_db.resolve() != production_fts_db
    assert vector_db.resolve() != production_vector_db

    patcher = pytest.MonkeyPatch()
    patcher.setattr(backend_config, "DB_PATH", str(traffic_db))
    patcher.setattr(rag_config, "RAG_V2_DB_PATH", str(rag_db))
    patcher.setattr(rag_config, "RAG_V2_FTS_PATH", str(fts_db))

    # Patch modules that capture the application DB path during import.
    patcher.setattr(db_tools, "DB_PATH", str(traffic_db))
    patcher.setattr(chat_db, "DB_PATH", str(traffic_db))
    patcher.setattr(collaboration_repository, "DB_PATH", str(traffic_db))
    chat_db.reset_initialized()
    db_tools.init_db()

    # Import auto-initializing storage modules only after config points at temp.
    from backend.rag.v2 import dense_index, document_repository, sparse_index
    from backend.rag.v2.pipeline import reset_pipeline
    from backend.rag.v2.providers import reset_providers
    from backend.rag import vector_store as legacy_vector_store

    patcher.setattr(document_repository, "RAG_V2_DB_PATH", str(rag_db))
    patcher.setattr(sparse_index, "RAG_V2_FTS_PATH", str(fts_db))
    patcher.setattr(dense_index, "_VECTOR_DB_PATH", str(vector_db))

    # Phase 11 compatibility tests exercise the legacy indexer too.
    patcher.setattr(legacy_vector_store, "VECTOR_DB_PATH", str(vector_db))
    patcher.setattr(legacy_vector_store, "_BACKEND_DIR", temp_root)

    reset_pipeline()
    reset_providers()
    document_repository.init_db()
    sparse_index.init_fts()

    env = {
        "root": temp_root,
        "traffic_db": traffic_db,
        "rag_db": rag_db,
        "fts_db": fts_db,
        "vector_db": vector_db,
        "production_rag_db": production_rag_db,
        "production_fts_db": production_fts_db,
        "production_vector_db": production_vector_db,
        "production_traffic_db": production_traffic_db,
    }
    yield env

    reset_pipeline()
    reset_providers()
    chat_db.reset_initialized()
    assert Path(backend_config.DB_PATH).resolve() == traffic_db.resolve()
    assert Path(db_tools.DB_PATH).resolve() == traffic_db.resolve()
    assert Path(chat_db.DB_PATH).resolve() == traffic_db.resolve()
    assert Path(collaboration_repository.DB_PATH).resolve() == traffic_db.resolve()
    assert Path(document_repository.RAG_V2_DB_PATH).resolve() == rag_db.resolve()
    assert Path(sparse_index.RAG_V2_FTS_PATH).resolve() == fts_db.resolve()
    assert Path(dense_index._get_vector_db_path()).resolve() == vector_db.resolve()
    assert Path(legacy_vector_store.VECTOR_DB_PATH).resolve() == vector_db.resolve()
    patcher.undo()
    document_repository.RAG_V2_DB_PATH = rag_config.RAG_V2_DB_PATH
    sparse_index.RAG_V2_FTS_PATH = rag_config.RAG_V2_FTS_PATH
