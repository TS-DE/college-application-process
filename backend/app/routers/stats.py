"""统计类接口：首页地图等聚合视图。"""
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, func, select

from app.models.dataset import (
    KIND_MAJOR,
    normalize_code,
    normalize_int,
    resolve_batch,
    resolve_category,
    table_name,
)

router = APIRouter(prefix="/api/stats", tags=["stats"])

# ECharts 中国地图使用的省份名（短名），数据集里的写法可能带"省/自治区/市"后缀
_PROVINCE_ALIAS = {
    "内蒙古自治区": "内蒙古",
    "广西壮族自治区": "广西",
    "宁夏回族自治区": "宁夏",
    "新疆维吾尔自治区": "新疆",
    "西藏自治区": "西藏",
    "香港特别行政区": "香港",
    "澳门特别行政区": "澳门",
    "台湾省": "台湾",
}

# 地图里不参与着色/点击的条目
_SKIP_NAMES = {"南海诸岛"}


def _normalize_province(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    s = str(name).strip()
    if not s:
        return None
    s = _PROVINCE_ALIAS.get(s, s)
    for suffix in ("省", "市", "自治区"):
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)]
            break
    # "广西壮族自治区" 被上面截断后可能变成 "广西壮族"，兜底再映射一次
    s = _PROVINCE_ALIAS.get(s, s)
    return s or None


@router.get("/major-count-by-province")
def major_count_by_province(
    province: str = Query(default="河南", description="考生所在省份（数据集维度）"),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
    batch: str = Query(default="本科批"),
) -> Dict:
    """各省高校在 `province` 投放的专业数量（用于首页中国地图）。

    按 `school_province`（学校所在省份）聚合：
      - university_count：涉及院校数（distinct university_code）
      - major_count：专业数（distinct university_code + major_code）
    """
    from app.database import fetch_all, get_table

    try:
        tbl = get_table(table_name(KIND_MAJOR, year, province))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    conds = [tbl.c.school_province.isnot(None), tbl.c.school_province != ""]
    cats = resolve_category(category, year, KIND_MAJOR)
    if cats:
        conds.append(tbl.c.category.in_(cats))
    batches = resolve_batch(batch, year, KIND_MAJOR)
    if batches:
        conds.append(tbl.c.batch.in_(batches))

    major_key = func.concat(tbl.c.university_code, "-", tbl.c.major_code)
    stmt = (
        select(
            tbl.c.school_province.label("school_province"),
            func.count(func.distinct(tbl.c.university_code)).label("university_count"),
            func.count(func.distinct(major_key)).label("major_count"),
        )
        .where(and_(*conds))
        .group_by(tbl.c.school_province)
        .order_by(func.count(func.distinct(major_key)).desc())
    )
    rows = fetch_all(stmt)

    data: List[Dict] = []
    for r in rows:
        name = _normalize_province(r.get("school_province"))
        if not name or name in _SKIP_NAMES:
            continue
        data.append(
            {
                "province": name,
                "university_count": normalize_int(r.get("university_count")) or 0,
                "major_count": normalize_int(r.get("major_count")) or 0,
            }
        )

    data.sort(key=lambda x: x["major_count"], reverse=True)
    total_major = sum(d["major_count"] for d in data)
    total_university = sum(d["university_count"] for d in data)

    return {
        "code": 200,
        "msg": "ok",
        "province": province,
        "year": year,
        "category": category,
        "batch": batch,
        "total_major": total_major,
        "total_university": total_university,
        "data": data,
    }


@router.get("/province-stats")
def province_stats_alias(
    province: str = Query(default="河南"),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
    batch: str = Query(default="本科批"),
) -> Dict:
    """兼容旧前端 `/api/meta/province-stats` 的返回结构（items: name/value）。"""
    res = major_count_by_province(province=province, year=year, category=category, batch=batch)
    return {
        "items": [
            {"name": d["province"], "value": d["major_count"]} for d in res["data"]
        ]
    }


__all__ = ["router", "major_count_by_province", "normalize_code"]
