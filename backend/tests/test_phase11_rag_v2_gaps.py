"""Phase 11 RAG V2 — Gap Tests: Expired rule hard filter, SSE success chain, Memory Rewrite"""
import json, os, sys, pytest, hashlib, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ["RAG_ALLOW_MODEL_DOWNLOAD"] = "false"
os.environ["RAG_ALLOW_HASH_FALLBACK"] = "true"
os.environ["RAG_DEVICE"] = "cpu"

# ------------------------------------------------------------
# Deterministic Provider: guaranteed match for specific queries
# ------------------------------------------------------------
from backend.rag.v2.providers import (
    FakeEmbeddingProvider, FakeRerankerProvider,
    set_embedding_provider, set_reranker_provider, reset_providers,
)

class DeterministicEmbeddingProvider(FakeEmbeddingProvider):
    """Fake embedder: any text containing the keyword gets SAME deterministic high-score vector."""
    def __init__(self, dimension=384):
        super().__init__(dimension)
        self._keywords = set()

    def set_keyword(self, keyword: str):
        self._keywords.add(keyword)

    def embed_text(self, text: str) -> list:
        # If text contains a known keyword, produce a fixed high-similarity vector
        # The same vector is produced for BOTH query and chunk content
        for kw in self._keywords:
            if kw in text:
                # Fixed vector: first dim = 1.0, rest = 0 (normalized to [1,0,0,...])
                vec = [0.0] * self._dim
                vec[0] = 1.0
                return vec
        return super().embed_text(text)

class DeterministicRerankerProvider(FakeRerankerProvider):
    """Reranker that assigns HIGH score when query or doc contains the keyword."""
    def __init__(self):
        super().__init__()
        self._keywords = set()

    def set_keyword(self, keyword: str):
        self._keywords.add(keyword)

    def rerank(self, query, documents, top_k=25):
        scores = []
        for i, doc in enumerate(documents):
            # If doc contains the acceptance keyword, give it a very high score
            if any(kw in doc for kw in self._keywords):
                scores.append(0.95)
            else:
                scores.append(0.1)
        return scores


from fastapi.testclient import TestClient
import logging
logging.getLogger("rag.v2").setLevel(logging.WARNING)

DIM = 384

@pytest.fixture(scope="module")
def deterministic_providers():
    """Set up deterministic providers for this module, clean up after."""
    emb = DeterministicEmbeddingProvider(dimension=DIM)
    rr = DeterministicRerankerProvider()
    set_embedding_provider(emb)
    set_reranker_provider(rr)
    yield emb, rr
    reset_providers()

@pytest.fixture(scope="module", autouse=True)
def save_restore_active_collection():
    """Save active index version before tests, restore after."""
    from backend.rag.v2.document_repository import get_latest_index_version
    from backend.rag.v2.document_repository import _get_conn as repo_conn
    saved = get_latest_index_version()
    saved_id = saved.version_id if saved else None
    yield
    # Restore previous active version
    if saved_id:
        conn = repo_conn()
        try:
            # Re-activate the saved version
            conn.execute(
                "UPDATE rag_index_versions SET status='active' WHERE version_id=?",
                (saved_id,)
            )
            # Mark others as superseded
            conn.execute(
                "UPDATE rag_index_versions SET status='superseded' WHERE version_id!=? AND status='active'",
                (saved_id,)
            )
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()

@pytest.fixture(scope="module")
def client(deterministic_providers):
    from backend.app import app
    with TestClient(app) as c:
        yield c

# ------------------------------------------------------------
# Fixture setup
# ------------------------------------------------------------
KEY_EXP = "ZACCEPT_EXPIRED_HARD_FILTER"
KEY_SSE = "ZACCEPT_SSE_SUCCESS_122_120"

