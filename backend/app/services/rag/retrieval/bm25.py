"""BM25 稀疏检索（0.18.0 收敛为一处实现）。

收敛前有两份等价逻辑：
  · `rag_service.HybridRetrieval._build_bm25 / bm25_search / _token_overlap_search`
  · `retrieval.BM25Channel.search`（内联了同一套「分数全 ≤0 时退化为词命中计数」）

本类把两者合并：语料统一成 `[{"id","text","metadata"}]`，
打分、降级、Top-K 只写一遍；调用方各自决定怎么打包输出。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.services.rag.constants import DEFAULT_CANDIDATE_N
from app.services.rag.retrieval.base import BaseRetriever


class BM25Retriever(BaseRetriever):
    """BM25Okapi 稀疏召回（jieba 中文分词）。

    ## 小语料降级（行为与 0.17.x 完全一致）
    `rank_bm25` 的 IDF 公式为 `log((N-df+0.5)/(df+0.5))`，
    语料很小时 `N≈df`，IDF 会变成 0 甚至负数，导致所有分数 ≤ 0。
    此时退化为「查询词在文档中出现的次数」打分，保证稀疏路仍然有效。
    """

    name = "bm25"

    def __init__(
        self,
        corpus: List[Dict],
        fields: Optional[List[str]] = None,
        k1: Optional[float] = None,
        b: Optional[float] = None,
    ):
        self.corpus = corpus or []
        self.fields = fields or ["text"]
        self.k1 = k1
        self.b = b
        #: 参与检索的文本（多字段时先拼接，默认只有 text）
        self.texts: List[str] = [
            " ".join(str(doc.get(f, "")) for f in self.fields) for doc in self.corpus
        ]
        self.index = self._build_index()

    # ---------------- 索引 ----------------

    def _build_index(self):
        """构建 BM25Okapi 索引；依赖缺失时返回 None（关闭稀疏路，不抛异常）。"""
        try:
            from rank_bm25 import BM25Okapi
            import jieba

            tokenized = [list(jieba.cut(text)) for text in self.texts]
            if not tokenized:
                return None
            kwargs = {}
            if self.k1 is not None:
                kwargs["k1"] = self.k1
            if self.b is not None:
                kwargs["b"] = self.b
            return BM25Okapi(tokenized, **kwargs)
        except Exception:  # noqa: BLE001  bm25 / jieba 缺失时关闭稀疏路
            return None

    # ---------------- 检索 ----------------

    def retrieve(
        self,
        query: str,
        top_k: int = DEFAULT_CANDIDATE_N,
        truncate_fallback: bool = False,
    ) -> List[Dict]:
        """返回 `[{index, doc_id, score}]`（按得分降序，只保留正分）。

        :param truncate_fallback: 词命中兜底是否也截断到 top_k。
            两条历史调用链的截断口径不同，必须区分才能保证行为一致：
              · Chroma 侧（`HybridRetrieval.bm25_search`）兜底**返回全量**；
              · 内存侧（`BM25Channel.search`）兜底**截断到 top_k**。
        """
        if not self.texts or self.index is None:
            return []
        try:
            import jieba

            scores = self.index.get_scores(list(jieba.cut(query)))
        except Exception:  # noqa: BLE001
            return []

        hits = self._rank(scores, top_k)
        if hits:
            return hits
        # 小语料兜底（见类 docstring）
        return self._token_overlap(query, top_k if truncate_fallback else None)

    def _rank(self, scores, top_k: int) -> List[Dict]:
        """按得分降序取前 top_k（用 sorted 而非 argsort，保持与旧实现的稳定排序一致）。"""
        values = [float(s) for s in scores]
        ranked = sorted(range(len(values)), key=lambda i: values[i], reverse=True)
        return [
            self._pack(i, values[i]) for i in ranked[:top_k] if values[i] > 0
        ]

    def _token_overlap(self, query: str, top_k: Optional[int] = None) -> List[Dict]:
        """降级打分：查询词在文档中出现的次数（BM25 分数全 ≤0 时使用）。"""
        try:
            import jieba

            tokens = [t for t in jieba.cut(query) if len(t) >= 2]
        except Exception:  # noqa: BLE001
            tokens = [query]
        tokens = tokens or [query]

        scored = []
        for i, text in enumerate(self.texts):
            score = sum(text.count(t) for t in tokens)
            if score:
                scored.append(self._pack(i, float(score)))
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k] if top_k else scored

    def _pack(self, index: int, score: float) -> Dict:
        """统一的内部结构（下游据此生成 doc_id / text / metadata）。"""
        doc = self.corpus[index] if index < len(self.corpus) else {}
        return {
            "index": index,
            "doc_id": doc.get("id") or f"{self.name}_{index}",
            "score": float(score),
        }


class BM25Channel(BM25Retriever):
    """稀疏通道的**兼容适配器**（0.18.0 保留旧构造与旧输出结构）。

    老 `retrieval.BM25Channel` 是 `MultiRecall` 的通道之一，
    对外契约是 `{doc_id, score, text, channel, full_doc}`。
    打分逻辑仍只有 `BM25Retriever` 一份，这里只做输出打包。
    """

    def __init__(
        self,
        name: str,
        docs: List[Dict],
        fields: Optional[List[str]] = None,
        weight: float = 1.0,
    ):
        super().__init__(docs, fields)
        self.name = name
        self.weight = weight

    def retrieve(self, query: str, top_k: int = 3) -> List[Dict]:
        hits = super().retrieve(query, top_k, truncate_fallback=True)
        return [self._pack_channel(h["index"], h["score"]) for h in hits]

    def _pack_channel(self, idx: int, score: float) -> Dict:
        """统一输出结构，便于上层融合与去重（与 0.17.x 完全一致）。"""
        return {
            "doc_id": self.corpus[idx].get("id") or f"{self.name}_{idx}",
            "score": float(score),
            "text": self.texts[idx],
            "channel": self.name,
            "full_doc": self.corpus[idx],
        }
