"""统一 LLM / Embedding 通道（v2.5.1 热修复核心）。

## 为什么必须改（背景）
限时模型 `qwen3.7-flash-2026-07-15` **只能**走 OpenAI 兼容接口，且 base_url 必须是
工作空间专属域名：

    https://ws-66jxf85tc3oa6b98.cn-beijing.maas.aliyuncs.com/compatible-mode/v1

既**不能**用 `dashscope` Python SDK（`dashscope.Generation`），
也**不能**用通用域名 `https://dashscope.aliyuncs.com/compatible-mode/v1`（该模型不在那上面）。
v2.5.0 用的就是「通用域名 + requests 裸调」，结果所有 LLM 调用都要等到超时才降级 → **全部问答超时**。

Key 统一读环境变量 `Ali_API_KEY`；向量模型 `text-embedding-v3` 与大语言模型
共用同一个 Key 和同一个 base_url。

## 设计原则（面向对象七大原则）
- 单一职责：本模块只负责「怎么调模型」+「失败了怎么降级」，**不持有任何 Prompt**
- 开闭原则：新增通道只需加一个 `BaseLLMChannel` 子类，`LLMClient` 不用改
- 里氏替换：所有通道实现同一接口，可互相替换
- 依赖倒置：业务模块依赖抽象 `BaseLLMChannel / BaseEmbeddingChannel`，不依赖 openai SDK
- 接口隔离：LLM 只有 `chat()`，Embedding 只有 `embed()`，互不污染
- 迪米特法则：调用方只知道 `llm_client.chat()/embed()`，不知道背后是 Ali 还是 Ollama
- 合成复用：`LLMClient` **组合** primary + fallback 通道，而不是继承某个具体通道

## 降级链路
    Ali 通道（主） ──失败/无 Key──▶ Ollama 通道（兜底） ──失败──▶ None / ""
    每次失败都打印 [LLM] 日志；上层拿到 None 后做保守处理，绝不抛异常。
"""
from __future__ import annotations

import abc
import logging
import os
import re
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

# 环境变量名（大小写保持与系统配置一致）
ALI_KEY_ENV = "Ali_API_KEY"

# 降级日志统一前缀，便于 grep
LOG_PREFIX = "[LLM]"


# ====================== API Key 解析 ======================


def get_api_key() -> str:
    """读取 Ali_API_KEY。

    ① 环境变量 → ② Windows 注册表（Machine / User）。

    ② 的原因：系统环境变量是**服务进程启动之后**才配置的，Python 启动时读过的 os.environ
    里没有它；从注册表补读一次，就不必重启服务。
    """
    key = (os.getenv(ALI_KEY_ENV) or "").strip()
    if key:
        return key
    if os.name != "nt":
        return ""
    try:  # 仅 Windows
        import winreg

        # 系统级环境变量的真实位置是这个（不是 HKLM\Environment）
        for hive, sub in (
            (winreg.HKEY_CURRENT_USER, "Environment"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            ),
        ):
            try:
                with winreg.OpenKey(hive, sub) as h:
                    value, _ = winreg.QueryValueEx(h, ALI_KEY_ENV)
                    if value:
                        return str(value).strip()
            except OSError:
                continue
    except Exception:  # noqa: BLE001 读不到就是没有 Key，走降级
        pass
    return ""


def mask(key: str) -> str:
    """脱敏展示 Key（日志里不打印完整密钥）。"""
    if not key:
        return "<empty>"
    return f"{key[:6]}***{key[-4:]}"


# ====================== 通道抽象（接口隔离 + 依赖倒置） ======================


class BaseLLMChannel(abc.ABC):
    """LLM 通道抽象：只暴露 chat()。"""

    name: str = "base"

    @abc.abstractmethod
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        top_p: Optional[float] = None,
    ) -> Optional[str]:
        """返回模型回复文本；不可用/失败返回 None（由门面决定降级）。

        :param top_p: 核采样阈值，None 表示用通道自己的默认（保留 v2.3.1 兜底策略里调过的 0.3）
        """

    def available(self) -> bool:
        """通道是否可用（无 Key / SDK 缺失都算不可用）。供门面跳过该通道。"""
        return True


