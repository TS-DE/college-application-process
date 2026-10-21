"""稠密向量检索（0.18.0 收敛为一处实现）。

收敛前有两套：
  · `rag_service.HybridRetrieval.dense_search` —— 查 Chroma 的 ANN 索引
  · `retrieval.DenseChannel`                   —— 内存里算余弦矩阵

两者「用向量找相似文档」的本质相同，只是数据源不同。本模块用
`DenseRetriever` 统一下来（按构造方式选择数据源），并保留
`DenseChannel` 作为内存侧的兼容适配器（对外契约不变）。
"""
from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from app.services.rag.constants import DEFAULT_CANDIDATE_N
from app.services.rag.retrieval.base import BaseRetriever


# ====================== Embedding 编码器（懒加载） ======================

_embedding_model = None


class ProjectEmbedding:
    """复用项目已有的 embedding 能力（Ali text-embedding-v3 / Ollama nomic-embed-text），
    对外提供与 SentenceTransformer 一致的 `encode()` 接口（依赖倒置）。"""

    def __init__(self, dim: int = 768):
        self.dim = dim

    def encode(self, texts: Sequence[str], normalize_embeddings: bool = True) -> np.ndarray:
        from app.services.rag import rag_service  # 延迟导入，避免循环依赖

        # 0.7.1：整批一次请求（Ali 支持原生 batch），把 N 次网络往返压成 1 次
        batch = list(texts or [])
        raw_vectors: List[Optional[List[float]]] = (
            rag_service.get_embeddings_batch(batch) if batch else []
        )

        vectors: List[List[float]] = []
        dim = self.dim
        for _t, vec in zip(batch, raw_vectors):
            if vec:
                dim = len(vec)
                vectors.append([float(x) for x in vec])
            else:
                # 单条失败用零向量占位，保证矩阵形状一致（降级不中断）
                vectors.append([0.0] * dim)
        if not vectors:
            return np.zeros((0, dim), dtype=float)
        arr = np.asarray(vectors, dtype=float)
        if normalize_embeddings:
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            arr = arr / norms
        return arr


def get_embedding_model(model_path: Optional[str] = None):
    """懒加载 Embedding 模型。

    优先顺序：
      1. 环境变量 EMBEDDING_MODEL_PATH 指定了路径 → 本地 sentence-transformers（课堂案例方式）
      2. 否则 → 项目已有的 Ali / Ollama embedding（离线可跑）
    """
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model

    path = model_path or os.getenv("EMBEDDING_MODEL_PATH", "")
    if path:
        try:
            from sentence_transformers import SentenceTransformer

            _embedding_model = SentenceTransformer(path)
            return _embedding_model
        except Exception:  # noqa: BLE001 本地模型不可用 → 回落项目 embedding
            _embedding_model = None
    _embedding_model = ProjectEmbedding()
    return _embedding_model


def _cosine_matrix(query_vec: np.ndarray, doc_matrix: np.ndarray) -> np.ndarray:
    """计算余弦相似度（query 与全部文档），不依赖 sklearn。"""
    if doc_matrix.size == 0:
        return np.zeros(0, dtype=float)
    q = np.asarray(query_vec, dtype=float).reshape(1, -1)
    q_norm = np.linalg.norm(q)
    d_norms = np.linalg.norm(doc_matrix, axis=1)
    q_norm = q_norm or 1.0
    d_norms[d_norms == 0] = 1.0
    return (doc_matrix @ q.T).ravel() / (d_norms * q_norm)


# ====================== 稠密检索 ======================