@pytest.fixture(scope="module")
def indexed_fixtures(client, deterministic_providers):
    from backend.rag.v2.document_repository import upsert_document, soft_delete_document
    from backend.rag.v2.indexer import IncrementalIndexer
    from backend.rag.v2.models import RagDocument, DocStatus, DocType, AuthorityLevel
    from backend.rag.v2.providers import get_embedding_provider
    from backend.rag.v2.chunker import TrafficKnowledgeChunker

    index_emb = get_embedding_provider()
    chunker = TrafficKnowledgeChunker(child_min_chars=30, child_max_chars=200,
                                       parent_min_chars=100, parent_max_chars=500, overlap_chars=20)

    # --- Expired rules ---
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    past_date = (now - timedelta(days=365*3)).isoformat()
    expired_date = (now - timedelta(days=365)).isoformat()
    future_date = (now + timedelta(days=365)).isoformat()

    old_rule = RagDocument(
        document_id="acc_hard_old", source_id="acc:hard:old",
        doc_type=DocType.RULE, title=f"{KEY_EXP} 旧版施工占道规则",
        content=f"""## {KEY_EXP} 旧版施工占道处置规则
第一条 {KEY_EXP} 旧版施工占道单位需提前3天报备，仅设警示标志。
第二条 本规则已于三年前失效，不再适用于现行施工占道管理。
关键词 {KEY_EXP} 确保BM25精确匹配旧版。""",
        authority_level=AuthorityLevel.OPERATIONAL, version=1,
        effective_from=past_date, effective_to=expired_date,
        status=DocStatus.ACTIVE, checksum="acc_hard_old",
    )
    new_rule = RagDocument(
        document_id="acc_hard_new", source_id="acc:hard:new",
        doc_type=DocType.RULE, title=f"{KEY_EXP} 新版施工占道规则",
        content=f"""## {KEY_EXP} 新版施工占道处置规则
第一条 {KEY_EXP} 新版施工占道单位需提前7天审批，必须设隔离设施。
第二条 本规则长期有效，取代旧版规则。
关键词 {KEY_EXP} 确保BM25精确匹配新版。""",
        authority_level=AuthorityLevel.OFFICIAL, version=2,
        effective_from=past_date, effective_to=None,
        status=DocStatus.ACTIVE, checksum="acc_hard_new",
    )

    # --- SSE success rule ---
    sse_rule = RagDocument(
        document_id="acc_sse_success", source_id="acc:sse:success",
        doc_type=DocType.RULE, title=f"{KEY_SSE} 122和120联动规则",
        content=f"""## {KEY_SSE} 122和120联动处置要求
第一条 {KEY_SSE} 122事故处理中心负责现场交通管制和车辆疏导工作。
第二条 {KEY_SSE} 120急救中心负责伤员急救和快速转运。
第三条 指挥中心统一调度122和120资源，优先保障急救车辆通行。
验收关键词 {KEY_SSE} 确保BM25和Deterministic检索。""",
        authority_level=AuthorityLevel.OFFICIAL, version=1,
        effective_from=past_date, effective_to=None,
        status=DocStatus.ACTIVE, checksum="acc_sse_success",
    )

    all_docs = [old_rule, new_rule, sse_rule]
    for d in all_docs:
        try: soft_delete_document(d.document_id)
        except: pass
        upsert_document(d)

    indexer = IncrementalIndexer(index_emb, chunker=chunker)
    job = indexer.index_documents(all_docs)
    print(f"  Indexed {job.documents_processed} docs, {job.chunks_upserted} chunks")

    # Set up deterministic matching for SSE success fixture
    # Same keyword appears in BOTH query and chunk content → guaranteed match
    det_emb, det_rr = deterministic_providers
    det_emb.set_keyword(KEY_SSE)
    det_rr.set_keyword(KEY_SSE)

    yield {"KEY_EXP": KEY_EXP, "KEY_SSE": KEY_SSE,
           "old_id": "acc_hard_old", "new_id": "acc_hard_new",
           "sse_id": "acc_sse_success", "sse_chunk_id": "acc_sse_success_p0"}

    # Cleanup
    for d in all_docs:
        try: soft_delete_document(d.document_id)
        except: pass