class BaseEmbeddingChannel(abc.ABC):
    """Embedding 通道抽象：只暴露 embed()。"""

    name: str = "base"

    @abc.abstractmethod
    def embed(self, text: str, dimensions: Optional[int] = None) -> Optional[List[float]]:
        """返回向量；不可用/失败返回 None。dimensions 为 None 时用通道默认维度。"""

    def embed_batch(self, texts: List[str], dimensions: Optional[int] = None) -> List[Optional[List[float]]]:
        """批量向量化。默认实现是逐条调用；支持原生批次的通道应重写（Ali 一次请求即可）。"""
        return [self.embed(t, dimensions=dimensions) for t in texts]

    def available(self) -> bool:
        return True


# ====================== Ali 通道（OpenAI 兼容接口） ======================


class AliLLMChannel(BaseLLMChannel):
    """阿里云工作空间 LLM 通道：`openai.OpenAI` 客户端 + 专属 base_url。

    与 v2.5.0 的区别就在两点：
      1. base_url 从通用 dashscope 域名换成工作空间专属域名
      2. 取值从手写 HTTP 换成 SDK 的 response.choices[0].message.content
    """

    name = "ali"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        timeout: float = 0,
    ):
        from app.config import settings

        self.api_key = (api_key or get_api_key()).strip()
        self.base_url = (base_url or settings.ALI_BASE_URL).rstrip("/")
        self.model = model or settings.ALI_LLM_MODEL
        self.timeout = timeout or settings.ALI_TIMEOUT
        # 思考型模型默认关掉「先想后答」：实测同一请求 9.7s → 2.6s，
        # 对本项目的判断类调用（YES/NO、RELEVANT）收益极大，答案质量无明显差异。
        self.enable_thinking = settings.ALI_ENABLE_THINKING
        self._client = None

    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def client(self):
        """懒加载 OpenAI 客户端（进程内复用同一个连接）。"""
        if self._client is None:
            from openai import OpenAI  # 局部导入：SDK 缺失不影响其他通道

            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0,  # 重试交给上层降级策略，避免叠加等待
            )
            logger.info("%s Ali 通道就绪 base_url=%s model=%s key=%s", LOG_PREFIX, self.base_url, self.model, mask(self.api_key))
        return self._client

    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.0, max_tokens: int = 512, top_p: Optional[float] = None) -> Optional[str]:
        if not self.available():
            return None
        messages: List[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        try:
            kwargs = {"temperature": temperature, "max_tokens": max_tokens}
            if top_p is not None:
                kwargs["top_p"] = top_p
            if not self.enable_thinking:
                # OpenAI 兼容接口关闭思考的方式：透传厂商私有参数
                kwargs["extra_body"] = {"enable_thinking": False}
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                **kwargs,
            )
            # OpenAI 兼容接口统一取值方式（不再有 dashscope 的 output.choices）
            text = (resp.choices[0].message.content or "").strip()
            return text or None
        except Exception as exc:  # noqa: BLE001 超时 / 403 / 网络错误 → 交给我方降级
            logger.warning("%s Ali 通道失败，降级到 Ollama：%s %s", LOG_PREFIX, exc.__class__.__name__, str(exc)[:200])
            return None


