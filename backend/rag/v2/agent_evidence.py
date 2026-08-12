"""
RAG V2 Agent Evidence — 多 Agent 共享证据池 + 独立投影。

每个 Agent 获得独立 Evidence 投影：
- CongestionAgent: 拥堵规则、历史拥堵案例、信号优化、分流
- AccidentAgent: 事故应急、伤员救援、交通管制、清障
- SignalAgent: 信号规范、异常维护、配时策略
- PublicSafetyAgent: 学校、医院、行人、非机动车、应急通道
- DispatchAgent: 部门联动、警力、救援、公众提示
- FusionAgent: 只接收 Agent 选用的 Evidence 引用和摘要

Rules:
- Each domain agent gets max 4 evidence items
- Each agent has independent token budget
- Evidence written to AgentMessage.evidence_refs
- Collaboration Run detail can restore evidence_refs
- Agents may have different evidence
- No evidence → template fallback with explicit marker
- Context Projection continues with least privilege
- Does NOT break Phase 10 Memory injection
"""
from __future__ import annotations
from typing import Dict, List, Optional, Set

from backend.rag.v2.models import EvidenceItem, DocType


# ─── Agent domain profiles ──────────────────────────────────────────────────

AGENT_PROFILES = {
    "CongestionAgent": {
        "doc_types": ["rule", "dispatch_experience"],
        "event_types": ["拥堵"],
        "keywords": ["拥堵", "分流", "信号优化", "绿波", "排队", "疏导", "主干道", "快速路"],
        "max_evidence": 4,
    },
    "AccidentAgent": {
        "doc_types": ["rule", "dispatch_experience"],
        "event_types": ["事故"],
        "keywords": ["事故", "应急", "救援", "管制", "清障", "急救", "伤员", "拖车", "警戒"],
        "max_evidence": 4,
    },
    "SignalAgent": {
        "doc_types": ["rule", "dispatch_experience"],
        "event_types": ["信号灯异常"],
        "keywords": ["信号", "配时", "相位", "绿信比", "周期", "信号灯", "灯控", "维护"],
        "max_evidence": 4,
    },
    "PublicSafetyAgent": {
        "doc_types": ["rule", "dispatch_experience"],
        "event_types": ["行人闯入"],
        "keywords": ["学校", "医院", "行人", "非机动车", "应急通道", "学生", "安全", "过街"],
        "max_evidence": 4,
    },
    "DispatchAgent": {
        "doc_types": ["dispatch_experience", "rule"],
        "event_types": [],
        "keywords": ["联动", "警力", "救援", "部门", "协调", "公众提示", "媒体", "信息发布"],
        "max_evidence": 4,
    },
}


class SharedEvidencePool:
    """共享证据池 — 所有 Agent 共享的检索结果。"""

    def __init__(self):
        self._evidence: List[EvidenceItem] = []
        self._by_doc_type: Dict[str, List[EvidenceItem]] = {}
        self._by_event_type: Dict[str, List[EvidenceItem]] = {}

    def load(self, evidence: List[EvidenceItem]) -> None:
        """加载证据到池中。"""
        self._evidence = evidence
        self._by_doc_type = {}
        self._by_event_type = {}

        for e in evidence:
            dt = e.doc_type or "other"
            if dt not in self._by_doc_type:
                self._by_doc_type[dt] = []
            self._by_doc_type[dt].append(e)

            # Event type from content or metadata
            et = self._infer_event_type(e)
            if et:
                if et not in self._by_event_type:
                    self._by_event_type[et] = []
                self._by_event_type[et].append(e)

    def get_all(self) -> List[EvidenceItem]:
        return self._evidence

    def _infer_event_type(self, evidence: EvidenceItem) -> str:
        """从证据内容推断事件类型。"""
        content = (evidence.content + evidence.contextual_content).lower()
        type_keywords = {
            "拥堵": ["拥堵", "堵车", "排队", "缓行"],
            "事故": ["事故", "碰撞", "追尾", "撞车"],
            "信号灯异常": ["信号灯", "信号异常", "信号故障"],
            "行人闯入": ["行人闯入", "行人"],
            "施工占道": ["施工", "占道"],
            "违停": ["违停", "乱停"],
            "逆行": ["逆行"],
            "车辆滞留": ["滞留"],
        }
        for evt_type, keywords in type_keywords.items():
            if any(kw in content for kw in keywords):
                return evt_type
        return ""


