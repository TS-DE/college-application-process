"""高级 RAG：Corrective RAG（参考课堂案例 03_correctiveRAG（用python原生实现）.py）。

Corrective RAG 的核心是「**纠偏**」：
    检索 → 逐条筛掉无关文档 → 若一条都不相关，说明**查询本身有问题** →
    重写 Query 再检索一次 → 仍不足才拒答。

相比 Self-RAG（管"要不要检索/回答好不好"），Corrective RAG 管的是"**召回的文档对不对**"。

模型：settings.ALI_LLM_MODEL（默认 qwen3.7-flash-2026-07-15），走 OpenAI 兼容接口，
失败降级本地 Ollama（llm_client 负责通道编排）。
检索器/生成器通过构造函数注入（依赖倒置），不引入 LlamaIndex 等框架，纯 Python 原生实现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from app.config import settings


@dataclass
class CorrectiveRAGResult:
    """Corrective RAG 运行结果。"""

    answer: str
    used_docs: List[str] = field(default_factory=list)
    # 筛选后保留的原始 hit（含 metadata），供上层取来源，避免再检索一次
    hits: List[Dict] = field(default_factory=list)
    rewritten_query: str = ""
    retry_count: int = 0
    steps: List[str] = field(default_factory=list)


class CorrectiveRAG:
    """Corrective RAG：检索 → 相关性过滤 → 不足则重写查询重试 → 生成。

    :param retriever: 检索函数 (query, top_k) -> List[hit]
    :param generator: 生成函数 (query, context) -> str
    :param llm:      底层 LLM 调用（便于降级与测试）
    """

    def __init__(
        self,
        retriever: Callable[[str, int], List[Dict]],
        generator: Callable[[str, str], str],
        llm: Optional[Callable[[str], Optional[str]]] = None,
        top_k: int = 5,
        max_retry: int = 0,
    ):
        self.retriever = retriever
        self.generator = generator
        self.top_k = top_k
        self.max_retry = max_retry or settings.CORRECTIVE_MAX_RETRY
        self._llm = llm

    # ---------------- 底层 LLM（带降级） ----------------
    def llm(self, prompt: str, temperature: float = 0.0, max_tokens: int = 128) -> str:
        """底层 LLM 调用：Ali 通道优先，失败降级本地 Ollama；两级都失败返回空串做保守处理。

        :param max_tokens: 输出上限，判断类调用建议 16，改写类 128，生成类走 generator 另算
        """
        if self._llm:
            return (self._llm(prompt) or "").strip()
        try:
            from app.services.llm_client import get_llm_client

            return get_llm_client().chat("", prompt, temperature=temperature, max_tokens=max_tokens).strip()
        except Exception:  # noqa: BLE001
            return ""

    # ---------------- 三个原子能力 ----------------
    def is_relevant(self, query: str, doc: str) -> bool:
        """判断单条文档是否能回答用户问题（RELEVANT / IRRELEVANT）。

        只输出一个标签，因此 max_tokens 给到 16 就够 —— 推理 token 更少、返回更快。
        """
        prompt = (
            "判断文档是否能回答用户问题，只输出 RELEVANT 或 IRRELEVANT。\n\n"
            f"问题：{query}\n文档：{doc}\n输出："
        )
        out = self.llm(prompt, temperature=0.0, max_tokens=16).upper()
        return "IRRELEVANT" not in out and "RELEVANT" in out

    def _filter_relevant(self, query: str, hits: List[Dict], relevant: List[str], relevant_hits: List[Dict]) -> None:
        """并发执行相关性判断（v2.5.1 提速），结果按原始顺序追加到传入容器。"""
        if not hits:
            return
        if len(hits) == 1:
            if self.is_relevant(query, hits[0].get("text", "")):
                relevant.append(hits[0].get("text", ""))
                relevant_hits.append(hits[0])
            return
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=min(len(hits), 4)) as pool:
            flags = list(pool.map(lambda h: self.is_relevant(query, h.get("text", "")), hits))
        for h, ok in zip(hits, flags):
            if ok:
                relevant.append(h.get("text", ""))
                relevant_hits.append(h)

    def rewrite_query(self, query: str) -> str:
        """改写查询：让它更清晰、更容易命中知识库。"""
        prompt = (
            "优化这个问题，让它更清晰、更容易检索到相关信息。\n"
            "只输出优化后的问题，不要解释。\n\n"
            f"原始：{query}\n优化后："
        )
        out = self.llm(prompt, temperature=0.0)
        return out or query

    def generate_answer(self, query: str, docs: List[str]) -> str:
        """基于筛选后的文档生成答案（禁止编造）。"""
        context = "\n---\n".join(docs)
        return self.generator(query, context)

    # ---------------- 完整流程 ----------------
    def run(self, query: str, top_k: Optional[int] = None) -> CorrectiveRAGResult:
        """执行 Corrective RAG：检索 → 过滤 →（不足则重写重试）→ 生成。"""
        k = top_k or self.top_k
        result = CorrectiveRAGResult(answer="")

        # ① 初次检索
        hits = self.retriever(query, k) or []
        result.steps.append(f"retrieved={len(hits)}")
        if not hits:
            result.answer = "根据现有资料，未查询到具体信息，建议查阅学校官方招生简章。"
            return result

        # ② 相关性过滤（v2.5.1：各文档互不依赖，并发判断）
        relevant: List[str] = []
        relevant_hits: List[Dict] = []
        self._filter_relevant(query, hits, relevant, relevant_hits)
        result.steps.append(f"relevant={len(relevant)}")

        # ③ 全部无关 → 重写 Query 重试（最多 max_retry 次）
        current_query = query
        while not relevant and result.retry_count < self.max_retry:
            new_q = self.rewrite_query(current_query)
            result.rewritten_query = new_q
            result.retry_count += 1
            result.steps.append(f"retry_{result.retry_count}:{new_q}")
            retry_hits = self.retriever(new_q, k) or []
            self._filter_relevant(query, retry_hits, relevant, relevant_hits)
            current_query = new_q

        if not relevant:
            result.answer = "根据现有资料，未查询到具体信息，建议查阅学校官方招生简章。"
            return result

        # ④ 生成
        result.used_docs = relevant
        result.hits = relevant_hits
        result.answer = self.generate_answer(query, relevant)
        result.steps.append("generated")
        return result
