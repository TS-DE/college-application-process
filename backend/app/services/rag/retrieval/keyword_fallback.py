"""关键词兜底检索（0.18.0 从 rag_service 搬出）。

用途：向量库不可用（Chroma 起不来）或混合检索全部落空时，
直接对库内文档做「查询词出现次数」打分，保证链路不中断。
"""
from __future__ import annotations

import re
from typing import Dict, List

from app.services.rag.constants import DEFAULT_TOP_K
from app.services.rag.retrieval.base import BaseRetriever


class KeywordFallbackRetriever(BaseRetriever):
    """无向量能力时的兜底：对库内文档做关键词打分。

    输出结构与 0.17.x 保持一致：`{text, metadata, distance}`
    （`distance` 存负分，便于与向量距离同样按升序排序）。
    """

    name = "keyword_fallback"

    def __init__(self, store):
        #: VectorStore（提供 collection()）
        self._store = store

    def retrieve(self, query: str, top_k: int = DEFAULT_TOP_K) -> List[Dict]:
        col = self._store.collection()
        if col is None:
            return []
        try:
            data = col.get(include=["documents", "metadatas"])
        except Exception:  # noqa: BLE001
            return []
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        keys = [k for k in re.split(r"[\s，。？！、,.;!?]+", query) if len(k) >= 2]
        scored = []
        for doc, meta in zip(docs, metas):
            score = sum(doc.count(k) for k in keys)
            if score:
                scored.append({"text": doc, "metadata": meta or {}, "distance": float(-score)})
        scored.sort(key=lambda x: x["distance"])
        return scored[:top_k]