# ------------------------------------------------------------
# TEST 1: Expired rule hard filter
# ------------------------------------------------------------
class TestExpiredHardFilter:
    def test_old_rejected_new_accepted(self, client, indexed_fixtures):
        KEY = indexed_fixtures["KEY_EXP"]
        old_id = indexed_fixtures["old_id"]
        new_id = indexed_fixtures["new_id"]

        # Search: both should appear
        resp = client.post("/rag/v2/search", json={"query": f"{KEY} 施工占道处置", "top_k": 10})
        assert resp.status_code == 200
        results = resp.json().get("results", [])
        old_in_init = any(r.get("document_id") == old_id for r in results)
        new_in_init = any(r.get("document_id") == new_id for r in results)
        assert old_in_init, f"Old rule not in initial (n={len(results)})"
        assert new_in_init, f"New rule not in initial (n={len(results)})"

        # Ask: old must NOT be in evidence
        resp = client.post("/rag/v2/ask", json={"question": f"{KEY} 施工占道处置规范"})
        assert resp.status_code == 200
        body = resp.json()
        evidence = body.get("evidence", [])
        ev_docs = [e.get("document_id", "") for e in evidence]
        assert old_id not in ev_docs, f"Old rule in evidence: {ev_docs}"
        assert new_id in ev_docs, f"New rule not in evidence: {ev_docs}"

    def test_rejected_record_in_trace(self, client, indexed_fixtures):
        KEY = indexed_fixtures["KEY_EXP"]
        old_id = indexed_fixtures["old_id"]

        resp = client.post("/rag/v2/ask", json={"question": f"{KEY} 施工占道处置规范"})
        body = resp.json()
        trace_id = body.get("trace_id", "")
        assert trace_id

        resp = client.get(f"/rag/v2/traces/{trace_id}")
        assert resp.status_code == 200
        trace = resp.json()

        rr_stage = None
        for s in trace.get("stages", []):
            if s.get("stage") == "rerank_and_policy":
                rr_stage = s
                break
        assert rr_stage is not None, "No rerank_and_policy stage"
        out = rr_stage.get("output", {})
        assert out.get("accepted", 0) > 0
        assert out.get("rejected", 0) > 0

    def test_final_evidence_excludes_expired(self, client, indexed_fixtures):
        KEY = indexed_fixtures["KEY_EXP"]
        old_id = indexed_fixtures["old_id"]
        new_id = indexed_fixtures["new_id"]

        resp = client.post("/rag/v2/ask", json={"question": f"{KEY} 施工占道处置规范"})
        body = resp.json()
        evidence = body.get("evidence", [])
        ev_docs = [e.get("document_id", "") for e in evidence]
        assert old_id not in ev_docs
        assert new_id in ev_docs


# ------------------------------------------------------------
# TEST 2: SSE Success Chain (deterministic provider)
# ------------------------------------------------------------
class TestSSESuccessChain:
    def test_success_chain_events(self, client, indexed_fixtures):
        KEY = indexed_fixtures["KEY_SSE"]
        sse_id = indexed_fixtures["sse_id"]
        sse_chunk = indexed_fixtures["sse_chunk_id"]

        resp = client.post("/rag/v2/ask/stream", json={"question": f"{KEY} 122 120 联动处置"})
        assert resp.status_code == 200

        events = []
        buf = b""; en = None
        for chunk in resp.iter_bytes():
            buf += chunk
            while b"\n\n" in buf:
                blk, buf = buf.split(b"\n\n", 1)
                for line in blk.decode("utf-8", errors="replace").split("\n"):
                    s = line.strip()
                    if s.startswith("event: "): en = s[7:]
                    elif s.startswith("data: "):
                        try: ev = json.loads(s[6:]); ev["_en"] = en or "?"; events.append(ev)
                        except: events.append({"_en": en or "?"})

        names = [e.get("_en", "") for e in events]
        counts = {n: names.count(n) for n in set(names)}
        print(f"  Events: {names}")
        print(f"  Counts: {counts}")

        # All events present exactly once
        assert counts.get("rag_route_done", 0) == 1, f"route_done={counts.get('rag_route_done')}"
        assert counts.get("rag_query_rewritten", 0) == 1
        assert counts.get("rag_candidates_retrieved", 0) == 1
        assert counts.get("rag_rerank_done", 0) == 1
        assert counts.get("rag_evidence_selected", 0) == 1
        assert counts.get("rag_trace_ready", 0) == 1
        assert counts.get("done", 0) == 1
        assert counts.get("delta", 0) >= 1, f"delta={counts.get('delta')}"
        assert counts.get("error", 0) == 0
        assert counts.get("rag_abstained", 0) == 0

    def test_success_evidence_and_citation(self, client, indexed_fixtures):
        KEY = indexed_fixtures["KEY_SSE"]
        sse_chunk = indexed_fixtures["sse_chunk_id"]

        resp = client.post("/rag/v2/ask/stream", json={"question": f"{KEY} 122 120 联动处置"})
        events = []
        buf = b""; en = None
        for chunk in resp.iter_bytes():
            buf += chunk
            while b"\n\n" in buf:
                blk, buf = buf.split(b"\n\n", 1)
                for line in blk.decode("utf-8", errors="replace").split("\n"):
                    s = line.strip()
                    if s.startswith("event: "): en = s[7:]
                    elif s.startswith("data: "):
                        try: ev = json.loads(s[6:]); ev["_en"] = en or "?"; events.append(ev)
                        except: events.append({"_en": en or "?"})

        de = next((e for e in events if e.get("_en") == "done"), {})
        evidence = de.get("evidence", [])
        assert len(evidence) > 0, "No evidence in done event"
        e1 = next((e for e in evidence if e.get("evidence_id") == "E1"), None)
        assert e1 is not None, "E1 not found in evidence"
        assert e1.get("chunk_id") == sse_chunk, f"E1 chunk_id mismatch: {e1.get('chunk_id')}"

        ans = de.get("answer", "")
        assert "[E1]" in ans, f"[E1] not in answer: {ans[:80]}"
        assert de.get("abstained") is not True
        assert de.get("evidence_state") == "sufficient", f"state={de.get('evidence_state')}"

    def test_sse_trace_consistency(self, client, indexed_fixtures):
        KEY = indexed_fixtures["KEY_SSE"]

        resp = client.post("/rag/v2/ask/stream", json={"question": f"{KEY} 122 120 联动处置"})
        events = []
        buf = b""; en = None
        for chunk in resp.iter_bytes():
            buf += chunk
            while b"\n\n" in buf:
                blk, buf = buf.split(b"\n\n", 1)
                for line in blk.decode("utf-8", errors="replace").split("\n"):
                    s = line.strip()
                    if s.startswith("event: "): en = s[7:]
                    elif s.startswith("data: "):
                        try: ev = json.loads(s[6:]); ev["_en"] = en or "?"; events.append(ev)
                        except: events.append({"_en": en or "?"})

        de = next((e for e in events if e.get("_en") == "done"), {})
        sse_evidence = de.get("evidence", [])
        sse_e1 = next((e for e in sse_evidence if e.get("evidence_id") == "E1"), {})
        trace_id = de.get("trace_id", de.get("traceId", ""))

        if trace_id:
            resp = client.get(f"/rag/v2/traces/{trace_id}")
            assert resp.status_code == 200
            trace_evidence_total = resp.json().get("evidence_total", -1)
            assert trace_evidence_total == len(sse_evidence), \
                f"SSE evidence={len(sse_evidence)}, trace evidence={trace_evidence_total}"


