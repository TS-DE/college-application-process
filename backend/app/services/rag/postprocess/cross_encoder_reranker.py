"""CrossEncoder 精排（0.18.0 从 reranker.py 搬出，逻辑未改）。"""
from __future__ import annotations

from typing import List, Sequence

from app.services.rag.postprocess.base import BaseReranker


class CrossEncoderReranker(BaseReranker):
    """CrossEncoder 精排：把 (query, doc) 拼在一起过一遍模型，精度最高。

    需要 sentence_transformers + 本地模型（settings.RERANK_MODEL 指定路径）。
    模型不可用（未安装 / 路径错误）时抛错，由 `Reranker` 门面降级到 EmbeddingReranker。
    """

    name = "cross_encoder"

    def __init__(self, model_path: str):
        from sentence_transformers import CrossEncoder  # 延迟导入，缺失时由调用方捕获

        self.model = CrossEncoder(model_path)

    def score(self, query: str, docs: Sequence[str]) -> List[float]:
        pairs = [[query, d] for d in docs]
        return [float(s) for s in self.model.predict(pairs)]
