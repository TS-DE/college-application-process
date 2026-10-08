"""检索前模块：查询重写 / 查询扩展 / 子查询分解 / 统一预处理入口。

参考课堂案例 01_查询重写.py / 02_查询扩展.py / 03_子查询.py，
统一走 DashScope（OpenAI 兼容接口），API Key 从环境变量 DASHSCOPE_API_KEY 读取。

类结构：
    QueryRewriter    查询重写：把口语化问题改写成更适合检索的表达（temperature=0.0）
    QueryExpander    查询扩展：生成"后退一步"的宽泛查询，补充背景上下文（temperature=0.1）
    QueryDecomposer  子查询分解：把复合问题拆成多个聚焦子问题（temperature=0.2）
    QueryPreprocessor 统一入口：按需组合上面三步，输出最终用于检索的 Query 列表

降级策略（重要）：
    - 没有 DASHSCOPE_API_KEY / 调用失败 / 解析失败 → 自动回落到本地 Ollama；
    - 本地 Ollama 也不可用 → 返回原始 Query，按单路检索处理，链路不中断。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import requests


# ====================== DashScope（OpenAI 兼容）调用封装 ======================

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def default_chat_model() -> str:
    """统一的 DashScope 模型名（v2.5.0 起默认 qwen3.7-flash-2026-07-15）。

    优先级：环境变量 DASHSCOPE_CHAT_MODEL → config.DASHSCOPE_MODEL → 代码默认值。
    课堂案例里的 qwen-plus 已因免费额度用尽不可用，统一改到新模型。
    """
    from app.config import settings

    return (
        os.getenv("DASHSCOPE_CHAT_MODEL")
        or getattr(settings, "DASHSCOPE_MODEL", "")
        or "qwen3.7-flash-2026-07-15"
    )


DEFAULT_CHAT_MODEL = "qwen3.7-flash-2026-07-15"


def get_dashscope_key() -> str:
    """读取 DashScope API Key：环境变量优先，Windows 下补全读注册表（Machine/User 作用域）。

    说明：系统环境变量在「服务进程启动之后」才配置时，os.getenv 读不到，
    这里兜底从注册表读取，避免必须重启服务才生效。
    """
    key = os.getenv("DASHSCOPE_API_KEY") or ""
    if key:
        return key
    if os.name != "nt":
        return ""
    try:  # 仅 Windows
        import winreg

        # 注意：系统级环境变量在注册表中的真实位置是
        # HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment（不是 HKLM\Environment）
        paths = [
            (winreg.HKEY_CURRENT_USER, "Environment"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            ),
        ]
        for hive, sub in paths:
            try:
                with winreg.OpenKey(hive, sub) as h:
                    value, _ = winreg.QueryValueEx(h, "DASHSCOPE_API_KEY")
                    if value:
                        return str(value).strip()
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass
    return ""


def _dashscope_chat(system_prompt: str, user_prompt: str, temperature: float = 0.0,
                    model: Optional[str] = None) -> Optional[str]:
    """调用 DashScope 的 OpenAI 兼容 chat/completions 接口，失败返回 None。"""
    key = get_dashscope_key()
    if not key:
        return None
    try:
        resp = requests.post(
            f"{DASHSCOPE_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model or default_chat_model(),
                "temperature": temperature,
                # 思考型模型（如 qwen3.7-flash）的 reasoning_content 可能很长，
                # 不限制会拖到读超时（30s）后再降级，白白多等一轮，这里显式封顶
                "max_tokens": 512,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=(10, 30),  # （连接超时，读超时）
        )
        resp.raise_for_status()
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception:  # noqa: BLE001
        return None


def _ollama_chat(prompt: str) -> Optional[str]:
    """本地兜底：用项目已有的 Ollama 调用（ai_service.ask）。"""
    try:
        from app.services.ai_service import ask

        return ask(prompt, temperature=0.0, num_predict=200, timeout=30)
    except Exception:  # noqa: BLE001
        return None


def llm_chat(system_prompt: str, user_prompt: str, temperature: float = 0.0,
             model: Optional[str] = None) -> Optional[str]:
    """统一的 LLM 调用：DashScope 优先，失败回落本地 Ollama，再失败返回 None。"""
    text = _dashscope_chat(system_prompt, user_prompt, temperature=temperature, model=model)
    if text:
        return text
    return _ollama_chat(f"{system_prompt}\n\n{user_prompt}")


# ====================== 查询重写 ======================

class QueryRewriter:
    """查询重写：让 Query 更具体、更适合检索（补关键词、去口语化）。"""

    SYSTEM_PROMPT = (
        "你是一名擅长优化检索查询的AI助手。你的任务是将用户的查询改写得更加具体、详细，"
        "并包含有助于检索准确信息的相关术语和概念。"
    )

    def __init__(self, model: Optional[str] = None, max_len: int = 50):
        self.model = model
        self.max_len = max_len

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


# ====================== 查询扩展（后退一步） ======================

class QueryExpander:
    """查询扩展：生成"后退一步"的宽泛查询，用于补充背景上下文（Step-Back Prompting）。"""

    SYSTEM_PROMPT = (
        "你是一名擅长检索策略的AI助手。你的任务是将具体的用户查询改写为更宽泛、更通用的问题，"
        "以便检索到相关的背景信息和更广泛的上下文。"
    )

    def __init__(self, model: Optional[str] = None):
        self.model = model

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


# ====================== 子查询分解 ======================

class QueryDecomposer:
    """子查询分解：把复合问题拆成若干聚焦不同侧面的子问题。"""

    SYSTEM_PROMPT = (
        "你是一名擅长将复杂问题拆解为简单子问题的AI助手。你的任务是把复杂的用户查询分解为"
        "若干个更简单、聚焦不同方面的子问题，所有子问题的答案合起来可以完整回答原始问题。"
    )

    def __init__(self, model: Optional[str] = None, num_subqueries: int = 3, max_len: int = 30):
        self.model = model
        self.num_subqueries = num_subqueries
        self.max_len = max_len

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


# ====================== 统一预处理入口 ======================

@dataclass
class QueryBundle:
    """检索前预处理的产物。"""

    original: str                                  # 原始 Query（必定保留，兜底用）
    rewritten: str = ""                            # 重写后的 Query
    step_back: str = ""                            # 后退一步的宽泛 Query
    sub_queries: List[str] = field(default_factory=list)  # 子查询列表
    all_queries: List[str] = field(default_factory=list)  # 最终送给检索的 Query 列表
    source: str = "raw"                            # dashscope / ollama / raw（便于排查）


class QueryPreprocessor:
    """检索前统一入口：按需执行 重写 → 扩展 → 分解，产出用于多路召回的 Query 列表。

    输出顺序：原始 Query 置顶（保证兜底召回），其后是重写 / 扩展 / 子查询，
    去重后限制条数，避免多路召回拖慢响应。
    """

    def __init__(
        self,
        use_rewrite: bool = True,
        use_expansion: bool = True,
        use_decompose: bool = True,
        max_queries: int = 4,
        model: Optional[str] = None,
    ):
        self.use_rewrite = use_rewrite
        self.use_expansion = use_expansion
        self.use_decompose = use_decompose
        self.max_queries = max_queries
        self.rewriter = QueryRewriter(model=model)
        self.expander = QueryExpander(model=model)
        self.decomposer = QueryDecomposer(model=model)

    def process(self, query: str) -> QueryBundle:
        """执行检索前预处理。任一步失败都不影响整体（降级为原始 Query）。"""
        original = (query or "").strip()
        bundle = QueryBundle(original=original, all_queries=[original] if original else [])

        # ① 查询重写
        if self.use_rewrite:
            try:
                bundle.rewritten = self.rewriter.rewrite(original)
            except Exception:  # noqa: BLE001
                bundle.rewritten = ""

        # ② 查询扩展（后退一步）
        if self.use_expansion:
            try:
                bundle.step_back = self.expander.step_back(original)
            except Exception:  # noqa: BLE001
                bundle.step_back = ""

        # ③ 子查询分解
        if self.use_decompose:
            try:
                bundle.sub_queries = self.decomposer.decompose(original)
            except Exception:  # noqa: BLE001
                bundle.sub_queries = []

        # ④ 汇总去重 + 限条数（原始 Query 置顶）
        candidates = [original, bundle.rewritten, bundle.step_back, *bundle.sub_queries]
        seen, merged = set(), []
        for q in candidates:
            q = (q or "").strip()
            if not q or q in seen:
                continue
            seen.add(q)
            merged.append(q)
        bundle.all_queries = merged[: self.max_queries]

        # ⑤ 标注来源，便于排查
        bundle.source = "dashscope" if get_dashscope_key() else "ollama"
        if len(bundle.all_queries) <= 1:
            bundle.source = "raw"
        return bundle
