"""
Knowledge REST API — Phase 16 Round 1

Provides read/write access to the knowledge document lifecycle:
  - List / detail / chunks
  - Create (ingest) with validation
  - Soft-delete
  - Single-document reindex
  - Index status + consistency check
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.knowledge.service import (
    KnowledgeError,
    check_consistency,
    create_document,
    delete_document,
    get_document_chunks,
    get_document_detail,
    get_index_status,
    list_documents,
    reindex_document,
)

router = APIRouter(prefix="/knowledge", tags=["Knowledge V1"])


# ═══════════════════════════════════════════════════════════════════════════════
# Request models
# ═══════════════════════════════════════════════════════════════════════════════

class CreateDocumentRequest(BaseModel):
    """创建/录入知识文档。"""
    name: str
    docType: str
    content: str
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# Document CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/documents", summary="列出知识文档")
async def api_list_documents(
    status: Optional[str] = Query(None, description="状态筛选: active/deleted/superseded/expired/draft"),
    doc_type: Optional[str] = Query(None, description="类型筛选: rule/dispatch_experience/event_report/..."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_deleted: bool = Query(False, description="是否包含已删除文档"),
):
    """列出知识文档（分页）。默认不包含已删除。"""
    return list_documents(
        status=status,
        doc_type=doc_type,
        limit=limit,
        offset=offset,
        include_deleted=include_deleted,
    )


@router.get("/documents/{document_id}", summary="获取文档详情")
async def api_get_document(document_id: str):
    """获取单个文档的元数据、内容及 chunk 数量。"""
    result = get_document_detail(document_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"文档 '{document_id}' 不存在")
    return result


@router.post("/documents", summary="创建/录入知识文档")
async def api_create_document(body: CreateDocumentRequest):
    """录入新的知识文档。

    支持 .md / .txt 文本内容。
    自动进行内容校验、hash 去重、分块、向量化和索引。
    """
    try:
        return create_document(
            name=body.name,
            doc_type=body.docType,
            content=body.content,
            metadata=body.metadata,
        )
    except KnowledgeError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.delete("/documents/{document_id}", summary="删除文档")
async def api_delete_document(document_id: str):
    """软删除文档。重复删除安全。"""
    try:
        return delete_document(document_id)
    except KnowledgeError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("/documents/{document_id}/reindex", summary="重建文档索引")
async def api_reindex_document(document_id: str):
    """对单个文档重新执行索引。幂等操作。"""
    try:
        return reindex_document(document_id)
    except KnowledgeError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# Chunks
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/documents/{document_id}/chunks", summary="查看文档分块")
async def api_get_chunks(
    document_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """获取文档的分块列表（分页）。"""
    result = get_document_chunks(document_id, limit=limit, offset=offset)
    if result is None:
        raise HTTPException(status_code=404, detail=f"文档 '{document_id}' 不存在")
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Index status + consistency
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/index/status", summary="索引状态")
async def api_index_status():
    """获取当前知识索引状态（只读）。"""
    return get_index_status()


@router.get("/index/consistency", summary="索引一致性检查")
async def api_index_consistency():
    """检查 SQLite ↔ Chroma 数据一致性（只读）。"""
    return check_consistency()