class AgentEvidenceProjector:
    """为每个 Agent 投影其专属证据。"""

    def __init__(self, pool: Optional[SharedEvidencePool] = None):
        self.pool = pool or SharedEvidencePool()
        self._agent_selections: Dict[str, List[EvidenceItem]] = {}

    def set_pool(self, pool: SharedEvidencePool) -> None:
        self.pool = pool

    def project_for_agent(self, agent_name: str) -> List[EvidenceItem]:
        """为指定 Agent 投影证据。

        Args:
            agent_name: Agent 名称 (CongestionAgent, etc.)

        Returns:
            该 Agent 可见的证据列表（最多 max_evidence 条）
        """
        profile = AGENT_PROFILES.get(agent_name)
        if not profile:
            # Unknown agent: return top evidence
            selected = self.pool.get_all()[:4]
            self._agent_selections[agent_name] = selected
            return selected

        max_ev = profile["max_evidence"]
        doc_types = set(profile.get("doc_types", []))
        event_types = set(profile.get("event_types", []))
        keywords = set(profile.get("keywords", []))

        scored = []
        for ev in self.pool.get_all():
            score = 0.0

            # Match doc_type
            if ev.doc_type in doc_types:
                score += 3.0

            # Match event_type
            if any(et in (ev.content or "") for et in event_types):
                score += 2.0

            # Match keywords
            content_lower = (ev.content or "").lower()
            for kw in keywords:
                if kw in content_lower:
                    score += 0.5

            # Rerank/rrf score bonus
            if ev.rerank_score:
                score += float(ev.rerank_score) * 1.5
            elif ev.rrf_score:
                score += float(ev.rrf_score)

            if score > 0:
                scored.append((score, ev))

        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [ev for _, ev in scored[:max_ev]]

        self._agent_selections[agent_name] = selected
        return selected

    def get_agent_refs(self, agent_name: str) -> List[Dict]:
        """获取 Agent 的 evidence_refs（用于持久化）。"""
        evidence = self._agent_selections.get(agent_name, [])
        return [
            {
                "evidence_id": e.evidence_id,
                "chunk_id": e.chunk_id,
                "title": e.title,
                "doc_type": e.doc_type,
                "rerank_score": e.rerank_score,
                "rrf_score": e.rrf_score,
            }
            for e in evidence
        ]

    def project_for_fusion(self, agent_evidence_map: Dict[str, List[EvidenceItem]]) -> List[EvidenceItem]:
        """FusionAgent: 只接收其他 Agent 选用的 Evidence 摘要。

        不接收所有原始 Chunk。
        """
        fusion_evidence: List[EvidenceItem] = []
        seen_ids: Set[str] = set()

        for agent_name, evidence_list in agent_evidence_map.items():
            if agent_name == "FusionAgent":
                continue
            for ev in evidence_list:
                if ev.evidence_id not in seen_ids:
                    seen_ids.add(ev.evidence_id)
                    # Create summary version for Fusion
                    summary_ev = EvidenceItem(
                        evidence_id=ev.evidence_id,
                        chunk_id=ev.chunk_id,
                        document_id=ev.document_id,
                        title=f"[{agent_name}] {ev.title}",
                        section_path=ev.section_path,
                        doc_type=ev.doc_type,
                        content=ev.content[:300],
                        contextual_content=ev.contextual_content[:300],
                        authority_level=ev.authority_level,
                        effective_from=ev.effective_from,
                        effective_to=ev.effective_to,
                        retrieval_channels=ev.retrieval_channels,
                        rrf_score=ev.rrf_score,
                        rerank_score=ev.rerank_score,
                        source_uri=ev.source_uri,
                    )
                    fusion_evidence.append(summary_ev)

        # Cap at 6
        fusion_evidence.sort(key=lambda x: x.rerank_score or x.rrf_score or 0, reverse=True)
        return fusion_evidence[:6]
