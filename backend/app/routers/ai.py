"""AI 接口：意图解析与推荐理由（Ollama + Qwen3，失败自动降级）。"""
import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.schemas.student import (
    ParseIntentIn,
    ParseIntentOut,
    RecommendReasonIn,
    RecommendReasonOut,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
async def status() -> dict:
    """AI 状态探测：限时完成，避免阻塞前端。"""
    from app.services.ai_service import ai_enabled, ollama_health

    try:
        ok, msg = await asyncio.wait_for(
            run_in_threadpool(ollama_health), timeout=3.0
        )
    except asyncio.TimeoutError:
        ok, msg = False, "AI 状态探测超时"
    return {
        "ai_enabled": ai_enabled(),
        "ollama": ok,
        "message": msg,
        "model": _model_name(),
    }


def _model_name() -> str:
    from app.config import settings

    return settings.OLLAMA_MODEL


@router.post("/parse-intent", response_model=ParseIntentOut)
async def parse_intent(payload: ParseIntentIn) -> ParseIntentOut:
    """把「我想找个离家近、计算机强、学费便宜的学校」转成筛选条件。"""
    from app.services.ai_service import parse_intent as _parse

    data = await asyncio.wait_for(
        run_in_threadpool(_parse, payload.text, province=payload.province),
        timeout=30.0,
    )
    raw = data.pop("raw", None)
    return ParseIntentOut(**data, raw=raw)


@router.post("/recommend-reason", response_model=RecommendReasonOut)
async def recommend_reason(payload: RecommendReasonIn) -> RecommendReasonOut:
    """为单条志愿生成推荐理由。"""
    from app.services.ai_service import recommend_reason as _reason

    text, source = await asyncio.wait_for(
        run_in_threadpool(
            _reason,
            payload.model_dump(),
            {"rank": payload.student_rank, "score": payload.student_score},
        ),
        timeout=30.0,
    )
    return RecommendReasonOut(reason=text, source=source)


@router.post("/chat")
async def chat(payload: dict) -> dict:
    """志愿问答（可选 RAG）。

    v2.5.2：整体链路改为 async + 线程池执行，防止同步 LLM 调用阻塞主事件循环，
    进而拖慢首页、登录等非 AI 接口。整体超时 120 秒，超时返回 504。
    """
    return await asyncio.wait_for(
        run_in_threadpool(_chat_sync, payload), timeout=120.0
    )


def _chat_sync(payload: dict) -> dict:
    """原 /chat 同步实现，独立出来便于在线程池中运行。"""
    from app.services import rag_service
    from app.services.ai_service import ai_enabled, ask

    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")
    if not ai_enabled():
        raise HTTPException(status_code=503, detail="AI 未启用")
    # v2.5.2：不再强制探测 Ollama；Ali 通道可用时即可正常问答，Ollama 只作为兜底。
    # 真正不可用的情况由 ask() / rag_service 返回空值后抛出 504。

    # ---- v2.3.0 ① Query 意图路由：无关问题直接拦截，不走检索 ----
    use_rag = bool(payload.get("use_rag"))
    if use_rag and not rag_service.route_query(question):
        return {
            "answer": rag_service.OFF_TOPIC_ANSWER,
            "source": "router_blocked",   # 前端可据此展示"该问题不在服务范围内"
            "sources": [],
        }

    # ---- v2.5.0 ② Modular RAG：按 Query 特征走 Self-RAG / Corrective RAG / 标准 RAG ----
    if use_rag and rag_service.settings.ADVANCED_RAG_ENABLED:
        try:
            adv = rag_service.answer_with_strategy(
                question,
                top_k=int(payload.get("top_k") or 5),
                strategy=str(payload.get("strategy") or "auto"),
            )
            return {
                "answer": adv["answer"],
                "source": f"advanced:{adv['strategy']}",
                "sources": adv["sources"],
                "strategy": adv["strategy"],
                "steps": adv["steps"],
                "rewritten_query": adv.get("rewritten_query", ""),
            }
        except Exception:  # noqa: BLE001 高级链路异常 → 回落原有流程
            pass

    background = payload.get("context") or ""
    sources: list[str] = []
    rag_snippets = ""
    context_levels: list[str] = []

    if use_rag:
        hits = rag_service.search(question, int(payload.get("top_k") or 5))
        if hits:
            parts = []
            for h in hits:
                meta = h.get("metadata") or {}
                name = meta.get("filename") or "知识库"
                sources.append(name)
                context_levels.append(h.get("context_level") or "child")
                parts.append(f"[{name}] {h['text']}")
            rag_snippets = "\n".join(parts[:5])

    # ---- v2.3.0 ② 防幻觉生成：命中资料时用强约束 Prompt（temperature=0.1, top_p=0.1）----
    if use_rag and rag_snippets:
        # v2.3.1：top_p 从 0.1 放宽到 0.3，避免模型在极端保守采样下放弃生成
        answer = rag_service.generate_answer(question, rag_snippets, temperature=0.1, top_p=0.3)
        if not answer:
            raise HTTPException(status_code=504, detail="大模型响应超时")
        return {
            "answer": answer,
            "source": "rag+llm",
            "sources": sorted(set(sources)),
            "context_level": "parent" if "parent" in context_levels else "child",
        }

    # 未开启 RAG 或没检索到资料：走通用 Prompt（不编造具体数字，仅给通用建议）
    prompt_parts = [
        "你是高考志愿填报助手，回答要简洁实用，分点说明，不要编造具体院校分数线。",
    ]
    if background:
        prompt_parts.append(f"考生背景：{background}")
    if rag_snippets:
        prompt_parts.append(
            "以下是知识库检索到的参考资料，优先依据它们回答；资料不足时再结合常识，并说明这是通用建议：\n"
            + rag_snippets
        )
    if use_rag and not rag_snippets:
        # v2.3.1 修正：不再直接拒答，而是让模型基于通用知识给方向性建议，
        # 但明确禁止编造具体数字（学费 / 分数线 / 位次）
        prompt_parts.append(
            "注意：知识库中未检索到直接相关的资料。请基于你的通用知识给出**方向性建议**"
            "（如建议查阅学校官网、省教育考试院），"
            "但**禁止编造具体的学费、分数线、位次数字**。"
            "如果用户问的是具体数字，请明确说明“建议查阅官方招生简章获取准确数字”。"
        )
    prompt_parts.append(f"问题：{question}")
    prompt_parts.append("回答：")

    answer = ask("\n".join(prompt_parts), num_predict=400)
    if not answer:
        raise HTTPException(status_code=504, detail="大模型响应超时")
    return {
        "answer": answer,
        "source": "rag+llm" if rag_snippets else "llm",
        "sources": sorted(set(sources)),
    }