class AliEmbeddingChannel(BaseEmbeddingChannel):
    """阿里云工作空间 Embedding 通道：同一个 Key + 同一个 base_url。

    注意：text-embedding-v3 支持自定义维度，必须对齐已存在的 Chroma 集合维度，
    否则写入时会报维度不匹配（详见 rag_service.get_embedding）。
    """

    name = "ali_embed"

    def __init__(self, api_key: str = "", base_url: str = "", model: str = "", timeout: float = 0, dimensions: int = 0):
        from app.config import settings

        self.api_key = (api_key or get_api_key()).strip()
        self.base_url = (base_url or settings.ALI_BASE_URL).rstrip("/")
        self.model = model or settings.ALI_EMBED_MODEL
        self.timeout = timeout or settings.ALI_TIMEOUT
        self.dimensions = dimensions or settings.ALI_EMBED_DIMENSION
        self._client = None

    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0,
            )
        return self._client

    def embed(self, text: str, dimensions: Optional[int] = None) -> Optional[List[float]]:
        if not self.available() or not text:
            return None
        vecs = self.embed_batch([text], dimensions=dimensions)
        return vecs[0] if vecs else None

    def embed_batch(self, texts: List[str], dimensions: Optional[int] = None) -> List[Optional[List[float]]]:
        """一次请求向量化多条文本。

        多路召回要 embedding N 条 Query，逐条调用 = N 次网络往返；
        合成一次请求把「N 次往返」压成「1 次」，这是 search() 能否进 10 秒的关键。
        """
        batch = list(texts or [])
        if not batch or not self.available():
            return [None] * len(batch)
        dim = dimensions or self.dimensions
        try:
            resp = self.client.embeddings.create(
                input=batch,
                model=self.model,
                dimensions=dim,
            )
            # 接口不保证返回顺序，必须按 index 归位，否则会用到别人的向量
            result: List[Optional[List[float]]] = [None] * len(batch)
            for item in resp.data:
                idx = getattr(item, "index", None)
                if idx is None or not (0 <= idx < len(result)):
                    continue
                result[idx] = list(item.embedding)
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "%s Ali embedding 批量失败（%s 条/dim=%s），降级到 Ollama：%s %s",
                LOG_PREFIX, len(batch), dim, exc.__class__.__name__, str(exc)[:200],
            )
            return [None] * len(batch)


# ====================== Ollama 通道（本地兜底） ======================


class OllamaLLMChannel(BaseLLMChannel):
    """本地 Ollama 兜底通道：直接打原生 HTTP API，不依赖 ai_service（避免循环引用）。"""

    name = "ollama"

    def __init__(self, base_url: str = "", model: str = "", timeout: float = 0):
        from app.config import settings

        self.base_url = (base_url or settings.OLLAMA_URL).rstrip("/")
        self.model = model or settings.OLLAMA_FALLBACK_MODEL
        self.timeout = timeout or settings.OLLAMA_TIMEOUT

    _THINK_RE = re.compile(r"<think>.*?</think>", re.S)

    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.0, max_tokens: int = 512, top_p: Optional[float] = None) -> Optional[str]:
        prompt = f"{system_prompt}\n\n{user_prompt}" if system_prompt else user_prompt
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "top_p": top_p or 0.85, "num_predict": max_tokens},
        }
        try:
            resp = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout)
            if resp.status_code != 200:  # 老版本 Ollama 不认识 think 字段
                payload.pop("think", None)
                resp = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout)
            resp.raise_for_status()
            text = self._THINK_RE.sub("", resp.json().get("response", "") or "")
            return text.strip().strip("`").strip() or None
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s Ollama 通道失败，返回空串：%s %s", LOG_PREFIX, exc.__class__.__name__, str(exc)[:200])
            return None


