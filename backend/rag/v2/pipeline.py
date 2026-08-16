"""
RAG V2 Pipeline — 端到端检索增强生成流水线。

Stages: query_analysis → query_rewrite → hybrid_retrieval → rrf_fusion
→ rerank → policy_filter → evidence_evaluation → context_pack → generation

完整 Trace 记录：各阶段 latency、degraded 状态、candidates/accepted/rejected。
"""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from backend.rag.v2.models import (
    EvidenceState,
    QueryAnalysis,
    RagAnswer,
    RagTrace,
    RetrievalRequest,
    RetrievalRoute,
    TraceStage,
)
from backend.rag.v2.providers import (
    EmbeddingProvider,
    RerankerProvider,
    get_embedding_provider,
    get_reranker_provider,
)
from backend.rag.v2.query_analyzer import RagQueryAnalyzer
from backend.rag.v2.query_rewriter import RagQueryRewriter
from backend.rag.v2.hybrid_retriever import HybridRetriever
from backend.rag.v2.reranker import Reranker
from backend.rag.v2.evidence_evaluator import EvidenceEvaluator
from backend.rag.v2.context_packer import ContextPacker
from backend.rag.v2.grounded_generator import GroundedGenerator
from backend.rag.v2.config import RAG_STAGE_TIMEOUT_SECONDS, RAG_OVERALL_TIMEOUT_SECONDS, RAG_RERANK_TIMEOUT_SECONDS

logger = logging.getLogger("rag.v2.pipeline")


class RAGStageTimeout(Exception):
    """RAG 单 stage 超时。"""
    def __init__(self, stage: str, elapsed_ms: float):
        super().__init__(f"RAG stage '{stage}' timed out after {elapsed_ms:.0f}ms")
        self.stage = stage
        self.elapsed_ms = elapsed_ms


