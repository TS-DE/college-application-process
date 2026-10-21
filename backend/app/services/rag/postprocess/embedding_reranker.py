"""向量余弦精排（0.18.0 从 reranker.py 搬出，逻辑未改）。"""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence

from app.services.rag.postprocess.base import BaseReranker


class EmbeddingReranker(BaseReranker):
    """向量余弦精排：复用项目已有的 embedding（Ali / Ollama），无需额外模型。

    虽然不如 CrossEncoder 精准，但「召回用稀疏/稠密的融合分，精排用语义余弦」
    已经能把语义最贴近的文档顶到前面。
    """

    name = "embedding"

    def __init__(self, embed_fn: Optional[Callable[[str], Optional[List[float]]]] = None):
        self.embed_fn = embed_fn

    def _embed(self, text: str) -> Optional[List[float]]:
        if self.embed_fn:
            return self.embed_fn(text)
        from app.services.rag import rag_service  # 延迟导入，避免循环依赖

        return rag_service.get_embedding(text)

    def score(self, query: str, docs: Sequence[str]) -> List[float]:
        q_vec = self._embed(query)
        if not q_vec:
            return [0.0] * len(docs)
        scores: List[float] = []
        for d in docs:
            d_vec = self._embed(d)
            if not d_vec:
                scores.append(0.0)
                continue
            # 余弦相似度
            dot = sum(a * b for a, b in zip(q_vec, d_vec))
            nq = sum(a * a for a in q_vec) ** 0.5 or 1.0
            nd = sum(b * b for b in d_vec) ** 0.5 or 1.0
            scores.append(dot / (nq * nd))
        return scores
