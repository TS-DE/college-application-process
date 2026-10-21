"""AI 环境状态入口：GET /status（0.17.1 从 chat_router 拆出）。

只负责探测 Ollama / 模型名，不参与问答。
"""
import asyncio

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from app.config import settings
from app.services.llm.ai_service import ai_enabled, ollama_health

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/status")
async def status() -> dict:
    """AI 状态探测：限时完成，避免阻塞前端。"""
    from app.services.llm.ai_service import ai_enabled, ollama_health

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


