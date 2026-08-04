"""
RAG V2 Provider 接口 — Embedding + Reranker + Fake implementations for testing.

Design rules:
- Explicit embeddings passed to Chroma (NEVER rely on Chroma's built-in embedder)
- Production mode MUST NOT silently fall back to hash embeddings
- Hash embeddings only allowed for tests or explicit dev mode
- Model lazy-load on first use
- Degraded state returned with clear reason
"""
from __future__ import annotations
import hashlib
import logging
from abc import ABC, abstractmethod
from typing import List, Optional

from backend.rag.v2.config import (
    RAG_EMBEDDING_MODEL,
    RAG_EMBEDDING_DEVICE,
    RAG_EMBEDDING_BATCH_SIZE,
    RAG_RERANKER_MODEL,
    RAG_RERANKER_DEVICE,
    RAG_ALLOW_MODEL_DOWNLOAD,
    RAG_ALLOW_HASH_FALLBACK,
    RAG_MODEL_CACHE_DIR,
)

logger = logging.getLogger("rag.v2.providers")


# ─── Embedding Provider ──────────────────────────────────────────────────────

class EmbeddingProvider(ABC):
    """Embedding 模型抽象接口。"""

    @abstractmethod
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """将文本列表编码为向量列表。"""
        ...

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """将单条文本编码为向量。"""
        ...

    @abstractmethod
    def get_dimension(self) -> int:
        """返回向量维度。"""
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """返回配置的模型名称（如 Qwen/Qwen3-Embedding-0.6B）。"""
        ...

    @abstractmethod
    def get_resolved_model_name(self) -> str:
        """返回实际执行的模型/Provider标识。

        - 正常加载时：与 get_model_name() 相同
        - 降级时：如 "hash-fallback-384" 表示使用 hash 降级
        """
        ...

    @abstractmethod
    def is_degraded(self) -> bool:
        """是否处于降级状态。"""
        ...

    @abstractmethod
    def get_degraded_reason(self) -> str:
        """降级原因。"""
        ...


# ─── Reranker Provider ───────────────────────────────────────────────────────

class RerankerProvider(ABC):
    """Cross-Encoder Reranker 抽象接口。"""

    @abstractmethod
    def rerank(
        self,
        query: str,
        documents: List[str],
        top_k: int = 25,
    ) -> List[float]:
        """对文档列表重新排序，返回每个文档的得分列表（顺序不变）。"""
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """返回模型名称。"""
        ...

    @abstractmethod
    def is_degraded(self) -> bool:
        """是否处于降级状态。"""
        ...


# ─── Fake providers (for testing) ────────────────────────────────────────────

