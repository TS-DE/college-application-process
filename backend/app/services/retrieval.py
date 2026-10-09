"""检索中模块：混合检索（Hybrid Search）+ 多路召回（Multi-Recall）。

参考课堂案例 01_混合检索.py / 02_多路召回.py / 03_多路召回的封装.py，
按「面向对象 + 面向接口」的方式重构，独立于 rag_service，方便替换与测试。

类结构（单一职责 / 开闭 / 依赖倒置）：
    ChannelRetriever（抽象基类，定义单路召回接口）
      ├── DenseChannel  稠密向量通道：Embedding + 余弦相似度
      └── BM25Channel   稀疏关键词通道：jieba 分词 + BM25Okapi
    HybridSearch        单 Query 双路融合（稠密 + BM25 → RRF）
    MultiRecall         多路召回编排：多通道 × 多子查询 → RRF / 加权 / 轮询融合

与项目的对接：
    - Embedding 默认复用项目已有的 rag_service.get_embedding（Ali OpenAI 兼容 / Ollama），
      配置 EMBEDDING_MODEL_PATH 时可切换为本地 sentence-transformers（课堂案例方式）
    - 语料来自 Chroma 中的子块（父子块结构不变）
"""
from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Sequence

import jieba
import numpy as np
from rank_bm25 import BM25Okapi

# RRF 融合常数（与 rag_service.RRF_K 保持一致）
DEFAULT_RRF_K = 60


# ====================== Embedding 模型（懒加载） ======================

_embedding_model = None


class ProjectEmbedding:
    """复用项目已有的 embedding 能力（Ali text-embedding-v3 / Ollama nomic-embed-text），
    对外提供与 SentenceTransformer 一致的 `encode()` 接口（依赖倒置）。"""

    def __init__(self, dim: int = 768):
        self.dim = dim

    def encode(self, texts: Sequence[str], normalize_embeddings: bool = True) -> np.ndarray:
        from app.services import rag_service  # 延迟导入，避免循环依赖

        # v2.5.1：整批一次请求（Ali 支持原生 batch），把 N 次网络往返压成 1 次
        batch = list(texts or [])
        raw_vectors: List[Optional[List[float]]] = rag_service.get_embeddings_batch(batch) if batch else []

        vectors: List[List[float]] = []
        dim = self.dim
        for t, vec in zip(batch, raw_vectors):
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


def get_embedding_model(model_path: str | None = None):
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


# ====================== 检索器抽象基类 ======================

class ChannelRetriever:
    """单路召回抽象基类（接口隔离 + 依赖倒置）。

    docs：项目语料，形如 [{"id":..., "text":..., "metadata":{...}}]
    fields：参与检索的字段（默认只用 text；多字段时会先拼接再检索）
    weight：该通道在「加权融合」中的权重
    """

    def __init__(self, name: str, docs: List[Dict], fields: Optional[List[str]] = None, weight: float = 1.0):
        self.name = name
        self.docs = docs
        self.fields = fields or ["text"]
        self.weight = weight
        # 预拼接文本（各子类共用）
        self.texts = [" ".join(str(doc.get(f, "")) for f in self.fields) for doc in docs]

    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        raise NotImplementedError

    def _pack(self, idx: int, score: float) -> Dict:
        """统一输出结构，便于上层融合与去重。"""
        return {
            "doc_id": self.docs[idx].get("id") or f"{self.name}_{idx}",
            "score": float(score),
            "text": self.texts[idx],
            "channel": self.name,
            "full_doc": self.docs[idx],
        }


# ====================== 稠密向量通道 ======================

class DenseChannel(ChannelRetriever):
    """稠密向量召回：Embedding + 余弦相似度。

    embeddings 可传入预计算好的向量（项目里直接复用 Chroma 中已存的向量），
    避免每次请求都把全库重新编码一遍。
    """

    def __init__(
        self,
        name: str,
        docs: List[Dict],
        fields: Optional[List[str]] = None,
        weight: float = 1.0,
        model_path: str | None = None,
        embeddings: Optional[Sequence[Sequence[float]]] = None,
    ):
        super().__init__(name, docs, fields, weight)
        self.model = get_embedding_model(model_path)
        if embeddings is not None and len(embeddings) == len(self.texts):
            matrix = np.asarray(embeddings, dtype=float)
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self.embeddings = matrix / norms
        else:
            self.embeddings = self.model.encode(self.texts, normalize_embeddings=True)

    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        if self.embeddings.size == 0:
            return []
        query_emb = self.model.encode([query], normalize_embeddings=True)
        scores = _cosine_matrix(query_emb[0], self.embeddings)
        ranking = np.argsort(-scores)[:top_k]
        return [self._pack(int(idx), scores[int(idx)]) for idx in ranking]


# ====================== BM25 稀疏通道 ======================

class BM25Channel(ChannelRetriever):
    """BM25 稀疏召回：jieba 中文分词 + BM25Okapi。

    小语料降级：rank_bm25 的 IDF 在语料很小时可能为负 →
    所有得分 ≤ 0 时退化为「查询词命中计数」打分（与 rag_service 保持一致）。
    """

    def __init__(self, name: str, docs: List[Dict], fields: Optional[List[str]] = None, weight: float = 1.0):
        super().__init__(name, docs, fields, weight)
        self.tokenized = [list(jieba.cut(t)) for t in self.texts]
        self.bm25 = BM25Okapi(self.tokenized) if self.tokenized else None

    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        if not self.bm25:
            return []
        scores = np.asarray(self.bm25.get_scores(list(jieba.cut(query))), dtype=float)

        if scores.max() <= 0:  # 小语料降级
            tokens = [t for t in jieba.cut(query) if len(t) >= 2] or [query]
            scores = np.asarray([sum(t.count(tok) for tok in tokens) for t in self.texts], dtype=float)
            if scores.max() <= 0:
                return []

        ranking = np.argsort(-scores)[:top_k]
        return [self._pack(int(idx), scores[int(idx)]) for idx in ranking if scores[int(idx)] > 0]


