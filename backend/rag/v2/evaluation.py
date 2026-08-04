"""
RAG V2 Evaluation — 离线评估基准。

86 deterministic eval cases covering:
- exact_rule, operational_guidance, similar_case, cross_document, multi_hop
- query_rewrite, user_correction, insufficient_evidence, expired_rules, contradictory_rules

Metrics at BOTH document-level and chunk-level:
- Hit@K, Recall@K, MRR@K, nDCG@K

Plus generation-level:
- Citation Precision/Coverage, Unsupported Claim Rate, Abstain Precision/Recall

Invariants enforced:
- Recall@10 >= Recall@5, Hit@10 >= Hit@5
- 0 <= all metrics <= 1
- Abstain cases computed separately
"""
from __future__ import annotations
import json
import logging
import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("rag.v2.evaluation")


# ═══════════════════════════════════════════════════════════════════════════════
# Eval case structure
# ═══════════════════════════════════════════════════════════════════════════════

class EvalCase:
    """单个评估用例。"""
    def __init__(self, data: Dict[str, Any]):
        self.id: str = data.get("id", "")
        self.category: str = data.get("category", "")
        self.query: str = data.get("query", "")
        self.context: Optional[Dict] = data.get("context")
        self.expected_route: Optional[str] = data.get("expected_route")
        # Gold: list of expected document source_ids (e.g. "rule:title", "dispatch:title")
        self.expected_docs: List[str] = data.get("expected_docs", [])
        # Gold: list of expected chunk text substrings
        self.expected_chunks: List[str] = data.get("expected_chunks", [])
        # Backward compat: expected_hits treated as doc-level gold
        if not self.expected_docs and data.get("expected_hits"):
            self.expected_docs = data.get("expected_hits", [])
        self.expected_facets: List[str] = data.get("expected_facets", [])
        self.should_abstain: bool = data.get("should_abstain", False)
        self.min_evidence: int = data.get("min_evidence", 1)
        self.expected_citation_count: int = data.get("expected_citation_count", 0)
        self.exact_keywords: List[str] = data.get("exact_keywords", [])
        self.forbidden_keywords: List[str] = data.get("forbidden_keywords", [])


# ═══════════════════════════════════════════════════════════════════════════════
# Metrics containers
# ═══════════════════════════════════════════════════════════════════════════════

class EvalMetrics:
    """评估指标，同时提供 document-level 和 chunk-level。"""
    def __init__(self):
        # Document-level retrieval
        self.doc_hit_at_5: float = 0.0
        self.doc_hit_at_10: float = 0.0
        self.doc_recall_at_5: float = 0.0
        self.doc_recall_at_10: float = 0.0
        self.doc_mrr_at_10: float = 0.0
        self.doc_ndcg_at_10: float = 0.0
        # Chunk-level retrieval
        self.chunk_hit_at_5: float = 0.0
        self.chunk_hit_at_10: float = 0.0
        self.chunk_recall_at_5: float = 0.0
        self.chunk_recall_at_10: float = 0.0
        self.chunk_mrr_at_10: float = 0.0
        self.chunk_ndcg_at_10: float = 0.0
        # Generation
        self.citation_precision: float = 0.0
        self.citation_coverage: float = 0.0
        self.unsupported_claim_rate: float = 0.0
        self.abstain_precision: float = 0.0
        self.abstain_recall: float = 0.0
        # Performance
        self.latency_p50_ms: float = 0.0
        self.latency_p95_ms: float = 0.0
        # Counts
        self.total_cases: int = 0
        self.success_count: int = 0
        self.failure_count: int = 0
        self.abstain_case_count: int = 0
        self.cases_with_gold_docs: int = 0
        self.cases_with_gold_chunks: int = 0
        self.details: List[Dict] = []


# ═══════════════════════════════════════════════════════════════════════════════
# Metric computation helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _compute_hit_at_k(retrieved_ids: List[str], gold_ids: List[str], k: int) -> float:
    """Hit@K: 1 if any gold id appears in top K retrieved ids."""
    if not gold_ids:
        return 0.0
    top_k = set(retrieved_ids[:k])
    return 1.0 if any(g in top_k for g in gold_ids) else 0.0


