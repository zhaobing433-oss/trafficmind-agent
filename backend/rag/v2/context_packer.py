"""
RAG V2 Context Packer — Parent Context Pack + token-aware evidence formatting.

For each selected child chunk, include its parent chunk for context.
"""
from __future__ import annotations
from typing import Dict, List, Optional

from backend.rag.v2.config import RAG_MAX_CONTEXT_TOKENS
from backend.rag.v2.models import EvidenceItem


class ContextPacker:
    """上下文打包器。"""

    def __init__(self, max_tokens: int = RAG_MAX_CONTEXT_TOKENS):
        self.max_tokens = max_tokens

    def pack(
        self,
        evidence_items: List[EvidenceItem],
        include_parents: bool = True,
    ) -> str:
        """打包证据为 LLM prompt 上下文。

        Args:
            evidence_items: 选中的证据列表
            include_parents: 是否包含父 chunk 上下文

        Returns:
            格式化的上下文字符串
        """
        if not evidence_items:
            return "（无有效证据）"

        parts = []
        total_chars = 0
        char_budget = self.max_tokens * 2  # approximate: 2 chars per token

        for e in evidence_items:
            section_header = f"\n[{e.evidence_id}] {e.title or '知识片段'}"
            if e.section_path:
                section_header += f" — {e.section_path}"
            section_header += f"\n类型: {e.doc_type} | 权威等级: {e.authority_level}"

            if e.effective_from or e.effective_to:
                eff = f"{e.effective_from.strftime('%Y-%m-%d') if e.effective_from else '无'}"
                exp = f"{e.effective_to.strftime('%Y-%m-%d') if e.effective_to else '无'}"
                section_header += f" | 有效期: {eff} ~ {exp}"

            body = e.content if not include_parents else e.contextual_content

            block = f"{section_header}\n{body[:800]}"  # cap per evidence
            block_chars = len(block)

            if total_chars + block_chars > char_budget:
                # Truncate last evidence to fit budget
                remaining = char_budget - total_chars - 100  # leave margin
                if remaining > 200:
                    block = f"{section_header}\n{body[:remaining]}"
                    parts.append(block)
                break

            parts.append(block)
            total_chars += block_chars

        return "\n\n".join(parts)

    def format_evidence_for_display(self, evidence_items: List[EvidenceItem]) -> List[Dict]:
        """格式化为前端可用的结构化证据展示。"""
        return [
            {
                "evidenceId": e.evidence_id,
                "title": e.title,
                "sectionPath": e.section_path,
                "docType": e.doc_type,
                "authorityLevel": e.authority_level,
                "effectiveFrom": e.effective_from.isoformat() if e.effective_from else None,
                "effectiveTo": e.effective_to.isoformat() if e.effective_to else None,
                "retrievalChannels": e.retrieval_channels,
                "rrfScore": e.rrf_score,
                "rerankScore": e.rerank_score,
                "content": e.content[:300],
                "sourceUri": e.source_uri,
            }
            for e in evidence_items
        ]
