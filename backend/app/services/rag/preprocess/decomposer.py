"""子查询分解（0.18.0 从 query_rewrite.py 搬出，逻辑未改）。"""
from __future__ import annotations

import json
import re
from typing import List, Optional

from app.services.rag.preprocess.base import BasePreprocessor, llm_chat


class QueryDecomposer(BasePreprocessor):
    """子查询分解：把复合问题拆成若干聚焦不同侧面的子问题。"""

    name = "decompose"

    SYSTEM_PROMPT = (
        "你是一名擅长将复杂问题拆解为简单子问题的AI助手。你的任务是把复杂的用户查询分解为"
        "若干个更简单、聚焦不同方面的子问题，所有子问题的答案合起来可以完整回答原始问题。"
    )

    def __init__(self, model: Optional[str] = None, num_subqueries: int = 3, max_len: int = 30):
        self.model = model
        self.num_subqueries = num_subqueries
        self.max_len = max_len

    def run(self, query: str) -> List[str]:
        """`BasePreprocessor` 契约（等价于 `decompose`）。"""
        return self.decompose(query)

    def decompose(self, query: str) -> List[str]:
        """返回子查询列表；失败返回空列表（调用方按原始 Query 处理）。"""
        query = (query or "").strip()
        if not query:
            return []
        user_prompt = (
            f"请将下列复杂查询拆解为 {self.num_subqueries} 个更简单的子问题。每个子问题应关注原始问题的不同方面。\n"
            f"每条不超过 {self.max_len} 字，每行一个，格式如下：\n"
            "1. [第一个子问题]\n2. [第二个子问题]\n以此类推……\n\n"
            f"原始查询：{query}"
        )
        out = llm_chat(self.SYSTEM_PROMPT, user_prompt, temperature=0.2, model=self.model)
        return self._parse(out)

    def _parse(self, content: Optional[str]) -> List[str]:
        """解析编号列表，兼容 JSON 输出。"""
        if not content:
            return []
        # 情况一：模型返回 JSON
        if "{" in content and "}" in content:
            try:
                data = json.loads(content[content.find("{"): content.rfind("}") + 1])
                items = data.get("queries") if isinstance(data, dict) else data
                if isinstance(items, list):
                    return [str(x).strip() for x in items if str(x).strip()]
            except Exception:  # noqa: BLE001
                pass

        # 情况二：模型返回编号列表
        subs: List[str] = []
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^(\d+)[\.、\)]\s*(.+)$", line)
            text = m.group(2).strip() if m else line
            text = text.strip("[]【】").strip()
            if text and len(text) <= self.max_len + 10:
                subs.append(text)
        return subs
