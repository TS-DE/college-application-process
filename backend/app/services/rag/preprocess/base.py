"""检索前处理抽象基类 + LLM 通道（0.18.0 从 query_rewrite.py 搬出）。

## LLM 通道为什么放在这里
重写 / 扩展 / 分解三者都要调模型，而通道选择与降级由 `services/llm/llm_client.py` 负责
（单一职责）。这里只保留一个**极薄的统一入口** `llm_chat()`，
三个子类共用，避免各写一份「取 Key / 判空 / 兜底」。
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import List, Optional, Union


def default_chat_model() -> str:
    """当前生效的大语言模型名。

    优先级：环境变量 ALI_LLM_MODEL → settings.ALI_LLM_MODEL（默认 qwen3.7-flash）。
    真正的调用不在本包：通道选择与降级都由 `app/services/llm/llm_client.py` 负责。
    """
    from app.config import settings

    return os.getenv("ALI_LLM_MODEL") or settings.ALI_LLM_MODEL


DEFAULT_CHAT_MODEL = "qwen3.7-flash"


def get_api_key() -> str:
    """读取 Ali_API_KEY（委托 llm_client）。"""
    from app.services.llm.llm_client import get_api_key as _get_key

    return _get_key()


def llm_chat(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
    model: Optional[str] = None,
    max_tokens: int = 128,
) -> str:
    """统一的 LLM 调用入口（委托给 llm_client）。

    通道顺序由 llm_client 决定：Ali（OpenAI 兼容，已关思考）→ 本地 Ollama；
    两级都失败返回空串，调用方各自做保守处理（保留原始 Query / 走单路检索），不抛异常。

    :param model:      保留形参仅为兼容旧签名；实际模型名由通道自己的配置决定
    :param max_tokens: 本包只产出检索用的短语，128 足够
    """
    from app.services.llm.llm_client import get_llm_client

    return get_llm_client().chat(
        system_prompt or "", user_prompt, temperature=temperature, max_tokens=max_tokens
    )


class BasePreprocessor(ABC):
    """检索前处理器接口：一条 Query 进，增强结果出。

    三种实现的产出形态不同（字符串 / 字符串 / 列表），因此 `run()` 的返回类型用
    联合类型标注；调用方（`QueryPreprocessor`）知道具体子类的语义。
    """

    name: str = "base"

    @abstractmethod
    def run(self, query: str) -> Union[str, List[str]]:
        """执行预处理；失败时必须降级（返回原 Query 或空结果），不得抛异常。"""
