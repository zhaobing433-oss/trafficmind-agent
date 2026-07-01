"""
Embedding 工具模块
----------------
提供文本向量化能力。
优先使用本地 sentence-transformers，不可用时降级为简单哈希 embedding。
"""

from typing import List

_EMBEDDING_MODEL = None
_EMBEDDING_FN = None
_EMBED_MODE = "hash"  # hash | sentence_transformers | api


def _get_sentence_transformer():
    """惰性加载 sentence-transformers 模型。"""
    global _EMBEDDING_MODEL, _EMBED_MODE, _EMBEDDING_FN
    if _EMBEDDING_MODEL is not None:
        return _EMBEDDING_MODEL

    try:
        from sentence_transformers import SentenceTransformer
        # all-MiniLM-L6-v2: 轻量，384维，约80MB
        _EMBEDDING_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        _EMBED_MODE = "sentence_transformers"
        print("[Embedding] 使用本地 sentence-transformers (all-MiniLM-L6-v2)")
        return _EMBEDDING_MODEL
    except Exception as e:
        print(f"[Embedding] sentence-transformers 加载失败: {e}，降级为哈希 embedding")
        _EMBED_MODE = "hash"
        return None


def get_embedding_mode() -> str:
    """获取当前 embedding 模式。"""
    return _EMBED_MODE


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    将文本列表转换为向量。

    Args:
        texts: 文本列表

    Returns:
        向量列表，每个向量为 float 列表
    """
    if not texts:
        return []

    model = _get_sentence_transformer()
    if model is not None:
        try:
            embeddings = model.encode(texts, show_progress_bar=False)
            return embeddings.tolist()
        except Exception as e:
            print(f"[Embedding] 编码失败: {e}，降级为哈希 embedding")

    # 降级：简单哈希 embedding（384 维，确保 Chroma 能工作）
    return [_hash_embedding(t) for t in texts]


def embed_text(text: str) -> List[float]:
    """单条文本向量化。"""
    return embed_texts([text])[0]


def _hash_embedding(text: str, dim: int = 384) -> List[float]:
    """
    简单哈希 embedding 降级方案。
    用于在无 sentence-transformers 时保证系统能运行。
    """
    import hashlib

    text = text.lower().strip()
    if not text:
        return [0.0] * dim

    vec = [0.0] * dim
    # 字符级 n-gram 哈希
    for i, ch in enumerate(text):
        h = hashlib.md5(f"{i}_{ch}".encode()).digest()
        for j in range(0, len(h), 2):
            if j + 1 < len(h):
                val = (h[j] << 8 | h[j + 1]) / 65535.0
                idx = (i * 16 + j // 2) % dim
                vec[idx] += val

    # 词级哈希
    words = text.split()
    for i, word in enumerate(words):
        h = hashlib.md5(word.encode()).digest()
        for j in range(0, len(h), 2):
            if j + 1 < len(h):
                val = (h[j] << 8 | h[j + 1]) / 65535.0
                idx = (i * 31 + j // 2) % dim
                vec[idx] += val

    # L2 归一化
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec
