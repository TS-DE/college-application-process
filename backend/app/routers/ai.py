"""AI 接口：意图解析与推荐理由（Ollama + Qwen3，失败自动降级）。"""
from fastapi import APIRouter, HTTPException

from app.schemas.student import (
    ParseIntentIn,
    ParseIntentOut,
    RecommendReasonIn,
    RecommendReasonOut,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
def status() -> dict:
    from app.services.ai_service import ai_enabled, ollama_health

    ok, msg = ollama_health()
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
def parse_intent(payload: ParseIntentIn) -> ParseIntentOut:
    """把「我想找个离家近、计算机强、学费便宜的学校」转成筛选条件。"""
    from app.services.ai_service import parse_intent as _parse

    data = _parse(payload.text, province=payload.province)
    raw = data.pop("raw", None)
    return ParseIntentOut(**data, raw=raw)


@router.post("/recommend-reason", response_model=RecommendReasonOut)
def recommend_reason(payload: RecommendReasonIn) -> RecommendReasonOut:
    """为单条志愿生成推荐理由。"""
    from app.services.ai_service import recommend_reason as _reason

    text, source = _reason(payload.model_dump(), {"rank": payload.student_rank, "score": payload.student_score})
    return RecommendReasonOut(reason=text, source=source)


@router.post("/chat")
def chat(payload: dict) -> dict:
    """志愿问答（可选 RAG）。

    请求体：{ question, context?, use_rag?: true, top_k?: 5 }
    use_rag=true 时先从知识库检索相关片段，拼进 Prompt 再交给 Qwen3。
    """
    from app.services import rag_service
    from app.services.ai_service import ai_enabled, ask, ollama_health

    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")
    if not ai_enabled():
        raise HTTPException(status_code=503, detail="AI 未启用")
    ok, msg = ollama_health()
    if not ok:
        raise HTTPException(status_code=503, detail=msg)

    background = payload.get("context") or ""
    sources: list[str] = []
    rag_snippets = ""

    if payload.get("use_rag"):
        hits = rag_service.search(question, int(payload.get("top_k") or 5))
        if hits:
            parts = []
            for h in hits:
                meta = h.get("metadata") or {}
                name = meta.get("filename") or "知识库"
                sources.append(name)
                parts.append(f"[{name}] {h['text']}")
            rag_snippets = "\n".join(parts[:5])

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
