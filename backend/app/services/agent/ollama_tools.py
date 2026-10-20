"""本地 Ollama 的 Function Calling 客户端（0.13.0）。

## 为什么不用 llm_client.LLMClient
`LLMClient.chat()` 走的是 Ollama 的 `/api/generate`（纯文本补全），
**不支持 `tools` 参数**。Function Calling 必须用 `/api/chat`，
两者请求/响应结构都不同，硬塞进 `LLMClient` 会让那个门面变得又大又杂。
因此单独一个客户端，只负责「带 tools 的一轮对话」。

## 兼容性策略（两级）
1. **原生 tools**：`/api/chat` 带 `tools`，模型返回 `message.tool_calls`。
   qwen3:4b 在 Ollama 0.6+ 上支持。
2. **JSON 规划兜底**：若服务端返回 400（老版本 Ollama / 模型不带 tools 能力），
   标记 `_tools_supported=False`，改由 `runner` 用 `PLANNER_PROMPT` 让模型输出
   `{"tool": "...", "query": "..."}` 的 JSON，实现「同样的自主选择、不同的协议」。

这样即使换到不支持 tools 的环境，Agent 的核心能力（模型自主决定查什么）也不丢。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

from app.services.agent.base import ToolCall

logger = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think[^>]*>.*?</think[^>]*>", re.S | re.I)


@dataclass
class LLMReply:
    """一轮对话的返回。"""

    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    error: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


class OllamaToolClient:
    """Ollama `/api/chat` 客户端（支持 tools，含优雅降级）。"""

    def __init__(self, base_url: str = "", model: str = "", timeout: float = 0) -> None:
        from app.config import settings

        self.base_url = (base_url or settings.OLLAMA_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = timeout or settings.OLLAMA_TIMEOUT
        # 一旦探测到服务端不支持 tools 就永久关闭，避免每次都多打一次失败请求
        self._tools_supported: Optional[bool] = None

    # ---------------- 能力探测 ----------------

    @property
    def tools_supported(self) -> Optional[bool]:
        """True / False / None（尚未探测）。"""
        return self._tools_supported

    def mark_tools_unsupported(self) -> None:
        self._tools_supported = False

    def available(self) -> bool:
        return bool(self.base_url and self.model)

    # ---------------- 主入口 ----------------

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.1,
        num_predict: int = 600,
        timeout: Optional[float] = None,
        force_no_tools: bool = False,
    ) -> LLMReply:
        """带 tools 的一轮对话。

        :param messages:        OpenAI 格式消息列表
        :param tools:           工具规格；None / 空 表示不带工具
        :param force_no_tools:  强制不带工具（用于「必须给出最终答案」的收尾轮）
        """
        if not self.available():
            return LLMReply(error="Ollama 未配置")

        use_tools = bool(tools) and not force_no_tools and self._tools_supported is not False
        payload: Dict[str, Any] = {
            "model": self.model,
            # ★ 关键：qwen3 系列必须用 `/no_think` 软开关才会走 tool_calls。
            # 实测（Ollama + qwen3:4b）：
            #   · 只传 `"think": false` → 模型把推理写进 content，tool_calls 恒为空；
            #   · 在 system 末尾加 `/no_think` → 正确返回 tool_calls，content 为空。
            # 这是**模型/传输层**的怪癖，所以在这里统一处理，不污染 prompts.py。
            "messages": self._with_no_think(messages),
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_predict": num_predict, "top_p": 0.85},
        }
        if use_tools:
            payload["tools"] = tools

        http_timeout = timeout or self.timeout
        try:
            resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=http_timeout)
            # 400 且带 tools → 服务端/模型不支持工具调用，降级并重试一次
            if resp.status_code == 400 and use_tools:
                logger.info(
                    "[AGENT] Ollama 不支持 tools（HTTP 400），降级为 JSON 规划模式：%s",
                    resp.text[:160],
                )
                self.mark_tools_unsupported()
                payload.pop("tools", None)
                resp = requests.post(
                    f"{self.base_url}/api/chat", json=payload, timeout=http_timeout
                )
            if resp.status_code != 200:
                return LLMReply(error=f"HTTP {resp.status_code}: {resp.text[:160]}")
            data = resp.json()
        except requests.Timeout:
            return LLMReply(error=f"Ollama 超时（>{http_timeout}s）")
        except Exception as exc:  # noqa: BLE001
            return LLMReply(error=f"{exc.__class__.__name__}: {str(exc)[:150]}")

        message = data.get("message") or {}
        if use_tools and self._tools_supported is None:
            # 带 tools 且成功返回 → 说明支持
            self._tools_supported = True

        content = _THINK_RE.sub("", message.get("content") or "").strip()
        calls = self._parse_tool_calls(message.get("tool_calls") or [])
        return LLMReply(content=content, tool_calls=calls, raw=data)

    # ---------------- 模型适配 ----------------

    @staticmethod
    def _with_no_think(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """给 system 消息补上 Qwen3 的 `/no_think` 软开关。

        · 已有 system → 追加到末尾（幂等，不重复加）；
        · 没有 system → 在最前面插一条。
        只影响首条 system，不动 user / assistant / tool 消息。
        """
        out: List[Dict[str, Any]] = [dict(m) for m in (messages or [])]
        if not out:
            return [{"role": "system", "content": "/no_think"}]
        if out[0].get("role") == "system":
            content = str(out[0].get("content") or "")
            if "/no_think" not in content:
                out[0]["content"] = (content.rstrip() + "\n/no_think").strip()
            return out
        return [{"role": "system", "content": "/no_think"}] + out

    # ---------------- 解析 ----------------

    @staticmethod
    def _parse_tool_calls(raw_calls: List[Dict]) -> List[ToolCall]:
        """把 Ollama 的 tool_calls 解析成统一结构。

        不同版本差异：
          · `function.arguments` 可能是 dict，也可能是 JSON 字符串；
          · 部分版本把 name 放在 `function.name`，少数放在顶层。
        """
        out: List[ToolCall] = []
        for item in raw_calls or []:
            if not isinstance(item, dict):
                continue
            fn = item.get("function") or {}
            name = (fn.get("name") or item.get("name") or "").strip()
            if not name:
                continue
            args = fn.get("arguments") or item.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:  # noqa: BLE001 参数不是合法 JSON → 当空处理
                    args = {}
            if not isinstance(args, dict):
                args = {}
            out.append(
                ToolCall(
                    name=name,
                    arguments=args,
                    call_id=str(item.get("id") or ""),
                )
            )
        return out


__all__ = ["OllamaToolClient", "LLMReply"]
