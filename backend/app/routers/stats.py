"""统计类接口：首页地图等聚合视图。

0.11.1：数据源由分省表（`major_admission_2025_henan`）改为全国总表
（`major_admission_2025_all`），省份/科类/批次全部走 SQL 条件隔离，
表解析与条件构造统一交给 `services/dataset_access.py`。
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, func, select

from app.models.dataset import KIND_MAJOR, normalize_code, normalize_int
from app.services.dataset_access import DatasetUnavailable, resolve_table, scope_conditions

router = APIRouter(prefix="/api/stats", tags=["stats"])

# 0.12.1：school_province 缺失时的归集桶名。
# 吉林数据集整列无院校所在地，此前这些行被 `school_province IS NOT NULL` 过滤掉，
# 接口返回空数组、前端显示「暂无数据」。现在归到这个桶，至少能看到总量。
_UNKNOWN_BUCKET = "数据缺失"

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
      - university_count：涉及院校数（distinct **院校名**）
      - major_count：专业数（distinct **院校名 + 专业名**）

    0.12.1 修正统计口径：
      之前用 `university_code` / `major_code` 做 DISTINCT，但这两列在多个省大面积为空
      ——山东 `university_code` 33861/33861 全空，江西 `major_code` 9660/11725 为空，
      导致 `CONCAT(code,'-',code)` 整体为 NULL、`COUNT(DISTINCT NULL)=0`，
      表现为「招生专业 0 个」甚至「暂无数据」。名称列各省都有值，改用名称统计。

    0.12.1 同时兼容 `school_province` 缺失的省（吉林整列为 NULL）：
      不再把这些行过滤掉（那会返回空数组、前端显示「暂无数据」），
      而是归入 `数据缺失` 桶，并置 `degraded=True` 让前端给出明确说明。

    0.11.1：查全国总表 `major_admission_{year}_all`，
    `province=北京` 就只统计「北京考生能报的」数据，不会把外省数据混进来。
    """
    from app.database import fetch_all

    try:
        tbl = resolve_table(KIND_MAJOR, year, province)
    except DatasetUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # ★ 省份 + 科类 + 批次三重隔离（省份是 0.11.1 新增，防跨省串联）
    # 注意：这里**不再**过滤 school_province，缺失值归入「数据缺失」桶
    conds = scope_conditions(KIND_MAJOR, tbl, province, year, category, batch)

    # COALESCE：把缺失的 school_province 归到固定桶，避免整页空白
    school_prov = func.coalesce(
        func.nullif(tbl.c.school_province, ""), _UNKNOWN_BUCKET
    )
    major_key = func.concat_ws("||", tbl.c.university_name, tbl.c.major_name)
    stmt = (
        select(
            school_prov.label("school_province"),
            func.count(func.distinct(tbl.c.university_name)).label("university_count"),
            func.count(func.distinct(major_key)).label("major_count"),
        )
        .where(*conds)
        .group_by(school_prov)
        .order_by(func.count(func.distinct(major_key)).desc())
    )
    rows = fetch_all(stmt)

    data: List[Dict] = []
    for r in rows:
        raw_name = r.get("school_province")
        # 「数据缺失」桶原样保留，让前端能看到总量而不是空白
        if raw_name == _UNKNOWN_BUCKET:
            data.append(
                {
                    "province": _UNKNOWN_BUCKET,
                    "university_count": normalize_int(r.get("university_count")) or 0,
                    "major_count": normalize_int(r.get("major_count")) or 0,
                }
            )
            continue
        name = _normalize_province(raw_name)
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

    # 0.12.1：是否只有「数据缺失」桶（该省数据集没有院校所在地维度）
    unknown = [d for d in data if d["province"] == _UNKNOWN_BUCKET]
    degraded = bool(unknown) and len(unknown) == len(data)
    message = (
        f"{province} {year} 年数据集缺少院校所在地字段，仅能统计到总量，"
        "无法按省份分布展示。可在「查大学」页直接查看院校列表。"
        if degraded else ""
    )

    return {
        "code": 200,
        "msg": "ok",
        "province": province,
        "year": year,
        "category": category,
        "batch": batch,
        "total_major": total_major,
        "total_university": total_university,
        # 0.12.1：degraded=True 表示该省数据缺维度，前端应显示说明而不是「暂无数据」
        "degraded": degraded,
        "message": message,
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
