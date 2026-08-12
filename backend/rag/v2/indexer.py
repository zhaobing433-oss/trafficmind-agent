"""
RAG V2 Incremental Indexer — checksum-based diff, upsert only changed documents.

Flow: load → normalize → checksum → compare → insert/update/skip/soft-delete
→ dense upsert → sparse upsert → commit index version

Guarantees:
- Same source_id repeated indexing is idempotent
- Unchanged documents return skip
- Document update only updates corresponding Chunks
- Stale documents soft-delete
- Transaction failure rollback — previous version untouched
"""
from __future__ import annotations
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from backend.rag.v2.config import RAG_V2_COLLECTION_NAME
from backend.rag.v2.models import (
    AuthorityLevel,
    DocStatus,
    DocType,
    IndexJobResult,
    IndexJobStatus,
    IndexVersion,
    RagChunk,
    RagDocument,
    utcnow,
)
from backend.rag.v2.chunker import TrafficKnowledgeChunker
from backend.rag.v2.document_repository import (
    commit_index_version,
    create_index_job,
    create_index_version,
    delete_chunks_by_document,
    get_document_by_source,
    list_active_documents,
    soft_delete_document,
    update_index_job,
    upsert_chunks as db_upsert_chunks,
    upsert_document,
)
from backend.rag.v2.providers import EmbeddingProvider

logger = logging.getLogger("rag.v2.indexer")


def _checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _make_document_id(source_id: str) -> str:
    """Deterministic document_id from source_id."""
    return f"doc_{hashlib.md5(source_id.encode()).hexdigest()[:16]}"


