"""检索前模块（兼容外壳）：实现已拆分到 `preprocess/` 包（0.18.0）。

原文件里的四个类现在各自独立成模块：

    preprocess/base.py          BasePreprocessor + llm_chat 通道
    preprocess/rewriter.py      QueryRewriter
    preprocess/expander.py      StepBackExpander（原 QueryExpander）
    preprocess/decomposer.py    QueryDecomposer
    preprocess/preprocessor.py  QueryPreprocessor + QueryBundle

`QueryExpander` 保留为 `StepBackExpander` 的别名，
因此 `from app.services.rag.query_rewrite import QueryExpander` 等历史写法继续可用
（见 `tests/rag/test_query_preprocess_recall.py`）。
"""
from __future__ import annotations

from app.services.rag.preprocess.base import (
    DEFAULT_CHAT_MODEL,
    BasePreprocessor,
    default_chat_model,
    get_api_key,
    llm_chat,
)
from app.services.rag.preprocess.decomposer import QueryDecomposer
from app.services.rag.preprocess.expander import StepBackExpander
from app.services.rag.preprocess.preprocessor import QueryBundle, QueryPreprocessor
from app.services.rag.preprocess.rewriter import QueryRewriter

#: 兼容别名：0.18.0 起语义化命名为 StepBackExpander
QueryExpander = StepBackExpander

__all__ = [
    "DEFAULT_CHAT_MODEL",
    "BasePreprocessor",
    "QueryRewriter",
    "QueryExpander",
    "StepBackExpander",
    "QueryDecomposer",
    "QueryPreprocessor",
    "QueryBundle",
    "default_chat_model",
    "get_api_key",
    "llm_chat",
]
