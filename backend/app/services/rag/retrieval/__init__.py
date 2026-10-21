"""检索中：单路召回、融合与混合检索（0.18.0 从 rag_service / retrieval.py 收敛）。

## 为什么这里同时做 re-export
0.17.x 的实现放在**模块文件** `rag/retrieval.py`，0.18.0 改成了**包** `rag/retrieval/`。
同名文件与包不能共存（导入器优先取包），因此原 `retrieval.py` 的兼容导出
整体搬到这里 —— 历史调用方仍可写：

    from app.services.rag.retrieval import BM25Channel, DenseChannel, HybridSearch, MultiRecall

新代码建议直接从子模块导入（意图更明确）。
"""
from __future__ import annotations

from app.services.rag.constants import RRF_K as DEFAULT_RRF_K
from app.services.rag.retrieval.base import BaseRetriever as ChannelRetriever
from app.services.rag.retrieval.bm25 import BM25Channel
from app.services.rag.retrieval.dense import (
    DenseChannel,
    ProjectEmbedding,
    _cosine_matrix,
    get_embedding_model,
)
from app.services.rag.retrieval.fusion import (
    BaseFusion,
    RoundRobinFusion,
    RrfFusion,
    WeightFusion,
)
from app.services.rag.retrieval.hybrid import HybridRetriever, HybridSearch
from app.services.rag.retrieval.keyword_fallback import KeywordFallbackRetriever
from app.services.rag.retrieval.multi_recall import MultiRecallRetriever as MultiRecall


def _rrf_fuse(rankings, k: int = DEFAULT_RRF_K, top_k: int = 5):
    """RRF 融合兼容入口（旧实现是函数，现委托 `RrfFusion`，公式只有一份）。"""
    return RrfFusion(k=k, key="doc_id").fuse(rankings, top_k=top_k)


__all__ = [
    "DEFAULT_RRF_K",
    "ChannelRetriever",
    "BaseFusion",
    "RrfFusion",
    "WeightFusion",
    "RoundRobinFusion",
    "DenseChannel",
    "BM25Channel",
    "HybridSearch",
    "HybridRetriever",
    "MultiRecall",
    "KeywordFallbackRetriever",
    "ProjectEmbedding",
    "get_embedding_model",
    "_rrf_fuse",
    "_cosine_matrix",
]
