"""
RAG V2 Reranker — Cross-Encoder + Policy Filtering.

Steps:
1. Cross-Encoder rerank of RRF Top 25
2. Authority policy
3. Freshness policy
4. Effective date policy
5. Duplicate removal
6. Source diversity
7. Per-document cap (max 2)
8. Per-parent-section cap (max 2)

Final evidence: 4-6 items.
If reranker unavailable, uses deterministic fallback with trace degraded flag.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from backend.rag.v2.config import (
    RAG_RERANK_TOP_K,
    RAG_EVIDENCE_TOP_K,
)
from backend.rag.v2.models import (
    AuthorityLevel,
    EvidenceItem,
    EvidenceState,
    DocType,
)
from backend.rag.v2.providers import RerankerProvider

logger = logging.getLogger("rag.v2.reranker")


def _safe_dt(val) -> Optional[datetime]:
    """Safely parse a value to Optional[datetime]. Returns None for empty/invalid."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    return None


class EvidencePolicy:
    """证据策略过滤器。"""

    def __init__(self, now: Optional[datetime] = None):
        if now is None:
            self.now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            self.now = now.replace(tzinfo=timezone.utc)
        else:
            self.now = now.astimezone(timezone.utc)

    def apply(
        self,
        candidates: List[Dict],
        max_evidence: int = RAG_EVIDENCE_TOP_K,
    ) -> Tuple[List[Dict], List[Dict], bool]:
        """应用所有策略过滤。

        Returns:
            (accepted, rejected, is_degraded)
        """
        if not candidates:
            return [], [], False

        rejected: List[Dict] = []

        # 0. Hard filter: expired, not-yet-effective, deleted
        candidates, hard_rejected = self._hard_filter(candidates)
        rejected.extend(hard_rejected)

        # 1. Remove expired (soft check — kept for any remaining str dates)
        candidates, expired = self._filter_expired(candidates)
        rejected.extend(expired)

        # 2. Authority boost
        candidates = self._authority_boost(candidates)

        # 3. Remove duplicates (by content similarity)
        candidates, dups = self._remove_duplicates(candidates)
        rejected.extend(dups)

        # 4. Source diversity
        candidates = self._ensure_diversity(candidates)

        # 5. Per-document cap
        candidates, capped = self._per_document_cap(candidates, max_per_doc=2)
        rejected.extend(capped)

        # 6. Per-parent-section cap
        candidates, section_capped = self._per_section_cap(candidates, max_per_section=2)
        rejected.extend(section_capped)

        # 7. Pick top evidence
        accepted = candidates[:max_evidence]

        return accepted, rejected, False

    def _get_candidate_field(self, c: Dict, key: str):
        """Get field from candidate, checking both top-level and metadata sub-dict."""
        if key in c and c[key] is not None and c[key] != "":
            return c[key]
        meta = c.get("metadata", {})
        if isinstance(meta, dict) and key in meta and meta[key] is not None and meta[key] != "":
            return meta[key]
        return None

    def _parse_utc_datetime(self, val) -> Optional[datetime]:
        """Parse a datetime value to UTC-aware datetime. Returns None on failure."""
        if val is None:
            return None
        if isinstance(val, datetime):
            if val.tzinfo is None:
                return val.replace(tzinfo=timezone.utc)
            return val
        if isinstance(val, str):
            val = val.strip()
            if not val:
                return None
            try:
                # ISO format with timezone
                s = val.replace("Z", "+00:00")
                dt = datetime.fromisoformat(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, TypeError):
                pass
        return None

    def _hard_filter(self, candidates: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """硬过滤：过期、未生效、已删除。独立于 Embedding/Reranker 分数。

        这些过滤必须在 Evidence 生成之前执行，高分不能让被过滤的候选重新进入。
        """
        active = []
        rejected = []
        for c in candidates:
            doc_id = c.get("document_id", self._get_candidate_field(c, "document_id") or "?")
            chunk_id = c.get("chunk_id", "?")
            title = self._get_candidate_field(c, "title") or c.get("title", "")
            section = self._get_candidate_field(c, "section_path") or ""
            authority = self._get_candidate_field(c, "authority_level") or "operational"
            version = self._get_candidate_field(c, "version") or 0

            # Get effective dates from candidate
            eff_to_raw = self._get_candidate_field(c, "effective_to")
            eff_from_raw = self._get_candidate_field(c, "effective_from")
            status = self._get_candidate_field(c, "status") or "active"

            eff_to = self._parse_utc_datetime(eff_to_raw)
            eff_from = self._parse_utc_datetime(eff_from_raw)

            reason = None

            # 1. Deleted / soft-deleted
            if status in ("deleted", "soft_deleted"):
                reason = "deleted"

            # 2. Expired: effective_to is set AND in the past
            elif eff_to is not None and eff_to <= self.now:
                reason = "expired"

            # 3. Not yet effective: effective_from is set AND in the future
            elif eff_from is not None and eff_from > self.now:
                reason = "not_yet_effective"

            if reason:
                rejected.append({
                    "chunk_id": chunk_id,
                    "document_id": doc_id,
                    "title": title,
                    "section_path": section,
                    "effective_from": eff_from_raw,
                    "effective_to": eff_to_raw,
                    "version": version,
                    "authority_level": authority,
                    "status": status,
                    "rejection_reason": reason,
                    **{k: v for k, v in c.items() if k not in ("metadata",)},
                })
            else:
                active.append(c)

        return active, rejected

    def _filter_expired(self, candidates: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """过滤已过期的证据（补充检查，处理 metadata 嵌套）。"""
        active = []
        expired = []
        for c in candidates:
            eff_to = self._get_candidate_field(c, "effective_to")
            if eff_to:
                dt = self._parse_utc_datetime(eff_to)
                if dt and dt < self.now:
                    expired.append({**c, "rejection_reason": "expired"})
                    continue
            active.append(c)
        return active, expired

    def _authority_boost(self, candidates: List[Dict]) -> List[Dict]:
        """权威等级加权。"""
        weights = {
            AuthorityLevel.OFFICIAL: 0.15,
            AuthorityLevel.PROFESSIONAL: 0.10,
            AuthorityLevel.OPERATIONAL: 0.05,
            AuthorityLevel.AGENT_GENERATED: 0.0,
            AuthorityLevel.UNKNOWN: 0.0,
        }
        for c in candidates:
            auth = c.get("authority_level", AuthorityLevel.OPERATIONAL)
            bonus = weights.get(auth, 0.0)
            # Base score: rerank_score (sigmoid [0,1]) when available;
            # otherwise dense_score (real cosine [0,1]) — NOT rrf_score (rank fusion 0.01-0.05).
            current = c.get("rerank_score") or c.get("dense_score") or c.get("score") or c.get("rrf_score") or 0
            c["authority_bonus"] = bonus
            c["adjusted_score"] = round(current + bonus, 6)

        candidates.sort(key=lambda x: x.get("adjusted_score", x.get("rerank_score", 0)), reverse=True)
        return candidates

    def _remove_duplicates(self, candidates: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """去除内容高度重复的候选。"""
        seen = set()
        unique = []
        dups = []
        for c in candidates:
            content_key = (c.get("document_id", ""), c.get("section_path", ""))
            if content_key in seen:
                dups.append({**c, "rejection_reason": "duplicate_section"})
            else:
                seen.add(content_key)
                unique.append(c)
        return unique, dups

    def _ensure_diversity(self, candidates: List[Dict]) -> List[Dict]:
        """确保来源多样性 — 不同 docType 穿插。"""
        if not candidates:
            return candidates
        # Group by doc_type
        by_type: Dict[str, List[Dict]] = {}
        for c in candidates:
            dt = c.get("doc_type", "other")
            if dt not in by_type:
                by_type[dt] = []
            by_type[dt].append(c)

        # Interleave: one from each type in round-robin
        result = []
        types = sorted(by_type.keys())
        max_per_type = max(len(v) for v in by_type.values())
        for i in range(max_per_type):
            for dt in types:
                if i < len(by_type[dt]):
                    result.append(by_type[dt][i])
        return result

    def _per_document_cap(self, candidates: List[Dict], max_per_doc: int = 2) -> Tuple[List[Dict], List[Dict]]:
        """每个 document 最多 max_per_doc 条。"""
        doc_counts: Dict[str, int] = {}
        accepted = []
        capped = []
        for c in candidates:
            doc_id = c.get("document_id", "")
            count = doc_counts.get(doc_id, 0)
            if count < max_per_doc:
                doc_counts[doc_id] = count + 1
                accepted.append(c)
            else:
                capped.append({**c, "rejection_reason": f"per_doc_cap({max_per_doc})"})
        return accepted, capped

    def _per_section_cap(self, candidates: List[Dict], max_per_section: int = 2) -> Tuple[List[Dict], List[Dict]]:
        """每个 parent section 最多 max_per_section 条。"""
        section_counts: Dict[str, int] = {}
        accepted = []
        capped = []
        for c in candidates:
            parent_id = c.get("parent_chunk_id", "") or c.get("section_path", "")
            count = section_counts.get(parent_id, 0)
            if count < max_per_section:
                section_counts[parent_id] = count + 1
                accepted.append(c)
            else:
                capped.append({**c, "rejection_reason": f"per_section_cap({max_per_section})"})
        return accepted, capped


class Reranker:
    """Cross-Encoder 重排器。"""

    def __init__(
        self,
        reranker_provider: Optional[RerankerProvider] = None,
        *,
        policy_as_of: Optional[datetime] = None,
    ):
        from backend.rag.v2.providers import get_reranker_provider
        self.provider = reranker_provider or get_reranker_provider()
        self.policy = EvidencePolicy(policy_as_of)

    def rerank(
        self,
        query: str,
        candidates: List[Dict],
        rerank_top_k: int = RAG_RERANK_TOP_K,
    ) -> Tuple[List[Dict], List[Dict], bool]:
        """Cross-Encoder 重排 + Policy 过滤。

        Returns:
            (accepted_candidates, rejected_candidates, is_degraded)
        """
        if not candidates:
            return [], [], False

        # Limit to top N for reranking
        to_rerank = candidates[:rerank_top_k]

        # Cross-Encoder reranking
        is_degraded = self.provider.is_degraded()
        if not is_degraded:
            documents = [c.get("content", "")[:500] for c in to_rerank]
            try:
                scores = self.provider.rerank(query, documents, top_k=rerank_top_k)
                for i, c in enumerate(to_rerank):
                    c["rerank_score"] = round(scores[i], 6) if i < len(scores) else 0.0
            except Exception as e:
                logger.error(f"Reranker failed: {e}")
                is_degraded = True

        # Mark ranks
        to_rerank.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        for i, c in enumerate(to_rerank):
            c["rerank_rank"] = i + 1

        # Apply policy filters
        accepted, rejected, policy_degraded = self.policy.apply(to_rerank)
        return accepted, rejected, is_degraded or policy_degraded

    def fallback_rerank(
        self,
        candidates: List[Dict],
    ) -> Tuple[List[Dict], List[Dict], bool]:
        """Retrieval-ranking fallback（不调用 CrossEncoder）。

        用于 reranker 超时/不可用时：直接按 rrf_score 降序排序后应用
        EvidencePolicy。保证 RAG 仍可产出 grounded answer。
        """
        if not candidates:
            return [], [], True
        # Sort by rrf_score (or existing rerank_score) descending
        to_rerank = sorted(
            candidates,
            key=lambda x: x.get("rrf_score", x.get("rerank_score", 0.0)),
            reverse=True,
        )
        for i, c in enumerate(to_rerank):
            c["rerank_rank"] = i + 1
        accepted, rejected, _ = self.policy.apply(to_rerank)
        return accepted, rejected, True  # is_degraded=True (reranker not applied)

    def build_evidence_items(
        self,
        accepted: List[Dict],
        query: str,
    ) -> List[EvidenceItem]:
        """将 accepted candidates 转换为 EvidenceItem 列表（E1, E2...）。"""
        evidence = []
        for i, c in enumerate(accepted):
            evidence.append(EvidenceItem(
                evidence_id=f"E{i+1}",
                chunk_id=c.get("chunk_id", ""),
                document_id=c.get("document_id", ""),
                parent_chunk_id=c.get("parent_chunk_id"),
                title=c.get("title", c.get("metadata", {}).get("title", "")),
                section_path=c.get("section_path", c.get("metadata", {}).get("section_path", "")),
                doc_type=c.get("doc_type", c.get("metadata", {}).get("doc_type", "other")),
                content=c.get("content", ""),
                contextual_content=c.get("contextual_content", c.get("content", "")),
                authority_level=c.get("authority_level", AuthorityLevel.OPERATIONAL),
                effective_from=_safe_dt(c.get("effective_from")),
                effective_to=_safe_dt(c.get("effective_to")),
                retrieval_channels=c.get("retrieval_channels", []),
                rrf_score=c.get("rrf_score"),
                rerank_score=c.get("rerank_score"),
                dense_score=c.get("dense_score"),
                source_uri=c.get("source_uri", c.get("metadata", {}).get("source_uri")),
                event_type=c.get("event_type", c.get("metadata", {}).get("event_type")),
                road_name=c.get("road_name", c.get("metadata", {}).get("road_name")),
                region_id=c.get("region_id", c.get("metadata", {}).get("region_id")),
                road_id=c.get("road_id", c.get("metadata", {}).get("road_id")),
                intersection_id=c.get("intersection_id", c.get("metadata", {}).get("intersection_id")),
                grounding_scope=(
                    c.get("grounding_scope")
                    or c.get("metadata", {}).get("grounding_scope")
                    or "LEGACY_UNSCOPED"
                ),
            ))
        return evidence
