"""本地可算指标（★ 默认路径：完全不调用 LLM 打分，规避 API 报错 / 额度耗尽）。

实现参考课堂案例 `demo01_RAGAS.py` 的 `calc_retrieval_metrics`：
- 语义相似度由 embedding 向量余弦得出（优先 Ali text-embedding-v3，失败降级本地 Ollama）
- context_precision / context_recall 需要一个相似度阈值来判定「命中」，默认 0.65
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# 标准答案分句逻辑（与 data_builder 保持一致，单独内联以免跨层依赖）
_SPLIT_PATTERN = re.compile(r"(?<=[。！？；])")
_MIN_GOLD_CHUNK_LEN = 12


class LocalMetrics:
    """全部可在本地算出的检索 / 语义指标集合。"""

    def __init__(self, threshold: float = 0.65) -> None:
        self.threshold = threshold
        self._embed_cache: Dict[str, Optional[List[float]]] = {}

    # ---------------- 向量与相似度 ----------------

    def _embed(self, texts: Sequence[str]) -> List[Optional[List[float]]]:
        """批量向量化（带进程内缓存，避免同一段文本重复请求）。"""
        from app.services.rag import rag_service

        todo = [t for t in texts if t and t not in self._embed_cache]
        if todo:
            try:
                vectors = rag_service.get_embeddings_batch(todo)
            except Exception as exc:  # noqa: BLE001 通道异常时指标降级为 0，不中断评估
                logger.warning("[Eval] embedding 失败，指标降级：%s", exc)
                vectors = [None] * len(todo)
            for text, vec in zip(todo, vectors):
                self._embed_cache[text] = vec
        return [self._embed_cache.get(t) for t in texts]

    @staticmethod
    def _cosine(a: Optional[List[float]], b: Optional[List[float]]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        try:
            import numpy as np

            va, vb = np.array(a, dtype=float), np.array(b, dtype=float)
            denom = (va @ vb) / ((va @ va) ** 0.5 * (vb @ vb) ** 0.5)
            return float(denom) if (va @ va) and (vb @ vb) else 0.0
        except Exception:  # noqa: BLE001 没有 numpy 时退化到纯 Python
            dot = sum(x * y for x, y in zip(a, b))
            na = sum(x * x for x in a) ** 0.5
            nb = sum(y * y for y in b) ** 0.5
            return dot / (na * nb) if na and nb else 0.0

    def split_gold_chunks(self, text: str) -> List[str]:
        chunks = [c.strip() for c in _SPLIT_PATTERN.split(text or "")]
        return [c for c in chunks if len(c) >= _MIN_GOLD_CHUNK_LEN]

    def semantic_similarity(self, pred: str, gold: str) -> float:
        """预测答案与标准答案的语义相似度（BGE/Ali embedding 余弦）。"""
        if not pred or not gold:
            return 0.0
        a, b = self._embed([pred, gold])
        return round(self._cosine(a, b), 4)

    # ---------------- 上下文指标 ----------------

    def calc_context_precision(self, retrieved_contexts: Sequence[str], ground_truth: str,
                               threshold: Optional[float] = None) -> float:
        """召回片段中「与标准答案相关」的比例 → 越高说明噪声越少。

        判定方式：每个召回片段与任一标准答案句做余弦相似度，>= 阈值视为相关。
        """
        threshold = self.threshold if threshold is None else threshold
        if not retrieved_contexts:
            return 0.0
        gold_chunks = self.split_gold_chunks(ground_truth) or [ground_truth]
        vec_texts = list(retrieved_contexts) + gold_chunks
        vectors = self._embed(vec_texts)
        ctx_vecs = vectors[: len(retrieved_contexts)]
        gold_vecs = vectors[len(retrieved_contexts):]

        relevant = 0
        for cv in ctx_vecs:
            if any(self._cosine(cv, gv) >= threshold for gv in gold_vecs):
                relevant += 1
        return round(relevant / len(retrieved_contexts), 4)

    def calc_context_recall(self, retrieved_contexts: Sequence[str], ground_truth: str,
                            threshold: Optional[float] = None) -> float:
        """标准答案中被召回片段覆盖的比例 → 越高说明漏召回越少。"""
        threshold = self.threshold if threshold is None else threshold
        gold_chunks = self.split_gold_chunks(ground_truth) or [ground_truth]
        if not gold_chunks or not retrieved_contexts:
            return 0.0
        vec_texts = list(retrieved_contexts) + gold_chunks
        vectors = self._embed(vec_texts)
        ctx_vecs = vectors[: len(retrieved_contexts)]
        gold_vecs = vectors[len(retrieved_contexts):]

        covered = 0
        for gv in gold_vecs:
            if any(self._cosine(gv, cv) >= threshold for cv in ctx_vecs):
                covered += 1
        return round(covered / len(gold_vecs), 4)

    # ---------------- 排序指标 ----------------

    @staticmethod
    def calc_mrr(retrieved_ids: Sequence[str], gold_ids: Sequence[str]) -> float:
        """首个相关文档出现位次的倒数 → 关注「排第几」。"""
        gold = set(gold_ids or [])
        if not gold or not retrieved_ids:
            return 0.0
        for i, rid in enumerate(retrieved_ids):
            if rid in gold:
                return round(1.0 / (i + 1), 4)
        return 0.0

    @staticmethod
    def calc_ndcg(retrieved_ids: Sequence[str], gold_ids: Sequence[str], k: int = 5) -> float:
        """折损累计增益 → 同时关注「相关性」与「排序位置」。"""
        gold = set(gold_ids or [])
        ranked = list(retrieved_ids or [])[:k]
        if not gold or not ranked:
            return 0.0

        dcg = sum(1.0 / __import__("math").log2(i + 2) for i, rid in enumerate(ranked) if rid in gold)
        ideal_len = min(len(gold), len(ranked))
        idcg = sum(1.0 / __import__("math").log2(i + 2) for i in range(ideal_len))
        return round(dcg / idcg, 4) if idcg else 0.0

    @staticmethod
    def calc_hit_rate(retrieved_ids: Sequence[str], gold_ids: Sequence[str]) -> float:
        """命中率 → 前 K 条里是否含有相关文档（0/1）。"""
        gold = set(gold_ids or [])
        return 1.0 if gold and any(rid in gold for rid in (retrieved_ids or [])) else 0.0
