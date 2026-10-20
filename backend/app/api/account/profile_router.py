"""用户画像接口（0.12.0）。

## 单一职责
本文件只做三件事：
    ① 声明入参 Schema、② 校验登录态、③ 把 Service 结果包成响应模型。
Prompt 组装、大模型调用、JSON 清洗、落库全部在 `services/profile/` 内完成。

## 接口清单
    GET    /api/profile                  读取画像
    PUT    /api/profile/basic            完善基础资料
    GET    /api/profile/domains          可选领域（前端渲染勾选框）
    POST   /api/profile/survey/questions 生成业务问卷（途径 B）
    POST   /api/profile/survey/submit    提交问卷作答
    POST   /api/profile/report/upload    解析测评报告（途径 A）
    POST   /api/profile/summary/rebuild  手动重算画像
    DELETE /api/profile                  清空画像
"""
from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.account.auth_router import get_current_user
from app.schemas.profile import (
    ProfileBasicIn,
    ProfileOut,
    ReportUploadIn,
    SummaryOut,
    SurveyQuestionIn,
    SurveyQuestionOut,
    SurveySubmitIn,
)
from app.services.profile import (
    ALLOWED_DOMAINS,
    ProfileRepository,
    ProfileService,
)

router = APIRouter(prefix="/api/profile", tags=["profile"])


def get_profile_service(db: Session = Depends(get_db)) -> ProfileService:
    """FastAPI 依赖：每个请求装配一个 Service（Session 生命周期由请求控制）。

    用依赖注入而不是在函数里 new，好处是测试时可以 `app.dependency_overrides`
    整体替换成内存实现（依赖倒置的收益）。
    """
    return ProfileService(ProfileRepository(db))


# ---------------------------------------------------------------- 读取


