"""查询扩展（后退一步 / Step-Back，0.18.0 从 query_rewrite.py 搬出，逻辑未改）。

类名从 `QueryExpander` 改为语义更明确的 `StepBackExpander`；
旧名在 `query_rewrite.py` 里以别名保留，历史 import 不受影响。
"""
from __future__ import annotations

import re
from typing import Optional

from app.services.rag.preprocess.base import BasePreprocessor, llm_chat


class StepBackExpander(BasePreprocessor):
    """查询扩展：生成"后退一步"的宽泛查询，用于补充背景上下文（Step-Back Prompting）。"""

    name = "expansion"

    SYSTEM_PROMPT = (
        "你是一名擅长检索策略的AI助手。你的任务是将具体的用户查询改写为更宽泛、更通用的问题，"
        "以便检索到相关的背景信息和更广泛的上下文。"
    )

    def __init__(self, model: Optional[str] = None):
        self.model = model

    def run(self, query: str) -> str:
        """`BasePreprocessor` 契约（等价于 `step_back`）。"""
        return self.step_back(query)

    def step_back(self, query: str) -> str:
        """返回宽泛化的 Query；失败返回空串（调用方忽略）。"""
        query = (query or "").strip()
        if not query:
            return ""
        user_prompt = (
            "请将下列查询改写为更宽泛、更通用的问题，以便有助于检索相关的背景信息和更广泛的上下文。\n"
            "只输出一条问题，不要解释。\n\n"
            f"原始查询：{query}\n\n后退一步的查询："
        )
        out = llm_chat(self.SYSTEM_PROMPT, user_prompt, temperature=0.1, model=self.model)
        if not out:
            return ""
        out = re.sub(r"^后退一步的查询[:：]\s*", "", out.strip()).strip()
        return out
