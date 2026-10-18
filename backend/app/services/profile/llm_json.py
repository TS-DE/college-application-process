"""通用 LLM 文本解析器（0.12.0）。

## 为什么单独抽一个类（合成复用原则 CRP）
「报告提取」和「问卷总结」两个场景都要做同一件事：
把大模型返回的、可能带 markdown 围栏 / 前后废话 / 尾逗号的文本，
稳健地解析成 Python 对象。抽成 `LLMJsonParser` 后两处复用同一实现，
避免复制粘贴出两份略有差异的解析逻辑。

## 大模型输出常见的四种脏数据（都实测遇到过）
1. 带 `<think>...</think>` 思考块（Qwen 系模型）；
2. 被 ```json ``` 围栏包住；
3. 前后有「好的，以下是提取结果：」这类自然语言；
4. 尾随逗号 `{"a": 1,}` 或全角引号。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# <think>...</think>（含  tags 变体）
_THINK_RE = re.compile(r"<think[^>]*>.*?</think[^>]*>", re.S | re.I)
# ```json ... ``` / ``` ... ```
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.S)
# 尾随逗号：{"a":1,} / [1,2,]
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
# 全角引号 → 半角（部分模型会输出 “key”）
_SMART_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


class LLMJsonParser:
    """把 LLM 文本解析成 dict / list，失败一律返回 None（绝不抛异常）。

    使用方只需关心「拿到什么」，不用关心文本有多脏。
    """

    # ---------------- 对外接口 ----------------

    @classmethod
    def parse_object(cls, text: Optional[str]) -> Optional[Dict[str, Any]]:
        """解析出第一个 JSON 对象；失败返回 None。"""
        data = cls._parse(text, expect="object")
        return data if isinstance(data, dict) else None

    @classmethod
    def parse_array(cls, text: Optional[str]) -> Optional[List[Any]]:
        """解析出第一个 JSON 数组；失败返回 None。"""
        data = cls._parse(text, expect="array")
        return data if isinstance(data, list) else None

    @classmethod
    def parse_any(cls, text: Optional[str]) -> Optional[Any]:
        """不限定类型（对象或数组都接受）。"""
        return cls._parse(text, expect="any")

    # ---------------- 内部实现 ----------------

    @classmethod
    def _parse(cls, text: Optional[str], expect: str = "any") -> Optional[Any]:
        cleaned = cls.clean(text)
        if not cleaned:
            return None

        # ① 直接就是合法 JSON（最常见）
        direct = cls._loads(cleaned)
        if cls._type_ok(direct, expect):
            return direct

        # ② 从文本里抠出第一个 {...} 或 [...]
        for candidate in cls._candidates(cleaned, expect):
            data = cls._loads(candidate)
            if cls._type_ok(data, expect):
                return data

        logger.info("[PROFILE] LLM 返回无法解析为 JSON（前 120 字）：%s", cleaned[:120])
        return None

    @staticmethod
    def clean(text: Optional[str]) -> str:
        """去掉思考块、代码围栏、首尾空白，统一引号。"""
        if not text:
            return ""
        out = _THINK_RE.sub("", str(text))
        fence = _FENCE_RE.search(out)
        if fence:
            out = fence.group(1)
        return out.translate(_SMART_QUOTES).strip()

    @staticmethod
    def _loads(raw: str) -> Optional[Any]:
        """宽松 json.loads：先原样，再修尾逗号。"""
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            try:
                return json.loads(_TRAILING_COMMA_RE.sub(r"\1", raw))
            except Exception:  # noqa: BLE001
                return None

    @staticmethod
    def _type_ok(data: Any, expect: str) -> bool:
        if expect == "object":
            return isinstance(data, dict)
        if expect == "array":
            return isinstance(data, list)
        return isinstance(data, (dict, list))

    @staticmethod
    def _candidates(text: str, expect: str) -> List[str]:
        """括号配对扫描，取出所有顶层 JSON 片段（最坏 O(n)）。"""
        pairs = {"[": "]", "{": "}"}
        opens = "[" if expect == "array" else "{" if expect == "object" else "[{"
        out: List[str] = []
        for start, ch in enumerate(text):
            if ch not in opens:
                continue
            close = pairs[ch]
            depth = 0
            in_str = False
            escape = False
            for i in range(start, len(text)):
                c = text[i]
                if escape:
                    escape = False
                    continue
                if c == "\\":
                    escape = True
                    continue
                if c == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if c == ch:
                    depth += 1
                elif c == close:
                    depth -= 1
                    if depth == 0:
                        out.append(text[start: i + 1])
                        break
        return out


__all__ = ["LLMJsonParser"]
