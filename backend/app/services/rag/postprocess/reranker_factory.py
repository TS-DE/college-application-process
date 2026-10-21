"""精排门面：按配置选择实现并负责失败降级（0.18.0 从 reranker.py 搬出，逻辑未改）。

优先级：
  1. `settings.RERANK_MODEL` 有值且 CrossEncoder 可用 → CrossEncoderReranker
  2. `settings.RERANK_ENABLED=1`                     → EmbeddingReranker（默认）
  3. 关闭                                             → NoopReranker
"""
from __future__ import annotations

from typing import Dict, List, Optional

from app.config import settings
from app.services.rag.postprocess.base import BaseReranker
from app.services.rag.postprocess.cross_encoder_reranker import CrossEncoderReranker
from app.services.rag.postprocess.embedding_reranker import EmbeddingReranker
from app.services.rag.postprocess.noop_reranker import NoopReranker


class Reranker:
    """重排序门面：按配置选择实现，并负责失败降级（合成复用）。"""

    def __init__(self, impl: Optional[BaseReranker] = None):
        self.impl = impl or self._build()

    @staticmethod
    def _build() -> BaseReranker:
        if not settings.RERANK_ENABLED:
            return NoopReranker()
        if settings.RERANK_MODEL:
            try:
                return CrossEncoderReranker(settings.RERANK_MODEL)
            except Exception:  # noqa: BLE001 模型不可用 → 降级
                pass
        return EmbeddingReranker()

    def rerank(self, query: str, hits: List[Dict], top_k: Optional[int] = None) -> List[Dict]:
        """对候选列表二次精排。

        hits：项目内部 hit 结构（至少含 text / metadata）
        返回：按 rerank_score 降序的结果，并保留原始召回分（rrf_score）便于对比
        """
        if not hits:
            return hits
        try:
            scores = self.impl.score(query, [h.get("text", "") for h in hits])
        except Exception:  # noqa: BLE001 精排失败 → 保持召回顺序，链路不中断
            for h in hits:
                h["rerank_score"] = None
                h["reranker"] = "failed"
            return hits

        scored = []
        for h, s in zip(hits, scores):
            item = dict(h)
            item["rerank_score"] = float(s)
            item["reranker"] = self.impl.name
            scored.append(item)
        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored[:top_k] if top_k else scored