# ====================== 混合检索（单 Query 双路 RRF） ======================

class HybridSearch:
    """混合检索：稠密 + BM25 → RRF 融合（对应课堂案例 01_混合检索.py）。

    对 MultiRecall 来说它是一个「复合通道」：
    对外暴露与 ChannelRetriever 一致的 name / weight / search 接口（里氏替换）。
    """

    def __init__(
        self,
        docs: List[Dict],
        fields: Optional[List[str]] = None,
        model_path: str | None = None,
        k: int = DEFAULT_RRF_K,
        embeddings: Optional[Sequence[Sequence[float]]] = None,
        weight: float = 1.0,
    ):
        self.name = "hybrid"
        self.weight = weight
        self.dense = DenseChannel("dense", docs, fields, weight=1.0, model_path=model_path, embeddings=embeddings)
        self.bm25 = BM25Channel("bm25", docs, fields, weight=1.0)
        self.k = k

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        dense_hits = self.dense.search(query, top_k=20)
        bm25_hits = self.bm25.search(query, top_k=20)
        return _rrf_fuse([dense_hits, bm25_hits], k=self.k, top_k=top_k)


# ====================== 多路召回 ======================

class MultiRecall:
    """多路召回：多个通道 × 多条子查询 → RRF / 加权 / 轮询融合。

    - 通道：DenseChannel、BM25Channel、HybridSearch（把混合检索当作一个"复合通道"）
    - 子查询：检索前预处理产出的多条 Query，每条都独立召回
    - 单通道失败只跳过该通道（降级），不影响整体链路
    """

    def __init__(self, channels: List[ChannelRetriever]):
        self.channels = channels

    # ---------- 原始召回 ----------
    def _multi_recall(self, query: str, top_k_per_channel: int = 3) -> List[Dict]:
        """各通道独立召回，结果汇总（单通道异常自动跳过）。"""
        all_results: List[Dict] = []
        for ch in self.channels:
            try:
                all_results.extend(ch.search(query, top_k=top_k_per_channel))
            except Exception as exc:  # noqa: BLE001
                print(f"[MultiRecall] 通道 {ch.name} 召回失败: {exc}")
        return all_results

    # ---------- 融合策略一：RRF（推荐，量纲无关） ----------
    def rrf_fusion(
        self,
        queries: Sequence[str],
        top_k: int = 5,
        top_k_per_channel: int = 20,
        k: int = DEFAULT_RRF_K,
    ) -> List[Dict]:
        """跨「子查询 × 通道」的所有排名列表做 RRF 累加：score += 1/(k + rank)。"""
        rankings: List[List[Dict]] = []
        for q in queries:
            for ch in self.channels:
                try:
                    hits = ch.search(q, top_k=top_k_per_channel)
                    if hits:
                        rankings.append(hits)
                except Exception:  # noqa: BLE001
                    continue
        return _rrf_fuse(rankings, k=k, top_k=top_k)

    # ---------- 融合策略二：加权融合 ----------
    def weight_fusion(self, query: str, top_k: int = 5, top_k_per_channel: int = 3) -> List[Dict]:
        """加权融合：score × channel.weight，按 doc_id 去重后取 Top-K。"""
        all_results = self._multi_recall(query, top_k_per_channel)
        weight_map = {ch.name: ch.weight for ch in self.channels}
        dedup: Dict[str, Dict] = {}
        for r in all_results:
            weight = weight_map.get(r["channel"], 1.0)
            wscore = r["score"] * weight
            if r["doc_id"] not in dedup or wscore > dedup[r["doc_id"]]["weighted_score"]:
                dedup[r["doc_id"]] = {**r, "weighted_score": wscore}
        return sorted(dedup.values(), key=lambda x: x["weighted_score"], reverse=True)[:top_k]

    # ---------- 融合策略三：轮询融合 ----------
    def round_robin_fusion(self, query: str, top_k: int = 5, top_k_per_channel: int = 3) -> List[Dict]:
        """轮询融合：各通道轮流取一个，保证每路都有曝光。"""
        all_results = self._multi_recall(query, top_k_per_channel)
        by_channel: Dict[str, List[Dict]] = {}
        for r in all_results:
            by_channel.setdefault(r["channel"], []).append(r)

        final: List[Dict] = []
        pointers = {ch: 0 for ch in by_channel}
        while len(final) < top_k and any(pointers[ch] < len(by_channel[ch]) for ch in by_channel):
            for ch in by_channel:
                if pointers[ch] < len(by_channel[ch]):
                    final.append(by_channel[ch][pointers[ch]])
                    pointers[ch] += 1
                    if len(final) >= top_k:
                        break
        return final


def _rrf_fuse(rankings: List[List[Dict]], k: int = DEFAULT_RRF_K, top_k: int = 5) -> List[Dict]:
    """RRF 融合通用实现：把多条排名列表按 doc_id 累加 1/(k+rank) 后取 Top-K。

    k=60 的作用：压平前几名的分数差，让"多路都还行"的文档胜过"单路第一"的文档。
    """
    scores: Dict[str, float] = {}
    best: Dict[str, Dict] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            doc_id = hit["doc_id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            if doc_id not in best or hit["score"] > best[doc_id]["score"]:
                best[doc_id] = hit

    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    return [{**best[doc_id], "rrf_score": score, "channel": "multi"} for doc_id, score in ordered]