@router.get("", response_model=ProfileOut)
def read_profile(
    user: Dict = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileOut:
    """读取当前登录用户的画像（没有则返回空画像，不会 404）。"""
    return ProfileOut(**service.get(user["id"]))


@router.get("/domains", response_model=List[str])
def list_domains() -> List[str]:
    """问卷可选领域（前端渲染勾选框用，避免前后端各写一份常量）。"""
    return list(ALLOWED_DOMAINS)


# ---------------------------------------------------------------- 基础资料


@router.put("/basic", response_model=ProfileOut)
def update_basic(
    body: ProfileBasicIn,
    user: Dict = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> ProfileOut:
    """完善 / 修改基础资料（个人主页）。"""
    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    return ProfileOut(**service.update_basic(user["id"], payload))


# ---------------------------------------------------------------- 途径 B：问卷


@router.post("/survey/questions", response_model=SurveyQuestionOut)
async def generate_survey(
    body: SurveyQuestionIn,
    user: Dict = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> SurveyQuestionOut:
    """按用户勾选的领域生成 3-5 道业务问卷题（大模型不可用时返回内置题）。"""
    import asyncio

    from fastapi.concurrency import run_in_threadpool

    try:
        questions, fallback = await asyncio.wait_for(
            run_in_threadpool(service.generate_survey, body.domains, body.count),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="问卷生成超时，请稍后重试") from None

    return SurveyQuestionOut(
        questions=questions,
        fallback=fallback,
        message="大模型暂不可用，已返回内置问卷" if fallback else None,
    )


@router.post("/survey/submit", response_model=SummaryOut)
async def submit_survey(
    body: SurveySubmitIn,
    user: Dict = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> SummaryOut:
    """保存问卷作答并重算画像总结。"""
    import asyncio

    from fastapi.concurrency import run_in_threadpool

    try:
        result = await asyncio.wait_for(
            run_in_threadpool(
                service.submit_survey,
                user["id"],
                [q.model_dump() for q in body.questions],
                body.answers,
            ),
            timeout=90.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="画像生成超时，请稍后重试") from None
    return SummaryOut(**result)


# ---------------------------------------------------------------- 途径 A：报告


@router.post("/report/upload", response_model=SummaryOut)
async def upload_report(
    body: ReportUploadIn,
    user: Dict = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> SummaryOut:
    """解析 MBTI / 霍兰德等报告文本并重算画像。

    文件（PDF/图片）请先走 `/api/knowledge/upload` 的 OCR 链路转成文本，
    再把文本提交到本接口——画像模块不重复实现文件解析（合成复用）。
    """
    import asyncio

    from fastapi.concurrency import run_in_threadpool

    try:
        result = await asyncio.wait_for(
            run_in_threadpool(
                service.extract_report, user["id"], body.text, body.source_hint or ""
            ),
            timeout=90.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="报告解析超时，请稍后重试") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SummaryOut(**result)


# ---------------------------------------------------------------- 汇总 / 清空


@router.post("/report-upload", response_model=SummaryOut)
@router.post("/report/upload-file", response_model=SummaryOut, include_in_schema=False)
async def upload_report_file(
    file: UploadFile = File(...),
    user: Dict = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> SummaryOut:
    """**用户测评报告上传（0.13.0 独立接口）**：PDF / 图片 / 文档 → 画像特征。

    > 路径说明：0.13.0 起规范名为 `POST /api/profile/report-upload`
    > （任务书要求），`/report/upload-file` 作为 0.12.1 的旧路径保留兼容，
    > 不出现在 OpenAPI 文档里。

    ## 隐私隔离（物理级解耦）
    本接口与**知识库上传完全无关**，不复用任何 knowledge 代码路径：
      · 文件落在 `{UPLOAD_ROOT}/reports/`，与 `KNOWLEDGE_DIR` 不同目录；
      · 提取完文本后**立即删除**文件，不在磁盘留私人副本；
      · **不写 Chroma**（既不进 `gaokao_knowledge` 也不进 `gaokao_images`）；
      · **不写 knowledge_files 台账**——管理员的知识库管理页看不到这份报告；
      · 特质只写入当前登录用户的 `user_profiles.external_reports`。

    权限：仅限已登录用户，且只能读写自己的 `user_id`（Service 层强制隔离）。

    若只需粘贴文字，请用 `/api/profile/report/upload`。
    """
    import asyncio

    from fastapi.concurrency import run_in_threadpool

    from app.services.profile.report_reader import ReportReadError, ReportReader

    content = await file.read()
    reader = ReportReader()

    # ① 文件 → 文本（线程池执行，避免阻塞事件循环；内部用完即删文件）
    try:
        text = await asyncio.wait_for(
            run_in_threadpool(reader.read, content, file.filename or "report"),
            timeout=120.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="报告解析超时，请改用粘贴文字方式") from None
    except ReportReadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ② 文本 → 画像特征 → 汇总（与粘贴文字版完全同一条链路）
    try:
        result = await asyncio.wait_for(
            run_in_threadpool(service.extract_report, user["id"], text, ""),
            timeout=90.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="画像生成超时，请稍后重试") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SummaryOut(**result)


@router.post("/summary/rebuild", response_model=SummaryOut)
async def rebuild_summary(
    user: Dict = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> SummaryOut:
    """基于已有数据重新生成画像（改了基础资料后想刷新时用）。"""
    import asyncio

    from fastapi.concurrency import run_in_threadpool

    try:
        result = await asyncio.wait_for(
            run_in_threadpool(service.rebuild, user["id"]), timeout=90.0
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="画像生成超时，请稍后重试") from None
    return SummaryOut(**result)


@router.delete("")
def delete_profile(
    user: Dict = Depends(get_current_user),
    service: ProfileService = Depends(get_profile_service),
) -> Dict:
    """清空画像（不影响账号本身）。"""
    removed = service.delete(user["id"])
    return {"code": 200, "msg": "画像已清空" if removed else "本来就没有画像"}
