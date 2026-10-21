"""单路召回抽象基类（0.18.0）。

统一契约的目的：`HybridRetriever`、`MultiRecallRetriever` 这些编排者
只依赖 `retrieve()`，不关心对方是 Chroma ANN、BM25 还是关键词兜底
（依赖倒置 + 里氏替换）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from app.services.rag.constants import DEFAULT_TOP_K


class BaseRetriever(ABC):
    """单路召回接口：给 Query，返回按相关度降序的命中列表。

    统一输出字段（各实现可附加自己的字段）：
        index : int        该实现在自己语料里的下标（Chroma 侧用）
        doc_id: str        文档唯一标识（内存语料侧用）
        score : float|None 相似度/得分，越高越相关（距离类指标放 distance）
    """

    #: 通道名（用于加权融合与日志）
    name: str = "base"

    #: 通道权重（加权融合时使用；默认等权）
    weight: float = 1.0

    @abstractmethod
    def retrieve(self, query: str, top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        """召回 top_k 条。实现方必须自行吞掉异常并返回 []（不允许中断整条链路）。"""

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        """兼容旧名：`retrieval.py` 里各通道一直叫 search()。"""
        return self.retrieve(query, top_k)
