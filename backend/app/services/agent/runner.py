"""Agent 调度器（0.13.0 核心）。

## 与 0.12.x 的本质区别
0.12.x：`_chat_sync()` 里写死「路由 → 以文搜图 → 图谱+MySQL+向量 → 纯向量」，
        查什么由代码决定；
0.13.0：把三路数据源包装成工具交给模型，**由模型决定查什么、查几路**，
        代码只负责「执行工具 + 把结果喂回去」。

## 两种协议（同一套调度骨架）
1. `_run_native()`：模型直接返回 `tool_calls`（首选，Ollama 0.6+ / qwen3:4b 支持）；
2. `_run_planner()`：模型返回 `{"tool": "...", "query": "..."}` JSON（兜底）。

两条路径产出完全相同的 `AgentAnswer`，因此路由层/前端无需感知用的是哪种协议
（里氏替换）。

## 防呆设计
· `max_steps`：最多几轮「模型 → 工具 → 模型」，防止小模型陷入循环；
· `max_tools`：一次只暴露少量工具，降低 4b 选错的概率；
· 收尾轮 `force_no_tools`：轮数耗尽后强制不带工具生成答案，保证一定有回复；
· 任何工具异常都只影响该路（工具内部兜底），不会让整个问答失败。
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from app.services.agent.agent_result import AgentAnswer, ToolTrace
from app.services.agent.base import BaseTool, ToolCall, ToolResult
from app.services.agent.ollama_tools import OllamaToolClient
from app.services.agent.prompts import (
    AGENT_SYSTEM_PROMPT,
    AGENT_SYSTEM_PROMPT_WITH_PROFILE,
    FINAL_ANSWER_PROMPT,
    PLANNER_PROMPT,
)
from app.services.agent.registry import ToolRegistry, build_default_registry

logger = logging.getLogger(__name__)

#: 工具执行线程池（进程内复用；工具本身是 IO 密集，少量线程足够）
_TOOL_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent-tool")


class AgentRunner:
    """把「问题 + 工具集」交给本地模型，执行其选择的工具并产出最终回答。"""

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        llm: Optional[OllamaToolClient] = None,
        max_steps: int = 0,
        max_tools: int = 0,
    ) -> None:
        from app.config import settings

        self.registry = registry or build_default_registry()
        self.llm = llm or OllamaToolClient()
        self.max_steps = int(max_steps or settings.AGENT_MAX_STEPS or 2)
        self.max_tools = int(max_tools or settings.AGENT_MAX_TOOLS or 8)
        # 实测：qwen3:4b 的推理会占用 token 预算，512 太小会拿不到 tool_calls
        self.plan_tokens = int(settings.AGENT_PLAN_TOKENS or 768)
        self.answer_tokens = int(settings.AGENT_ANSWER_TOKENS or 512)
        self.tool_timeout = float(settings.AGENT_TOOL_TIMEOUT or 60)
        # 喂回模型的单路工具文本上限（字符）。本机 4b 处理长 prompt 很慢，
        # 1500 字/路会让生成轮直接超时（曾出现 120s 打满），600 是实测折中。
        self.tool_text_limit = int(getattr(settings, "AGENT_TOOL_TEXT_LIMIT", 0) or 600)
        # 规划轮 / 生成轮分开设超时：规划慢可以等，生成慢必须快速失败走兜底
        self.plan_timeout = float(settings.AGENT_PLAN_TIMEOUT or 90)
        self.answer_timeout = float(settings.AGENT_ANSWER_TIMEOUT or 50)

    # ============================================================ 对外入口

    def run(
        self,
        question: str,
        profile_context: str = "",
        province: str = "",
        category: str = "",
        top_k: int = 5,
    ) -> AgentAnswer:
        """执行一次完整问答。异常一律降级为空答案（由调用方决定兜底）。"""
        start = time.time()
        q = (question or "").strip()
        if not q:
            return AgentAnswer(answer="", source="agent_empty", model=self.llm.model)

        ctx: Dict[str, Any] = {
            "province": province,
            "category": category,
            "top_k": top_k,
            "question": q,
        }

        # 已确知服务端不支持 tools（老版本 Ollama）→ 走 JSON 规划协议
        if self.llm.tools_supported is False:
            return self._run_planner(q, profile_context, ctx, start)

        answer = self._run_native(q, profile_context, ctx, start)
        if answer is not None:
            return answer

        # 原生路径失败（超时 / 空返回）→ **返回失败标记**，由路由层回落到
        # 0.12.x 的确定性融合链路。为什么不在这里改走 JSON 规划？
        # 实测：规划 Prompt 也无法阻止 qwen3:4b 把推理写进 content，
        # 拿不到合法 JSON 时会产出「我先分析一下…」这类垃圾回答。
        # 与其给用户一段没用的文字，不如用已验证的检索链路兜底。
        logger.info("[AGENT] 原生 tool_calls 路径失败，交由路由层回落融合链路")
        return AgentAnswer(
            answer="",
            source="agent_failed",
            elapsed_ms=int((time.time() - start) * 1000),
            profile_injected=bool(profile_context),
            model=self.llm.model,
        )

    # ============================================================ 协议一：原生 tools

    def _run_native(
        self, question: str, profile_context: str, ctx: Dict[str, Any], start: float
    ) -> Optional[AgentAnswer]:
        specs = self.registry.specs(self.max_tools)
        if not specs:
            return None

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt(profile_context)},
            {"role": "user", "content": question},
        ]
        traces: List[ToolTrace] = []
        sources: List[str] = []
        # 保留工具原始结果：模型生成轮失败时可以直接用这些内容兜底，
        # 而不是让用户等了两分钟却只看到「失败」
        collected: List[ToolResult] = []

        for step in range(1, self.max_steps + 1):
            _t = time.time()
            # 第 1 轮是「规划」（选工具），后面是「基于工具结果生成答案」，
            # 两者对延迟的容忍度不同，所以分别给超时预算。
            is_planning = step == 1
            reply = self.llm.chat(
                messages,
                tools=specs,
                num_predict=self.plan_tokens if is_planning else self.answer_tokens,
                timeout=self.plan_timeout if is_planning else self.answer_timeout,
            )
            _elapsed = time.time() - _t
            logger.info(
                "[AGENT] 第 %d 轮 LLM 完成 %.1fs（tool_calls=%d）",
                step, _elapsed, len(reply.tool_calls),
            )
            # uvicorn 默认只输出 WARNING+，关键耗时用 print 保证可见（同 0.10.0 OCR）
            print(
                f"[AGENT] 第 {step} 轮（{'规划' if is_planning else '生成'}）"
                f"{_elapsed:.1f}s tool_calls={len(reply.tool_calls)}",
                flush=True,
            )
            if reply.error:
                logger.info("[AGENT] 第 %d 轮 LLM 失败：%s", step, reply.error)
                if collected:
                    return self._answer_from_results(
                        collected, traces, sources, profile_context, start,
                        source="agent_tool_only",
                    )
                return None

            # 没有工具调用 → 这就是最终答案
            if not reply.tool_calls:
                cleaned = clean_answer(reply.content)
                if not cleaned:
                    if collected:
                        return self._answer_from_results(
                            collected, traces, sources, profile_context, start,
                            source="agent_tool_only",
                        )
                    return None
                logger.info(
                    "[AGENT] 第 %d 轮直接回答（未用工具），model=%s", step, self.llm.model
                )
                return AgentAnswer(
                    answer=cleaned,
                    source="agent_no_tool" if not traces else "agent",
                    sources=_dedup(sources),
                    traces=traces,
                    steps=step,
                    elapsed_ms=int((time.time() - start) * 1000),
                    profile_injected=bool(profile_context),
                    model=self.llm.model,
                )

            # 把模型的工具请求回填成 assistant 消息，再逐条执行、回填 tool 消息
            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content or "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": c.name,
                                "arguments": c.arguments,
                            }
                        }
                        for c in reply.tool_calls
                    ],
                }
            )
            for call in reply.tool_calls:
                result, trace = self._execute(call, ctx)
                traces.append(trace)
                if result.ok:
                    collected.append(result)
                    sources.extend(result.sources)
                # 0.13.0：喂回模型的文本要截断。实测本机 4b 的 prompt 处理很慢，
                # 塞 1500 字/路会让生成轮直接超时（曾出现 120s 打满）。
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": call.name,
                        "content": result.to_model_text(limit=self.tool_text_limit),
                    }
                )

        # ---- 轮数耗尽 ----
        # 0.13.1：这里**不再**多做一次「强制收尾生成」。
        # 0.13.0 的做法是再发一轮 LLM（本机又是 25-60 秒），
        # 但此时工具结果已经拿到了——直接做抽取式回答，把总耗时压到
        # 「规划 + 工具」两段，符合「宁可给事实，也不要让用户多等一分钟」。
        if collected:
            logger.info(
                "[AGENT] 达到最大轮数 %d，直接用已获取的 %d 路工具结果作答",
                self.max_steps, len(collected),
            )
            return self._answer_from_results(
                collected, traces, sources, profile_context, start,
                source="agent_tool_only",
            )
        return None

    def _answer_from_results(
        self,
        collected: List[ToolResult],
        traces: List[ToolTrace],
        sources: List[str],
        profile_context: str,
        start: float,
        source: str = "agent_tool_only",
    ) -> AgentAnswer:
        """生成轮失败时，直接用工具查到的内容作答（0.13.0）。

        ## 为什么要有这条兜底
        实测本机 CPU 推理下，第二轮「喂工具结果 → 生成答案」可能需要 60-120 秒，
        一旦超时，用户等了两分钟后拿到的是空白 —— 而这时**工具其实已经查到了
        真实资料**（政策原文、分数、学费）。与其丢掉，不如把检索结果整理成
        结构化回答直接给出，并明确标注「以下是检索到的资料」。

        这符合「宁可给事实，也不要给空气」的降级原则。
        """
        # 0.13.1：明确告知用户「这是降级结果」，而不是假装是模型的完整回答
        parts: List[str] = [
            "（受限于本地算力，已为你直接提取检索结果）",
            "",
        ]
        for i, res in enumerate(collected, 1):
            text = (res.summary or "").strip()
            if not text:
                continue
            excerpts = _extract_excerpts(text, limit=3)
            body = " ".join(excerpts) if excerpts else text[:300]
            parts.append(f"{i}. {body}")
        if len(parts) <= 2:
            return AgentAnswer(answer="", source="agent_failed")
        parts.append("")
        parts.append("如需更精确的结论，可换一种问法（例如带上具体院校或专业名）再问一次。")
        logger.info("[AGENT] 生成轮失败，已用 %d 路工具结果直接作答", len(collected))
        return AgentAnswer(
            answer="\n".join(parts),
            source=source,
            sources=_dedup(sources),
            traces=traces,
            steps=len(traces),
            elapsed_ms=int((time.time() - start) * 1000),
            profile_injected=bool(profile_context),
            model=self.llm.model,
        )

    # ============================================================ 协议二：JSON 规划

    def _run_planner(
        self, question: str, profile_context: str, ctx: Dict[str, Any], start: float
    ) -> AgentAnswer:
        """模型不支持 tools 时的兜底：让它输出 JSON 决定查哪个工具。"""
        from app.services.profile.llm_json import LLMJsonParser  # 复用通用 JSON 解析器（CRP）

        traces: List[ToolTrace] = []
        sources: List[str] = []
        context_text = ""

        tools_desc = self.registry.describe(self.max_tools)
        if tools_desc:
            plan_reply = self.llm.chat(
                [
                    {"role": "user", "content": PLANNER_PROMPT.format(
                        tools=tools_desc, question=question
                    )},
                ],
                tools=None,
                force_no_tools=True,
                temperature=0.0,
                num_predict=120,
            )
            plan = LLMJsonParser.parse_object(plan_reply.content or "") or {}
            tool_name = str(plan.get("tool") or "").strip()
            tool_query = str(plan.get("query") or "").strip() or question

            if tool_name and tool_name.lower() not in ("none", "no", "null"):
                call = ToolCall(name=tool_name, arguments={"query": tool_query})
                result, trace = self._execute(call, ctx)
                traces.append(trace)
                if result.ok:
                    sources.extend(result.sources)
                    context_text = result.to_model_text()
                logger.info(
                    "[AGENT] JSON 规划命中工具 %s（ok=%s, %dms）",
                    tool_name, result.ok, result.elapsed_ms,
                )

        # 最终生成（一定不带工具，保证有回复）
        prompt = FINAL_ANSWER_PROMPT.format(
            profile_block=(
                f"【考生画像】{profile_context}\n" if profile_context else ""
            ),
            context=context_text or "（未检索到相关资料）",
            question=question,
        )
        final = self.llm.chat(
            [{"role": "user", "content": prompt}],
            tools=None,
            force_no_tools=True,
            temperature=0.2,
            num_predict=600,
        )
        answer = clean_answer(final.content or "")
        return AgentAnswer(
            answer=answer,
            source="agent" if context_text else "agent_planner_no_tool",
            sources=_dedup(sources),
            traces=traces,
            steps=1 + (1 if traces else 0),
            elapsed_ms=int((time.time() - start) * 1000),
            profile_injected=bool(profile_context),
            model=self.llm.model,
        )

    # ============================================================ 内部工具

    def _execute(self, call: ToolCall, ctx: Dict[str, Any]) -> tuple:
        """执行一次工具调用，返回 (ToolResult, ToolTrace)。"""
        args: Dict[str, Any] = dict(call.arguments or {})
        # 权威上下文（省份/科类/原始问题）由服务端注入，避免模型瞎填覆盖
        kwargs: Dict[str, Any] = {**ctx, **args}
        kwargs["question"] = ctx.get("question") or ""
        query = str(args.get("query") or kwargs["question"])
        # query 单独作为位置参数传给 tool.run()，必须从 kwargs 里摘掉，
        # 否则会与位置参数冲突（TypeError: got multiple values for 'query'）
        kwargs.pop("query", None)
        if ctx.get("province"):
            kwargs["province"] = ctx["province"]
        if ctx.get("category"):
            kwargs["category"] = ctx["category"]
        kwargs["top_k"] = int(args.get("top_k") or ctx.get("top_k") or 5)

        tool: Optional[BaseTool] = self.registry.get(call.name)
        if tool is None:
            result = ToolResult.empty(f"未知工具：{call.name}")
        else:
            result = self._run_with_timeout(tool, query, kwargs)

        trace = ToolTrace(
            name=call.name,
            arguments=args,
            ok=result.ok,
            skipped=result.skipped,
            elapsed_ms=result.elapsed_ms,
            error=result.error,
            preview=(result.summary or "")[:300],
        )
        logger.info(
            "[AGENT] 工具 %s ok=%s skipped=%s %dms %s",
            call.name, result.ok, result.skipped, result.elapsed_ms,
            (result.error or "")[:80],
        )
        return result, trace

    def _run_with_timeout(self, tool: BaseTool, query: str, kwargs: Dict[str, Any]) -> ToolResult:
        """给工具执行加一层硬超时。

        工具内部已有各自的超时（HTTP / LLM），这里再兜一层是为了保证
        「某个外部依赖卡住时，整条问答仍能在预算内结束」。
        超时后不等待后台线程（它会被自身 HTTP 超时终止），直接返回空结果。
        """
        from concurrent.futures import TimeoutError as FutureTimeout

        future = _TOOL_POOL.submit(tool.run, query, **kwargs)
        try:
            return future.result(timeout=self.tool_timeout)
        except FutureTimeout:
            logger.info(
                "[AGENT] 工具 %s 超时（>%.0fs），跳过该路", tool.name, self.tool_timeout
            )
            return ToolResult.empty(f"工具执行超时（>{self.tool_timeout:.0f} 秒）")

    @staticmethod
    def _system_prompt(profile_context: str) -> str:
        from app.config import settings

        if profile_context and settings.AGENT_INJECT_PROFILE:
            return AGENT_SYSTEM_PROMPT_WITH_PROFILE.format(profile=profile_context)
        return AGENT_SYSTEM_PROMPT


def _extract_excerpts(text: str, limit: int = 3, max_chars: int = 120) -> List[str]:
    """从工具原文里挑出可读的片段（0.13.0 兜底答案用）。

    工具返回的常常是 PDF 表格被抽取后的碎片（「本科一批 平行志愿 6 6 有」），
    整段倾倒给考生非常难读。这里做**抽取式**摘要：
      · 按行切分，丢弃过短（<12 字）与纯数字/符号占比过高的行；
      · 优先保留含中文说明性词汇的行（「原则」「可以」「需要」「批次」等）；
      · 最多取 limit 条，单条截断到 max_chars。
    """
    markers = ("原则", "可以", "需要", "建议", "批次", "志愿", "投档", "录取",
               "规则", "注意", "要求", "如果", "则", "应")
    picked: List[str] = []
    for raw in re.split(r"[\n\r]+", text):
        line = raw.strip(" ·|\t")
        if len(line) < 12:
            continue
        # 纯数字/符号占比过高 → 表格噪声
        alnum_ratio = sum(ch.isdigit() for ch in line) / max(1, len(line))
        if alnum_ratio > 0.45:
            continue
        if any(m in line for m in markers):
            picked.append(line[:max_chars])
        if len(picked) >= limit:
            break
    return picked


def clean_answer(text: str) -> str:
    """剥掉 qwen3 混进正文的「推理旁白」（0.13.0）。

    ## 为什么要这一层
    qwen3 是思考型模型，Ollama 的 `"think": false` 对它**不生效**，
    只有 `/no_think` 软开关能抑制；而 `/no_think` 在「选工具」时很有效，
    在「自由作答」时仍会漏出推理文本，实测输出形如：

        好的，用户问"你好，你能帮我做什么"，这属于闲聊……
        根据工具使用规则第5条，这类问题不需要调用任何工具……
        我应该列出：1) 政策查询 2) 院校信息

    直接返回给考生非常糟糕。这里按「段落 → 句子」逐层丢弃**开头**的旁白，
    一旦遇到第一句正常回答就停止丢弃，避免误删真正的答案。

    ## 判定依据
    旁白句通常含「用户问 / 用户的问题是 / 我需要 / 根据要求 / 首先，我」等
    第一人称的思考标记，而真正的回答是第二人称或陈述性内容。
    """
    if not text:
        return ""

    raw_text = str(text)

    # ① 处理「思考标签残片」：模型在 token 预算耗尽时只输出 `</think>` 而没有 `<think>`，
    #    前面的推理块会被当成正文漏出来（实测问候语就是这样被污染的）。
    #    有闭合标签时，取**最后一个** `</think>` 之后的内容——那才是真正的回答。
    if "</think>" in raw_text:
        tail = raw_text.rsplit("</think>", 1)[-1].strip()
        if len(tail) >= 2:
            raw_text = tail
    raw_text = raw_text.replace("<think>", "").replace("</think>", "")

    # 旁白句的两种特征（OR 关系）：
    #   ① 以思考连接词开头（所以 / 不过 / 首先 / 好的 / 回答要求 …）
    #   ② 含明确的元叙述短语（用户问 / 工具使用规则 / 不调用工具 …）
    meta_prefix = (
        "所以", "不过", "首先", "好的", "回答要求", "回答规则", "这里", "用户",
        "我需", "我应", "我要", "让我", "根据", "判断", "分析", "综上",
    )
    meta_phrases = (
        "用户问", "用户的问题是", "工具使用规则", "不需要调用", "不调用工具",
        "简单回应", "直接回复", "禁止输出思考", "不能输出思考", "应该调用",
        "这里没有工具", "应该直接输出", "所以直接输出",
        # 0.13.1 实测新增形态
        "检查一下", "是否需要调用", "这里不需要", "不调用任何工具",
    )

    def _is_meta(sent: str) -> bool:
        s = sent.strip()
        if len(s) < 2:
            return True                      # 纯标点碎片（如切句后的 ” ）
        if any(p in s for p in meta_phrases) and len(s) < 260:
            return True
        return s.startswith(meta_prefix) and len(s) < 260

    paragraphs = [p.strip() for p in raw_text.split("\n") if p.strip()]
    kept: List[str] = []

    for para in paragraphs:
        # 用中文句末标点 + 换行切句，保留标点
        sentences = [s for s in para.replace("！", "！\n").replace("？", "？\n")
                     .replace("。", "。\n").split("\n") if s.strip()]
        for sent in sentences:
            # ★ 全程过滤（0.13.0 只过滤开头，导致「首句正文之后」的旁白又漏了回来）
            if _is_meta(sent):
                continue
            kept.append(sent.strip())

    result = "\n".join(kept).strip()
    # 兜底一：全部被判成旁白时，尝试从引号里捞出模型「打算说出口」的那句话
    # 实测形态：所以应该简单回应“你好！有什么可以帮您的吗？”
    if not result:
        import re as _re

        quoted = _re.findall(r"[“\"「]([^”\"」]{4,120})[”\"」]", raw_text)
        if quoted:
            result = quoted[-1].strip()
    # 兜底二：仍为空则返回原文（宁可有噪声，也不要空白）
    if not result:
        result = raw_text.strip()
    return result


def _dedup(items: List[str]) -> List[str]:
    out: List[str] = []
    for item in items or []:
        if item and item not in out:
            out.append(item)
    return out


# ---------------------------------------------------------------- 便捷函数


def run_agent(
    question: str,
    profile_context: str = "",
    province: str = "",
    category: str = "",
    top_k: int = 5,
) -> AgentAnswer:
    """一次性调用的快捷入口（进程内复用 registry，避免每次重建工具）。"""
    global _runner
    if _runner is None:
        _runner = AgentRunner()
    return _runner.run(
        question,
        profile_context=profile_context,
        province=province,
        category=category,
        top_k=top_k,
    )


_runner: Optional[AgentRunner] = None


def reset_runner() -> None:
    """重置单例（配置变更 / 测试用）。"""
    global _runner
    _runner = None


__all__ = ["AgentRunner", "run_agent", "reset_runner"]