# ------------------------------------------------------------
# TEST 3: Memory Rewrite (already passing, kept for completeness)
# ------------------------------------------------------------
class TestMemoryRewrite:
    def test_scenario1_renminlu_school(self):
        from backend.rag.v2.query_analyzer import RagQueryAnalyzer
        from backend.rag.v2.query_rewriter import RagQueryRewriter
        analyzer = RagQueryAnalyzer()
        rewriter = RagQueryRewriter()
        analysis = analyzer.analyze("继续查询适用的学生疏导预案")
        memory = {
            "road.name": {"memory_id": "m1", "value": "人民路小学", "status": "active", "memory_type": "stable_fact"},
            "event.type": {"memory_id": "m2", "value": "拥堵", "status": "active", "memory_type": "stable_fact"},
            "school.nearby": {"memory_id": "m3", "value": True, "status": "active", "memory_type": "stable_fact"},
            "avgSpeed": {"memory_id": "mbad", "value": 8.0, "status": "temporary_fact", "memory_type": "temporary_fact"},
        }
        ev = {"eventType": "拥堵", "roadName": "人民路", "nearbySchool": True}
        evb = dict(ev)
        r = rewriter.rewrite("继续查询适用的学生疏导预案", analysis, memory_context=memory, event_info=ev)
        assert "人民路" in r
        assert ("学校" in r or "nearbySchool" in r)
        assert "8km" not in r
        assert ev == evb

    def test_scenario2_zhongshanlu_correction(self):
        from backend.rag.v2.query_analyzer import RagQueryAnalyzer
        from backend.rag.v2.query_rewriter import RagQueryRewriter
        analyzer = RagQueryAnalyzer()
        rewriter = RagQueryRewriter()
        analysis = analyzer.analyze("继续检索适用预案")
        memory = {
            "road.name": {"memory_id": "m4", "value": "中山路", "status": "active", "memory_type": "stable_fact"},
            "user.correction": {"memory_id": "mc", "value": "corrected from 人民路", "status": "confirmed", "memory_type": "user_correction"},
        }
        ev = {"eventType": "拥堵", "roadName": "中山路"}
        evb = dict(ev)
        r = rewriter.rewrite("继续检索适用预案", analysis, memory_context=memory, event_info=ev)
        assert "中山路" in r
        assert "人民路" not in r
        assert ev == evb
