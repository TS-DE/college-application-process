"""精排抽象基类（0.18.0 从 reranker.py 搬出，逻辑未改）。

两阶段检索的第 2 阶段：
    第 1 阶段（召回）：多路召回拿到较多数量的候选（Recall，重在全）
    第 2 阶段（精排）：Reranker 对「(query, doc)」逐对打分并重排（Precision，重在准）

只要求实现 `score()`，具体用 CrossEncoder、向量余弦还是空实现由子类决定
（接口隔离 + 里氏替换）。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Sequence


class BaseReranker(ABC):
    """重排序抽象基类（接口隔离）：只要求实现 score()。"""

    name = "base"

    @abstractmethod
    def score(self, query: str, docs: Sequence[str]) -> List[float]:
        """给「问题-文档」逐对打分，分数越高越相关。"""
