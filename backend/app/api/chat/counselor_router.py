"""云端「心理师」入口：/counselor。

0.17.0 从 `routers/ai.py` 拆出，路由路径、响应模型、函数体均未改动。
"""
import time
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.api.account.auth_router import get_current_user
from app.schemas.ai import CounselorIn, CounselorOut
from app.services.llm.ai_executor import (
    _load_profile_summary,
    _reject_if_overloaded,
    _run_ai,
)

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/counselor", response_model=CounselorOut)
async def counselor(
    body: CounselorIn,
    user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CounselorOut:
    """云端「心理师 / 画像构建师」多轮对话（0.13.0）。

    ## 与 /chat 的分工
    · `/chat`   本地 qwen3:4b + 工具，查政策与数据，毫秒级，数据不出本机；
    · `/counselor` 云端 qwen3.7-flash，谈心、疏导、采集画像，**不降级到本地**。

    ## 为什么必须登录
    画像与历史都挂在 `user_id` 上；同时把 `summary_text` 注入 system prompt，
    让云端模型知道「这个考生已经说过什么」，避免反复问同样的问题。
    """
    from app.services.counselor import CounselorService

    _t0 = time.time()
    # 0.15.1：入口预检，过载时立刻拒绝
    _reject_if_overloaded("counselor")

    # 0.15.0：读画像与云端生成都走 AI 专用线程池，不挤占认证接口
    profile_summary = await _run_ai(
        _load_profile_summary,
        db,
        user["id"],
        timeout=settings.AUTH_TIMEOUT_SECONDS,
        label="read-profile",
    )
    _t_profile = time.time()

    service = CounselorService()
    result = await _run_ai(
        service.chat,
        [m.model_dump() for m in body.messages],
        profile_summary,
        timeout=settings.COUNSELOR_TIMEOUT,
        label="counselor",
    )
    if result.get("error"):
        print(f"[COUNSELOR] 失败 user={user['id']}：{result['error']}", flush=True)
        raise HTTPException(status_code=503, detail=result["error"])

    print(
        f"[COUNSELOR] user={user['id']} 读画像={_t_profile - _t0:.2f}s "
        f"生成={result.get('elapsed_ms', 0)}ms model={result.get('model')} "
        f"画像注入={result.get('profile_injected')}",
        flush=True,
    )
    return CounselorOut(
        answer=result["answer"],
        source=result["source"],
        model=result.get("model"),
        elapsed_ms=result.get("elapsed_ms", 0),
        profile_injected=result.get("profile_injected", False),
        error=None,
    )


