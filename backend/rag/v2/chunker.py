"""
TrafficKnowledgeChunker — 上下文化 Parent-Child 分块策略。

规则文档: 文档 → H1 → H2 → H3 → 条款/列表
历史案例: case_facts / case_action / case_outcome

每个 child chunk 添加 Context Prefix:
  文档：
  章节：
  适用事件：
  权威等级：
  版本：
  有效期：
  正文：
"""
from __future__ import annotations
import hashlib
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from backend.rag.v2.config import (
    RAG_CHILD_MIN_CHARS,
    RAG_CHILD_MAX_CHARS,
    RAG_PARENT_MIN_CHARS,
    RAG_PARENT_MAX_CHARS,
    RAG_CHUNK_OVERLAP_CHARS,
)
from backend.rag.v2.models import (
    AuthorityLevel,
    DocType,
    RagChunk,
    RagDocument,
    utcnow,
)


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class TrafficKnowledgeChunker:
    """交通领域知识分块器 — 确定性 Parent-Child 分块 + Context Prefix。"""

    def __init__(
        self,
        child_min_chars: int = RAG_CHILD_MIN_CHARS,
        child_max_chars: int = RAG_CHILD_MAX_CHARS,
        parent_min_chars: int = RAG_PARENT_MIN_CHARS,
        parent_max_chars: int = RAG_PARENT_MAX_CHARS,
        overlap_chars: int = RAG_CHUNK_OVERLAP_CHARS,
    ):
        self.child_min = child_min_chars
        self.child_max = child_max_chars
        self.parent_min = parent_min_chars
        self.parent_max = parent_max_chars
        self.overlap = overlap_chars

    # ── Public API ──────────────────────────────────────────────────────────

    def chunk_document(self, doc: RagDocument) -> Tuple[List[RagChunk], List[RagChunk]]:
        """返回 (parent_chunks, child_chunks)。"""
        if doc.doc_type in (DocType.EVENT_REPORT, DocType.CASE):
            return self._chunk_case(doc)
        elif doc.doc_type in (DocType.DAILY_REPORT, DocType.WEEKLY_REPORT):
            return self._chunk_report(doc)
        else:
            return self._chunk_rules(doc)

    def build_context_prefix(self, doc: RagDocument, section_path: str) -> str:
        """构建确定性 Context Prefix。"""
        parts = [
            f"文档：{doc.title}",
            f"章节：{section_path or '全文'}",
        ]
        if doc.event_type:
            parts.append(f"适用事件：{doc.event_type}")
        parts.append(f"权威等级：{doc.authority_level}")
        parts.append(f"版本：v{doc.version}")
        if doc.effective_from or doc.effective_to:
            eff = f"{doc.effective_from.strftime('%Y-%m-%d') if doc.effective_from else '无'}"
            exp = f"{doc.effective_to.strftime('%Y-%m-%d') if doc.effective_to else '无'}"
            parts.append(f"有效期：{eff} ~ {exp}")
        parts.append("正文：")
        return "\n".join(parts)

    def build_contextual_content(self, doc: RagDocument, section_path: str, raw: str) -> str:
        """完整 contextual_content = context_prefix + raw_content。"""
        prefix = self.build_context_prefix(doc, section_path)
        return f"{prefix}\n{raw}"

    # ── Rule document chunking ──────────────────────────────────────────────

    def _chunk_rules(self, doc: RagDocument) -> Tuple[List[RagChunk], List[RagChunk]]:
        """规则文档：H1→parent, H2/H3→child。"""
        content = doc.content
        sections = self._split_by_headers(content)
        parents: List[RagChunk] = []
        children: List[RagChunk] = []
        p_idx, c_idx = 0, 0

        for sec_level, sec_title, sec_body in sections:
            sec_path = sec_title
            # Parent chunk from H1 sections
            if sec_level >= 1 and len(sec_body) >= self.parent_min:
                parent = self._make_chunk(
                    doc, f"{doc.document_id}_p{p_idx}",
                    None, sec_path, sec_body, doc.content, p_idx,
                )
                parents.append(parent)
                p_idx += 1

            # Child chunks — split sub-sections
            sub_children = self._split_into_children(doc, sec_body, sec_path, c_idx)
            children.extend(sub_children)
            c_idx += len(sub_children)

        return parents, children

    def _split_by_headers(self, content: str) -> List[Tuple[int, str, str]]:
        """按 Markdown headers 拆分，返回 (level, title, body)。"""
        lines = content.split("\n")
        sections: List[Tuple[int, str, str]] = []
        current_level = None
        current_title = ""
        current_lines: List[str] = []

        for line in lines:
            m = re.match(r"^(#{1,6})\s+(.+)", line)
            if m:
                # Save previous section
                if current_title or current_lines:
                    body = "\n".join(current_lines).strip()
                    sections.append((current_level or 0, current_title, body))
                level = len(m.group(1))
                current_title = m.group(2).strip()
                current_level = level
                current_lines = []
            else:
                current_lines.append(line)

        # Last section
        if current_title or current_lines:
            body = "\n".join(current_lines).strip()
            sections.append((current_level or 0, current_title, body))

        return sections

    def _split_into_children(
        self, doc: RagDocument, body: str, parent_path: str, start_idx: int,
    ) -> List[RagChunk]:
        """将 body 拆分为 child-sized 块，保留 overlap。"""
        if not body.strip():
            return []
        children: List[RagChunk] = []
        paragraphs = self._split_paragraphs(body)
        current_text = ""
        idx = start_idx

        for para in paragraphs:
            if len(current_text) + len(para) <= self.child_max:
                current_text += ("\n" if current_text else "") + para
            else:
                if len(current_text) >= self.child_min:
                    children.append(self._make_child(doc, current_text, parent_path, idx))
                    idx += 1
                    # Overlap: keep last portion
                    if self.overlap > 0 and len(current_text) > self.overlap:
                        current_text = current_text[-self.overlap:] + "\n" + para
                    else:
                        current_text = para
                else:
                    current_text += ("\n" if current_text else "") + para
                    if len(current_text) >= self.child_max:
                        children.append(self._make_child(doc, current_text, parent_path, idx))
                        idx += 1
                        current_text = ""

        # Emit the final chunk for ANY non-empty content — short documents
        # must still produce at least one retrievable chunk (Phase 16 Round 2).
        if current_text.strip():
            children.append(self._make_child(doc, current_text.strip(), parent_path, idx))

        return children

    def _split_paragraphs(self, body: str) -> List[str]:
        """按段落/列表项拆分。"""
        # Split on double newline (paragraphs) or single newline for list items
        raw_parts = re.split(r"\n{2,}", body)
        paragraphs = []
        for part in raw_parts:
            part = part.strip()
            if not part:
                continue
            # For list items, split into individual items
            if re.match(r"^[\d一二三四五六七八九十]+[\.、\)）]", part):
                items = re.split(r"\n(?=[\d一二三四五六七八九十]+[\.、\)）])", part)
                paragraphs.extend(i.strip() for i in items if i.strip())
            else:
                paragraphs.append(part)
        return paragraphs

    # ── Case/Event Report chunking ──────────────────────────────────────────

    def _chunk_case(self, doc: RagDocument) -> Tuple[List[RagChunk], List[RagChunk]]:
        """历史案例按 facts/action/outcome 拆分。"""
        content = doc.content
        facts, actions, outcomes = self._extract_case_sections(content)

        parents: List[RagChunk] = []
        children: List[RagChunk] = []

        # Parent = full case
        parent = self._make_chunk(
            doc, f"{doc.document_id}_p0",
            None, "完整案例", content, content, 0,
        )
        parents.append(parent)

        sections = [
            ("case_facts", "案例事实", facts),
            ("case_action", "处置措施", actions),
            ("case_outcome", "处置结果", outcomes),
        ]
        for i, (sec_type, sec_label, sec_text) in enumerate(sections):
            if not sec_text:
                continue
            section_path = f"案例 > {sec_label}"
            child = self._make_child(doc, sec_text, section_path, i)
            children.append(child)

        return parents, children

    def _extract_case_sections(self, content: str) -> Tuple[str, str, str]:
        """从案例文本提取 facts/action/outcome。"""
        facts, actions, outcomes = "", "", ""
        # Try to find labeled sections
        patterns = [
            (r"(?:事实|经过|背景|案情)[：:]\s*", "facts"),
            (r"(?:处置|措施|行动|方案)[：:]\s*", "actions"),
            (r"(?:结果|效果|总结|经验)[：:]\s*", "outcomes"),
        ]
        lines = content.split("\n")
        current = "facts"
        for line in lines:
            for pat, label in patterns:
                if re.search(pat, line):
                    current = label
                    line = re.sub(pat, "", line)
                    break
            if current == "facts":
                facts += line + "\n"
            elif current == "actions":
                actions += line + "\n"
            else:
                outcomes += line + "\n"
        # If no sections found, treat first half as facts, rest as actions
        if not facts.strip() and content.strip():
            mid = len(content) // 2
            facts = content[:mid]
            actions = content[mid:]
        return facts.strip(), actions.strip(), outcomes.strip()

    # ── Report chunking ─────────────────────────────────────────────────────

    def _chunk_report(self, doc: RagDocument) -> Tuple[List[RagChunk], List[RagChunk]]:
        """日报/周报：按日期或统计项拆分。"""
        return self._chunk_rules(doc)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _make_chunk(
        self, doc: RagDocument, chunk_id: str, parent_id: Optional[str],
        section_path: str, raw: str, full_doc_content: str, index: int,
    ) -> RagChunk:
        raw = raw.strip()
        ctx = self.build_contextual_content(doc, section_path, raw)
        return RagChunk(
            chunk_id=chunk_id,
            document_id=doc.document_id,
            parent_chunk_id=parent_id,
            section_path=section_path,
            raw_content=raw,
            contextual_content=ctx,
            token_count=len(raw),  # approximate: char count
            chunk_index=index,
            doc_type=doc.doc_type,
            event_type=doc.event_type,
            road_name=doc.road_name,
            risk_level=doc.risk_level,
            authority_level=doc.authority_level,
            version=doc.version,
            effective_from=doc.effective_from,
            effective_to=doc.effective_to,
            region_id=doc.region_id,
            road_id=doc.road_id,
            intersection_id=doc.intersection_id,
            grounding_scope=doc.grounding_scope,
            checksum=_checksum(raw),
            created_at=utcnow(),
            updated_at=utcnow(),
        )

    def _make_child(
        self, doc: RagDocument, raw: str, section_path: str, index: int,
        parent_id: Optional[str] = None,
    ) -> RagChunk:
        child_id = f"{doc.document_id}_c{index}"
        return self._make_chunk(doc, child_id, parent_id, section_path, raw, doc.content, index)
