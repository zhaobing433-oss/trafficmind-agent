"""
RAG V2 Evidence Evaluator — 评估证据充分性。

States: sufficient / partial / insufficient / contradictory

判断维度:
- requiredFacets 覆盖率
- Top rerank score
- 有效正式规则数量
- 权威等级
- 是否过期
- 证据冲突
- 是否只有低权威自动报告
- 是否高度重复
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from backend.rag.v2.models import (
    AuthorityLevel,
    EvidenceItem,
    EvidenceState,
)


class EvidenceEvaluator:
    """证据充分性评估器。"""

    def evaluate(
        self,
        evidence: List[EvidenceItem],
        required_facets: List[str],
        query: str = "",
    ) -> Tuple[EvidenceState, str]:
        """评估证据是否充分。

        Returns:
            (evidence_state, reason)
        """
        if not evidence:
            return EvidenceState.INSUFFICIENT, "无检索结果"

        # 1. Check facet coverage
        covered_facets = self._check_facet_coverage(evidence, required_facets)
        facet_ratio = len(covered_facets) / max(len(required_facets), 1)

        # 2. Check top rerank score
        top_score = max((e.rerank_score or e.rrf_score or 0) for e in evidence)

        # 3. Count formal rules
        formal_rules = sum(1 for e in evidence if e.doc_type in ("rule", "regulation"))

        # 4. Check authority
        has_high_authority = any(
            e.authority_level in (AuthorityLevel.OFFICIAL, AuthorityLevel.PROFESSIONAL)
            for e in evidence
        )

        # 5. Check for expired evidence
        expired = [e for e in evidence if self._is_expired(e)]
        if expired:
            return EvidenceState.PARTIAL, f"存在{len(expired)}条过期证据，已过滤"

        # 6. Check for contradictions
        has_contradiction = self._detect_contradictions(evidence)
        if has_contradiction:
            return EvidenceState.CONTRADICTORY, (
                "检测到证据冲突，建议人工确认。不同来源对同一问题的建议存在显著差异。"
            )

        # 7. Check if only low-authority auto-generated
        all_low_auth = all(
            e.authority_level in (AuthorityLevel.AGENT_GENERATED, AuthorityLevel.UNKNOWN)
            for e in evidence
        )
        if all_low_auth:
            return EvidenceState.INSUFFICIENT, (
                "仅有低权威自动生成内容，缺少正式规则或专业指南支持"
            )

        # 8. Sufficiency decision
        if facet_ratio >= 0.7 and top_score > 0.3 and (formal_rules > 0 or has_high_authority):
            return EvidenceState.SUFFICIENT, (
                f"证据充分：覆盖{len(covered_facets)}/{len(required_facets)}需求面，"
                f"包含{formal_rules}条正式规则，最高相关度{top_score:.3f}"
            )

        if facet_ratio >= 0.4 and top_score > 0.15:
            missing = set(required_facets) - covered_facets
            return EvidenceState.PARTIAL, (
                f"证据部分充分：覆盖{len(covered_facets)}/{len(required_facets)}需求面"
                + (f"，缺失: {', '.join(list(missing)[:3])}" if missing else "")
            )

        return EvidenceState.INSUFFICIENT, (
            f"证据不足：仅覆盖{len(covered_facets)}/{len(required_facets)}需求面，"
            f"最高相关度{top_score:.3f}"
        )

    def _check_facet_coverage(
        self, evidence: List[EvidenceItem], required_facets: List[str],
    ) -> set:
        """检查哪些 required_facets 被证据覆盖。"""
        covered = set()
        for e in evidence:
            content = (e.content + e.contextual_content).lower()
            for facet in required_facets:
                if facet in ("applicable_rules", "regulations"):
                    if e.doc_type in ("rule", "regulation"):
                        covered.add(facet)
                elif facet in ("dispatch_actions", "operational_guidance"):
                    if e.doc_type in ("dispatch_experience", "rule"):
                        covered.add(facet)
                elif facet == "similar_cases":
                    if e.doc_type == "event_report":
                        covered.add(facet)
                elif facet == "signal_config":
                    if "信号" in content or "配时" in content or "相位" in content:
                        covered.add(facet)
                elif facet == "responsible_units":
                    if any(kw in content for kw in ["部门", "单位", "交警", "急救", "联动"]):
                        covered.add(facet)
                elif facet == "statistics":
                    if any(kw in content for kw in ["统计", "数据", "趋势", "占比"]):
                        covered.add(facet)
                elif facet == "general_guidance":
                    covered.add(facet)
        return covered

    def _is_expired(self, evidence: EvidenceItem) -> bool:
        """检查证据是否过期。"""
        if evidence.effective_to is None:
            return False
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return evidence.effective_to < now

    def _detect_contradictions(self, evidence: List[EvidenceItem]) -> bool:
        """检测证据矛盾（启发性检测）。"""
        if len(evidence) < 2:
            return False

        # Simple heuristic: check for contradictory keywords
        has_positive = False
        has_negative = False

        for e in evidence:
            content = e.content.lower()
            if any(kw in content for kw in ["必须", "应当", "立即", "优先"]):
                has_positive = True
            if any(kw in content for kw in ["不建议", "不应", "禁止", "不可"]):
                has_negative = True

        # Contradiction if conflicting authorities disagree
        if has_positive and has_negative:
            # Check if from different documents
            doc_ids = set(e.document_id for e in evidence)
            if len(doc_ids) > 1:
                return True

        return False
