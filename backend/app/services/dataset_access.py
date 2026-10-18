"""数据集访问层（0.11.1）：表解析 + 省份/科类过滤条件。

## 为什么单独一层（单一职责 / 接口隔离）
0.11.0 之前，路由层各自写 `get_table(table_name(KIND_MAJOR, year, province))`，
一旦「分省表 → 全国总表」的存储方式变化，就要在 5 个路由里各改一遍，
而且很容易漏加 `province` 条件导致跨省数据串联。

本模块把两件事收口：
  1. **表解析**：`resolve_table()` —— 统一走全国总表，并对没有 `_all` 表的
     数据集（`school_admission`）自动回落到可替代的表；
  2. **省份隔离**：`province_conditions()` / `category_conditions()` ——
     保证每条查询都带上 `WHERE province = ? AND category IN (...)`。

路由层只负责接收参数、拼装响应，不再关心表名怎么来的（单一职责）。
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Optional

from sqlalchemy import select

from app.database import TableNotFound, fetch_all, get_table, table_exists
from app.models.dataset import (
    KIND_MAJOR,
    canonical_batch,
    resolve_batch,
    resolve_category,
    resolve_kind,
    table_name,
)
from app.utils.region_mapper import normalize_province

logger = logging.getLogger(__name__)


class DatasetUnavailable(Exception):
    """数据集不可用（该年份没有总表 / 反射失败），由路由层转成 404。"""


def resolve_table(kind: str, year: int, province: str = ""):
    """反射并返回该数据集在该年份下的**全国总表**。

    :param kind:     数据集类型（major_admission / enrollment_plan / score_range / school_admission）
    :param year:     年份
    :param province: 省份（仅用于日志，**不再参与表名拼接**）
    :return:         SQLAlchemy Table
    :raises DatasetUnavailable: 表不存在或反射失败

    类型回落：`school_admission` 没有 `_all` 总表，自动回落到
    `major_admission`（同样含院校名 / 分数 / 位次 / 985/211 等列）。
    """
    actual_kind = resolve_kind(kind)
    name = table_name(actual_kind, year, province)
    if not table_exists(name):
        raise DatasetUnavailable(f"{year} 年数据集缺失：{name}")
    try:
        return get_table(name)
    except TableNotFound as exc:
        raise DatasetUnavailable(str(exc)) from exc


def province_conditions(tbl, province: Optional[str]) -> List:
    """返回 `WHERE province = ?` 条件列表（省份为空时返回空列表 = 不隔离）。

    ★ 这是「多省自适应」的核心保护：总表里存着 30+ 省的数据，
    漏掉这个条件就会把外省院校混进结果里。
    """
    prov = normalize_province(province)
    if not prov:
        return []
    col = getattr(tbl.c, "province", None)
    if col is None:
        # 极少数表没有 province 列（如全局词表），此时不做隔离而不是报错
        logger.info("[DATASET] 表 %s 无 province 列，跳过省份隔离", tbl.name)
        return []
    return [col == prov]


def category_conditions(kind: str, tbl, category: Optional[str], year: int) -> List:
    """返回科类过滤条件（把新老高考写法统一成表里的真实取值）。

    科类在不同省份叫法不同：3+3 是「综合」、3+1+2 是「物理类/历史类」、
    老高考是「理科/文科」。`resolve_category()` 负责按年份做映射。
    """
    if not category:
        return []
    col = getattr(tbl.c, "category", None)
    if col is None:
        return []
    cats = resolve_category(category, year, kind)
    if not cats:
        return []
    return [col.in_(list(cats))]


@lru_cache(maxsize=128)
def _province_batches(province: str, year: int, kind: str) -> tuple:
    """某省某年实际存在哪些 batch 取值（缓存，避免每次请求都查一遍）。"""
    try:
        tbl = resolve_table(kind, year, province)
        col = getattr(tbl.c, "batch", None)
        if col is None:
            return ()
        stmt = select(col).distinct()
        conds = province_conditions(tbl, province)
        if conds:
            stmt = stmt.where(*conds)
        return tuple(r.get("batch") for r in fetch_all(stmt) if r.get("batch"))
    except Exception as exc:  # noqa: BLE001 查不到就当作无批次信息
        logger.info("[DATASET] 读取批次字典失败 %s/%s：%s", province, year, exc.__class__.__name__)
        return ()


def _batch_matches(canon: str, actual: str) -> bool:
    """判断某省的真实批次写法能否归入规范批次。

    ★ 为什么需要这一步
    各省批次写法差异很大（实测 `major_admission_2025_all`）：
      · 「本科批」    19 省通用
      · 「本科批A/B/C段」 四川、陕西等 4+1 省按段拆分
      · 「普通本科批」   1 省
      · 「专科批」/「专科批次」/「高职专科」/「高职(专科)批」
      · 「普通类一段 / 二段」 浙江、山东的段次写法
    直接用 `batch = '本科批'` 精确匹配，四川这类省份会一条都查不到
    （表现为「查大学页面空白」）。
    """
    if not actual:
        return False
    if actual == canon:
        return True
    if canon == "本科批":
        return (
            actual == "本科"                     # 四川：本科 / 专科 两档最简写法
            or actual.startswith("本科批")       # 本科批A段 / B段 / C段
            or actual.startswith("普通本科批")   # 普通本科批
            or actual.startswith("本科普通批")   # 广西：本科普通批
            or actual == "普通类一段"            # 浙江/山东：一段为本科段
        )
    if canon == "专科批":
        return (
            actual == "专科"                     # 四川：最简写法
            or actual.startswith("专科批")       # 专科批 / 专科批次
            or actual.startswith("高职")         # 高职专科 / 高职(专科)批
            or actual == "普通类二段"            # 浙江/山东：二段含专科
        )
    return actual.startswith(canon)              # 本科提前批 → 本科提前批B段


def batch_conditions(
    kind: str, tbl, batch: Optional[str], year: int, province: str = ""
) -> List:
    """返回批次过滤条件（省份感知）。

    先按规范批次在**该省真实批次字典**里找语义等价的写法；
    一个都找不到时**不按批次过滤**并记日志——宁可多给数据，
    也不要因为批次写法不同让整页空白。
    """
    if not batch:
        return []
    col = getattr(tbl.c, "batch", None)
    if col is None:
        return []
    canon = canonical_batch(batch)
    actual = _province_batches(normalize_province(province), year, kind)
    if actual:
        matched = [b for b in actual if _batch_matches(canon, b)]
        if matched:
            return [col.in_(matched)]
        logger.info("[DATASET] %s %s 无匹配批次「%s」，跳过批次过滤", province, year, canon)
        return []
    # 拿不到批次字典时退回精确值
    batches = resolve_batch(batch, year, kind)
    if not batches:
        return []
    return [col.in_(list(batches))]


def scope_conditions(
    kind: str,
    tbl,
    province: Optional[str],
    year: int,
    category: Optional[str] = None,
    batch: Optional[str] = None,
) -> List:
    """一次性拿到「省份 + 科类 + 批次」三组过滤条件（路由层最常用的组合）。"""
    return (
        province_conditions(tbl, province)
        + category_conditions(kind, tbl, category, year)
        + batch_conditions(kind, tbl, batch, year, province or "")
    )


def default_scope(kind: str = KIND_MAJOR) -> dict:
    """省份/科类缺省值（供路由层 Query(default=...) 复用，避免各处写死「河南」）。"""
    from app.config import settings

    return {"province": settings.DEFAULT_PROVINCE, "category": "物理类"}


__all__ = [
    "DatasetUnavailable",
    "resolve_table",
    "province_conditions",
    "category_conditions",
    "batch_conditions",
    "scope_conditions",
    "default_scope",
]
