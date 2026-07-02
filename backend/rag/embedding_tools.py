"""Embedding tools — local sentence-transformers with hash fallback"""
from typing import List
_EMBEDDING_MODEL = None
_EMBED_MODE = "hash"

def _get_model():
    global _EMBEDDING_MODEL, _EMBED_MODE
    if _EMBEDDING_MODEL is not None: return _EMBEDDING_MODEL
    try:
        from sentence_transformers import SentenceTransformer
        _EMBEDDING_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        _EMBED_MODE = "sentence_transformers"
        return _EMBEDDING_MODEL
    except: _EMBED_MODE = "hash"; return None

def get_embedding_mode(): return _EMBED_MODE

def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts: return []
    model = _get_model()
    if model is not None:
        try: return model.encode(texts, show_progress_bar=False).tolist()
        except: pass
    return [_hash_emb(t) for t in texts]

def embed_text(text: str) -> List[float]: return embed_texts([text])[0]

def _hash_emb(text: str, dim: int = 384) -> List[float]:
    import hashlib
    text = text.lower().strip()
    if not text: return [0.0] * dim
    vec = [0.0] * dim
    for i, ch in enumerate(text):
        h = hashlib.md5(f"{i}_{ch}".encode()).digest()
        for j in range(0, len(h), 2):
            if j + 1 < len(h):
                idx = (i * 16 + j // 2) % dim
                vec[idx] += (h[j] << 8 | h[j + 1]) / 65535.0
    words = text.split()
    for i, word in enumerate(words):
        h = hashlib.md5(word.encode()).digest()
        for j in range(0, len(h), 2):
            if j + 1 < len(h):
                idx = (i * 31 + j // 2) % dim
                vec[idx] += (h[j] << 8 | h[j + 1]) / 65535.0
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0: vec = [v / norm for v in vec]
    return vec
