"""查询重写（0.18.0 从 query_rewrite.py 搬出，逻辑未改）。"""
from __future__ import annotations

import re
from typing import Optional

from app.services.rag.preprocess.base import BasePreprocessor, llm_chat


class QueryRewriter(BasePreprocessor):
    """查询重写：让 Query 更具体、更适合检索（补关键词、去口语化）。"""

    name = "rewrite"

    SYSTEM_PROMPT = (
        "你是一名擅长优化检索查询的AI助手。你的任务是将用户的查询改写得更加具体、详细，"
        "并包含有助于检索准确信息的相关术语和概念。"
    )

    def __init__(self, model: Optional[str] = None, max_len: int = 50):
        self.model = model
        self.max_len = max_len

    def run(self, query: str) -> str:
        """`BasePreprocessor` 契约（等价于 `rewrite`）。"""
        return self.rewrite(query)

    def rewrite(self, query: str) -> str:
        """返回重写后的 Query；失败时原样返回（降级）。"""
        query = (query or "").strip()
        if not query:
            return query
        user_prompt = (
            "请将下列查询改写为更具体、更详细的表达，补充相关的关键词和概念，"
            "以便更好地检索到准确的信息。\n"
            f"约束：{self.max_len}字以内，只输出改写后的查询，不要解释。\n\n"
            f"原始查询：{query}\n\n改写后的查询："
        )
        out = llm_chat(self.SYSTEM_PROMPT, user_prompt, temperature=0.0, model=self.model)
        return self._clean(out) or query

    @staticmethod
    def _clean(text: Optional[str]) -> str:
        if not text:
            return ""
        # 去掉可能的前缀说明与引号
        text = text.strip().strip('"').strip("'").strip()
        text = re.sub(r"^(改写后的查询|结果)[:：]\s*", "", text)
        return text.strip()