class FakeEmbeddingProvider(EmbeddingProvider):
    """测试用假 Embedding — 基于文本 hash 产生确定性向量（仅测试）。"""

    def __init__(self, dimension: int = 384):
        self._dim = dimension

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [self._hash_vec(t) for t in texts]

    def embed_text(self, text: str) -> List[float]:
        return self._hash_vec(text)

    def get_dimension(self) -> int:
        return self._dim

    def get_model_name(self) -> str:
        return "fake-embedding-test"

    def get_resolved_model_name(self) -> str:
        return "fake-embedding-test"

    def is_degraded(self) -> bool:
        return False

    def get_degraded_reason(self) -> str:
        return ""

    def _hash_vec(self, text: str) -> List[float]:
        text = text.lower().strip()
        vec = [0.0] * self._dim
        for i, ch in enumerate(text):
            h = hashlib.md5(f"{i}_{ch}".encode()).digest()
            for j in range(0, len(h), 2):
                if j + 1 < len(h):
                    idx = (i * 16 + j // 2) % self._dim
                    vec[idx] += (h[j] << 8 | h[j + 1]) / 65535.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


class FakeRerankerProvider(RerankerProvider):
    """测试用假 Reranker — 基于 keyword 匹配重排（仅测试）。"""

    def rerank(self, query: str, documents: List[str], top_k: int = 25) -> List[float]:
        q_words = set(query.lower().split())
        scores = []
        for doc in documents:
            d_words = set(doc.lower().split())
            overlap = len(q_words & d_words)
            scores.append(overlap / max(len(q_words), 1))
        return scores

    def get_model_name(self) -> str:
        return "fake-reranker-test"

    def get_resolved_model_name(self) -> str:
        return "fake-reranker-test"

    def is_degraded(self) -> bool:
        return False

    def get_degraded_reason(self) -> str:
        return ""


# ─── Production Embedding Provider ───────────────────────────────────────────

class HashEmbeddingProvider(EmbeddingProvider):
    """Hash 降级 Embedding Provider — 明确定义，不隐藏在 SentenceTransformers 内部。"""

    def __init__(self, dimension: int = 1024):
        self._dim = dimension

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        return [FakeEmbeddingProvider(dimension=self._dim)._hash_vec(t) for t in texts]

    def embed_text(self, text: str) -> List[float]:
        return self.embed_texts([text])[0]

    def get_dimension(self) -> int:
        return self._dim

    def get_model_name(self) -> str:
        return "hash-fallback"

    def get_resolved_model_name(self) -> str:
        return "hash-fallback"

    def is_degraded(self) -> bool:
        return True

    def get_degraded_reason(self) -> str:
        return "model_unavailable:hash_fallback_active"


class SentenceTransformersEmbeddingProvider(EmbeddingProvider):
    """基于 sentence-transformers 的生产级 Embedding。"""

    def __init__(self, model_name: Optional[str] = None, device: Optional[str] = None):
        self._model_name = model_name or RAG_EMBEDDING_MODEL
        self._device = device or RAG_EMBEDDING_DEVICE
        self._model = None
        self._degraded = False
        self._degraded_reason = ""
        self._loaded = False
        self._fallback_provider: Optional[HashEmbeddingProvider] = None

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        if not RAG_ALLOW_MODEL_DOWNLOAD:
            self._degraded = True
            self._degraded_reason = "RAG_ALLOW_MODEL_DOWNLOAD=false"
            return
        try:
            from sentence_transformers import SentenceTransformer
            model_kwargs = {}
            if RAG_MODEL_CACHE_DIR:
                model_kwargs["cache_folder"] = RAG_MODEL_CACHE_DIR
            self._model = SentenceTransformer(
                self._model_name,
                device=self._device,
                **model_kwargs,
            )
            logger.info(f"Embedding model loaded: {self._model_name}")
        except Exception as e:
            self._degraded = True
            self._degraded_reason = f"Failed to load embedding model '{self._model_name}': {e}"
            logger.error(self._degraded_reason)

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        self._load()
        if self._model is not None:
            try:
                embeddings = self._model.encode(
                    texts,
                    batch_size=RAG_EMBEDDING_BATCH_SIZE,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                )
                return embeddings.tolist()
            except Exception as e:
                logger.error(f"Embedding encode failed: {e}")
                self._degraded = True
                self._degraded_reason = f"Encode error: {e}"
        # Degraded — use explicit HashEmbeddingProvider
        if RAG_ALLOW_HASH_FALLBACK:
            if self._fallback_provider is None:
                self._fallback_provider = HashEmbeddingProvider(dimension=1024)
            logger.warning("Falling back to hash embeddings (RAG_ALLOW_HASH_FALLBACK=true)")
            return self._fallback_provider.embed_texts(texts)
        raise RuntimeError(
            f"Embedding model unavailable: {self._degraded_reason}. "
            "Set RAG_ALLOW_HASH_FALLBACK=true only for testing."
        )

    def embed_text(self, text: str) -> List[float]:
        return self.embed_texts([text])[0]

    def get_dimension(self) -> int:
        self._load()
        if self._model is not None:
            try:
                return self._model.get_sentence_embedding_dimension()
            except Exception:
                pass
        return 1024  # default for Qwen3-Embedding-0.6B

    def get_model_name(self) -> str:
        return self._model_name

    def get_resolved_model_name(self) -> str:
        self._load()
        if self._model is not None and not self._degraded:
            return self._model_name
        # Degraded: always identify as hash-fallback regardless of allow flag
        if self._degraded:
            return "hash-fallback"
        return self._model_name

    def is_degraded(self) -> bool:
        self._load()
        return self._degraded

    def get_degraded_reason(self) -> str:
        return self._degraded_reason


# ─── Production Reranker Provider ────────────────────────────────────────────

class CrossEncoderRerankerProvider(RerankerProvider):
    """基于 sentence-transformers CrossEncoder 的生产级 Reranker。"""

    def __init__(self, model_name: Optional[str] = None, device: Optional[str] = None):
        self._model_name = model_name or RAG_RERANKER_MODEL
        self._device = device or RAG_RERANKER_DEVICE
        self._model = None
        self._degraded = False
        self._degraded_reason = ""
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        if not RAG_ALLOW_MODEL_DOWNLOAD:
            self._degraded = True
            self._degraded_reason = "RAG_ALLOW_MODEL_DOWNLOAD=false"
            return
        try:
            from sentence_transformers import CrossEncoder
            model_kwargs = {}
            if RAG_MODEL_CACHE_DIR:
                model_kwargs["cache_folder"] = RAG_MODEL_CACHE_DIR
            self._model = CrossEncoder(
                self._model_name,
                device=self._device,
                **model_kwargs,
            )
            logger.info(f"Reranker model loaded: {self._model_name}")
        except Exception as e:
            self._degraded = True
            self._degraded_reason = f"Failed to load reranker model '{self._model_name}': {e}"
            logger.error(self._degraded_reason)

    def rerank(self, query: str, documents: List[str], top_k: int = 25) -> List[float]:
        if not documents:
            return []
        self._load()
        if self._model is not None:
            try:
                pairs = [[query, doc] for doc in documents]
                scores = self._model.predict(pairs, show_progress_bar=False)
                return [float(s) for s in scores]
            except Exception as e:
                logger.error(f"Reranker predict failed: {e}")
                self._degraded = True
                self._degraded_reason = f"Predict error: {e}"
        # Degraded — deterministic fallback
        logger.warning(f"Reranker degraded, using deterministic fallback: {self._degraded_reason}")
        fake = FakeRerankerProvider()
        return fake.rerank(query, documents, top_k)

    def get_model_name(self) -> str:
        return self._model_name

    def get_resolved_model_name(self) -> str:
        self._load()
        if self._model is not None and not self._degraded:
            return self._model_name
        if self._degraded:
            return "keyword-fallback"
        return self._model_name

    def is_degraded(self) -> bool:
        self._load()
        return self._degraded

    def get_degraded_reason(self) -> str:
        return self._degraded_reason


# ─── Provider factory ────────────────────────────────────────────────────────

_embedding_provider: Optional[EmbeddingProvider] = None
_reranker_provider: Optional[RerankerProvider] = None


def get_embedding_provider() -> EmbeddingProvider:
    """获取全局 EmbeddingProvider（懒加载）。"""
    global _embedding_provider
    if _embedding_provider is None:
        _embedding_provider = SentenceTransformersEmbeddingProvider()
    return _embedding_provider


def get_reranker_provider() -> RerankerProvider:
    """获取全局 RerankerProvider（懒加载）。"""
    global _reranker_provider
    if _reranker_provider is None:
        _reranker_provider = CrossEncoderRerankerProvider()
    return _reranker_provider


def set_embedding_provider(provider: EmbeddingProvider) -> None:
    """注入自定义 EmbeddingProvider（测试用）。"""
    global _embedding_provider
    _embedding_provider = provider


def set_reranker_provider(provider: RerankerProvider) -> None:
    """注入自定义 RerankerProvider（测试用）。"""
    global _reranker_provider
    _reranker_provider = provider


def reset_providers() -> None:
    """重置 providers（测试清理）。"""
    global _embedding_provider, _reranker_provider
    _embedding_provider = None
    _reranker_provider = None
