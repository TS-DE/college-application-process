"""RAG 量化评估路由（0.8.0）——仅管理员可用。

原则：路由层只做参数校验与异常映射，所有评估 / 诊断 / 调优逻辑下沉到 services/eval/。
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.config import settings
from app.api.account.auth_router import get_current_admin
from app.services.eval.auto_tuner import AutoTuner
from app.services.eval.data_builder import EvalDataBuilder, ProjectRAGRunner
from app.services.eval.diagnoser import RAGDiagnoser
from app.services.eval.eval_config import RAGEvalConfig
from app.services.eval.evaluator import EvalReport, RAGEvaluator
from app.services.eval.report_generator import ReportGenerator
from app.services.eval.report_store import EvalReportStore

router = APIRouter(prefix="/api/eval", tags=["eval"])

# data/eval 与 data/eval_reports 均相对仓库根目录
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _resolve_dir(path: str) -> str:
    """相对路径一律按仓库根目录解析，绝对路径直接用。"""
    return path if os.path.isabs(path) else os.path.join(_REPO_ROOT, path)


def _dataset_path(dataset_id: str) -> str:
    """根据 dataset_id 找到文件（防目录穿越：只允许文件名）。"""
    safe = os.path.basename(dataset_id)
    directory = _resolve_dir(settings.EVAL_DATA_DIR)
    candidate = os.path.join(directory, safe if safe.endswith((".json", ".csv")) else f"{safe}.json")
    if not os.path.exists(candidate):
        alt = os.path.join(directory, f"{os.path.splitext(safe)[0]}.csv")
        candidate = alt if os.path.exists(alt) else candidate
    return candidate


def _default_dataset() -> Optional[str]:
    """没有指定数据集时，优先用项目真实场景的高考评估集。"""
    directory = _resolve_dir(settings.EVAL_DATA_DIR)
    for name in ("gaokao_qa.json", "rag_demo_qa.json"):
        path = os.path.join(directory, name)
        if os.path.exists(path):
            return path
    return None


# ---------------- 同步实现（在线程池里跑，避免阻塞事件循环） ----------------

def _run_eval_sync(dataset_id: Optional[str], overrides: Dict[str, Any]) -> Dict[str, Any]:
    if not settings.EVAL_ENABLED:
        raise HTTPException(status_code=503, detail="评估模块已关闭（EVAL_ENABLED=0）")

    path = _dataset_path(dataset_id) if dataset_id else _default_dataset()
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="评估数据集不存在，请先上传或指定 dataset_id")

    config = RAGEvalConfig(overrides or {})
    builder = EvalDataBuilder()
    qa_pairs = builder.load_qa_pairs(path)
    if not qa_pairs:
        raise HTTPException(status_code=400, detail="数据集为空或缺少 question / ground_truth 字段")

    # 依赖倒置：适配器对外就是 BaseRAGRunner，评估器不关心底层是 Chroma 还是别的
    runner = ProjectRAGRunner()
    dataset = builder.build_dataset(
        qa_pairs, runner, top_k=config.TOP_K_FOR_EVAL, max_samples=config.MAX_SAMPLES
    )

    evaluator = RAGEvaluator(config, builder)
    report: EvalReport = evaluator.run(dataset, config)

    diagnoses = RAGDiagnoser().diagnose(report)
    report.report_id = ReportGenerator.new_report_id()
    report.created_at = uuid_created_at()

    generator = ReportGenerator()
    output_dir = _resolve_dir(settings.EVAL_REPORT_DIR)
    generator.save(report, output_dir, diagnoses)

    store = EvalReportStore(output_dir)
    history = store.latest_summary(limit=20)
    baseline = None
    if len(history) > 1:
        try:
            baseline = store.load_report_object(history[1]["report_id"])
        except Exception:  # noqa: BLE001
            baseline = None

    return {
        "report_id": report.report_id,
        "created_at": report.created_at,
        "dataset": os.path.basename(path),
        "dataset_size": report.dataset_size,
        "aggregate": report.aggregate,
        "grade": report.grade,
        "duration_sec": round(report.duration_sec, 2),
        "details": report.rows,
        "chart_data": generator.to_chart_data(report, baseline, list(reversed(history[1:])) + [_summary(report)]),
        "diagnoses": [d.to_dict() for d in diagnoses],
        "diagnosis_summary": RAGDiagnoser.summarize(diagnoses),
    }


def _summary(report: EvalReport) -> Dict[str, Any]:
    return {"created_at": report.created_at, "aggregate": report.aggregate, "grade": report.grade}


def uuid_created_at() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------- 接口 ----------------

@router.post("/run")
async def run_eval(payload: Dict[str, Any], _admin: dict = Depends(get_current_admin)) -> Dict[str, Any]:
    """一键运行评估：加载数据集 → 跑 RAG → 算指标 → 生成诊断与图表数据 → 落盘。"""
    dataset_id = payload.get("dataset_id")
    overrides = payload.get("config_overrides") or {}
    return await run_in_threadpool(_run_eval_sync, dataset_id, overrides)


@router.get("/report/{report_id}")
async def get_report(report_id: str, _admin: dict = Depends(get_current_admin)) -> Dict[str, Any]:
    """读取完整评估报告（含明细与诊断）。"""
    try:
        return await run_in_threadpool(EvalReportStore(_resolve_dir(settings.EVAL_REPORT_DIR)).load, report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reports")
async def list_reports(_admin: dict = Depends(get_current_admin)) -> Dict[str, Any]:
    """历史报告列表（倒序），供趋势图使用。"""
    summaries = await run_in_threadpool(EvalReportStore(_resolve_dir(settings.EVAL_REPORT_DIR)).latest_summary, 20)
    return {"total": len(summaries), "data": summaries}


@router.post("/apply-suggestion")
async def apply_suggestion(payload: Dict[str, Any], _admin: dict = Depends(get_current_admin)) -> Dict[str, Any]:
    """一键应用诊断建议：把白名单内的参数变更写回 .env（需重启生效）。"""
    report_id = payload.get("report_id")
    suggestion_id = payload.get("suggestion_id")
    dry_run = bool(payload.get("dry_run"))
    if not report_id or not suggestion_id:
        raise HTTPException(status_code=400, detail="report_id 与 suggestion_id 不能为空")

    def _apply() -> Dict[str, Any]:
        store = EvalReportStore(_resolve_dir(settings.EVAL_REPORT_DIR))
        try:
            data = store.load(report_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        diagnoses = [
            _dict_to_item(d) for d in data.get("diagnoses", [])
            if d.get("suggestion_id") == suggestion_id
        ]
        if not diagnoses:
            raise HTTPException(status_code=404, detail=f"报告中不存在建议：{suggestion_id}")

        tuner = AutoTuner()
        changes = tuner.plan(diagnoses, report_id=report_id)
        if not changes:
            return {"applied": False, "need_restart": False, "changes": [],
                    "message": "该建议对应的参数已在理想取值，无需变更"}
        return tuner.apply(changes, dry_run=dry_run).to_dict()

    return await run_in_threadpool(_apply)


@router.get("/changes")
async def list_changes(_admin: dict = Depends(get_current_admin)) -> Dict[str, Any]:
    """最近 10 条参数变更日志（含 apply / rollback 记录）。"""
    records = await run_in_threadpool(AutoTuner().recent_changes, 10)
    return {"total": len(records), "data": records}


@router.post("/rollback")
async def rollback(_admin: dict = Depends(get_current_admin)) -> Dict[str, Any]:
    """回滚到最近一次备份（找不到备份时用变更日志反向回滚）。"""
    return await run_in_threadpool(AutoTuner().rollback)


@router.get("/datasets")
async def list_datasets(_admin: dict = Depends(get_current_admin)) -> Dict[str, Any]:
    """列出可用评估数据集（data/eval 下的 json / csv）。"""
    def _list() -> Dict[str, Any]:
        directory = _resolve_dir(settings.EVAL_DATA_DIR)
        if not os.path.isdir(directory):
            return {"total": 0, "data": []}
        items: List[Dict[str, Any]] = []
        for name in sorted(os.listdir(directory)):
            if not name.endswith((".json", ".csv")):
                continue
            path = os.path.join(directory, name)
            count = 0
            try:
                count = len(EvalDataBuilder().load_qa_pairs(path))
            except Exception:  # noqa: BLE001 坏文件也列出来，但样本数记 0
                count = 0
            items.append({
                "dataset_id": name,
                "filename": name,
                "size_kb": round(os.path.getsize(path) / 1024, 1),
                "sample_count": count,
            })
        return {"total": len(items), "data": items}

    return await run_in_threadpool(_list)


@router.post("/datasets")
async def upload_dataset(
    file: UploadFile = File(...),
    _admin: dict = Depends(get_current_admin),
) -> Dict[str, Any]:
    """上传评估数据集（JSON / CSV），校验 question + ground_truth 字段完整性。

    注：评估所需的 answer / contexts 由 RAG 系统实时生成，
    因此上传语料只需有 question + ground_truth（构建后补齐四字段）。
    """
    content = await file.read()
    name = os.path.basename(file.filename or "")
    if not name.endswith((".json", ".csv")):
        raise HTTPException(status_code=400, detail="仅支持 .json / .csv 格式")
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="数据集不能超过 5MB")

    directory = _resolve_dir(settings.EVAL_DATA_DIR)
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, f"{uuid.uuid4().hex[:8]}_{name}")
    with open(target, "wb") as f:
        f.write(content)

    def _validate() -> Dict[str, Any]:
        try:
            pairs = EvalDataBuilder().load_qa_pairs(target)
        except Exception as exc:  # noqa: BLE001
            return {"code": 400, "msg": f"数据集解析失败：{exc}", "dataset_id": os.path.basename(target)}
        if not pairs:
            return {"code": 400, "msg": "缺少 question / ground_truth 字段", "dataset_id": os.path.basename(target)}
        return {
            "code": 200,
            "msg": "上传成功",
            "dataset_id": os.path.basename(target),
            "filename": name,
            "sample_count": len(pairs),
        }

    result = await run_in_threadpool(_validate)
    if result.get("code") != 200:
        raise HTTPException(status_code=400, detail=result["msg"])
    return result


def _dict_to_item(data: Dict[str, Any]):
    """把持久化的诊断字典还原为 DiagnosisItem（AutoTuner 只读 attribute，无需完整类）。"""
    from app.services.eval.diagnoser import DiagnosisItem

    return DiagnosisItem(
        suggestion_id=data.get("suggestion_id", ""),
        metric=data.get("metric", ""),
        score=data.get("score", 0.0),
        threshold=data.get("threshold", 0.0),
        level=data.get("level", "medium"),
        problem=data.get("problem", ""),
        suggestions=data.get("suggestions", []),
        param_changes=data.get("param_changes", {}),
    )