class DenseRetriever(BaseRetriever):
    """稠密召回：Chroma ANN（优先）或内存余弦。

    两种数据源共用 `retrieve()` 契约，编排者无需感知差异：
      · 传 `collection` / `store` → 走向量库 ANN（`rag_service` 的检索链路）
      · 传 `docs`（+ 可选 `embeddings`）→ 走内存余弦（`MultiRecall` 的通道）
    """

    name = "dense"

    def __init__(
        self,
        store=None,
        embed_fn: Optional[Callable[[str], Optional[List[float]]]] = None,
        candidate_n: int = DEFAULT_CANDIDATE_N,
        collection=None,
        docs: Optional[List[Dict]] = None,
        embeddings: Optional[Sequence[Sequence[float]]] = None,
        encoder=None,
        fields: Optional[List[str]] = None,
        weight: float = 1.0,
    ):
        self.store = store
        self.collection = collection          #: 显式传入的集合（优先于 store）
        self.embed_fn = embed_fn              #: 查询向量化函数（ANN 模式必需）
        self.candidate_n = candidate_n
        self.docs = docs or []
        self.fields = fields or ["text"]
        self.weight = weight
        self.encoder = encoder
        self.texts: List[str] = [
            " ".join(str(doc.get(f, "")) for f in self.fields) for doc in self.docs
        ]
        self._matrix = self._build_matrix(embeddings) if self.docs else None

    # ---------------- 内存模式 ----------------

    def _build_matrix(self, embeddings: Optional[Sequence[Sequence[float]]]):
        """预计算文档向量矩阵（传了就复用，省掉全库重新编码）。"""
        if embeddings is not None and len(embeddings) == len(self.texts):
            matrix = np.asarray(embeddings, dtype=float)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            return matrix / norms
        if self.encoder is None:
            self.encoder = get_embedding_model()
        return self.encoder.encode(self.texts, normalize_embeddings=True)

    # ---------------- 检索 ----------------

    def _resolve_collection(self):
        if self.collection is not None:
            return self.collection
        if self.store is not None:
            return self.store.get_collection()
        return None

    def retrieve(self, query: str, top_k: int = DEFAULT_CANDIDATE_N) -> List[Dict]:
        """返回 `[{index, doc_id, score, distance}]`（按相关度降序）。

        ANN 模式没有「分数」只有「距离」，因此 `score` 为 None、`distance` 有值；
        内存模式相反。下游按需取用（RRF 只用名次，两种都能融合）。
        """
        col = self._resolve_collection()
        if col is not None:
            return self._retrieve_ann(col, query)
        return self._retrieve_memory(query, top_k)

    def _retrieve_ann(self, col, query: str) -> List[Dict]:
        """向量库 ANN：返回 `[{doc_id, distance}]`（Chroma 已按距离升序）。"""
        vec = self.embed_fn(query) if self.embed_fn else None
        if vec is None:
            return []
        try:
            res = col.query(
                query_embeddings=[vec],
                n_results=min(self.candidate_n, max(1, col.count())),
                include=["documents", "metadatas", "distances"],
            )
        except Exception:  # noqa: BLE001
            return []

        hits = []
        for cid, dist in zip((res.get("ids") or [[]])[0], (res.get("distances") or [[]])[0]):
            hits.append({"index": -1, "doc_id": cid, "score": None, "distance": dist})
        return hits

    def _retrieve_memory(self, query: str, top_k: int) -> List[Dict]:
        """内存余弦：返回 `[{index, doc_id, score}]`。"""
        if self._matrix is None or self._matrix.size == 0:
            return []
        if self.encoder is None:
            self.encoder = get_embedding_model()
        query_emb = self.encoder.encode([query], normalize_embeddings=True)
        if query_emb.size == 0:
            return []
        scores = _cosine_matrix(query_emb[0], self._matrix)
        ranking = np.argsort(-scores)[:top_k]
        return [
            {
                "index": int(idx),
                "doc_id": self.docs[int(idx)].get("id") or f"{self.name}_{int(idx)}",
                "score": float(scores[int(idx)]),
                "distance": None,
            }
            for idx in ranking
        ]


class DenseChannel(DenseRetriever):
    """内存稠密通道的**兼容适配器**（0.18.0 保留旧构造与旧输出结构）。

    老 `retrieval.DenseChannel` 是 `MultiRecall` 的通道之一，
    对外契约是 `{doc_id, score, text, channel, full_doc}`，与检索内核不同。
    这里只做「再包一层输出」，逻辑仍然只有 `DenseRetriever` 一份。
    """

    def __init__(
        self,
        name: str,
        docs: List[Dict],
        fields: Optional[List[str]] = None,
        weight: float = 1.0,
        model_path: Optional[str] = None,
        embeddings: Optional[Sequence[Sequence[float]]] = None,
    ):
        super().__init__(
            docs=docs,
            fields=fields,
            weight=weight,
            embeddings=embeddings,
            encoder=get_embedding_model(model_path),
            candidate_n=len(docs) or DEFAULT_CANDIDATE_N,
        )
        self.name = name

    def retrieve(self, query: str, top_k: int = 3) -> List[Dict]:
        hits = super().retrieve(query, top_k)
        return [self._pack(h["index"], h["score"]) for h in hits]

    def _pack(self, idx: int, score: float) -> Dict:
        """统一输出结构，便于上层融合与去重（与 0.17.x 完全一致）。"""
        return {
            "doc_id": self.docs[idx].get("id") or f"{self.name}_{idx}",
            "score": float(score),
            "text": self.texts[idx],
            "channel": self.name,
            "full_doc": self.docs[idx],
        }
