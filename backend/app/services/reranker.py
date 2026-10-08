"""检索后优化：Re-ranking 重排序（参考课堂案例 01_检索后优化_重排序.py）。

两阶段检索：
    第 1 阶段（召回）：多路召回拿到较多数量的候选（Recall，重在全）
    第 2 阶段（精排）：Reranker 对「(query, doc)」逐对打分并重排（Precision，重在准）

类结构（单一职责 + 开闭 + 依赖倒置 + 里氏替换）：
    BaseReranker            抽象基类：定义 score(query, docs) 接口
      ├── CrossEncoderReranker  用 sentence_transformers 的 CrossEncoder（效果最好，需本地模型）
      ├── EmbeddingReranker     用项目已有 embedding 做余弦精排（无额外依赖，永远可用）
      └── NoopReranker         空实现（关闭精排时直传，保证链路一致）
    Reranker                门面类：按配置选择具体实现（合成复用）
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Sequence

from app.config import settings


class BaseReranker(ABC):
    """重排序抽象基类（接口隔离）：只要求实现 score()。"""

    name = "base"

    @abstractmethod
    def score(self, query: str, docs: Sequence[str]) -> List[float]:
        """给「问题-文档」逐对打分，分数越高越相关。"""


class CrossEncoderReranker(BaseReranker):
    """CrossEncoder 精排：把 (query, doc) 拼在一起过一遍模型，精度最高。

    需要 sentence_transformers + 本地模型（settings.RERANK_MODEL 指定路径）。
    模型不可用（未安装 / 路径错误）时抛错，由 Reranker 门面降级到 EmbeddingReranker。
    """

    name = "cross_encoder"

    def __init__(self, model_path: str):
        from sentence_transformers import CrossEncoder  # 延迟导入，缺失时由调用方捕获

        self.model = CrossEncoder(model_path)

    def score(self, query: str, docs: Sequence[str]) -> List[float]:
        pairs = [[query, d] for d in docs]
        return [float(s) for s in self.model.predict(pairs)]


class EmbeddingReranker(BaseReranker):
    """向量余弦精排：复用项目已有的 embedding（Ollama / DashScope），无需额外模型。

    虽然不如 CrossEncoder 精准，但「召回用稀疏/稠密的融合分，精排用语义余弦」
    已经能把语义最贴近的文档顶到前面。
    """

    name = "embedding"

    def __init__(self, embed_fn: Optional[Callable[[str], Optional[List[float]]]] = None):
        self.embed_fn = embed_fn

    def _embed(self, text: str) -> Optional[List[float]]:
        if self.embed_fn:
            return self.embed_fn(text)
        from app.services import rag_service  # 延迟导入，避免循环依赖

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


class NoopReranker(BaseReranker):
    """空精排：关闭 Rerank 时直传（保证调用方无需分支判断）。"""

    name = "noop"

    def score(self, query: str, docs: Sequence[str]) -> List[float]:
        return [1.0] * len(docs)


class Reranker:
    """重排序门面：按配置选择实现，并负责失败降级。

    优先级：
      1. settings.RERANK_MODEL 有值且 CrossEncoder 可用 → CrossEncoderReranker
      2. settings.RERANK_ENABLED=1                     → EmbeddingReranker（默认）
      3. 关闭                                          → NoopReranker
    """

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
