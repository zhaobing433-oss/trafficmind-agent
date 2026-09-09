"""Phase 20 Round 1 — Real Data Sources 测试

覆盖：
  A. 知识库 TXT/MD 文件上传（temp RAG DB / temp Chroma / FakeEmbedding）
  B. 事件批量导入 POST /events/import（temp 主 DB）

数据安全：全部使用 temp 存储，绝不触碰生产 trafficmind.db / rag_v2.db / vector_db；
fixture 拆除时断言生产库行数未变化。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from typing import Any, Dict, Generator

import pytest
from fastapi.testclient import TestClient

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROD_DB = os.path.join(_BACKEND_DIR, "data", "trafficmind.db")
PROD_RAG_DB = os.path.join(_BACKEND_DIR, "data", "rag_v2", "rag_v2.db")


def _count_rows(db_path: str, table: str) -> int:
    """只读连接统计表行数（URI 模式，绝不创建/修改文件）。"""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures — 全部 temp 存储，生产数据零接触
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _isolate_main_db(monkeypatch):
    """隔离主 SQLite（trafficmind.db 的所有消费者都指向 temp 文件）。"""
    import backend.config as cfg
    import backend.tools.db_tools as db_tools

    prod_count = None
    if os.path.exists(PROD_DB):
        prod_count = _count_rows(PROD_DB, "event_records")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "trafficmind_test.db")
        monkeypatch.setattr(cfg, "DB_PATH", db_path)
        monkeypatch.setattr(db_tools, "DB_PATH", db_path)
        # chat_db 在模块导入时捕获 DB_PATH，需显式补丁（若已导入）
        import backend.chat.chat_db as chat_db
        monkeypatch.setattr(chat_db, "DB_PATH", db_path)
        yield db_path

    # 拆除断言：生产 event_records 行数不变
    if prod_count is not None:
        assert _count_rows(PROD_DB, "event_records") == prod_count, (
            "生产 trafficmind.db 的 event_records 被测试修改！"
        )


@pytest.fixture(autouse=True)
def _isolate_rag(monkeypatch):
    """隔离 RAG V2（temp rag_v2.db + temp Chroma + FakeEmbeddingProvider）。"""
    import backend.rag.v2.config as v2_config
    import backend.rag.v2.document_repository as doc_repo
    from backend.rag.v2.providers import FakeEmbeddingProvider

    prod_rag_count = None
    if os.path.exists(PROD_RAG_DB):
        prod_rag_count = _count_rows(PROD_RAG_DB, "rag_documents")

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "rag_v2_test.db")
        chroma_path = os.path.join(tmpdir, "test_chroma")

        monkeypatch.setattr(v2_config, "RAG_V2_DB_PATH", db_path)
        monkeypatch.setattr(doc_repo, "RAG_V2_DB_PATH", db_path)

        import backend.rag.v2.dense_index as dense_idx
        monkeypatch.setattr(dense_idx, "_VECTOR_DB_PATH", chroma_path)
        monkeypatch.setattr(dense_idx, "_get_vector_db_path", lambda: chroma_path)

        fake_provider = FakeEmbeddingProvider(dimension=384)
        monkeypatch.setattr(
            "backend.rag.v2.providers.get_embedding_provider",
            lambda: fake_provider,
        )
        monkeypatch.setattr(
            "backend.knowledge.service.get_embedding_provider",
            lambda: fake_provider,
        )

        doc_repo.init_db()
        yield

    # 拆除断言：生产 rag_documents 行数不变
    if prod_rag_count is not None:
        assert _count_rows(PROD_RAG_DB, "rag_documents") == prod_rag_count, (
            "生产 rag_v2.db 的 rag_documents 被测试修改！"
        )


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    """FastAPI TestClient（不进入 lifespan）。

    本文件只覆盖确定性 上传/导入 路径（均不依赖 lifespan）：
      - 主表由 db_tools 的 init_db() 惰性创建（save/get 前自动调用）
      - RAG 表由 _isolate_rag fixture 的 doc_repo.init_db() 创建
    不启动 lifespan 可避免 WaitScheduler/RunDriver 单例 asyncio.Event
    跨事件循环绑定问题（既有测试基建缺陷，不在 Phase 20 维护范围）。
    """
    from backend.app import app
    c = TestClient(app)
    yield c


# ═══════════════════════════════════════════════════════════════════════════════
# A. 知识库文件上传
# ═══════════════════════════════════════════════════════════════════════════════

TXT_CONTENT = (
    "## 高速匝道拥堵处置预案\n\n"
    "- 平均速度 < 20 km/h 时启动疏导\n"
    "- 排队超过 100 米协调信号配时\n\n"
    "### 恢复条件\n"
    "- 速度恢复至 30 km/h 以上\n"
    "- 排队长度降至 50 米以下\n"
)

MD_CONTENT = "# 学校周边拥堵\n\n## 措施\n1. 护学岗疏导\n2. 信号优先配时\n"


def test_upload_txt_creates_document_via_ingestion_pipeline(client):
    """TXT 上传 → 文档创建 → 既有摄取管道（分块/向量化）→ 列表可见。"""
    r = client.post(
        "/knowledge/documents/upload",
        files={"file": ("预案_ramp.txt", TXT_CONTENT.encode("utf-8"), "text/plain")},
        data={"doc_type": "rule"},
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "active"
    assert doc["chunkCount"] > 0
    assert doc["sourceUri"] == "upload:预案_ramp.txt"
    assert doc["docType"] == "rule"

    lst = client.get("/knowledge/documents").json()
    ids = [d["documentId"] for d in lst["documents"]]
    assert doc["documentId"] in ids


def test_upload_md_uses_default_doc_type(client):
    """MD 上传，未指定 doc_type → 默认 other，正常索引。"""
    r = client.post(
        "/knowledge/documents/upload",
        files={"file": ("school.md", MD_CONTENT.encode("utf-8"), "text/markdown")},
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["docType"] == "other"
    assert doc["status"] == "active"


def test_upload_pdf_rejected(client):
    """PDF 明确拒绝（400），不进入任何管道。"""
    r = client.post(
        "/knowledge/documents/upload",
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert r.status_code == 400
    assert "不支持的文件类型" in r.json()["detail"]


def test_upload_empty_file_rejected(client):
    """空文件 → 400 内容为空。"""
    r = client.post(
        "/knowledge/documents/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert r.status_code == 400
    assert "为空" in r.json()["detail"]


def test_upload_invalid_utf8_rejected(client):
    """非法 UTF-8 字节 → 400。"""
    r = client.post(
        "/knowledge/documents/upload",
        files={"file": ("bad.txt", b"\xff\xfe\x00\x9c\x9c", "text/plain")},
    )
    assert r.status_code == 400
    assert "UTF-8" in r.json()["detail"]


def test_upload_oversize_rejected(client):
    """超过 100KB 上限 → 413。"""
    big = ("x" * 100_001).encode("utf-8")
    r = client.post(
        "/knowledge/documents/upload",
        files={"file": ("big.txt", big, "text/plain")},
    )
    assert r.status_code == 413


def test_upload_invalid_doc_type_rejected(client):
    """非法 doc_type → 400（由 create_document 校验）。"""
    r = client.post(
        "/knowledge/documents/upload",
        files={"file": ("a.txt", TXT_CONTENT.encode("utf-8"), "text/plain")},
        data={"doc_type": "not_a_type"},
    )
    assert r.status_code == 400
    assert "文档类型" in r.json()["detail"]


def test_upload_duplicate_checksum_idempotent_then_version_bump(client):
    """同名同内容 → 幂等（不新建）；同名不同内容 → 版本升级。"""
    files = {"file": ("dup.md", MD_CONTENT.encode("utf-8"), "text/markdown")}
    r1 = client.post("/knowledge/documents/upload", files=files)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()
    assert d1["version"] == 1

    # 同名同内容重传 → 幂等返回既有文档，版本不变
    r2 = client.post("/knowledge/documents/upload", files=files)
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["documentId"] == d1["documentId"]
    assert d2["version"] == 1

    # 同名不同内容 → 同一 documentId，版本升级到 2
    content2 = MD_CONTENT + "\n新增：放学时段限速 30\n"
    r3 = client.post(
        "/knowledge/documents/upload",
        files={"file": ("dup.md", content2.encode("utf-8"), "text/markdown")},
    )
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["documentId"] == d1["documentId"]
    assert d3["version"] == 2
    assert d3["status"] == "active"


def test_upload_path_traversal_sanitized(client):
    """路径穿越文件名 → 仅保留 basename，source_id 确定性。"""
    r = client.post(
        "/knowledge/documents/upload",
        files={"file": ("../../../etc/evil.md", MD_CONTENT.encode("utf-8"), "text/markdown")},
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["name"] == "evil.md"
    assert doc["sourceUri"] == "upload:evil.md"
    expected_doc_id = "doc_" + hashlib.md5(b"upload:evil.md").hexdigest()[:16]
    assert doc["documentId"] == expected_doc_id


# ═══════════════════════════════════════════════════════════════════════════════
# B. 事件批量导入 /events/import
# ═══════════════════════════════════════════════════════════════════════════════

EVENT_A: Dict[str, Any] = {
    "eventId": "P20_EV_001",
    "eventType": "congestion",
    "roadName": "G50沪渝高速匝道",
    "avgSpeed": 8,
    "queueLength": 220,
    "duration": 700,
    "confidence": 0.9,
    "weather": "rain",
    "timePeriod": "morning_peak",
    "isMainRoad": True,
}

EVENT_B: Dict[str, Any] = {
    "eventId": "P20_EV_002",
    "eventType": "事故",  # 中文类型 → 归一化
    "roadName": "中山北路",
    "avgSpeed": 15,
    "queueLength": 80,
    "duration": 300,
    "confidence": 0.8,
}


def test_import_valid_events(client):
    """有效批量导入：确定性评分 + 中文类型归一化 + /history 可见。"""
    r = client.post("/events/import", json={"events": [EVENT_A, EVENT_B]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2
    assert body["imported"] == 2
    assert body["skipped"] == 0
    assert body["failed"] == 0

    hist = client.get("/history?limit=10").json()
    ids = {rec["eventId"] for rec in hist["records"]}
    assert {"P20_EV_001", "P20_EV_002"} <= ids

    d = client.get("/event/P20_EV_002").json()
    assert d["eventTypeCn"] == "事故"
    assert d["riskScore"] > 0
    assert d["status"] == "待派单"
    assert d["report"]  # 确定性模板报告非空


def test_import_duplicate_skipped_never_overwrite(client):
    """重复 eventId → skipped，绝不静默覆盖（内容不变）。"""
    assert client.post("/events/import", json={"events": [EVENT_A]}).json()["imported"] == 1
    before = client.get("/event/P20_EV_001").json()

    # 同 eventId 但内容完全不同 → 必须跳过，不覆盖
    modified = dict(EVENT_A, avgSpeed=1, queueLength=1, duration=1, weather="clear")
    r = client.post("/events/import", json={"events": [modified]})
    body = r.json()
    assert body["imported"] == 0
    assert body["skipped"] == 1

    after = client.get("/event/P20_EV_001").json()
    assert after["riskScore"] == before["riskScore"]
    assert after["avgSpeed"] == before["avgSpeed"] == 8


def test_import_per_item_fail_closed(client):
    """逐条 fail-closed：坏条目失败不影响其他条目。"""
    r = client.post("/events/import", json={"events": [
        {"eventId": "P20_BAD_001", "roadName": "X"},  # 缺核心字段
        dict(EVENT_A, eventId="P20_OK_001"),          # 有效
    ]})
    body = r.json()
    assert body["imported"] == 1
    assert body["failed"] == 1
    by_id = {res["eventId"]: res for res in body["results"]}
    assert by_id["P20_BAD_001"]["status"] == "failed"
    assert "缺少核心字段" in by_id["P20_BAD_001"]["message"]
    assert by_id["P20_OK_001"]["status"] == "imported"


def test_import_empty_event_id_failed(client):
    """空 eventId → 逐条 failed。"""
    r = client.post("/events/import", json={"events": [dict(EVENT_A, eventId="")]})
    body = r.json()
    assert body["imported"] == 0
    assert body["failed"] == 1
    assert body["results"][0]["status"] == "failed"


def test_import_strips_unknown_fields(client):
    """仅 Event 模型字段持久化，未知字段被白名单过滤。"""
    ev = dict(EVENT_A, eventId="P20_EV_003", hackerField="evil", anotherUnknown=123)
    r = client.post("/events/import", json={"events": [ev]})
    assert r.json()["imported"] == 1

    d = client.get("/event/P20_EV_003").json()
    raw = d.get("rawEvent")
    if isinstance(raw, str):
        raw = json.loads(raw)
    assert "hackerField" not in raw
    assert "anotherUnknown" not in raw
    # fullResult 中也只应有标准字段
    full = d.get("fullResult")
    if isinstance(full, str):
        full = json.loads(full)
    assert "hackerField" not in full.get("standardEvent", {})


def test_import_batch_cap(client):
    """超过批量上限 200 → 400。"""
    events = [dict(EVENT_A, eventId=f"P20_CAP_{i:03d}") for i in range(201)]
    r = client.post("/events/import", json={"events": events})
    assert r.status_code == 400
    assert "200" in r.json()["detail"]
