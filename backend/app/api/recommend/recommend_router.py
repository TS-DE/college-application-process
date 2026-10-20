"""志愿推荐接口。

0.11.0 全国多省自适应：
  · `/api/recommend`        保留原「河南单省富信息版」（带学费/计划数/AI 理由），
                            同时新增 `rank` + `tiers` 字段（全国引擎结果）；
  · `/api/recommend/national` 纯全国引擎版，只返回 `{rank, tiers}`。
两条路径都会先做「省份 + 科类」合法性校验，非法组合直接 400。
"""
import asyncio
from typing import Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.schemas.student import RecommendIn, RecommendItem, RecommendOut
from app.utils.region_mapper import (
    get_categories_by_province,
    has_data,
    normalize_province,
)

router = APIRouter(prefix="/api", tags=["recommend"])


def _validate_province_category(province: str, category: str) -> str:
    """校验「省份 + 科类」组合，返回归一后的省份中文名；不合法直接 400。

    这是全国多省自适应的第一道闸门：不同省份科类名不同
    （3+3=综合 / 3+1+2=物理类·历史类 / 老高考=理科·文科），
    放错组合会让 SQL 查不到数据甚至串省。
    """
    cats = get_categories_by_province(province)
    if not cats:
        raise HTTPException(status_code=400, detail=f"不支持的省份：{province}")
    cat = (category or "").strip()
    if cat not in cats:
        raise HTTPException(
            status_code=400,
            detail=f"该省份不支持此科类：{normalize_province(province)} 仅支持 {'、'.join(cats)}",
        )
    if not has_data(province):
        raise HTTPException(
            status_code=400,
            detail=f"{normalize_province(province)} 暂无 2025 年录取数据，请切换省份",
        )
    return normalize_province(province)


@router.post("/recommend", response_model=RecommendOut)
async def recommend(payload: RecommendIn) -> RecommendOut:
    """生成冲/稳/保三档志愿推荐。

    0.11.0 起以**全国多省自适应引擎**为主路径（查 `major_admission_{year}_all` 总表）：
      1. 校验「省份 + 科类」组合；
      2. `rank_service.score_to_rank(score, province, category)` 算位次；
      3. `recommend_service.calculate_tiers(rank, province, category)` 算三档；
      4. `enrich_with_plan()` 用招生计划总表补学费 / 计划数 / 学制。

    原「河南单省富信息版」`recommend_service.recommend()` 依赖分省表
    （`score_range_2025_henan` 等），这些表在数据合并后已不存在，
    因此降级为**可选增强**：能跑成功就额外带 AI 推荐理由，跑失败也不影响主结果。

    响应字段与 0.10.0 及以前保持一致（student / chong / wen / bao / meta），
    另新增 `rank` 与 `tiers`（全国引擎原始结果），向前兼容。
    """
    from app.services.recommend.rank_service import score_to_rank
    from app.services.recommend.recommend_service import calculate_tiers, enrich_with_plan

    # ---- 第一道闸门：省份 + 科类合法性 ----
    prov = _validate_province_category(payload.province, payload.category)
    cat = (payload.category or "").strip()

    # ---- 第二步：分数 → 位次（全国总表）----
    rank = payload.rank
    if not rank:
        if not payload.score:
            raise HTTPException(status_code=400, detail="score 与 rank 至少提供一个")
        rank = score_to_rank(payload.score, prov, cat, payload.year)
    if not rank:
        raise HTTPException(status_code=400, detail="未在当年一分一段表中找到该分数")

    # ---- 第三步：位次 → 冲稳保三档 ----
    try:
        tiers = await asyncio.wait_for(
            run_in_threadpool(calculate_tiers, rank, prov, cat, payload.year),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="推荐生成超时，请稍后重试") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"推荐失败：{exc}") from exc

    # ---- 第四步：富化（学费 / 计划数 / 学制）----
    try:
        # 0.11.2：富化要带批次，否则计划索引会按默认批次取，跨批次院校对不上
        tiers = await asyncio.wait_for(
            run_in_threadpool(enrich_with_plan, tiers, prov, cat, payload.year, payload.batch),
            timeout=30.0,
        )
    except Exception:  # noqa: BLE001 富化失败不影响主结果
        pass

    total = sum(len(v) for v in tiers.values())
    return RecommendOut(
        student={
            "province": prov,
            "year": payload.year,
            "category": cat,
            "batch": payload.batch,
            "score": payload.score,
            "rank": int(rank),
        },
        chong=tiers.get("chong", []),
        wen=tiers.get("wen", []),
        bao=tiers.get("bao", []),
        meta={
            "total_scanned": total,
            "buffer": 0,
            "span_factor": 0,
            "table": f"major_admission_{payload.year}_all",
            "ai_enabled": False,
            "ai_generated": 0,
            "elapsed_ms": 0,
        },
        rank=int(rank),
        tiers=tiers,
    )


@router.post("/recommend/national")
async def recommend_national(payload: RecommendIn) -> Dict:
    """0.11.0 纯全国引擎版推荐：只返回 `{rank, tiers}`。

    适合只要结构化结果的场景；不做富化、不调 AI。
    """
    from app.services.recommend.rank_service import score_to_rank
    from app.services.recommend.recommend_service import calculate_tiers

    prov = _validate_province_category(payload.province, payload.category)
    cat = (payload.category or "").strip()

    rank = payload.rank
    if not rank:
        if not payload.score:
            raise HTTPException(status_code=400, detail="score 与 rank 至少提供一个")
        rank = score_to_rank(payload.score, prov, cat, payload.year)
    if not rank:
        raise HTTPException(status_code=400, detail="未在当年一分一段表中找到该分数")

    try:
        tiers = await asyncio.wait_for(
            run_in_threadpool(calculate_tiers, rank, prov, cat, payload.year),
            timeout=60.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="推荐生成超时，请稍后重试") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"推荐失败：{exc}") from exc

    return {
        "rank": int(rank),
        "province": prov,
        "category": cat,
        "year": payload.year,
        "tiers": tiers,
    }


@router.post("/recommend/ai-reasons")
async def batch_ai_reasons(payload: Dict) -> Dict:
    """对已生成的推荐条目批量补充 AI 理由。

    入参：{ "student": {...}, "items": [ { ...推荐条目 } ], "limit": 10 }
    0.7.2：改为 async + 线程池，避免阻塞非 AI 接口。
    """
    from app.services.llm.ai_service import ai_enabled, recommend_reason

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
