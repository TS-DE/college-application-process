"""结构化意图入口：/parse-intent 与 /recommend-reason（0.17.1 从 chat_router 拆出）。

两者都是「自然语言 ⇄ 结构化数据」的转换，与多轮问答无关。
路径、响应模型、超时值均保持原样。
"""
from fastapi import APIRouter

from app.schemas.student import (
    ParseIntentIn,
    ParseIntentOut,
    RecommendReasonIn,
    RecommendReasonOut,
)
from app.services.llm.ai_executor import _reject_if_overloaded, _run_ai

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/parse-intent", response_model=ParseIntentOut)
async def parse_intent(payload: ParseIntentIn) -> ParseIntentOut:
    """把「我想找个离家近、计算机强、学费便宜的学校」转成筛选条件。

    0.15.1：改走 `_run_ai`，与 `/chat` 共用 AI 专用池与过载保护。
    此前走 `run_in_threadpool`（anyio 默认池），LLM 调用同样会挤占认证线程。
    """
    from app.services.llm.ai_service import parse_intent as _parse

    _reject_if_overloaded("parse-intent")
    data = await _run_ai(
        _parse,
        payload.text,
        payload.province,   # 位置参数，保持与 ai_service.parse_intent(text, province) 一致
        timeout=30.0,
        label="parse-intent",
    )
    raw = data.pop("raw", None)
    return ParseIntentOut(**data, raw=raw)


@router.post("/recommend-reason", response_model=RecommendReasonOut)
async def recommend_reason(payload: RecommendReasonIn) -> RecommendReasonOut:
    """为单条志愿生成推荐理由（0.15.1：改走 `_run_ai`）。"""
    from app.services.llm.ai_service import recommend_reason as _reason

    _reject_if_overloaded("recommend-reason")
    text, source = await _run_ai(
        _reason,
        payload.model_dump(),
        {"rank": payload.student_rank, "score": payload.student_score},
        timeout=30.0,
        label="recommend-reason",
    )
    return RecommendReasonOut(reason=text, source=source)


