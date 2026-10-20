"""人机协同志愿规划接口（0.14.0）。

三个端点对应 HITL 的三次交互：

```
POST /api/plan/start    → 生成初稿，图停在 human_review 之前，返回 thread_id
POST /api/plan/resume   → 注入用户意见，恢复执行，返回终稿
GET  /api/plan/state/{thread_id} → 读取会话现场（刷新页面后可恢复）
```

## 为什么单独一个路由文件
任务要求「不要破坏现有 RAG / Agent 链路」。把 HITL 放在独立的 `plan.py`，
好处是：`ai.py` 一行不改，出问题时也能单独回滚这个模块。
两者共用的只有「读用户画像」这一件事。

## 权限与隐私
所有端点都 `Depends(get_current_user)`；`thread_id` 里存了 `user_id`，
Service 层会校验归属，A 用户拿不到 B 用户的方案。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.account.auth_router import get_current_user
from app.schemas.plan import (
    PlanResumeIn,
    PlanResumeOut,
    PlanStartIn,
    PlanStartOut,
    PlanStateOut,
)

router = APIRouter(prefix="/api/plan", tags=["plan"])

#: 生成初稿的整体超时（纯规则引擎，实测 1 秒级，给足余量应对慢查询）
_START_TIMEOUT = 60.0
#: 重新规划的整体超时（可能含一次大模型调用）
_RESUME_TIMEOUT = 90.0


def _profile_summary(db: Session, user_id: int) -> str:
    """读画像总结（失败静默为空，规划不依赖它也能跑）。"""
    try:
        from app.services.profile import ProfileRepository, ProfileService

        return ProfileService(ProfileRepository(db)).get_summary_for_prompt(user_id)
    except Exception:  # noqa: BLE001
        return ""


def _workflow():
    """取工作流单例；langgraph 缺失时给出可操作的 503。"""
    from app.services.agent.workflow import get_plan_workflow

    wf = get_plan_workflow()
    if not wf.available:
        raise HTTPException(
            status_code=503,
            detail=(
                '人机协同规划暂不可用：缺少 langgraph 依赖。'
                '请执行 pip install "langgraph>=1.0" 后重启服务。'
            ),
        )
    return wf


@router.post("/start", response_model=PlanStartOut)
async def start_plan(
    body: PlanStartIn,
    user: Dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlanStartOut:
    """生成初步志愿方案，并**暂停**等待用户修改。

    返回的 `thread_id` 必须在后续 `resume` 时带上——
    它对应 Checkpointer 里保存的那份中间状态。
    """
    from app.services.agent.plan_builder import PlanInputError

    wf = _workflow()
    profile = await run_in_threadpool(_profile_summary, db, user["id"])
    user_info = {
        "province": body.province,
        "category": body.category,
        "score": body.score,
        "rank": body.rank,
        "year": body.year,
        "preferences": body.preferences,
    }

    try:
        res = await asyncio.wait_for(
            run_in_threadpool(wf.start, user["id"], user_info, profile),
            timeout=_START_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="生成初稿超时，请稍后重试") from None
    except PlanInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:  # 依赖缺失等
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"生成初稿失败：{exc}") from exc

    return PlanStartOut(**res, awaiting_feedback=True)


@router.post("/resume", response_model=PlanResumeOut)
async def resume_plan(
    body: PlanResumeIn,
    user: Dict = Depends(get_current_user),
) -> PlanResumeOut:
    """提交修改意见，恢复图执行，返回终稿。

    `user_feedback` 允许为空（表示「就这样，不用改」）——
    此时规则层解析为空，原稿直接作为终稿返回。
    """
    wf = _workflow()
    try:
        res = await asyncio.wait_for(
            run_in_threadpool(
                wf.resume, body.thread_id, user["id"], body.user_feedback
            ),
            timeout=_RESUME_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="重新规划超时，请稍后重试") from None
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"重新规划失败：{exc}") from exc

    return PlanResumeOut(**res)


@router.get("/state/{thread_id}", response_model=PlanStateOut)
async def get_plan_state(
    thread_id: str,
    user: Dict = Depends(get_current_user),
) -> PlanStateOut:
    """读取会话现场：前端刷新后据此恢复「初稿 / 终稿」界面。"""
    wf = _workflow()
    try:
        res = await run_in_threadpool(wf.get_state, thread_id, user["id"])
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return PlanStateOut(**res)


@router.get("/health")
async def plan_health() -> Dict[str, Any]:
    """依赖自检：前端可据此决定是否显示「智能生成」按钮。"""
    from app.services.agent.workflow import LANGGRAPH_AVAILABLE, LANGGRAPH_IMPORT_ERROR

    return {
        "available": LANGGRAPH_AVAILABLE,
        "engine": "langgraph",
        "interrupt_before": "human_review",
        "error": LANGGRAPH_IMPORT_ERROR,
    }
