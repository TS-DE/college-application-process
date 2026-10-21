"""多路结果融合（0.18.0 收敛为一处实现）。

## 为什么必须收敛
收敛前 RRF 公式存在两份：
  · `rag_service.HybridRetrieval.rrf()` —— 以语料下标 `index` 为键
  · `retrieval._rrf_fuse()`             —— 以 `doc_id` 为键
两者公式完全相同（`score += 1/(k+rank)`），只是键不同。
于是 `RrfFusion.accumulate()` 把「按什么键累加」做成参数，
两条调用链共用同一段数学实现（改 bug 只改这里）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.rag.constants import DEFAULT_TOP_K, RRF_K


class BaseFusion(ABC):
    """融合策略接口：把多路已排序的命中列表合成一个排名。"""

    name: str = "base"

    @abstractmethod
    def fuse(self, rankings: List[List[Dict]], top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        """rankings[i] 是第 i 路的召回结果（各自已按相关度降序）。"""


class RrfFusion(BaseFusion):
    """倒数排名融合（Reciprocal Rank Fusion）。

    公式：score(doc) = Σ 1 / (k + rank_i)
      - k = 60：常数，用来"压平"前几名的分数差。
        没有 k 时 rank=1 得 1.0、rank=2 得 0.5，第一名权重过大；
        加了 60 之后 rank=1 → 1/61、rank=2 → 1/62，差距被平滑，
        让"两路都还行"的文档能压过"一路第一、另一路垫底"的文档。
      - rank_i：该文档在第 i 路检索结果里的名次（从 1 开始）
      - 用排名而不是分数：稠密距离与 BM25 得分量纲不同，无法直接加权平均，
        换成排名后无需归一化即可融合。

    示例（文档 A：稠密第 2、BM25 第 5）：
        score = 1/(60+2) + 1/(60+5) = 0.01613 + 0.01538 = 0.03151
    示例（文档 B：稠密第 1、BM25 第 20）：
        score = 1/(60+1) + 1/(60+20) = 0.01639 + 0.01250 = 0.02889
    → A > B：单路第一但另一路很差的 B 会被拉低。
    """

    name = "rrf"

    def __init__(self, k: int = RRF_K, key: str = "doc_id"):
        self.k = k
        #: 用哪个字段做文档标识（Chroma 侧是 index，内存语料侧是 doc_id）
        self.key = key

    def accumulate(
        self, rankings: Sequence[List[Dict]]
    ) -> Tuple[Dict[Any, float], List[Dict[Any, int]]]:
        """只做数学部分：返回（文档 → 累加分数，每路的名次表）。

        `HybridRetrieval.rrf()` 需要「分数 + 各路名次」做调试字段，
        `fuse()` 只需要分数 + 原始命中，因此把累加单独抽出来复用。
        """
        rank_maps: List[Dict[Any, int]] = []
        scores: Dict[Any, float] = {}
        for ranking in rankings:
            rank_map = {h[self.key]: rank for rank, h in enumerate(ranking, start=1)}
            rank_maps.append(rank_map)
            for key, rank in rank_map.items():
                scores[key] = scores.get(key, 0.0) + 1.0 / (self.k + rank)
        return scores, rank_maps

    def fuse(self, rankings: List[List[Dict]], top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        """累加后取 Top-K，并保留每个文档的「最高分命中」作为代表。"""
        scores, _ = self.accumulate(rankings)
        best: Dict[Any, Dict] = {}
        for ranking in rankings:
            for hit in ranking:
                key = hit[self.key]
                if key not in best or hit.get("score", 0.0) > best[key].get("score", 0.0):
                    best[key] = hit

        ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        return [{**best[key], "rrf_score": score, "channel": "multi"} for key, score in ordered]


class WeightFusion(BaseFusion):
    """加权融合：命中分 × 通道权重，按 doc_id 去重后取 Top-K。

    与 RRF 的区别：RRF 只看名次（量纲无关），加权融合直接用原始分数，
    因此**只在各通道分数可比时**才合适（当前仅作为可配置项保留）。
    """

    name = "weight"

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or {}

    def fuse(self, rankings: List[List[Dict]], top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        dedup: Dict[str, Dict] = {}
        for ranking in rankings:
            for hit in ranking:
                channel = hit.get("channel", "")
                wscore = float(hit.get("score", 0.0)) * self.weights.get(channel, 1.0)
                doc_id = hit.get("doc_id")
                if doc_id not in dedup or wscore > dedup[doc_id]["weighted_score"]:
                    dedup[doc_id] = {**hit, "weighted_score": wscore}
        ordered = sorted(dedup.values(), key=lambda x: x["weighted_score"], reverse=True)
        return ordered[:top_k]


class RoundRobinFusion(BaseFusion):
    """轮询融合：各通道轮流取一个，保证每路都有曝光。"""

    name = "round_robin"

    def fuse(self, rankings: List[List[Dict]], top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        final: List[Dict] = []
        pointers = [0] * len(rankings)
        while len(final) < top_k and any(p < len(r) for p, r in zip(pointers, rankings)):
            for i, ranking in enumerate(rankings):
                if pointers[i] < len(ranking):
                    final.append(ranking[pointers[i]])
                    pointers[i] += 1
                    if len(final) >= top_k:
                        break
        return final
