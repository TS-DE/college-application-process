"""混合检索：稠密 + 稀疏 → RRF（0.18.0 从 rag_service 搬出）。

对外仍保留老类名 `HybridRetrieval` 的构造与 `search` 签名
（`rag_service` 里做别名），因此 `_load_corpus` / `dense_search` /
`bm25_search` / `rrf` 这些**被 multi_route_search 直接调用的方法**必须原样保留。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.services.rag.constants import DEFAULT_CANDIDATE_N, DEFAULT_TOP_K, RRF_K
from app.services.rag.retrieval.base import BaseRetriever
from app.services.rag.retrieval.bm25 import BM25Channel, BM25Retriever
from app.services.rag.retrieval.dense import DenseChannel, DenseRetriever, get_embedding_model
from app.services.rag.retrieval.fusion import RrfFusion


class HybridRetriever(BaseRetriever):
    """混合检索器：稠密向量（Chroma）+ 稀疏关键词（BM25）→ RRF 融合。

    对应《混合检索》文档「代码三：封装成类」的结构：
        dense_search()  ≈ bgeChou()   稠密路召回（本项目用 Chroma 自带 ANN 检索）
        bm25_search()   ≈ bm25Xi()    稀疏路召回（rank_bm25 + jieba 中文分词）
        rrf()           ≈ rrf()       倒数排名融合
        search()        ≈ get_rrf()   对外统一入口
    """

    name = "hybrid"

    def __init__(
        self,
        collection,
        k: int = RRF_K,
        top_k: int = DEFAULT_TOP_K,
        candidate_n: int = DEFAULT_CANDIDATE_N,
    ):
        self.collection = collection
        self.k = k                    # RRF 常数，固定 60
        self.top_k = top_k            # 最终返回条数
        self.candidate_n = candidate_n  # 每一路各自召回的候选数量
        self._corpus: Optional[list] = None      # [(chunk_id, text, metadata)]
        self._corpus_count = -1                  # 语料快照对应的 collection.count()
        self._bm25: Optional[BM25Retriever] = None  # BM25 索引（按语料缓存）
        self._fusion = RrfFusion(k=k, key="index")
        # 稠密路由 DenseRetriever 承担；embedding 用项目统一通道
        from app.services.rag import rag_service

        self._dense = DenseRetriever(
            collection=collection,
            embed_fn=rag_service.get_embedding,
            candidate_n=candidate_n,
        )

    # ========== 1. 语料 & BM25 索引 ==========

    def _load_corpus(self) -> list:
        """从 Chroma 取出全部文本构建 BM25 语料（按 count 变化做失效判断）。

        说明：BM25 需要"分词后的文本序列"，必须拿到原文；
        当前知识库规模（千级 chunk）全量取回可接受，
        若后续到十万级可改为「BM25 索引持久化 + 增量更新」。
        """
        count = self.collection.count()
        if self._corpus is not None and count == self._corpus_count:
            return self._corpus

        data = self.collection.get(include=["documents", "metadatas"])
        ids = data.get("ids") or []
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        self._corpus = [
            {"id": i, "text": d or "", "metadata": m or {}}
            for i, d, m in zip(ids, docs, metas)
        ]
        self._corpus_count = count
        self._bm25 = BM25Retriever(self._corpus)
        return self._corpus

    @staticmethod
    def _build_bm25(documents: List[str]):
        """构建 BM25Okapi 稀疏索引（兼容入口，实现见 `BM25Retriever._build_index`）。"""
        corpus = [{"id": str(i), "text": d, "metadata": {}} for i, d in enumerate(documents or [])]
        return BM25Retriever(corpus).index

    # ========== 2. 稠密向量检索（Chroma 自带 ANN） ==========

    def dense_search(self, query: str) -> List[Dict]:
        """稠密路：Chroma 向量检索，返回 [{index, distance}]（按相似度降序）。"""
        raw = self._dense.retrieve(query, self.candidate_n)
        if not raw:
            return []
        corpus = self._load_corpus()
        id_to_idx = {c["id"]: i for i, c in enumerate(corpus)}
        return [
            {"index": id_to_idx[h["doc_id"]], "distance": h["distance"]}
            for h in raw
            if h["doc_id"] in id_to_idx
        ]  # Chroma 已按距离升序返回，即相似度降序

    # ========== 3. 稀疏关键词检索（BM25） ==========

    def bm25_search(self, query: str) -> List[Dict]:
        """稀疏路：BM25 关键词检索，返回 [{index, score}]（按得分降序）。"""
        corpus = self._load_corpus()
        if not corpus or self._bm25 is None:
            return []
        # Chroma 侧的兜底不截断（与 0.17.x 一致）
        return [
            {"index": h["index"], "score": h["score"]}
            for h in self._bm25.retrieve(query, self.candidate_n)
        ]

    @staticmethod
    def _token_overlap_search(query: str, corpus: list) -> List[Dict]:
        """稀疏路兜底：按「查询词在文档中出现的次数」打分（兼容入口）。"""
        hits = BM25Retriever(corpus)._token_overlap(query)  # noqa: SLF001 同一份实现
        return [{"index": h["index"], "score": h["score"]} for h in hits]

    # ========== 4. RRF 融合 ==========

    def rrf(self, dense_ranking: List[Dict], bm25_ranking: List[Dict]):
        """倒数排名融合（公式与降级说明见 `RrfFusion`）。"""
        scores, rank_maps = self._fusion.accumulate([dense_ranking, bm25_ranking])
        final_ranking = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return final_ranking, rank_maps[0], rank_maps[1]

    # ========== 5. 对外入口 ==========

    def search(self, query: str, top_k: int | None = None) -> List[Dict]:
        """混合检索主流程：两路召回 → RRF 融合 → Top-K。"""
        top_k = top_k or self.top_k
        corpus = self._load_corpus()
        if not corpus:
            return []

        dense_hits = self.dense_search(query)
        bm25_hits = self.bm25_search(query)

        # 单路失效时自动退化：只有稠密 → 纯向量检索；只有 BM25 → 关键词检索
        if not dense_hits and not bm25_hits:
            return []
        if not bm25_hits:
            return [self._to_hit(corpus, h["index"], h.get("distance"), dense_rank=i + 1)
                    for i, h in enumerate(dense_hits[:top_k])]
        if not dense_hits:
            return [self._to_hit(corpus, h["index"], None, bm25_rank=i + 1)
                    for i, h in enumerate(bm25_hits[:top_k])]

        final_ranking, dense_ranks, bm25_ranks = self.rrf(dense_hits, bm25_hits)

        dist_map = {h["index"]: h.get("distance") for h in dense_hits}
        return [
            self._to_hit(
                corpus,
                idx,
                dist_map.get(idx),
                rrf_score=score,
                dense_rank=dense_ranks.get(idx),
                bm25_rank=bm25_ranks.get(idx),
            )
            for idx, score in final_ranking[:top_k]
        ]

    def retrieve(self, query: str, top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        """`BaseRetriever` 契约（与 `search` 等价）。"""
        return self.search(query, top_k)

    @staticmethod
    def _to_hit(corpus: list, index: int, distance, rrf_score=None, dense_rank=None, bm25_rank=None) -> Dict:
        c = corpus[index]
        return {
            "text": c["text"],
            "metadata": c["metadata"],
            "distance": distance,
            # 便于排查与对比（纯向量检索时后三项为 None）
            "rrf_score": rrf_score,
            "dense_rank": dense_rank,
            "bm25_rank": bm25_rank,
        }


class HybridSearch(BaseRetriever):
    """内存版混合检索（`MultiRecall` 的复合通道，0.18.0 保留旧构造）。

    与 `HybridRetriever` 的区别只在数据源：这里用语料内的预计算向量做余弦，
    不查 Chroma。融合与打分全部复用同一批叶子类。
    """

    def __init__(
        self,
        docs: List[Dict],
        fields: Optional[List[str]] = None,
        model_path: Optional[str] = None,
        k: int = RRF_K,
        embeddings=None,
        weight: float = 1.0,
    ):
        self.name = "hybrid"
        self.weight = weight
        self.dense = DenseChannel("dense", docs, fields, weight=1.0,
                                  model_path=model_path, embeddings=embeddings)
        self.bm25 = BM25Channel("bm25", docs, fields, weight=1.0)
        self.k = k

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        dense_hits = self.dense.search(query, top_k=20)
        bm25_hits = self.bm25.search(query, top_k=20)
        return RrfFusion(k=self.k, key="doc_id").fuse([dense_hits, bm25_hits], top_k=top_k)

    def retrieve(self, query: str, top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        return self.search(query, top_k)


__all__ = ["HybridRetriever", "HybridSearch", "get_embedding_model"]
