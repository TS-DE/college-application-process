"""空精排（0.18.0 从 reranker.py 搬出，逻辑未改）。

关闭 Rerank 时直传，保证调用方无需分支判断（里氏替换：与其它实现契约一致）。
"""
from __future__ import annotations

from typing import List, Sequence

from app.services.rag.postprocess.base import BaseReranker


class NoopReranker(BaseReranker):
    """空精排：所有文档同分，排序结果即召回顺序。"""

    name = "noop"

    def score(self, query: str, docs: Sequence[str]) -> List[float]:
        return [1.0] * len(docs)
