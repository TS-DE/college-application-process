"""多路召回（0.18.0 从 retrieval.py 搬出）。

结构不变：
  · 通道：DenseChannel / BM25Channel / HybridSearch（把混合检索当"复合通道"）
  · 子查询：检索前预处理产出的多条 Query，每条都独立召回
  · 融合：RRF / 加权 / 轮询，三种策略都委托给 `fusion.py`（数学只写一份）
  · 降级：单通道异常只跳过该通道，不影响整体链路
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from app.services.rag.constants import DEFAULT_TOP_K, RRF_K
from app.services.rag.retrieval.fusion import RoundRobinFusion, RrfFusion, WeightFusion


class MultiRecallRetriever:
    """多路召回：多个通道 × 多条子查询 → RRF / 加权 / 轮询融合。"""

    def __init__(self, channels: List):
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

    def _rankings(
        self, queries: Sequence[str], top_k_per_channel: int
    ) -> List[List[Dict]]:
        """收集「子查询 × 通道」的每一路排名（空路与异常路直接跳过）。"""
        rankings: List[List[Dict]] = []
        for query in queries:
            for ch in self.channels:
                try:
                    hits = ch.search(query, top_k=top_k_per_channel)
                    if hits:
                        rankings.append(hits)
                except Exception:  # noqa: BLE001
                    continue
        return rankings

    # ---------- 融合策略一：RRF（推荐，量纲无关） ----------
    def rrf_fusion(
        self,
        queries: Sequence[str],
        top_k: int = DEFAULT_TOP_K,
        top_k_per_channel: int = 20,
        k: int = RRF_K,
    ) -> List[Dict]:
        """跨「子查询 × 通道」的所有排名列表做 RRF 累加：score += 1/(k + rank)。"""
        rankings = self._rankings(queries, top_k_per_channel)
        return RrfFusion(k=k, key="doc_id").fuse(rankings, top_k=top_k)

    # ---------- 融合策略二：加权融合 ----------
    def weight_fusion(
        self, query: str, top_k: int = DEFAULT_TOP_K, top_k_per_channel: int = 3
    ) -> List[Dict]:
        """加权融合：score × channel.weight，按 doc_id 去重后取 Top-K。"""
        all_results = self._multi_recall(query, top_k_per_channel)
        by_channel: Dict[str, List[Dict]] = {}
        for hit in all_results:
            by_channel.setdefault(hit.get("channel", ""), []).append(hit)
        weights = {ch.name: ch.weight for ch in self.channels}
        return WeightFusion(weights).fuse(list(by_channel.values()), top_k=top_k)

    # ---------- 融合策略三：轮询融合 ----------
    def round_robin_fusion(
        self, query: str, top_k: int = DEFAULT_TOP_K, top_k_per_channel: int = 3
    ) -> List[Dict]:
        """轮询融合：各通道轮流取一个，保证每路都有曝光。"""
        all_results = self._multi_recall(query, top_k_per_channel)
        by_channel: Dict[str, List[Dict]] = {}
        for hit in all_results:
            by_channel.setdefault(hit.get("channel", ""), []).append(hit)
        return RoundRobinFusion().fuse(list(by_channel.values()), top_k=top_k)
