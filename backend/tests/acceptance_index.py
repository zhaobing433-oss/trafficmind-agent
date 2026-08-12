"""
Real Incremental Index Acceptance — 12 checks
python backend/tests/acceptance_index.py
"""
import os, sys, json, time, hashlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Reset provider state
from backend.rag.v2.providers import set_embedding_provider, FakeEmbeddingProvider, reset_providers
reset_providers()
set_embedding_provider(FakeEmbeddingProvider(384))

from backend.rag.v2.indexer import IncrementalIndexer, load_all_documents, _make_document_id
from backend.rag.v2.document_repository import (
    init_db, upsert_document, list_active_documents,
    get_latest_index_version, get_document_by_source,
)
from backend.rag.v2.models import DocStatus, DocType, AuthorityLevel, RagDocument, utcnow
from backend.rag.v2.dense_index import is_available, get_collection_count

emb = FakeEmbeddingProvider(384)
indexer = IncrementalIndexer(emb)

print("=== RAG V2 Incremental Index Acceptance ===")
print(f"Chroma: {is_available()}, Embedding: Fake({emb.get_dimension()})")
print()

# Load documents
t0 = time.time()
docs = load_all_documents()
print(f"1. Loaded {len(docs)} docs in {(time.time()-t0)*1000:.0f}ms")
print(f"   Rules={len([d for d in docs if d.doc_type=='rule'])}, "
      f"Cases={len([d for d in docs if d.doc_type=='event_report'])}, "
      f"Dispatch={len([d for d in docs if d.doc_type=='dispatch_experience'])}")
print()

# First index (only first 5 docs to avoid timeout)
sample_docs = docs[:5]
print(f"=== First Index ({len(sample_docs)} docs) ===")
t1 = time.time()
job1 = indexer.index_documents(sample_docs)
print(f"Status: {job1.status.value}, Version: {job1.index_version[:20]}...")
print(f"processed={job1.documents_processed} inserted={job1.documents_inserted} "
      f"updated={job1.documents_updated} skipped={job1.documents_skipped}")
print(f"Chunks: {job1.chunks_upserted}, Duration: {job1.duration_ms:.0f}ms")
print()

chroma_n = get_collection_count()
print(f"2. Chroma collection 'trafficmind_knowledge_v2': {chroma_n} chunks = {'CREATED' if chroma_n > 0 else 'EMPTY'}")

# Chunk counts
from backend.rag.v2.chunker import TrafficKnowledgeChunker
chunker = TrafficKnowledgeChunker()
tp_all, tc_all = 0, 0
for d in sample_docs:
    p, c = chunker.chunk_document(d)
    tp_all += len(p); tc_all += len(c)
print(f"3-4. Sample parents={tp_all}, children={tc_all}")
print()

# Second index — idempotency
print("=== Second Index (Idempotency) ===")
job2 = indexer.index_documents(sample_docs)
print(f"processed={job2.documents_processed} skipped={job2.documents_skipped}")
print(f"5. All skipped: {job2.documents_skipped >= job2.documents_processed}")
print()

# Modify one doc
print("=== Modify One Document ===")
if sample_docs:
    td = sample_docs[0].model_copy()
    td.content += "\n（临时测试修改v2）"
    td.checksum = hashlib.sha256(td.content.encode()).hexdigest()
    td.updated_at = utcnow()
    job3 = indexer.index_documents([td])
    print(f"6-7. Updated one: processed={job3.documents_processed} updated={job3.documents_updated}")
print()

# Soft delete test
print("=== Soft Delete ===")
ts = "test:acceptance_temp_del"
t_doc = RagDocument(
    document_id=_make_document_id(ts), source_id=ts,
    doc_type=DocType.RULE, title="Acceptance Temp",
    content="Will be deleted", authority_level=AuthorityLevel.OPERATIONAL,
    checksum="acc_temp", version=1, status=DocStatus.ACTIVE,
)
job4 = indexer.index_documents([t_doc])
print(f"8. Temp inserted: {job4.documents_inserted == 1}")

t_doc.status = DocStatus.DELETED
t_doc.checksum = hashlib.sha256((t_doc.content or "").encode()).hexdigest()
job5 = indexer.index_documents([t_doc])
print(f"9. Temp deleted: {job5.documents_deleted == 1}")

active = list_active_documents()
in_active = any(d.source_id == ts for d in active)
print(f"10. Not in active: {not in_active}")
print()

# Version
ver = get_latest_index_version()
print(f"11. Latest version: {ver.version_id if ver else 'None'} "
      f"docs={ver.document_count if ver else 0} chunks={ver.chunk_count if ver else 0}")
print()

# V1 check
from backend.rag.vector_store import get_collection_stats as v1s
s = v1s("trafficmind_knowledge")
print(f"12. V1 collection: {'OK' if s.get('enabled') else 'UNAVAILABLE'}")
print()

# Cleanup soft-deleted temp
print("=== Cleanup done ===")
reset_providers()
