"""检索后优化：Re-ranking 重排序（兼容外壳，0.18.0 起只做 re-export）。

实现已拆分到 `postprocess/` 包：

    postprocess/base.py                    BaseReranker（抽象）
    postprocess/cross_encoder_reranker.py  CrossEncoderReranker
    postprocess/embedding_reranker.py      EmbeddingReranker
    postprocess/noop_reranker.py           NoopReranker
    postprocess/reranker_factory.py        Reranker（门面：按配置选择 + 失败降级）

历史调用方（如 `tests/rag/test_advanced_rag.py: from app.services.rag.reranker import Reranker`）
无需改动。
"""
from __future__ import annotations

from app.services.rag.postprocess.base import BaseReranker
from app.services.rag.postprocess.cross_encoder_reranker import CrossEncoderReranker
from app.services.rag.postprocess.embedding_reranker import EmbeddingReranker
from app.services.rag.postprocess.noop_reranker import NoopReranker
from app.services.rag.postprocess.reranker_factory import Reranker

__all__ = [
    "BaseReranker",
    "CrossEncoderReranker",
    "EmbeddingReranker",
    "NoopReranker",
    "Reranker",
]
