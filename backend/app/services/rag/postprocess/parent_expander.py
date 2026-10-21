"""父块回填（0.18.0 从 rag_service 搬出，逻辑未改）。

「小块命中、大块生成」的后半段：
  命中子块的 metadata 里有 `parent_chunk_id`，据此从 docstore 取回父块原文，
  把 120 字的子块换成 500 字的父块交给 LLM（上下文更完整）。
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Set

from app.services.knowledge.parent_store import get_parent


class ParentExpander:
    """把命中的子块替换为父块原文。

    三条件（与 0.17.x 完全一致）：
      1. 取回成功 → text 换成父块，标记 `context_level="parent"`
      2. **降级**：父块缺失 / 取回异常 → 保留子块，标记 `context_level="child"`，链路不中断
      3. 多个子块指向同一父块时按父块去重，保留得分最高的那个（先出现的）
    """

    def __init__(
        self,
        parent_lookup: Optional[Callable[[Optional[str]], Optional[Dict]]] = None,
    ):
        #: 父块查询函数（构造注入，便于测试替换；默认走 docstore）
        self._lookup = parent_lookup or get_parent

    def expand(self, hits: List[Dict]) -> List[Dict]:
        expanded: List[Dict] = []
        seen_parents: Set[str] = set()

        for hit in hits:
            meta = hit.get("metadata") or {}
            parent_id = meta.get("parent_chunk_id")
            parent = self._lookup(parent_id)

            if parent and parent.get("text"):
                if parent_id in seen_parents:
                    continue  # 同一父块的多个子块只保留一次
                seen_parents.add(parent_id)
                expanded.append({
                    **hit,
                    "text": parent["text"],           # 用父块原文替换子块，交给 LLM
                    "metadata": {**meta, "chunk_index": meta.get("chunk_index")},
                    "parent_chunk_id": parent_id,
                    "context_level": "parent",
                })
            else:
                # 降级：docstore 没有该父块（旧数据 / 文件被清），直接返回子块
                expanded.append({
                    **hit,
                    "parent_chunk_id": parent_id,
                    "context_level": "child",
                })

        return expanded
