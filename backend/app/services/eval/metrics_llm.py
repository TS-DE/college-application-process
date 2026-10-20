"""LLM 打分指标（可选，默认关闭）。

三个指标均属于「生成质量」维度，需要 LLM 做裁判：
- faithfulness       ：答案是否忠于检索到的上下文（有没有编造）
- answer_relevance   ：答案是否切题（有没有答非所问）
- answer_correctness ：答案与标准答案的事实一致性（0~1 打分）

工程约束：
1. 默认由 `settings.EVAL_LLM_METRICS_ENABLED` 关闭，避免额度耗尽时把评估流程拖垮；
2. 所有调用统一走 `llm_client`（Ali OpenAI 兼容 → Ollama 兜底），且 **enable_thinking=False**，
   评估脚本严禁使用思考版模型（多一轮思考链路会显著拖慢并放大超时概率）；
3. 单条失败返回 None 而不抛异常，由 evaluator 降级为「不计入均值」。
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_FAITHFULNESS_PROMPT = """你是 RAG 系统的忠实度评分员。
请判断【答案】中的每一条事实陈述，是否都能在【上下文】中找到依据。

【上下文】：
{context}

【答案】：
{answer}

评分规则：
- 1.0：全部陈述都能在上下文中找到依据
- 0.5：部分陈述有依据，部分无法判断
- 0.0：存在与上下文矛盾或完全编造的陈述

只输出一个 0~1 之间的小数，不要输出任何其他文字。"""

_RELEVANCE_PROMPT = """你是 RAG 系统的相关性评分员。
请判断【答案】是否直接回答了【问题】，是否存在答非所问、过度发散的问题。

【问题】：
{question}

【答案】：
{answer}

评分规则：
- 1.0：完全切题，直接回答了问题
- 0.5：部分切题，有明显的无关内容
- 0.0：完全答非所问

只输出一个 0~1 之间的小数，不要输出任何其他文字。"""

_CORRECTNESS_PROMPT = """你是答案正确性评分员。
请比较【预测答案】与【标准答案】在事实层面的吻合程度。

【标准答案】：
{ground_truth}

【预测答案】：
{prediction}

评分规则：
- 1.0：关键事实完全一致
- 0.5：部分关键事实一致，或遗漏了部分要点
- 0.0：关键事实错误

只输出一个 0~1 之间的小数，不要输出任何其他文字。"""


class LLMMetrics:
    """可选的 LLM 打分指标集合（默认不启用）。"""

    def __init__(self, enabled: bool = False, model: str = "") -> None:
        self.enabled = enabled
        self.model = model

    def _chat(self, prompt: str, max_tokens: int = 8) -> Optional[float]:
        """调用统一 LLM 通道取一个 0~1 的分数；失败一律返回 None。"""
        if not self.enabled:
            return None
        try:
            from app.services.llm.llm_client import get_llm_client

            raw = get_llm_client().chat(
                system_prompt="你是一个严格的评分助手，只输出数字。",
                user_prompt=prompt,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Eval] LLM 指标调用失败，跳过该指标：%s", exc)
            return None

        match = re.search(r"(\d+(?:\.\d+)?)", raw or "")
        if not match:
            return None
        score = float(match.group(1))
        return max(0.0, min(1.0, score))

    def calc_faithfulness(self, answer: str, contexts: list) -> Optional[float]:
        context = "\n".join(contexts or [])
        if not answer or not context:
            return None
        return self._chat(_FAITHFULNESS_PROMPT.format(context=context, answer=answer))

    def calc_answer_relevance(self, question: str, answer: str) -> Optional[float]:
        if not question or not answer:
            return None
        return self._chat(_RELEVANCE_PROMPT.format(question=question, answer=answer))

    def calc_answer_correctness(self, prediction: str, ground_truth: str) -> Optional[float]:
        if not prediction or not ground_truth:
            return None
        return self._chat(_CORRECTNESS_PROMPT.format(ground_truth=ground_truth, prediction=prediction))
