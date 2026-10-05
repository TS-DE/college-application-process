"""查大学 / 查专业接口。"""
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, func, or_, select

from app.config import settings
from app.models.dataset import (
    KIND_MAJOR,
    KIND_SCHOOL,
    normalize_code,
    normalize_int,
    normalize_score,
    resolve_batch,
    resolve_category,
    table_name,
)
from app.services.recommend_service import _probability

router = APIRouter(prefix="/api", tags=["university"])

TIER_LABEL = {"chong": "冲", "wen": "稳", "bao": "保"}


_BUFFER = settings.RANK_BUFFER


def _tier_of(min_rank: int, rank: int, buffer: int = _BUFFER) -> str:
    if min_rank < rank - buffer:
        return "chong"
    if min_rank > rank + buffer:
        return "bao"
    return "wen"


@router.get("/universities")
def universities(
    province: str = Query(default="河南"),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
    batch: str = Query(default="本科批"),
    keyword: Optional[str] = Query(default=None),
    school_province: Optional[str] = Query(default=None),
    school_nature: Optional[str] = Query(default=None),
    is_985: Optional[bool] = Query(default=None),
    is_211: Optional[bool] = Query(default=None),
    rank: Optional[int] = Query(default=None, description="传入考生位次可给出推荐概率"),
    min_rank: Optional[int] = Query(default=None),
    max_rank: Optional[int] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Dict:
    """院校列表（来源：院校投档表 school_admission）。"""
    tbl = get_school_table(province, year)
    conds = [tbl.c.min_rank.isnot(None), tbl.c.university_name.isnot(None)]

    cats = resolve_category(category, year, KIND_SCHOOL)
    if cats:
        conds.append(tbl.c.category.in_(cats))
    batches = resolve_batch(batch, year, KIND_SCHOOL)
    if batches:
        conds.append(tbl.c.batch.in_(batches))

    if keyword:
        conds.append(tbl.c.university_name.like(f"%{keyword}%"))
    if school_province:
        conds.append(tbl.c.school_province == school_province)
    if school_nature:
        conds.append(tbl.c.school_nature == school_nature)
    if is_985:
        conds.append(tbl.c.is_985 == 1)
    if is_211:
        conds.append(tbl.c.is_211 == 1)
    if min_rank is not None:
        conds.append(tbl.c.min_rank >= min_rank)
    if max_rank is not None:
        conds.append(tbl.c.min_rank <= max_rank)

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
            func.sum(tbl.c.admit_count).label("admit_count"),
            func.count().label("group_count"),
        )
        .where(and_(*conds))
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
    from app.database import fetch_all

    rows = fetch_all(stmt)

    items: List[Dict] = []
    for r in rows:
        mr = normalize_int(r.get("min_rank"))
        tier = _tier_of(mr, rank) if (rank and mr) else None
        items.append(
            {
                "university_code": normalize_code(r.get("university_code")),
                "university_name": r.get("university_name"),
                "school_province": r.get("school_province"),
                "school_nature": r.get("school_nature"),
                "is_985": int(r.get("is_985") or 0) == 1,
                "is_211": int(r.get("is_211") or 0) == 1,
                "min_score": normalize_score(r.get("min_score")),
                "min_rank": mr,
                "admit_count": normalize_score(r.get("admit_count")),
                "group_count": r.get("group_count"),
                "rank_diff": (mr - rank) if (rank and mr) else None,
                "tier": tier,
                "tier_label": TIER_LABEL.get(tier) if tier else None,
                "probability": (
                    _probability(tier, mr - rank, _BUFFER, settings.RANK_SPAN_FACTOR)
                    if (rank and mr and tier)
                    else None
                ),
            }
        )

    total = len(items)
    start = (page - 1) * page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items[start : start + page_size],
    }


@router.get("/majors")
def majors(
    university_code: Optional[str] = Query(default=None),
    university_name: Optional[str] = Query(default=None),
    province: str = Query(default="河南"),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
    batch: str = Query(default="本科批"),
    keyword: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
) -> Dict:
    """某院校的专业录取明细（来源：major_admission）。"""
    from app.database import fetch_all

    if not university_code and not university_name:
        raise HTTPException(status_code=400, detail="university_code 或 university_name 必填其一")

    tbl = get_major_table(province, year)
    conds = [tbl.c.min_rank.isnot(None)]
    cats = resolve_category(category, year, KIND_MAJOR)
    if cats:
        conds.append(tbl.c.category.in_(cats))
    batches = resolve_batch(batch, year, KIND_MAJOR)
    if batches:
        conds.append(tbl.c.batch.in_(batches))

    if university_code:
        try:
            conds.append(tbl.c.university_code == float(university_code))
        except ValueError:
            conds.append(tbl.c.university_code == university_code)
    if university_name:
        conds.append(tbl.c.university_name.like(f"%{university_name}%"))
    if keyword:
        conds.append(
            or_(tbl.c.major_name.like(f"%{keyword}%"), tbl.c.major_note.like(f"%{keyword}%"))
        )

    stmt = (
        select(tbl)
        .where(and_(*conds))
        .order_by(tbl.c.min_rank)
    )
    rows = fetch_all(stmt)

    from app.services.recommend_service import _plan_index, _lookup_plan

    plan_idx = _plan_index(province, year, category, batch)
    items: List[Dict] = []
    for r in rows:
        plan = _lookup_plan(
            plan_idx, r.get("university_code"), r.get("university_name"),
            r.get("major_code"), r.get("major_name"),
        )
        items.append(
            {
                "university_code": normalize_code(r.get("university_code")),
                "university_name": r.get("university_name"),
                "major_code": normalize_code(r.get("major_code")),
                "major_name": r.get("major_name"),
                "major_group": r.get("major_group"),
                "major_note": r.get("major_note"),
                "subject_req": r.get("subject_req") or plan.get("subject_req"),
                "min_score": normalize_score(r.get("min_score")),
                "min_rank": normalize_int(r.get("min_rank")),
                "max_score": normalize_score(r.get("max_score")),
                "avg_score": normalize_score(r.get("avg_score")),
                "admit_count": normalize_score(r.get("admit_count")),
                "plan_count": normalize_score(plan.get("plan_count")),
                "tuition": normalize_score(plan.get("tuition")),
                "duration": plan.get("duration"),
            }
        )

    total = len(items)
    start = (page - 1) * page_size
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items[start : start + page_size],
    }


def get_school_table(province: str, year: int):
    from app.database import get_table

    try:
        return get_table(table_name(KIND_SCHOOL, year, province))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def get_major_table(province: str, year: int):
    from app.database import get_table

    try:
        return get_table(table_name(KIND_MAJOR, year, province))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc
