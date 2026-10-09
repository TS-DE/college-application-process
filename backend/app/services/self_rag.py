"""高级 RAG：Self-RAG（参考课堂案例 02_self_RAG（python原生）.py）。

Self-RAG 的核心不是"多检索几次"，而是让模型**自己判断每一步**：
    ① 是否真的需要检索（避免无关问题浪费检索）
    ② 检索到的上下文是否有用（避免拿噪声去生成）
    ③ 生成结果是否合格（不完整就反思修正）

模型：统一使用 settings.ALI_LLM_MODEL（默认 qwen3.7-flash-2026-07-15），
走 OpenAI 兼容接口（llm_client.AliLLMChannel），失败自动降级本地 Ollama（OLLAMA_FALLBACK_MODEL）。
检索器与生成器通过构造函数注入（依赖倒置），便于替换与单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class SelfRAGResult:
    """Self-RAG 的运行结果（含每一步的判断，便于排查与演示）。"""

    answer: str
    used_context: List[str] = field(default_factory=list)
    # 命中的原始 hit（含 metadata），供上层取来源，避免再检索一次
    hits: List[Dict] = field(default_factory=list)
    need_retrieve: bool = True
    context_useful: bool = False
    steps: List[str] = field(default_factory=list)


class SelfRAG:
    """Self-RAG：判断 → 检索 → 再判断 → 生成 → 反思修正。

    :param retriever: 检索函数 (query, top_k) -> List[hit]，hit 至少含 text
    :param generator: 生成函数 (query, context) -> str，无资料时 context 为空串
    :param llm:      底层 LLM 调用 (prompt) -> str，由调用方注入（便于降级与测试）
    """

    def __init__(
        self,
        retriever: Callable[[str, int], List[Dict]],
        generator: Callable[[str, str], str],
        llm: Optional[Callable[[str], Optional[str]]] = None,
        top_k: int = 3,
    ):
        self.retriever = retriever
        self.generator = generator
        self.top_k = top_k
        self._llm = llm

    # ---------------- 底层 LLM（带降级） ----------------
    def llm(self, prompt: str, temperature: float = 0.0, max_tokens: int = 16) -> str:
        """底层 LLM 调用：Ali OpenAI 兼容通道优先，失败降级本地 Ollama（llm_client 内部编排）。

        :param max_tokens: 本类只用 LLM 做判断（YES/NO），输出一个标签即够，
                          默认 16 token，既省推理时间也省费用。
        两级都失败 → 返回空串，由各判断做保守处理（不抛异常，链路不中断）。
        """
        if self._llm:
            return (self._llm(prompt) or "").strip()
        try:
            from app.services.llm_client import get_llm_client

            return get_llm_client().chat("", prompt, temperature=temperature, max_tokens=max_tokens).strip()
        except Exception:  # noqa: BLE001 两层都失败 → 返回空串，由各判断做保守处理
            return ""

    # ---------------- Self-RAG 四步判断 ----------------
    def should_retrieve(self, query: str) -> bool:
        """步骤①：是否需要检索外部知识？（YES / NO）"""
        prompt = (
            "判断问题是否需要检索外部知识才能回答。\n"
            "只输出 YES 或 NO，不要输出其他内容。\n\n"
            f"问题：{query}"
        )
        out = self.llm(prompt, temperature=0.0).upper()
        if "YES" in out and "NO" not in out.split("YES")[0]:
            return True
        # 兜底：模型没按格式输出时，按「是否像知识型问题」保守判断
        return out.startswith("YES")

    def is_context_useful(self, query: str, context: str) -> bool:
        """步骤②：检索到的上下文能否支撑回答？（YES / NO）"""
        prompt = (
            "根据检索到的内容，判断能否准确回答用户问题。\n"
            "只输出 YES 或 NO，不要输出其他内容。\n\n"
            f"问题：{query}\n内容：{context}"
        )
        return self.llm(prompt, temperature=0.0).upper().startswith("YES")

    def should_continue_generate(self, query: str, context: str, answer: str) -> bool:
        """步骤③：回答是否完整准确？（YES=合格 / NO=需要修正）"""
        prompt = (
            "判断回答是否完整、准确、无幻觉。\n"
            "完整准确 → YES；不完整或错误 → NO。\n"
            "只输出 YES 或 NO。\n\n"
            f"问题：{query}\n内容：{context}\n回答：{answer}"
        )
        return self.llm(prompt, temperature=0.0).upper().startswith("YES")

    def reflect_and_correct(self, query: str, context: str, answer: str) -> str:
        """步骤④：自我反思修正（Self-RAG 的灵魂）—— 对照上下文改掉幻觉与遗漏。"""
        prompt = (
            "你是严谨的 Self-RAG 修正器，请检查回答是否：\n"
            "1. 完全符合检索内容；2. 无编造数字；3. 完整回答问题。\n"
            "若有不符，请修正后输出最终回答（不要解释修改过程）。\n\n"
            f"检索内容：{context}\n问题：{query}\n原回答：{answer}\n\n修正后的回答："
        )
        out = self.llm(prompt, temperature=0.1)
        return out or answer

    # ---------------- 完整流程 ----------------
    def run(self, query: str, top_k: Optional[int] = None) -> SelfRAGResult:
        """执行 Self-RAG 全流程。任一步失败都有兜底，不会抛异常给上层。"""
        k = top_k or self.top_k
        result = SelfRAGResult(answer="")

        # ① 是否需要检索
        result.need_retrieve = self.should_retrieve(query)
        result.steps.append(f"need_retrieve={result.need_retrieve}")
        if not result.need_retrieve:
            result.answer = self.generator(query, "")
            result.steps.append("direct_generate")
            return result

        # ② 检索
        hits = self.retriever(query, k) or []
        context = "\n".join(h.get("text", "") for h in hits)
        result.used_context = [h.get("text", "") for h in hits]
        result.hits = hits
        result.steps.append(f"retrieved={len(hits)}")
        if not hits:
            result.answer = "根据现有资料，未查询到具体信息，建议查阅学校官方招生简章。"
            return result

        # ③ 上下文是否有用
        result.context_useful = self.is_context_useful(query, context)
        result.steps.append(f"context_useful={result.context_useful}")
        if not result.context_useful:
            # 上下文没用：不再生成，直接按拒答话术返回（避免幻觉）
            result.answer = "根据现有资料，未查询到具体信息，建议查阅学校官方招生简章。"
            return result

        # ④ 生成初稿
        answer = self.generator(query, context)
        result.steps.append("generated")

        # ⑤ 反思修正（仅当自评不合格时才修，省一次 LLM 调用）
        if not self.should_continue_generate(query, context, answer):
            answer = self.reflect_and_correct(query, context, answer)
            result.steps.append("reflected")
        else:
            result.steps.append("passed_check")

        result.answer = answer
        return result
