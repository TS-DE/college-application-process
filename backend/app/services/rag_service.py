"""RAG 服务：Chroma 向量库 + Ollama embedding。

设计要点：
- 所有向量库操作都封装在本文件，将来换 Milvus 只需替换这几个函数
- 默认调用本地 Ollama embedding（离线可用），可通过 DASHSCOPE_API_KEY 切到千问 text-embedding-v3
- 若 Ollama 不可用，退化为「关键词打分」的本地检索，保证链路不中断
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

import requests

from app.config import settings

# ---------------- Chroma 客户端（延迟初始化，避免导入即失败） ----------------

_client = None
_collection = None
_chroma_error: Optional[str] = None


def _get_collection():
    """获取（或创建）持久化集合。"""
    global _client, _collection, _chroma_error
    if _collection is not None:
        return _collection
    try:
        import chromadb

        os.makedirs(settings.CHROMA_DB_PATH, exist_ok=True)
        _client = chromadb.PersistentClient(path=settings.CHROMA_DB_PATH)
        _collection = _client.get_or_create_collection(name=settings.CHROMA_COLLECTION)
        return _collection
    except Exception as exc:  # noqa: BLE001
        _chroma_error = str(exc)
        return None


def collection():
    """供路由层直接操作（如按 file_id 删除向量）。"""
    return _get_collection()


def backend_info() -> dict:
    col = _get_collection()
    return {
        "vector_store": "chroma",
        "persist_path": settings.CHROMA_DB_PATH,
        "collection": settings.CHROMA_COLLECTION,
        "embedding_model": settings.OLLAMA_EMBED_MODEL,
        "embedding_provider": "dashscope" if settings.DASHSCOPE_API_KEY else "ollama",
        "ready": col is not None,
        "error": _chroma_error,
        "count": (col.count() if col else 0),
    }


# ---------------- Embedding ----------------

def get_embedding(text: str) -> Optional[List[float]]:
    """获取文本向量：优先 DashScope，其次 Ollama，都失败返回 None。"""
    if settings.DASHSCOPE_API_KEY:
        vec = _dashscope_embedding(text)
        if vec:
            return vec
    return _ollama_embedding(text)


def _ollama_embedding(text: str) -> Optional[List[float]]:
    try:
        resp = requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/embeddings",
            json={"model": settings.OLLAMA_EMBED_MODEL, "prompt": text},
            timeout=settings.OLLAMA_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("embedding")
    except Exception:  # noqa: BLE001
        return None


def _dashscope_embedding(text: str) -> Optional[List[float]]:
    """千问官方 text-embedding-v3（需 DASHSCOPE_API_KEY）。"""
    try:
        resp = requests.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
            headers={
                "Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": settings.DASHSCOPE_EMBED_MODEL, "input": text},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
    except Exception:  # noqa: BLE001
        return None


# ---------------- 写入 / 删除 / 检索 ----------------

def add_document(doc_id: str, text: str, metadata: dict, embedding: Optional[List[float]] = None) -> bool:
    """写入单个切片；embedding 为 None 时内部再计算一次。"""
    col = _get_collection()
    if col is None or not text:
        return False
    vec = embedding if embedding is not None else get_embedding(text)
    if vec is None:
        return False
    col.add(ids=[doc_id], embeddings=[vec], documents=[text], metadatas=[metadata])
    return True


def add_documents(chunks: List[str], metadata: dict, key_fmt: str = "{idx}") -> int:
    """批量写入切片，返回成功写入数量。"""
    ok = 0
    for idx, chunk in enumerate(chunks):
        doc_id = key_fmt.format(idx=idx)
        if add_document(doc_id, chunk, {**metadata, "chunk_index": idx}):
            ok += 1
    return ok


def delete_by_file(file_id: int) -> bool:
    """删除某个文件在向量库中的全部切片。"""
    col = _get_collection()
    if col is None:
        return False
    try:
        col.delete(where={"file_id": file_id})
        return True
    except Exception:  # noqa: BLE001
        return False


def search(query: str, top_k: int = 5) -> List[Dict]:
    """语义检索；Ollama/Chroma 不可用时退化为关键词匹配。"""
    col = _get_collection()
    if col is None:
        return _keyword_fallback(query, top_k)

    vec = get_embedding(query)
    if vec is None:
        return _keyword_fallback(query, top_k)

    try:
        res = col.query(
            query_embeddings=[vec],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:  # noqa: BLE001
        return _keyword_fallback(query, top_k)

    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    return [
        {"text": d, "metadata": m or {}, "distance": dist}
        for d, m, dist in zip(docs, metas, dists)
    ]


def _keyword_fallback(query: str, top_k: int) -> List[Dict]:
    """无向量能力时的兜底：对库内文档做关键词打分。"""
    col = _get_collection()
    if col is None:
        return []
    try:
        data = col.get(include=["documents", "metadatas"])
    except Exception:  # noqa: BLE001
        return []
    docs = data.get("documents") or []
    metas = data.get("metadatas") or []
    keys = [k for k in re.split(r"[\s，。？！、,.;!?]+", query) if len(k) >= 2]
    scored = []
    for doc, meta in zip(docs, metas):
        score = sum(doc.count(k) for k in keys)
        if score:
            scored.append({"text": doc, "metadata": meta or {}, "distance": float(-score)})
    scored.sort(key=lambda x: x["distance"])
    return scored[:top_k]