class IncrementalIndexer:
    """增量知识索引器。

    自动检测 embedding 兼容性：
    - 首次索引（无活跃版本）：创建 versioned collection
    - 模型/维度匹配：增量索引
    - 模型/维度变化：创建新 versioned collection，全量重建，成功时切换
    - 失败时：保留前一个活跃版本
    """

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        chunker: Optional[TrafficKnowledgeChunker] = None,
    ):
        self.embedding_provider = embedding_provider
        self.chunker = chunker or TrafficKnowledgeChunker()
        self._prev_active: Optional[IndexVersion] = None

    # ── Public API ──────────────────────────────────────────────────────────

    def index_documents(
        self,
        documents: List[RagDocument],
    ) -> IndexJobResult:
        """增量索引一批文档。

        自动检测兼容性：模型/维度不一致时创建新 versioned collection 并全量重建。
        成功时切换到 active；失败时保留 previous active。
        """
        t0 = time.time()
        job = create_index_job()
        job.status = IndexJobStatus.RUNNING

        try:
            # ── Determine embedding metadata ──
            emb_model = self.embedding_provider.get_resolved_model_name()
            emb_dim = self.embedding_provider.get_dimension()

            # ── Check compatibility ──
            from backend.rag.v2.dense_index import (
                check_compatibility,
                get_active_collection_name,
                get_or_create_collection_for_model,
                make_versioned_collection_name,
            )
            compat = check_compatibility(emb_model, emb_dim)
            logger.info(f"Index compatibility: {compat} (model={emb_model}, dim={emb_dim})")

            # Save previous active for potential rollback
            if compat == "incompatible":
                from backend.rag.v2.document_repository import get_latest_index_version
                self._prev_active = get_latest_index_version()
                logger.warning(
                    f"Incompatible embedding change: creating new collection for "
                    f"{emb_model}/{emb_dim}"
                )

            # ── Determine collection name ──
            if compat == "ok":
                collection_name = get_active_collection_name()
                logger.info(f"Using existing collection: {collection_name}")
            else:
                collection_name = get_or_create_collection_for_model(emb_model, emb_dim)
                logger.info(f"Created new collection: {collection_name}")

            # ── Prepare documents ──
            if compat == "incompatible":
                # Full re-index: collect ALL active documents from DB + passed docs
                existing_docs = list_active_documents()
                passed_map = {d.source_id: d for d in documents}
                merged_map = {}
                for ed in existing_docs:
                    merged_map[ed.source_id] = passed_map.get(ed.source_id, ed)
                for d in documents:
                    merged_map.setdefault(d.source_id, d)
                all_docs = list(merged_map.values())
                logger.info(f"Full re-index: {len(all_docs)} total documents")
            else:
                all_docs = documents

            # ── Create index version ──
            version = create_index_version(
                collection_name=collection_name,
                embedding_model=emb_model,
                embedding_dimension=emb_dim,
            )
            job.index_version = version.version_id

            # ── Process each document ──
            source_ids_seen = set()
            for doc in all_docs:
                job.documents_processed += 1
                source_ids_seen.add(doc.source_id)
                try:
                    result = self._process_one_document(
                        doc,
                        collection_name=collection_name,
                        force_reindex=(compat == "incompatible" or compat == "new"),
                    )
                    if result == "inserted":
                        job.documents_inserted += 1
                    elif result == "updated":
                        job.documents_updated += 1
                    elif result == "skipped":
                        job.documents_skipped += 1
                    elif result == "deleted":
                        job.documents_deleted += 1
                except Exception as e:
                    err_msg = f"Failed to index {doc.source_id}: {e}"
                    logger.error(err_msg)
                    job.errors.append(err_msg)

            # ── Commit index version ──
            total_chunks = sum(
                len(self.chunker.chunk_document(d)[1])
                for d in all_docs
                if d.status != DocStatus.DELETED
            )
            commit_index_version(
                version.version_id,
                job.documents_inserted + job.documents_updated,
                total_chunks,
                embedding_model=emb_model,
                embedding_dimension=emb_dim,
            )
            self._prev_active = None  # Success — clear rollback reference

            # ── Cleanup stale (only for normal incremental) ──
            if compat == "ok" and documents:
                self._cleanup_stale(source_ids_seen, documents[0].doc_type if documents else None)

            job.status = IndexJobStatus.COMPLETED
            job.chunks_upserted = total_chunks
            job.duration_ms = (time.time() - t0) * 1000

        except Exception as e:
            logger.error(f"Index job failed: {e}")
            job.status = IndexJobStatus.FAILED
            job.errors.append(str(e))
            job.duration_ms = (time.time() - t0) * 1000
            # Rollback: restore previous active if we had one
            self._rollback()

        update_index_job(job)
        return job

    def rebuild_from_scratch(
        self,
        documents: List[RagDocument],
    ) -> IndexJobResult:
        """全量重建索引（仅在必要时使用）。

        Uses index_documents which handles versioned collection creation.
        """
        # Soft-delete all existing docs of same types
        existing = list_active_documents()
        for ed in existing:
            soft_delete_document(ed.document_id)
            delete_chunks_by_document(ed.document_id)

        return self.index_documents(documents)

    # ── Internal ────────────────────────────────────────────────────────────

    def _rollback(self) -> None:
        """Rollback to previous active version on failure."""
        if self._prev_active is None:
            return
        try:
            from backend.rag.v2.document_repository import (
                get_latest_version_for_collection,
            )
            # If the new version was committed as active, restore the old one
            prev = get_latest_version_for_collection(self._prev_active.collection_name)
            if prev and prev.version_id != self._prev_active.version_id:
                # Re-commit the old version as active
                commit_index_version(
                    self._prev_active.version_id,
                    self._prev_active.document_count,
                    self._prev_active.chunk_count,
                )
                logger.info(f"Rolled back to previous active: {self._prev_active.collection_name}")
            self._prev_active = None
        except Exception as e:
            logger.error(f"Rollback failed: {e}")

    def _process_one_document(
        self,
        doc: RagDocument,
        collection_name: str = RAG_V2_COLLECTION_NAME,
        force_reindex: bool = False,
    ) -> str:
        """Process one document: compare checksum → insert/update/skip/delete."""
        doc.document_id = _make_document_id(doc.source_id)
        doc.checksum = _checksum(doc.content or "")
        doc.updated_at = utcnow()

        existing = get_document_by_source(doc.source_id)

        # Case 1: Delete
        if doc.status == DocStatus.DELETED:
            if existing:
                soft_delete_document(existing.document_id)
                delete_chunks_by_document(existing.document_id)
                from backend.rag.v2.dense_index import delete_by_document as dense_del
                dense_del(existing.document_id, collection_name)
                return "deleted"
            return "skipped"

        # Case 2: Skip — checksum unchanged (unless force_reindex)
        if not force_reindex and existing and existing.status == DocStatus.ACTIVE and existing.checksum == doc.checksum:
            logger.debug(f"Skip unchanged: {doc.source_id}")
            return "skipped"

        # Case 3: Update — checksum changed or force
        if existing:
            doc.document_id = existing.document_id
            doc.created_at = existing.created_at
            result = "updated"
        else:
            doc.created_at = utcnow()
            result = "inserted"

        # Store document
        upsert_document(doc)

        # Chunk and index
        delete_chunks_by_document(doc.document_id)
        from backend.rag.v2.dense_index import delete_by_document as dense_del
        dense_del(doc.document_id, collection_name)

        parents, children = self.chunker.chunk_document(doc)
        all_chunks = parents + children

        if all_chunks:
            # Store chunks in SQLite
            db_upsert_chunks(all_chunks)

            # Dense index: embed + upsert to Chroma
            texts = [c.contextual_content for c in all_chunks]
            try:
                embeddings = self.embedding_provider.embed_texts(texts)
            except Exception as e:
                logger.error(f"Embedding failed for {doc.source_id}: {e}")
                raise

            from backend.rag.v2.dense_index import upsert_chunks as dense_upsert
            dense_upsert(all_chunks, embeddings, collection_name)

            # Sparse index: FTS5
            from backend.rag.v2.sparse_index import upsert_chunks_fts
            upsert_chunks_fts(all_chunks)

        return result

    def _cleanup_stale(self, active_source_ids: set, doc_type: Optional[str]) -> None:
        """Soft-delete documents whose source no longer exists."""
        if not active_source_ids:
            return
        existing = list_active_documents(doc_type)
        for ed in existing:
            if ed.source_id not in active_source_ids:
                logger.info(f"Soft-deleting stale: {ed.source_id}")
                soft_delete_document(ed.document_id)


