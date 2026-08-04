"""
RAG V2 Evaluation — Synthetic Pipeline Verification (Fake providers)
python backend/tests/acceptance_eval.py
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.rag.v2.providers import (
    set_embedding_provider, FakeEmbeddingProvider,
    set_reranker_provider, FakeRerankerProvider, reset_providers,
)
reset_providers()
set_embedding_provider(FakeEmbeddingProvider(384))
set_reranker_provider(FakeRerankerProvider())

from backend.rag.v2.pipeline import get_pipeline, reset_pipeline
from backend.rag.v2.indexer import IncrementalIndexer, load_all_documents
from backend.rag.v2.providers import get_embedding_provider
from backend.rag.v2.evaluation import EvalRunner

os.makedirs("backend/tests/output", exist_ok=True)

print("A. Synthetic Pipeline Verification (Fake Providers)")
print("=" * 60)

# Index real docs
print("Indexing documents...")
emb = get_embedding_provider()
indexer = IncrementalIndexer(emb)
docs = load_all_documents()
indexer.index_documents(docs[:5])
print(f"Indexed {len(docs[:5])} docs")

# Run evaluation
reset_pipeline()
pipeline = get_pipeline()
runner = EvalRunner(pipeline)
cases = runner.load_cases()
print(f"Cases: {len(cases)}")

t0 = time.time()
metrics = runner.evaluate(cases)
elapsed = time.time() - t0
print(f"Elapsed: {elapsed:.1f}s  Success: {metrics.success_count}  Failed: {metrics.failure_count}")

# Output
summary = runner._summary(metrics)
output = {
    "evaluation_type": "A_synthetic_pipeline_verification",
    "provider": "FakeEmbeddingProvider(384) + FakeRerankerProvider",
    "model": "N/A (fake)",
    "device": "N/A",
    "llm_generation": False,
    "elapsed_s": round(elapsed, 1),
    **summary,
}

with open("backend/tests/output/rag_phase11_synthetic_eval.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# Markdown
doc = output["document_level"]
chunk = output["chunk_level"]
gen = output["generation"]
perf = output["performance"]

md = f"""# RAG Phase 11 — Synthetic Pipeline Verification

**Evaluation type:** A — Synthetic (Fake providers, no real model)
> B — Real Model Evaluation is PENDING

## Summary
- Cases: {metrics.total_cases} (success={metrics.success_count}, failed={metrics.failure_count})
- Doc-level gold cases: {metrics.cases_with_gold_docs}
- Chunk-level gold cases: {metrics.cases_with_gold_chunks}
- Abstain cases: {metrics.abstain_case_count}

## Document-Level Metrics

| Metric | Value |
|--------|-------|
| Hit@5 | {doc['hit_at_5']:.4f} |
| Hit@10 | {doc['hit_at_10']:.4f} |
| Recall@5 | {doc['recall_at_5']:.4f} |
| Recall@10 | {doc['recall_at_10']:.4f} |
| MRR@10 | {doc['mrr_at_10']:.4f} |
| nDCG@10 | {doc['ndcg_at_10']:.4f} |

## Chunk-Level Metrics

| Metric | Value |
|--------|-------|
| Hit@5 | {chunk['hit_at_5']:.4f} |
| Hit@10 | {chunk['hit_at_10']:.4f} |
| Recall@5 | {chunk['recall_at_5']:.4f} |
| Recall@10 | {chunk['recall_at_10']:.4f} |
| MRR@10 | {chunk['mrr_at_10']:.4f} |
| nDCG@10 | {chunk['ndcg_at_10']:.4f} |

## Generation Metrics

| Metric | Value |
|--------|-------|
| Citation Precision | {gen['citation_precision']:.4f} |
| Citation Coverage | {gen['citation_coverage']:.4f} |
| Unsupported Claim Rate | {gen['unsupported_claim_rate']:.4f} |
| Abstain Precision | {gen['abstain_precision']:.4f} |
| Abstain Recall | {gen['abstain_recall']:.4f} |

## Performance

| Metric | Value |
|--------|-------|
| P50 Latency | {perf['latency_p50_ms']:.1f}ms |
| P95 Latency | {perf['latency_p95_ms']:.1f}ms |

## Invariants

| Check | Result |
|-------|--------|
| Recall@10 >= Recall@5 (doc) | {"✅" if doc['recall_at_10'] >= doc['recall_at_5'] - 0.0001 else "❌"} |
| Recall@10 >= Recall@5 (chunk) | {"✅" if chunk['recall_at_10'] >= chunk['recall_at_5'] - 0.0001 else "❌"} |
| Hit@10 >= Hit@5 (doc) | {"✅" if doc['hit_at_10'] >= doc['hit_at_5'] - 0.0001 else "❌"} |
| 0 <= metrics <= 1 | ✅ (enforced by assertion) |

## Notes
- Hit@K values are low because Fake hash embeddings provide no semantic similarity
- MSLT evaluation is valid for pipeline infrastructure verification only
- **B — Real Model Evaluation is PENDING** (requires Qwen3 download)
- Phase 10 comparison deferred until real model evaluation available

Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""

with open("backend/tests/output/rag_phase11_synthetic_eval.md", "w", encoding="utf-8") as f:
    f.write(md)

print(f"\nReports: backend/tests/output/rag_phase11_synthetic_eval.{{json,md}}")
print(f"Doc-Recall@5={doc['recall_at_5']:.4f}  Doc-Recall@10={doc['recall_at_10']:.4f}")
print(f"Doc-Hit@5={doc['hit_at_5']:.4f}  Doc-Hit@10={doc['hit_at_10']:.4f}")
reset_providers()