def _compute_recall_at_k(retrieved_ids: List[str], gold_ids: List[str], k: int) -> float:
    """Recall@K: |retrieved ∩ gold| / |gold| at rank K."""
    if not gold_ids:
        return 1.0  # No gold = vacuously recalled
    top_k = set(retrieved_ids[:k])
    found = sum(1 for g in gold_ids if g in top_k)
    return found / len(gold_ids)


def _compute_mrr_at_k(retrieved_ids: List[str], gold_ids: List[str], k: int) -> float:
    """MRR@K: mean reciprocal rank of first gold hit."""
    if not gold_ids:
        return 1.0
    for rank, rid in enumerate(retrieved_ids[:k], 1):
        if rid in gold_ids:
            return 1.0 / rank
    return 0.0


def _compute_ndcg_at_k(retrieved_ids: List[str], gold_ids: List[str], k: int) -> float:
    """nDCG@K: binary relevance, DCG / IDCG."""
    if not gold_ids:
        return 1.0
    gold_set = set(gold_ids)
    dcg = 0.0
    for rank, rid in enumerate(retrieved_ids[:k], 1):
        if rid in gold_set:
            dcg += 1.0 / math.log2(rank + 1)
    idcg = 0.0
    for rank in range(1, min(len(gold_set), k) + 1):
        idcg += 1.0 / math.log2(rank + 1)
    return dcg / idcg if idcg > 0 else 0.0


def _assert_invariants(metrics: EvalMetrics) -> None:
    """Ensure monotonicity and range invariants."""
    for name, k5, k10 in [
        ("doc_hit", metrics.doc_hit_at_5, metrics.doc_hit_at_10),
        ("doc_recall", metrics.doc_recall_at_5, metrics.doc_recall_at_10),
        ("chunk_hit", metrics.chunk_hit_at_5, metrics.chunk_hit_at_10),
        ("chunk_recall", metrics.chunk_recall_at_5, metrics.chunk_recall_at_10),
    ]:
        assert k10 >= k5 - 0.0001, f"INVARIANT VIOLATION: {name}@10 ({k10:.4f}) < {name}@5 ({k5:.4f})"

    all_metrics = [
        metrics.doc_hit_at_5, metrics.doc_hit_at_10, metrics.doc_recall_at_5, metrics.doc_recall_at_10,
        metrics.doc_mrr_at_10, metrics.doc_ndcg_at_10,
        metrics.chunk_hit_at_5, metrics.chunk_hit_at_10, metrics.chunk_recall_at_5, metrics.chunk_recall_at_10,
        metrics.chunk_mrr_at_10, metrics.chunk_ndcg_at_10,
        metrics.citation_precision, metrics.citation_coverage,
        metrics.unsupported_claim_rate, metrics.abstain_precision, metrics.abstain_recall,
    ]
    for m in all_metrics:
        assert 0.0 <= m <= 1.0 + 0.0001, f"INVARIANT VIOLATION: metric {m:.4f} out of [0,1]"


# ═══════════════════════════════════════════════════════════════════════════════
# Evaluation Runner
# ═══════════════════════════════════════════════════════════════════════════════

