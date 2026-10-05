"""元信息接口：可用维度、省份分布、热门院校、一分一段表。"""
from typing import Dict, List

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.config import settings
from app.database import fetch_all, get_table, table_exists
from app.models.dataset import (
    KIND_MAJOR,
    KIND_SCHOOL,
    KIND_SCORE,
    normalize_code,
    normalize_int,
    normalize_score,
    province_suffix,
    resolve_batch,
    resolve_category,
    table_name,
)

router = APIRouter(prefix="/api/meta", tags=["meta"])

def _available_years(province: str) -> List[int]:
    """扫描 information_schema，找出该省份实际导入了哪些年份。"""
    from sqlalchemy import text

    from app.database import engine

    suffix = province_suffix(province)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :db AND table_name LIKE :p"
            ),
            {"db": settings.DB_NAME, "p": f"{KIND_SCORE}_%_{suffix}"},
        ).fetchall()
    years = set()
    for (tname,) in rows:
        parts = tname.split("_")
        for p in parts:
            if p.isdigit() and len(p) == 4:
                years.add(int(p))
    return sorted(years)


@router.get("/options")
def options(province: str = Query(default=settings.DEFAULT_PROVINCE)) -> Dict:
    """返回该省份可用的年份 / 科类 / 批次，避免前端写死下拉框。"""
    years = _available_years(province)
    categories: List[str] = []
    batches: List[str] = []
    for y in years:
        tbl = get_table(table_name(KIND_SCORE, y, province))
        rows = fetch_all(
            select(tbl.c.category, tbl.c.batch).distinct()
        )
        for r in rows:
            c, b = r.get("category"), r.get("batch")
            if c and c not in categories:
                categories.append(c)
            if b and b not in batches:
                batches.append(b)
    # 前端按新高考口径展示
    canon_batches: List[str] = []
    for b in batches:
        cb = "本科批" if b in ("本科一批", "本科二批", "本一", "本二", "本科批") else b
        if cb not in canon_batches:
            canon_batches.append(cb)
    return {
        "province": province,
        "years": years,
        "categories": categories,
        "batches": canon_batches,
        "raw_batches": batches,
        "default": {
            "year": years[-1] if years else 2025,
            "category": "物理类" if "物理类" in categories else (categories[0] if categories else "物理类"),
            "batch": "本科批",
        },
    }


@router.get("/province-stats")
def province_stats(
    province: str = Query(default=settings.DEFAULT_PROVINCE),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
    batch: str = Query(default="本科批"),
) -> Dict:
    """各省份在河南招生的院校专业数量，供首页地图渲染。"""
    tbl = get_table(table_name(KIND_MAJOR, year, province))
    stmt = select(tbl.c.school_province, func.count().label("cnt")).where(
        tbl.c.school_province.isnot(None)
    )
    cats = resolve_category(category, year, KIND_MAJOR)
    batches = resolve_batch(batch, year, KIND_MAJOR)
    if cats:
        stmt = stmt.where(tbl.c.category.in_(cats))
    if batches:
        stmt = stmt.where(tbl.c.batch.in_(batches))
    stmt = stmt.group_by(tbl.c.school_province)
    rows = fetch_all(stmt)
    return {
        "year": year,
        "category": category,
        "batch": batch,
        "items": [{"name": r["school_province"], "value": r["cnt"]} for r in rows],
    }


@router.get("/hot-schools")
def hot_schools(
    province: str = Query(default=settings.DEFAULT_PROVINCE),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
    batch: str = Query(default="本科批"),
    limit: int = Query(default=12, ge=1, le=50),
) -> Dict:
    """首页热门院校卡片：优先 985/211，按投档位次排序。"""
    tbl = get_table(table_name(KIND_SCHOOL, year, province))
    conds = [tbl.c.min_rank.isnot(None), tbl.c.university_name.isnot(None)]
    cats = resolve_category(category, year, KIND_SCHOOL)
    batches = resolve_batch(batch, year, KIND_SCHOOL)
    if cats:
        conds.append(tbl.c.category.in_(cats))
    if batches:
        conds.append(tbl.c.batch.in_(batches))

    stmt = (
        select(
            tbl.c.university_code,
            tbl.c.university_name,
            tbl.c.school_province,
            tbl.c.school_nature,
            tbl.c.is_985,
            tbl.c.is_211,
            func.min(tbl.c.min_score).label("min_score"),
            func.min(tbl.c.min_rank).label("min_rank"),
        )
        .where(*conds)
        .group_by(
            tbl.c.university_code,
            tbl.c.university_name,
            tbl.c.school_province,
            tbl.c.school_nature,
            tbl.c.is_985,
            tbl.c.is_211,
        )
        .order_by(func.min(tbl.c.min_rank))
    )
    rows = fetch_all(stmt)

    def _tags(r) -> List[str]:
        tags = []
        if int(r.get("is_985") or 0) == 1:
            tags.append("985")
        if int(r.get("is_211") or 0) == 1:
            tags.append("211")
        if tags:
            tags.append("双一流")
        return tags

    featured = [r for r in rows if _tags(r)]
    others = [r for r in rows if not _tags(r)]
    picked = (featured + others)[:limit]
    return {
        "items": [
            {
                "university_code": normalize_code(r.get("university_code")),
                "university_name": r.get("university_name"),
                "school_province": r.get("school_province"),
                "school_nature": r.get("school_nature"),
                "min_score": normalize_score(r.get("min_score")),
                "min_rank": normalize_int(r.get("min_rank")),
                "tags": _tags(r),
            }
            for r in picked
        ]
    }


@router.get("/score-table")
def score_table(
    province: str = Query(default=settings.DEFAULT_PROVINCE),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
    batch: str = Query(default="本科批"),
) -> Dict:
    """一分一段表（快捷工具）。"""
    from app.services.rank_service import score_table as _tbl

    rows = _tbl(province, year, category, batch)
    return {"items": rows}


@router.get("/control-lines")
def control_lines(
    province: str = Query(default=settings.DEFAULT_PROVINCE),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
) -> Dict:
    """各批次省控线 + 本科/专科的可填写分数区间（按年份、科类动态变化）。

    前端用 bounds 控制「成绩类型 = 本科/专科」时预估分数的合法区间，
    用 lines 渲染「分数未过线」的温馨提示弹窗。
    """
    from app.services.rank_service import control_lines as _lines

    try:
        return _lines(province, year, category)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/score-check")
def score_check(
    score: float = Query(..., ge=0, le=750, description="预估分数"),
    province: str = Query(default=settings.DEFAULT_PROVINCE),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
) -> Dict:
    """分数校验三合一：是否过线 + 自动推荐批次 + 自动换算位次。

    below_all=True 时 rank / recommend_batch 为空，前端应弹出温馨提示。
    """
    from app.services.rank_service import score_check as _check

    try:
        return _check(province, year, category, score)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