class RagPipeline:
    """RAG V2 主流水线。"""

    def __init__(
        self,
        embedding_provider: Optional[EmbeddingProvider] = None,
        reranker_provider: Optional[RerankerProvider] = None,
    ):
        self.embedding_provider = embedding_provider or get_embedding_provider()
        self.reranker_provider = reranker_provider or get_reranker_provider()
        self.query_analyzer = RagQueryAnalyzer()
        self.query_rewriter = RagQueryRewriter()
        self.hybrid_retriever = HybridRetriever(self.embedding_provider)
        self.reranker = Reranker(self.reranker_provider)
        self.evidence_evaluator = EvidenceEvaluator()
        self.context_packer = ContextPacker()
        self.grounded_generator = GroundedGenerator(self.context_packer)

    async def _run_stage(self, fn, stage: str, *args, timeout: Optional[float] = None):
        """在独立线程运行同步 stage，并施加单 stage 超时。

        Returns:
            fn 的返回值。
        Raises:
            RAGStageTimeout: stage 超过 timeout（默认 RAG_STAGE_TIMEOUT_SECONDS）。
        """
        t0 = time.time()
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(fn, *args),
                timeout=timeout if timeout is not None else RAG_STAGE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            raise RAGStageTimeout(stage, (time.time() - t0) * 1000)

    # ── Main API ────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[Dict] = None,
        memory_context: Optional[Dict] = None,
        event_info: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """RAG search with full trace."""
        t0 = time.time()
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"
        trace = RagTrace(
            trace_id=trace_id,
            original_query=query,
            filters=filters or {},
            embedding_model=self.embedding_provider.get_model_name(),
            reranker_model=self.reranker_provider.get_model_name(),
        )

        # Stage 1: Query analysis
        t1 = time.time()
        analysis = self.query_analyzer.analyze(query, event_info)
        trace.stages.append(TraceStage(
            stage="query_analysis",
            duration_ms=(time.time() - t1) * 1000,
            input={"query": query},
            output=analysis.model_dump(),
        ))

        if not analysis.needs_retrieval:
            trace.stages.append(TraceStage(stage="aborted", output={"reason": "no_retrieval_needed"}))
            trace.total_latency_ms = (time.time() - t0) * 1000
            return {
                "results": [],
                "trace": trace.model_dump(mode="json"),
                "analysis": analysis.model_dump(),
            }

        # Stage 2: Query rewrite
        t2 = time.time()
        rewritten = self.query_rewriter.rewrite(query, analysis, memory_context, event_info)
        trace.rewritten_query = rewritten
        trace.stages.append(TraceStage(
            stage="query_rewrite",
            duration_ms=(time.time() - t2) * 1000,
            input={"original": query},
            output={"rewritten": rewritten},
        ))

        # Stage 3-5: Multi-channel retrieval + RRF
        t3 = time.time()
        candidates = self.hybrid_retriever.retrieve(query, rewritten, analysis, top_k=top_k * 3)
        trace.candidates_total = len(candidates)
        trace.stages.append(TraceStage(
            stage="hybrid_retrieval",
            duration_ms=(time.time() - t3) * 1000,
            output={"candidates": len(candidates), "sample": [c.get("chunk_id") for c in candidates[:3]]},
        ))

        # Stage 6: Rerank + policy
        t4 = time.time()
        accepted, rejected, rerank_degraded = self.reranker.rerank(rewritten, candidates)
        trace.accepted_total = len(accepted)
        trace.rejected_total = len(rejected)
        trace.stages.append(TraceStage(
            stage="rerank_and_policy",
            duration_ms=(time.time() - t4) * 1000,
            degraded=rerank_degraded,
            output={
                "accepted": len(accepted),
                "rejected": len(rejected),
                "degraded": rerank_degraded,
            },
        ))

        # Stage 7: Evidence building
        evidence_items = self.reranker.build_evidence_items(accepted[:top_k], rewritten)
        trace.evidence_total = len(evidence_items)

        # Stage 8: Evidence evaluation
        t5 = time.time()
        ev_state, ev_reason = self.evidence_evaluator.evaluate(
            evidence_items, analysis.required_facets, query,
        )
        trace.evidence_state = ev_state
        trace.stages.append(TraceStage(
            stage="evidence_evaluation",
            duration_ms=(time.time() - t5) * 1000,
            output={"state": ev_state.value, "reason": ev_reason},
        ))

        if rerank_degraded:
            trace.degraded = True
            trace.degraded_reasons.append("reranker_degraded")

        trace.total_latency_ms = (time.time() - t0) * 1000

        # Store trace
        from backend.rag.v2.document_repository import save_trace
        try:
            save_trace(trace)
        except Exception as e:
            logger.error(f"Failed to save trace: {e}")

        return {
            "results": candidates[:top_k],
            "evidence": [e.model_dump(mode="json") for e in evidence_items],
            "evidence_state": ev_state.value,
            "evidence_reason": ev_reason,
            "trace": trace.model_dump(mode="json"),
            "analysis": analysis.model_dump(),
            "rewritten_query": rewritten,
        }

    def ask(
        self,
        question: str,
        memory_context: Optional[Dict] = None,
        event_info: Optional[Dict] = None,
        session_context: Optional[Dict] = None,
    ) -> RagAnswer:
        """RAG Q&A with grounded answer and citations."""
        t0 = time.time()
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"
        trace = RagTrace(
            trace_id=trace_id,
            original_query=question,
            embedding_model=self.embedding_provider.get_model_name(),
            reranker_model=self.reranker_provider.get_model_name(),
        )

        # Stage 1: Analyze
        t1 = time.time()
        analysis = self.query_analyzer.analyze(question, event_info)
        trace.required_facets = analysis.required_facets
        trace.stages.append(TraceStage(
            stage="query_analysis",
            duration_ms=(time.time() - t1) * 1000,
            output=analysis.model_dump(),
        ))

        if not analysis.needs_retrieval:
            return RagAnswer(
                question=question,
                answer="您好，请问有什么交通管理方面的问题需要帮助？",
                evidence_state=EvidenceState.SUFFICIENT,
                trace_id=trace_id,
                abstained=False,
            )

        # Stage 2: Rewrite
        t2 = time.time()
        rewritten = self.query_rewriter.rewrite(question, analysis, memory_context, event_info, session_context)
        trace.rewritten_query = rewritten
        trace.used_memory_ids = self.query_rewriter.extract_used_memory_ids(memory_context)
        trace.stages.append(TraceStage(
            stage="query_rewrite", duration_ms=(time.time() - t2) * 1000,
            input={"original": question}, output={"rewritten": rewritten},
        ))

        # Stage 3: Subquery decomposition
        subqueries = analysis.subqueries
        if subqueries:
            trace.subqueries = subqueries
            trace.stages.append(TraceStage(
                stage="query_decomposition", duration_ms=0,
                output={"subqueries": subqueries},
            ))

        # Stage 4-6: Multi-channel retrieval + RRF
        t3 = time.time()
        all_candidates = []
        search_queries = [rewritten] + subqueries
        for sq in search_queries[:3]:
            candidates = self.hybrid_retriever.retrieve(sq, rewritten, analysis)
            all_candidates.extend(candidates)

        # Dedup by chunk_id
        seen = set()
        deduped = []
        for c in all_candidates:
            cid = c.get("chunk_id", "")
            if cid not in seen:
                seen.add(cid)
                deduped.append(c)
        # Re-sort by RRF
        deduped.sort(key=lambda x: x.get("rrf_score", 0), reverse=True)
        all_candidates = deduped

        trace.candidates_total = len(all_candidates)
        trace.stages.append(TraceStage(
            stage="hybrid_retrieval", duration_ms=(time.time() - t3) * 1000,
            output={"candidates": len(all_candidates), "channels_used": len(search_queries)},
        ))

        # Stage 7: Rerank + policy
        t4 = time.time()
        accepted, rejected, rerank_degraded = self.reranker.rerank(rewritten, all_candidates)
        trace.accepted_total = len(accepted)
        trace.rejected_total = len(rejected)
        trace.stages.append(TraceStage(
            stage="rerank_and_policy", duration_ms=(time.time() - t4) * 1000,
            degraded=rerank_degraded,
            output={"accepted": len(accepted), "rejected": len(rejected)},
        ))

        # Stage 8: Build evidence
        evidence_items = self.reranker.build_evidence_items(accepted, rewritten)
        trace.evidence_total = len(evidence_items)

        # Stage 9: Evidence evaluation
        t5 = time.time()
        ev_state, ev_reason = self.evidence_evaluator.evaluate(
            evidence_items, analysis.required_facets, question,
        )
        trace.evidence_state = ev_state
        trace.stages.append(TraceStage(
            stage="evidence_evaluation", duration_ms=(time.time() - t5) * 1000,
            output={"state": ev_state.value, "reason": ev_reason},
        ))

        # Stage 10: Context pack + generate
        t6 = time.time()
        memory_str = self._build_memory_string(memory_context)
        answer = self.grounded_generator.generate(
            question, evidence_items, ev_state, trace_id, memory_str,
            trace.used_memory_ids,
        )
        answer.index_version = trace.index_version
        answer.embedding_model = trace.embedding_model
        answer.reranker_model = trace.reranker_model
        # Add latency info
        answer.latency_ms = {
            "query_analysis": trace.stages[0].duration_ms if trace.stages else 0,
            "query_rewrite": trace.stages[1].duration_ms if len(trace.stages) > 1 else 0,
            "hybrid_retrieval": trace.stages[2].duration_ms if len(trace.stages) > 2 else 0,
            "rerank": trace.stages[3].duration_ms if len(trace.stages) > 3 else 0,
            "evidence_evaluation": trace.stages[4].duration_ms if len(trace.stages) > 4 else 0,
            "total": (time.time() - t0) * 1000,
        }

        trace.total_latency_ms = answer.latency_ms.get("total", 0)
        if rerank_degraded:
            trace.degraded = True
            trace.degraded_reasons.append("reranker_degraded")

        trace.stages.append(TraceStage(
            stage="generation", duration_ms=(time.time() - t6) * 1000,
            output={"answer_length": len(answer.answer), "evidence_count": len(evidence_items)},
        ))

        # Save trace
        from backend.rag.v2.document_repository import save_trace
        try:
            save_trace(trace)
        except Exception as e:
            logger.error(f"Failed to save trace: {e}")

        return answer

    def _build_memory_string(self, memory_context: Optional[Dict]) -> str:
        if not memory_context:
            return ""
        parts = []
        for k, v in memory_context.items():
            if isinstance(v, dict):
                parts.append(f"{k}: {v.get('value', v)}")
            else:
                parts.append(f"{k}: {v}")
        return "; ".join(parts[:8])

    # ── SSE Streaming (for chat integration) ────────────────────────────────

    async def ask_stream(
        self,
        question: str,
        memory_context: Optional[Dict] = None,
        event_info: Optional[Dict] = None,
        session_context: Optional[Dict] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式 RAG Q&A — yields SSE event dicts."""
        t0 = time.time()
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"

        # Build trace incrementally (same structure as non-streaming ask())
        trace = RagTrace(
            trace_id=trace_id,
            original_query=question,
            embedding_model=self.embedding_provider.get_model_name(),
            reranker_model=self.reranker_provider.get_model_name(),
        )

        # 1. Analyze
        t1 = time.time()
        analysis = await self._run_stage(self.query_analyzer.analyze, "analyze", question, event_info)
        trace.required_facets = analysis.required_facets
        trace.stages.append(TraceStage(
            stage="query_analysis", duration_ms=(time.time()-t1)*1000,
            output=analysis.model_dump(),
        ))
        yield {"event": "rag_route_done", "data": {
            "route": analysis.route.value,
            "complexity": analysis.complexity,
            "entities": analysis.explicit_entities,
            "facets": analysis.required_facets,
            "needs_retrieval": analysis.needs_retrieval,
        }}

        if not analysis.needs_retrieval:
            yield {"event": "done", "data": {"answer": "您好，请问有什么交通管理问题？", "traceId": trace_id}}
            return

        # CONTROLLED ERROR INJECTION: for SSE error chain testing
        if "FORCE_RAG_ERROR_TEST" in question:
            raise RuntimeError("controlled rag generation failure for sse error chain test")

        # 2. Rewrite
        t2 = time.time()
        rewritten = await self._run_stage(self.query_rewriter.rewrite, "rewrite", question, analysis, memory_context, event_info, session_context)
        trace.rewritten_query = rewritten
        trace.stages.append(TraceStage(
            stage="query_rewrite", duration_ms=(time.time()-t2)*1000,
            input={"original": question}, output={"rewritten": rewritten},
        ))
        yield {"event": "rag_query_rewritten", "data": {"original": question, "rewritten": rewritten}}

        # 3. Retrieve
        t3 = time.time()
        candidates = await self._run_stage(self.hybrid_retriever.retrieve, "retrieve", question, rewritten, analysis)
        trace.candidates_total = len(candidates)
        trace.stages.append(TraceStage(
            stage="hybrid_retrieval", duration_ms=(time.time()-t3)*1000,
            output={"candidates": len(candidates)},
        ))
        yield {"event": "rag_candidates_retrieved", "data": {
            "total": len(candidates),
            "channels": list(set(
                ch for c in candidates
                for ch in c.get("retrieval_channels", [])
            )),
        }}

        # 4. Rerank (optional — fallback to retrieval ranking on timeout/unavailable)
        t4 = time.time()
        rerank_applied = True
        rerank_fallback_reason: Optional[str] = None
        try:
            accepted, rejected, rerank_degraded = await self._run_stage(
                self.reranker.rerank, "rerank", rewritten, candidates,
                timeout=RAG_RERANK_TIMEOUT_SECONDS,
            )
            if rerank_degraded:
                rerank_applied = False
                rerank_fallback_reason = "degraded"
        except RAGStageTimeout:
            # Reranker cold-load/timeout → fallback to retrieval ranking (RRF)
            accepted, rejected, rerank_degraded = self.reranker.fallback_rerank(candidates)
            rerank_applied = False
            rerank_fallback_reason = "timeout"
        trace.accepted_total = len(accepted)
        trace.rejected_total = len(rejected)
        trace.stages.append(TraceStage(
            stage="rerank_and_policy", duration_ms=(time.time()-t4)*1000,
            degraded=rerank_degraded,
            output={"accepted": len(accepted), "rejected": len(rejected),
                    "rerank_applied": rerank_applied, "fallback_reason": rerank_fallback_reason},
        ))
        yield {"event": "rag_rerank_done", "data": {
            "accepted": len(accepted), "rejected": len(rejected),
            "degraded": rerank_degraded,
            "rerankApplied": rerank_applied,
            "rerankFallbackUsed": not rerank_applied,
            "rerankFallbackReason": rerank_fallback_reason,
        }}

        # 5. Evidence
        evidence_items = self.reranker.build_evidence_items(accepted, rewritten)
        trace.evidence_total = len(evidence_items)
        ev_state, ev_reason = self.evidence_evaluator.evaluate(
            evidence_items, analysis.required_facets, question,
            rerank_applied=rerank_applied,
        )
        trace.evidence_state = ev_state
        trace.stages.append(TraceStage(
            stage="evidence_evaluation", duration_ms=0,
            output={"state": ev_state.value, "reason": ev_reason},
        ))
        yield {"event": "rag_evidence_selected", "data": {
            "evidence_count": len(evidence_items),
            "state": ev_state.value,
            "evidence": [
                {
                    "evidence_id": e.evidence_id,
                    "title": e.title,
                    "doc_type": e.doc_type,
                    "channels": e.retrieval_channels,
                    "rrf_score": e.rrf_score,
                    "rerank_score": e.rerank_score,
                }
                for e in evidence_items
            ],
        }}

        if ev_state == EvidenceState.INSUFFICIENT:
            trace.index_version = self._get_latest_index_version()
            if rerank_degraded:
                trace.degraded = True
                trace.degraded_reasons.append("reranker_degraded")
            yield {"event": "rag_abstained", "data": {"reason": ev_reason}}
            # Save trace, then yield trace_ready
            self._save_trace_safe(trace)
            yield {"event": "rag_trace_ready", "data": {"traceId": trace_id}}
            yield {"event": "done", "data": {
                "answer": f"抱歉，当前知识库没有检索到足够证据回答「{question[:40]}」。\n\n{ev_reason}",
                "traceId": trace_id, "abstained": True,
            }}
            return

        # 6. Generate (streaming)
        t5 = time.time()
        memory_str = self._build_memory_string(memory_context)

        # Stream LLM deltas from a worker thread via an asyncio queue
        delta_queue: asyncio.Queue = asyncio.Queue()

        def _generate_worker():
            def _on_delta(d: str):
                delta_queue.put_nowait(("delta", d))
            try:
                result = self.grounded_generator.stream_answer(
                    question, evidence_items, ev_state, memory_str, _on_delta,
                )
                delta_queue.put_nowait(("done", result))
            except Exception as e:
                delta_queue.put_nowait(("error", str(e)))

        asyncio.create_task(asyncio.to_thread(_generate_worker))

        answer_text = ""
        citations: List = []
        used_llm = False
        while True:
            msg = await delta_queue.get()
            if msg[0] == "delta":
                answer_text += msg[1]
                yield {"event": "delta", "data": {"text": msg[1]}}
            else:
                if msg[0] == "done" and msg[1]:
                    answer_text, citations, used_llm = msg[1]
                break

        # Build RagAnswer (template fallback if streaming failed)
        if not used_llm or not answer_text.strip():
            t_text, t_citations = self.grounded_generator._template_generate(
                question, evidence_items, ev_state,
            )
            answer = self.grounded_generator._build_answer(
                question, t_text, evidence_items, ev_state, t_citations,
                trace_id, [], used_llm=False, degraded=True,
                degraded_reasons=["LLM generation failed, using template fallback"],
            )
        else:
            answer = self.grounded_generator._build_answer(
                question, answer_text, evidence_items, ev_state, citations,
                trace_id, [], used_llm=True, degraded=False,
            )

        answer.index_version = self._get_latest_index_version()
        answer.embedding_model = self.embedding_provider.get_model_name()
        answer.reranker_model = self.reranker_provider.get_model_name()
        answer.latency_ms = {"total": (time.time() - t0) * 1000}

        trace.index_version = answer.index_version
        trace.embedding_model = answer.embedding_model
        trace.reranker_model = answer.reranker_model
        trace.total_latency_ms = answer.latency_ms.get("total", 0)
        if rerank_degraded:
            trace.degraded = True
            trace.degraded_reasons.append("reranker_degraded")
        trace.stages.append(TraceStage(
            stage="generation", duration_ms=(time.time()-t5)*1000,
            output={"answer_length": len(answer.answer), "evidence_count": len(evidence_items)},
        ))
        # Save trace, then yield trace_ready + done
        self._save_trace_safe(trace)
        yield {"event": "rag_trace_ready", "data": {"traceId": trace_id}}
        yield {"event": "done", "data": {
            **answer.model_dump(mode="json"),
            "traceId": trace_id,
        }}

    def _save_trace_safe(self, trace: RagTrace) -> None:
        """Save trace to DB. On failure, log warning but do NOT raise."""
        try:
            from backend.rag.v2.document_repository import save_trace
            save_trace(trace)
        except Exception as e:
            logger.error(f"Failed to save trace {trace.trace_id}: {e}")

    def _get_latest_index_version(self) -> str:
        try:
            from backend.rag.v2.document_repository import get_latest_index_version
            ver = get_latest_index_version()
            return ver.version_id if ver else ""
        except Exception:
            return ""


# Global pipeline instance
_pipeline: Optional[RagPipeline] = None


def get_pipeline() -> RagPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = RagPipeline()
    return _pipeline


def reset_pipeline() -> None:
    global _pipeline
    _pipeline = None