class OllamaEmbeddingChannel(BaseEmbeddingChannel):
    """本地 Ollama embedding 兜底（nomic-embed-text，768 维，维度固定不可调）。"""

    name = "ollama_embed"

    def __init__(self, base_url: str = "", model: str = "", timeout: float = 0):
        from app.config import settings

        self.base_url = (base_url or settings.OLLAMA_URL).rstrip("/")
        self.model = model or settings.OLLAMA_EMBED_MODEL
        self.timeout = timeout or settings.OLLAMA_TIMEOUT

    def embed(self, text: str, dimensions: Optional[int] = None) -> Optional[List[float]]:
        if not text:
            return None
        try:
            resp = requests.post(
                f"{self.base_url}/api/embeddings",
                json={"model": self.model, "prompt": text},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json().get("embedding")
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s Ollama embedding 失败：%s %s", LOG_PREFIX, exc.__class__.__name__, str(exc)[:200])
            return None


# ====================== 门面（合成复用 + 降级编排） ======================


class _EmbeddingCache:
    """进程内向量缓存（组合进 LLMClient，不参与继承体系）。

    为什么必须有：一次问答里同一条 Query 会被多路召回 / Rerank 反复向量化 4~8 次，
    每次都是一次网络往返；缓存之后这些重复请求成本变为 0。
    """

    def __init__(self, max_items: int = 1024):
        self.max_items = max_items
        self._data: dict = {}

    @staticmethod
    def key(dim: Optional[int], text: str) -> tuple:
        return (dim, text)

    def get(self, dim: Optional[int], text: str) -> Optional[List[float]]:
        return self._data.get(self.key(dim, text))

    def set(self, dim: Optional[int], text: str, vec: Optional[List[float]]) -> None:
        if vec is None:
            return
        if len(self._data) >= self.max_items:  # 简易 FIFO，防止无限增长
            self._data.pop(next(iter(self._data)), None)
        self._data[self.key(dim, text)] = vec


class LLMClient:
    """LLM / Embedding 统一入口：主通道失败自动降级到兜底通道。

    两条通道都是构造时注入的抽象（依赖倒置）；换实现不用改本类。
    """

    def __init__(
        self,
        llm_channels: Optional[List[BaseLLMChannel]] = None,
        embed_channels: Optional[List[BaseEmbeddingChannel]] = None,
    ):
        self._llm_channels = llm_channels if llm_channels is not None else [AliLLMChannel(), OllamaLLMChannel()]
        self._embed_channels = embed_channels if embed_channels is not None else [AliEmbeddingChannel(), OllamaEmbeddingChannel()]
        self._cache = _EmbeddingCache()

    # ---------------- LLM ----------------
    def chat(self, system_prompt: str, user_prompt: str, temperature: float = 0.0, max_tokens: int = 512, top_p: Optional[float] = None) -> str:
        """按通道顺序尝试，返回首个非空结果；全失败返回空串（调用方做保守处理）。"""
        for ch in self._llm_channels:
            if not ch.available():
                continue
            out = ch.chat(system_prompt, user_prompt, temperature=temperature, max_tokens=max_tokens, top_p=top_p)
            if out:
                return out
        return ""

    @property
    def llm_channel_names(self) -> List[str]:
        return [c.name for c in self._llm_channels]

    # ---------------- Embedding ----------------
    def embed(self, text: str, dimensions: Optional[int] = None) -> Optional[List[float]]:
        """同样按通道顺序降级；全失败返回 None。命中缓存则零成本返回。"""
        cached = self._cache.get(dimensions, text)
        if cached is not None:
            return cached
        for ch in self._embed_channels:
            if not ch.available():
                continue
            vec = ch.embed(text, dimensions=dimensions)
            if vec:
                self._cache.set(dimensions, text, vec)
                return vec
        return None

    def embed_batch(self, texts: List[str], dimensions: Optional[int] = None) -> List[Optional[List[float]]]:
        """批量向量化：按通道顺序降级，「这一批没补齐的部分」才交给下一个通道补。

        返回长度与入参一致，缺失位置用 None 占位，调用方按位置自行降级。
        """
        batch = list(texts or [])
        if not batch:
            return []
        # ① 先过缓存，命中的不再发请求
        result: List[Optional[List[float]]] = [self._cache.get(dimensions, t) for t in batch]
        # ② 未命中的才按通道降级请求
        for ch in self._embed_channels:
            missing = [i for i, v in enumerate(result) if v is None]
            if not missing or not ch.available():
                continue
            vecs = ch.embed_batch([batch[i] for i in missing], dimensions=dimensions) or []
            for slot, vec in zip(missing, vecs):
                if vec:
                    result[slot] = vec
                    self._cache.set(dimensions, batch[slot], vec)
        return result

    @property
    def embed_channel_names(self) -> List[str]:
        return [c.name for c in self._embed_channels]


_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """进程内单例（懒加载）。"""
    global _client
    if _client is None:
        _client = LLMClient()
    logger.debug("%s 通道顺序 llm=%s embed=%s", LOG_PREFIX, _client.llm_channel_names, _client.embed_channel_names)
    return _client


def reset_client() -> None:
    """重置单例（测试或配置变更后使用）。"""
    global _client
    _client = None