class EvalRunner:
    """离线评估运行器。"""

    def __init__(self, pipeline=None):
        self.pipeline = pipeline

    def load_cases(self, path: Optional[str] = None) -> List[EvalCase]:
        if path is None:
            path = str(Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "rag_eval_cases.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.warning(f"Eval cases file not found: {path}")
            return self._builtin_cases()
        return [EvalCase(c) for c in data.get("cases", [])]

    def evaluate(
        self,
        cases: Optional[List[EvalCase]] = None,
        baseline_name: str = "phase11",
    ) -> EvalMetrics:
        if cases is None:
            cases = self.load_cases()
        if not self.pipeline:
            from backend.rag.v2.pipeline import get_pipeline
            self.pipeline = get_pipeline()

        metrics = EvalMetrics()
        metrics.total_cases = len(cases)
        details: List[Dict] = []
        latencies: List[float] = []

        for case in cases:
            t0 = time.time()
            try:
                result = self.pipeline.ask(
                    case.query,
                    memory_context=case.context.get("memory") if case.context else None,
                    event_info=case.context.get("event") if case.context else None,
                    session_context=case.context.get("session") if case.context else None,
                )
                latency_ms = (time.time() - t0) * 1000
                latencies.append(latency_ms)
                metrics.success_count += 1

                detail = self._score_one_case(case, result, latency_ms)
                details.append(detail)

            except Exception as e:
                logger.error(f"Eval case {case.id} FAILED: {e}")
                metrics.failure_count += 1
                details.append({"id": case.id, "error": str(e), "category": case.category})
                latencies.append(0.0)

        metrics.details = details

        # Separate abstain cases
        abstain_ids = {c.id for c in cases if c.should_abstain}
        regular_details = [d for d in details if d.get("id") not in abstain_ids and "error" not in d]
        abstain_details = [d for d in details if d.get("id") in abstain_ids and "error" not in d]
        metrics.abstain_case_count = len(abstain_details)

        # ── Document-level metrics (only cases with gold docs) ──
        doc_cases = [c for c in cases if c.expected_docs and c.id not in abstain_ids]
        metrics.cases_with_gold_docs = len(doc_cases)
        if doc_cases:
            doc_hit5_sum = 0.0; doc_hit10_sum = 0.0
            doc_rec5_sum = 0.0; doc_rec10_sum = 0.0
            doc_mrr_sum = 0.0; doc_ndcg_sum = 0.0
            n_doc = len(doc_cases)

            for case in doc_cases:
                detail = next((d for d in regular_details if d.get("id") == case.id), None)
                if detail is None:
                    continue
                retrieved = detail.get("retrieved_doc_ids", [])
                gold = case.expected_docs
                doc_hit5_sum += _compute_hit_at_k(retrieved, gold, 5)
                doc_hit10_sum += _compute_hit_at_k(retrieved, gold, 10)
                doc_rec5_sum += _compute_recall_at_k(retrieved, gold, 5)
                doc_rec10_sum += _compute_recall_at_k(retrieved, gold, 10)
                doc_mrr_sum += _compute_mrr_at_k(retrieved, gold, 10)
                doc_ndcg_sum += _compute_ndcg_at_k(retrieved, gold, 10)

            metrics.doc_hit_at_5 = doc_hit5_sum / n_doc
            metrics.doc_hit_at_10 = doc_hit10_sum / n_doc
            metrics.doc_recall_at_5 = doc_rec5_sum / n_doc
            metrics.doc_recall_at_10 = doc_rec10_sum / n_doc
            metrics.doc_mrr_at_10 = doc_mrr_sum / n_doc
            metrics.doc_ndcg_at_10 = doc_ndcg_sum / n_doc

        # ── Chunk-level metrics (only cases with gold chunks) ──
        chunk_cases = [c for c in cases if c.expected_chunks and c.id not in abstain_ids]
        metrics.cases_with_gold_chunks = len(chunk_cases)
        if chunk_cases:
            ch_hit5_sum = 0.0; ch_hit10_sum = 0.0
            ch_rec5_sum = 0.0; ch_rec10_sum = 0.0
            ch_mrr_sum = 0.0; ch_ndcg_sum = 0.0
            n_ch = len(chunk_cases)

            for case in chunk_cases:
                detail = next((d for d in regular_details if d.get("id") == case.id), None)
                if detail is None:
                    continue
                retrieved = detail.get("retrieved_chunk_ids", [])
                gold = case.expected_chunks
                ch_hit5_sum += _compute_hit_at_k(retrieved, gold, 5)
                ch_hit10_sum += _compute_hit_at_k(retrieved, gold, 10)
                ch_rec5_sum += _compute_recall_at_k(retrieved, gold, 5)
                ch_rec10_sum += _compute_recall_at_k(retrieved, gold, 10)
                ch_mrr_sum += _compute_mrr_at_k(retrieved, gold, 10)
                ch_ndcg_sum += _compute_ndcg_at_k(retrieved, gold, 10)

            metrics.chunk_hit_at_5 = ch_hit5_sum / n_ch
            metrics.chunk_hit_at_10 = ch_hit10_sum / n_ch
            metrics.chunk_recall_at_5 = ch_rec5_sum / n_ch
            metrics.chunk_recall_at_10 = ch_rec10_sum / n_ch
            metrics.chunk_mrr_at_10 = ch_mrr_sum / n_ch
            metrics.chunk_ndcg_at_10 = ch_ndcg_sum / n_ch

        # ── Generation-level metrics ──
        n_reg = len(regular_details)
        if n_reg > 0:
            # Citation precision: |valid citations| / |total citations|
            total_valid = sum(d.get("valid_citation_count", 0) for d in regular_details)
            total_cit = sum(d.get("total_citation_count", 0) for d in regular_details)
            metrics.citation_precision = total_valid / max(total_cit, 1)

            # Citation coverage: cases_with_citations / total_cases
            cases_with_cit = sum(1 for d in regular_details if d.get("total_citation_count", 0) > 0)
            metrics.citation_coverage = cases_with_cit / n_reg

            # Unsupported claim rate
            forbidden = sum(d.get("forbidden_found", 0) for d in regular_details)
            metrics.unsupported_claim_rate = forbidden / n_reg

        # Abstain metrics
        if abstain_details:
            correct_abstains = sum(1 for d in abstain_details if d.get("abstain_correct") is True)
            should_abstain_total = len(abstain_details)
            total_predicted_abstains = sum(
                1 for d in details if d.get("abstained_in_response") is True and "error" not in d
            ) or 1
            metrics.abstain_precision = correct_abstains / max(total_predicted_abstains, 1)
            metrics.abstain_recall = correct_abstains / max(should_abstain_total, 1)

        # Latency
        sorted_lat = sorted(l for l in latencies if l > 0)
        if sorted_lat:
            metrics.latency_p50_ms = sorted_lat[len(sorted_lat) // 2]
            metrics.latency_p95_ms = sorted_lat[min(int(len(sorted_lat) * 0.95), len(sorted_lat) - 1)]

        _assert_invariants(metrics)
        return metrics

    def _score_one_case(self, case: EvalCase, result, latency_ms: float) -> Dict:
        from backend.rag.v2.models import RagAnswer
        detail: Dict[str, Any] = {
            "id": case.id,
            "category": case.category,
            "query": case.query,
            "latency_ms": latency_ms,
        }

        # Extract retrieved doc IDs (from evidence's document_id)
        retrieved_doc_ids = [e.document_id for e in result.evidence]
        detail["retrieved_doc_ids"] = retrieved_doc_ids

        # Extract retrieved chunk IDs
        retrieved_chunk_ids = [e.chunk_id for e in result.evidence]
        detail["retrieved_chunk_ids"] = retrieved_chunk_ids

        # Hit counts
        if case.expected_docs:
            gold_set = set(case.expected_docs)
            detail["doc_hits"] = sum(1 for rid in retrieved_doc_ids if rid in gold_set)
        if case.expected_chunks:
            gold_set = set(case.expected_chunks)
            detail["chunk_hits"] = sum(1 for rid in retrieved_chunk_ids if rid in gold_set)

        # Citations
        if isinstance(result, RagAnswer):
            detail["total_citation_count"] = len(result.citation_map)
            valid_evidence_ids = {e.evidence_id for e in result.evidence}
            detail["valid_citation_count"] = sum(
                1 for c in result.citation_map if c.evidence_id in valid_evidence_ids
            )
            detail["abstained_in_response"] = result.abstained
            detail["evidence_count"] = len(result.evidence)
            detail["evidence_state"] = result.evidence_state.value if hasattr(result.evidence_state, 'value') else str(result.evidence_state)

        # Keyword checks
        if case.exact_keywords:
            detail["keywords_found"] = sum(1 for kw in case.exact_keywords if kw in result.answer)
        if case.forbidden_keywords:
            detail["forbidden_found"] = sum(1 for kw in case.forbidden_keywords if kw in result.answer)

        # Abstain evaluation
        if case.should_abstain:
            detail["abstain_correct"] = result.abstained if isinstance(result, RagAnswer) else False

        # Route
        detail["min_evidence_met"] = len(result.evidence) >= case.min_evidence

        return detail

    def compare(self, baseline: EvalMetrics, candidate: EvalMetrics) -> Dict:
        return {
            "baseline": self._summary(baseline),
            "candidate": self._summary(candidate),
        }

    def _summary(self, m: EvalMetrics) -> Dict:
        return {
            "total_cases": m.total_cases,
            "success_count": m.success_count,
            "failure_count": m.failure_count,
            "abstain_case_count": m.abstain_case_count,
            "cases_with_gold_docs": m.cases_with_gold_docs,
            "cases_with_gold_chunks": m.cases_with_gold_chunks,
            "document_level": {
                "hit_at_5": round(m.doc_hit_at_5, 4),
                "hit_at_10": round(m.doc_hit_at_10, 4),
                "recall_at_5": round(m.doc_recall_at_5, 4),
                "recall_at_10": round(m.doc_recall_at_10, 4),
                "mrr_at_10": round(m.doc_mrr_at_10, 4),
                "ndcg_at_10": round(m.doc_ndcg_at_10, 4),
            },
            "chunk_level": {
                "hit_at_5": round(m.chunk_hit_at_5, 4),
                "hit_at_10": round(m.chunk_hit_at_10, 4),
                "recall_at_5": round(m.chunk_recall_at_5, 4),
                "recall_at_10": round(m.chunk_recall_at_10, 4),
                "mrr_at_10": round(m.chunk_mrr_at_10, 4),
                "ndcg_at_10": round(m.chunk_ndcg_at_10, 4),
            },
            "generation": {
                "citation_precision": round(m.citation_precision, 4),
                "citation_coverage": round(m.citation_coverage, 4),
                "unsupported_claim_rate": round(m.unsupported_claim_rate, 4),
                "abstain_precision": round(m.abstain_precision, 4),
                "abstain_recall": round(m.abstain_recall, 4),
            },
            "performance": {
                "latency_p50_ms": round(m.latency_p50_ms, 1),
                "latency_p95_ms": round(m.latency_p95_ms, 1),
            },
        }

    def _builtin_cases(self) -> List[EvalCase]:
        cases_data = [
            {"id":"exact_001","category":"exact_rule","query":"122和120在事故中如何联动？","expected_route":"exact_rule","expected_docs":["122","120"],"exact_keywords":["122","120"]},
            {"id":"op_001","category":"operational","query":"雨天通勤高峰城市主路车流停滞怎样疏导？","min_evidence":1},
            {"id":"multi_001","category":"multi_hop","query":"学校门口拥堵影响医院急救怎样兼顾？","expected_route":"multi_hop","min_evidence":2},
            {"id":"mem_001","category":"follow_up","query":"继续查询学生疏导预案","context":{"memory":{"road.name":"人民路小学"}},"min_evidence":1,"exact_keywords":["学生","学校"]},
            {"id":"corr_001","category":"correction","query":"继续检索适用预案","context":{"correction":{"road.name":"中山路"}},"min_evidence":1,"forbidden_keywords":["人民路"]},
            {"id":"insuf_001","category":"insufficient","query":"请给出当前路口最优精确信号周期和相位秒数","should_abstain":True,"forbidden_keywords":["秒","周期"]},
            {"id":"simple_001","category":"simple","query":"拥堵怎么处置？","min_evidence":1},
            {"id":"greet_001","category":"no_retrieval","query":"你好","expected_route":"no_retrieval"},
            {"id":"case_001","category":"similar_case","query":"有没有类似历史拥堵案例？","expected_route":"similar_case","min_evidence":1},
            {"id":"rule_001","category":"exact_rule","query":"信号配时异常怎么处理？","expected_route":"exact_rule","min_evidence":1},
        ]
        return [EvalCase(c) for c in cases_data]