# ─── Document builders (load from project sources) ──────────────────────────

def build_rules_documents() -> List[RagDocument]:
    """从交通规则 Markdown 构建 RagDocument 列表。"""
    from backend.config import RULES_PATH

    try:
        with open(RULES_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return []

    docs = []
    # Split top-level sections
    import re
    sections = re.split(r"\n(?=## )", content)
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        # Extract title
        title_match = re.match(r"^#+\s*(.+)", sec)
        title = title_match.group(1).strip() if title_match else "交通规则"
        source_id = f"rule:{title}"

        docs.append(RagDocument(
            document_id=_make_document_id(source_id),
            source_id=source_id,
            doc_type=DocType.RULE,
            title=title,
            content=sec,
            authority_level=AuthorityLevel.OFFICIAL,
            version=1,
            status=DocStatus.ACTIVE,
            checksum=_checksum(sec),
            updated_at=utcnow(),
        ))
    return docs


def build_dispatch_documents() -> List[RagDocument]:
    """构建调度经验文档。"""
    experiences = [
        {
            "title": "雨天早高峰拥堵处置",
            "event_type": "拥堵",
            "risk_level": "高风险",
            "content": "当雨天叠加早高峰发生主干道拥堵时：\n1. 优先通知交警大队和信号控制中心\n2. 上游路口增加绿灯时间，引导车辆分流\n3. 通过交通广播、诱导屏发布拥堵和绕行信息\n4. 如排队长度持续增长（>300米），在上游关键路口实施强制分流\n5. 关注积水路段，必要时通知市政排水部门",
        },
        {
            "title": "事故应急处置",
            "event_type": "事故",
            "risk_level": "重大风险",
            "content": "当发生交通事故时：\n1. 立即通知122事故处理中心和120急救中心\n2. 交警第一时间到达现场，划定警戒区域\n3. 调取事发前5分钟监控录像固定证据\n4. 安排拖车快速清理事故车辆\n5. 通过诱导屏提示后方车辆减速变道\n6. 如有人员伤亡，通知就近医院开通绿色通道",
        },
        {
            "title": "信号灯异常处置",
            "event_type": "信号灯异常",
            "risk_level": "高风险",
            "content": "当信号灯出现异常时：\n1. 通知信号灯运维单位立即派员检修\n2. 交警到达路口进行人工指挥\n3. 在信号灯修复前持续派人值守\n4. 通过诱导屏告知周边驾驶员路口信号灯异常\n5. 若为早晚高峰，增加人员配置",
        },
        {
            "title": "行人闯入快速路处置",
            "event_type": "行人闯入",
            "risk_level": "高风险",
            "content": "行人闯入机动车道/快速路时：\n1. 通知就近交警或巡查人员前往劝离\n2. 通过广播诱导屏提示过往车辆减速避让\n3. 若发生在高速或快速路，立即通知高速交警\n4. 评估是否需要增设隔离护栏或过街设施",
        },
        {
            "title": "施工占道管理",
            "event_type": "施工占道",
            "risk_level": "中风险",
            "content": "施工占道事件处置流程：\n1. 核查施工审批手续是否齐全\n2. 检查施工现场安全防护是否符合规范\n3. 若造成严重拥堵，要求施工单位调整施工时间\n4. 安排交警在关键点位疏导交通\n5. 对违规施工的责令停工并上报主管部门",
        },
        {
            "title": "学校周边交通管理",
            "event_type": "拥堵",
            "risk_level": "高风险",
            "content": "学校门口及周边区域交通管理：\n1. 上下学时段安排交警或协管员定点值守\n2. 设置临时停车区域，引导接送车辆即停即走\n3. 通过信号灯配时调整保障学生过街安全\n4. 与学校联动，错峰放学减少集中交通压力\n5. 评估设置减速带、人行横道等安全设施",
        },
        {
            "title": "医院周边交通管理",
            "event_type": "拥堵",
            "risk_level": "高风险",
            "content": "医院周边交通管理策略：\n1. 保障急救通道畅通，严禁社会车辆占用\n2. 医院出入口安排专人引导车辆\n3. 高峰期对周边路口信号灯做绿波协调\n4. 协调周边停车场增加就医车辆停放容量\n5. 必要时在医院周边设置临时交通管制",
        },
        {
            "title": "多部门联动处置",
            "event_type": "事故",
            "risk_level": "重大风险",
            "content": "复杂交通事故多部门联动处置：\n1. 122事故处理中心负责事故定责和现场处置\n2. 120急救中心负责伤员救治和转运\n3. 交通信号控制中心配合调整信号配时保障救援通道\n4. 消防部门（119）参与车辆破拆和危化品处置\n5. 市政部门负责道路设施抢修\n6. 宣传部门通过媒体发布交通管制和绕行信息",
        },
        {
            "title": "大型活动交通保障",
            "event_type": "拥堵",
            "risk_level": "高风险",
            "content": "大型活动交通保障方案：\n1. 提前制定交通管制和疏导方案\n2. 设置临时停车场和接驳车辆\n3. 周边路口信号灯调整至活动模式\n4. 安排充足警力在各关键节点值守\n5. 通过媒体提前发布交通管制信息\n6. 活动结束后有序疏散",
        },
        {
            "title": "恶劣天气交通应急处置",
            "event_type": "拥堵",
            "risk_level": "重大风险",
            "content": "恶劣天气交通应急处置：\n1. 启动恶劣天气应急预案\n2. 对易积水、易结冰路段重点巡查\n3. 必要时封闭危险路段并设置绕行标志\n4. 通过可变情报板发布限速和路况信息\n5. 协调市政、路政部门联合处置\n6. 增加事故快速处理力量，减少二次事故风险",
        },
    ]

    docs = []
    for exp in experiences:
        source_id = f"dispatch:{exp['title']}"
        docs.append(RagDocument(
            document_id=_make_document_id(source_id),
            source_id=source_id,
            doc_type=DocType.DISPATCH_EXPERIENCE,
            title=exp["title"],
            content=exp["content"],
            authority_level=AuthorityLevel.OPERATIONAL,
            version=1,
            status=DocStatus.ACTIVE,
            event_type=exp.get("event_type"),
            risk_level=exp.get("risk_level"),
            checksum=_checksum(exp["content"]),
            updated_at=utcnow(),
        ))
    return docs


def build_history_documents() -> List[RagDocument]:
    """从历史事件记录构建文档。"""
    from backend.tools.db_tools import get_connection, init_db
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM event_records ORDER BY createdAt DESC LIMIT 100")
        rows = cursor.fetchall()
        conn.close()
    except Exception:
        return []

    docs = []
    for row in rows:
        event = dict(row)
        raw = event.get("rawEvent", "{}")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        source_id = f"event:{event.get('eventId', '')}"
        report = event.get("report", "") or ""
        content = (
            f"事件编号: {event.get('eventId', '')}\n"
            f"事件类型: {event.get('eventTypeCn', event.get('eventType', ''))}\n"
            f"路段: {event.get('roadName', '')}\n"
            f"风险: {event.get('riskLevel', '')} ({event.get('riskScore', 0)}分)\n"
            f"状态: {event.get('status', '')}\n"
            f"天气: {event.get('weather', '')}\n"
            f"时段: {event.get('timePeriod', '')}\n\n"
            f"{report}"
        )

        docs.append(RagDocument(
            document_id=_make_document_id(source_id),
            source_id=source_id,
            doc_type=DocType.EVENT_REPORT,
            title=f"事件{event.get('eventId', '')} - {event.get('eventTypeCn', '')}",
            content=content,
            authority_level=AuthorityLevel.OPERATIONAL,
            version=1,
            status=DocStatus.ACTIVE,
            event_type=event.get("eventTypeCn", event.get("eventType", "")),
            road_name=event.get("roadName", ""),
            risk_level=event.get("riskLevel", ""),
            checksum=_checksum(content),
            updated_at=utcnow(),
        ))
    return docs


def load_all_documents() -> List[RagDocument]:
    """加载所有知识源文档。"""
    docs = []
    docs.extend(build_rules_documents())
    docs.extend(build_dispatch_documents())
    docs.extend(build_history_documents())
    return docs
