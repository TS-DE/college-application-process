"""志愿推荐接口。"""
import asyncio
from typing import Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.schemas.student import RecommendIn, RecommendItem, RecommendOut

router = APIRouter(prefix="/api", tags=["recommend"])


@router.post("/recommend", response_model=RecommendOut)
async def recommend(payload: RecommendIn) -> RecommendOut:
    """生成冲/稳/保三档志愿推荐。

    规则引擎负责位次换算与分档，AI 只负责（可选的）推荐理由润色。
    v2.5.2：改为 async，整体放入线程池执行，避免 AI 润色阻塞主事件循环。
    """
    from app.services.recommend_service import recommend as _recommend

    try:
        data = await asyncio.wait_for(
            run_in_threadpool(
                _recommend,
                province=payload.province,
                year=payload.year,
                category=payload.category,
                batch=payload.batch,
                rank=payload.rank,
                score=payload.score,
                filters=payload.filters.model_dump() if payload.filters else None,
                buffer=payload.buffer,
                span_factor=payload.span_factor,
                limit=payload.limit,
                with_ai=payload.with_ai,
                ai_limit=payload.ai_limit,
            ),
            timeout=60.0,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="推荐生成超时，请减少 AI 理由数量或稍后重试") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"推荐失败：{exc}") from exc
    return RecommendOut(**data)


@router.post("/recommend/ai-reasons")
async def batch_ai_reasons(payload: Dict) -> Dict:
    """对已生成的推荐条目批量补充 AI 理由。

    入参：{ "student": {...}, "items": [ { ...推荐条目 } ], "limit": 10 }
    v2.5.2：改为 async + 线程池，避免阻塞非 AI 接口。
    """
    from app.services.ai_service import ai_enabled, recommend_reason

    if not ai_enabled():
        raise HTTPException(status_code=503, detail="AI 未启用或 Ollama 不可用")

    student = payload.get("student") or {}
    items: List[Dict] = payload.get("items") or []
    limit = int(payload.get("limit") or 10)
    targets = items[:limit]

    async def _reason_for(it: Dict) -> Dict:
        text, source = await asyncio.wait_for(
            run_in_threadpool(recommend_reason, it, student), timeout=30.0
        )
        out = dict(it)
        out["ai_reason"] = text
        out["ai"] = source == "llm"
        return out

    results = await asyncio.gather(*[_reason_for(it) for it in targets])
    return {
        "items": results,
        "generated": sum(1 for r in results if r["ai"]),
        "total": len(results),
    }
