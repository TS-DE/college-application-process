"""分数 <-> 位次 换算服务。

## 0.11.0 全国多省自适应
原先只查 `score_range_{year}_{province}`（河南单省写死），现新增全国总表
`score_range_{year}_all` 的查询入口，province / category / year 全部参数化：

    score_to_rank(score, province, category, year=2025) -> int
    rank_to_score(rank, province, category, year=2025) -> int

## ★ 三个坑（都已在代码里处理）
1. `province` 列存的是**中文名**（"河南"），入参可传拼音（"henan"），
   由 `utils/region_mapper.normalize_province()` 归一；
2. `score` / `cumulative_count` 列是 **TEXT**，且值是 `'710.0'` 这类浮点字符串，
   数值比较必须 `CAST(... AS SIGNED)`——直接 `score <= '600'` 会因字符串比较
   把 '600.0' 漏掉（'600.0' > '600'）；
3. 单省数据缺失时**返回 0 并记 warning，不抛异常**，由上层决定报 400 还是降级。

cumulative_count = 该分数及以上的累计人数，即该分数对应的最低位次。
河南 2024 老高考一分一段按「本科一批 / 本科二批 / 专科批」分段存储，
分数区间互不重叠（一本 511-709、二本 396-510、专科 100-395），
因此选「本科批」时要在一本、二本两张区间里按分数定位。
"""
from typing import Dict, List, Optional

from sqlalchemy import select, text

from app.config import settings
from app.database import SessionLocal, fetch_all, get_table, table_exists
from app.models.dataset import (
    KIND_SCORE,
    canonical_batch,
    normalize_int,
    resolve_batch,
    resolve_category,
    table_name,
)
from app.utils.region_mapper import normalize_province

import logging

logger = logging.getLogger(__name__)

FULL_SCORE = 750

# 0.11.0 全国总表名模板：score_range_{year}_all
_NATIONAL_TABLE = "score_range_{year}_all"

# 单次查询最多返回行数（内存保护：绝不全表 SELECT *）
_NATIONAL_LIMIT = 50


def _load_score_range(
    province: str, year: int, category: str, batch: Optional[str] = None
) -> List[Dict]:
    """batch 传 None 时加载该科类全部批次的分数段（用于批次线 / 跨批次定位）。

    0.11.1：查全国总表 `score_range_{year}_all`，**必须**按省份隔离——
    否则会把三十多个省的一分一段混在一起，位次换算结果完全错误。
    """
    from app.services.recommend.dataset_access import province_conditions

    tbl = get_table(table_name(KIND_SCORE, year, province))
    stmt = select(tbl)
    # ★ 省份隔离（总表里存着 30+ 省数据，漏掉会跨省串联）
    prov_conds = province_conditions(tbl, province)
    if prov_conds:
        stmt = stmt.where(*prov_conds)
    cats = resolve_category(category, year, KIND_SCORE)
    if cats:
        stmt = stmt.where(tbl.c.category.in_(cats))
    if batch:
        batches = resolve_batch(batch, year, KIND_SCORE)
        if batches:
            stmt = stmt.where(tbl.c.batch.in_(batches))
    rows = fetch_all(stmt)
    out = []
    for r in rows:
        score = r.get("score")
        if score is None:
            continue
        try:
            score = float(score)
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "score": score,
                "cumulative_count": normalize_int(r.get("cumulative_count")),
                "segment_count": normalize_int(r.get("segment_count")),
                "rank_range": r.get("rank_range"),
                "control_score": normalize_int(r.get("control_score")),
                "batch": r.get("batch"),
                "category": r.get("category"),
            }
        )
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def score_to_rank_detail(province: str, year: int, category: str, batch: str, score: float) -> Dict:
    """分数 -> 位次（**河南单省富信息版**，走分省表）。

    0.11.0 起原 `score_to_rank` 已让位给全国版（见下方 `score_to_rank`），
    这里保留改名后的实现，供 student.py / score_check 等需要
    control_score / rank_range 等附加信息的调用方使用。

    优先精确命中；若无该分数，则取「大于该分数的最小分数」的累计人数
    （因为该分数无人，位次等价于其上方最近一档的累计人数）。
    """
    rows = _load_score_range(province, year, category, batch)
    if not rows:
        raise ValueError(
            f"未找到一分一段数据：province={province} year={year} "
            f"category={category} batch={batch}"
        )

    target = float(score)
    exact = next((r for r in rows if abs(r["score"] - target) < 1e-6), None)
    if exact:
        chosen, is_exact = exact, True
    else:
        above = [r for r in rows if r["score"] > target]
        chosen = above[-1] if above else rows[0]
        is_exact = False

    return {
        "province": province,
        "year": year,
        "category": category,
        "batch": batch,
        "score": target,
        "rank": chosen["cumulative_count"] or 0,
        "segment_count": chosen["segment_count"],
        "rank_range": chosen["rank_range"],
        "control_score": chosen["control_score"],
        "batch_used": chosen["batch"],
        "exact": is_exact,
        "score_diff": (
            int(target - chosen["control_score"])
            if chosen["control_score"] is not None
            else None
        ),
    }


def rank_to_score_detail(province: str, year: int, category: str, batch: str, rank: int) -> Dict:
    """位次 -> 分数：按分数从高到低，找第一个累计人数 >= rank 的分数（河南单省富信息版）。"""
    rows = _load_score_range(province, year, category, batch)
    if not rows:
        raise ValueError("未找到一分一段数据")
    chosen = None
    for r in rows:  # rows 已按分数降序，累计人数递增
        if r["cumulative_count"] is not None and r["cumulative_count"] >= int(rank):
            chosen = r
            break
    if chosen is None:
        chosen = rows[-1]
    return {
        "province": province,
        "year": year,
        "category": category,
        "batch": batch,
        "rank": int(rank),
        "score": chosen["score"],
        "rank_range": chosen["rank_range"],
        "control_score": chosen["control_score"],
    }


# ============================================================
# 0.11.0 全国多省自适应：统一查 score_range_{year}_all 总表
# ============================================================
#
# ## 与上面 _detail 版的区别
#   · 数据源：全国总表 `score_range_{year}_all`（30+ 省合并），不再是河南分省表；
#   · 入参  ：(score, province, category, year)，province/category 必传，
#             避免跨省数据串联污染；
#   · 返回  ：裸位次 int（0 表示没查到），不再返回富信息 Dict；
#   · 异常  ：任何失败都返回 0 + logger.warning，不抛异常（优雅降级）。
#
# ## 参数传递路径
#   前端 province/category → routers 参数校验 → 本函数归一 → SQL 绑定
#   → 返回位次 → recommend_service.calculate_tiers(rank, province, category)


def _national_table(year: int) -> str:
    """全国总表名（年份只接受数字，防止拼接出奇怪表名）。"""
    return _NATIONAL_TABLE.format(year=int(year))


def score_to_rank(score: float, province: str, category: str, year: int = 2025) -> int:
    """分数 → 位次（全国版，查 `score_range_{year}_all`）。

    :param score:     高考分数
    :param province:  省份，中文名（"河南"）或拼音（"henan"）均可
    :param category:  科类，如 "物理类" / "综合" / "理科"
    :param year:      数据年份，默认 2025
    :return:          位次；查不到 / 该省无数据 / 数据库异常时返回 **0**
    """
    prov = normalize_province(province)
    cat = (category or "").strip()
    tbl = _national_table(year)
    if not prov or not cat:
        logger.warning("[RANK] 参数不完整 province=%s category=%s", province, category)
        return 0
    if not table_exists(tbl):
        logger.warning("[RANK] 总表不存在：%s", tbl)
        return 0

    # 取「大于该分数的最近一档」的累计人数：该分数无人时，位次等价于其上最近一档
    sql = (
        f"SELECT `score`, `cumulative_count` FROM `{tbl}` "
        "WHERE `province` = :prov AND `category` = :cat "
        "AND CAST(`score` AS SIGNED) <= :score "
        "ORDER BY CAST(`score` AS SIGNED) DESC LIMIT 1"
    )
    try:
        with SessionLocal() as db:
            row = db.execute(text(sql), {"prov": prov, "cat": cat, "score": int(score)}).first()
    except Exception as exc:  # noqa: BLE001 单省异常不该炸掉整个推荐链路
        logger.warning("[RANK] score_to_rank 查询失败 %s/%s/%s：%s %s",
                       prov, cat, year, exc.__class__.__name__, str(exc)[:150])
        return 0

    if not row:
        logger.warning("[RANK] 未找到一分一段数据：%s %s %s 分", prov, cat, score)
        return 0
    rank = normalize_int(row[1])
    if not rank:
        logger.warning("[RANK] cumulative_count 为空：%s %s %s 分", prov, cat, score)
        return 0
    return int(rank)


def rank_to_score(rank: int, province: str, category: str, year: int = 2025) -> int:
    """位次 → 分数（全国版，查 `score_range_{year}_all`）。

    :return: 分数；查不到 / 该省无数据 / 数据库异常时返回 **0**
    """
    prov = normalize_province(province)
    cat = (category or "").strip()
    tbl = _national_table(year)
    if not prov or not cat:
        logger.warning("[RANK] 参数不完整 province=%s category=%s", province, category)
        return 0
    if not table_exists(tbl):
        logger.warning("[RANK] 总表不存在：%s", tbl)
        return 0

    sql = (
        f"SELECT `score` FROM `{tbl}` "
        "WHERE `province` = :prov AND `category` = :cat "
        "AND CAST(`cumulative_count` AS SIGNED) >= :rank "
        "ORDER BY CAST(`cumulative_count` AS SIGNED) ASC LIMIT 1"
    )
    try:
        with SessionLocal() as db:
            row = db.execute(text(sql), {"prov": prov, "cat": cat, "rank": int(rank)}).first()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[RANK] rank_to_score 查询失败 %s/%s/%s：%s %s",
                       prov, cat, year, exc.__class__.__name__, str(exc)[:150])
        return 0

    if not row:
        logger.warning("[RANK] 未找到位次对应分数：%s %s %s 名", prov, cat, rank)
        return 0
    try:
        return int(float(row[0]))
    except (TypeError, ValueError):
        logger.warning("[RANK] score 值无法解析：%r", row[0])
        return 0


def control_score(province: str, year: int, category: str, batch: str) -> Optional[int]:
    rows = _load_score_range(province, year, category, batch)
    for r in rows:
        if r["control_score"] is not None:
            return r["control_score"]
    return None


def score_table(province: str, year: int, category: str, batch: str) -> List[Dict]:
    """完整一分一段表（前端画分布图 / 快捷工具用）。"""
    return _load_score_range(province, year, category, batch)


# ------------------------------------------------------------ 批次线 / 分数校验


def control_lines(province: str, year: int, category: str) -> Dict:
    """该年份 + 科类下的各批次省控线，以及本科/专科的可填写分数区间。

    2024 老高考会返回 本科一批/本科二批/专科批 三条线；
    2025 新高考返回 本科批/专科批 两条线。
    """
    rows = _load_score_range(province, year, category, None)
    if not rows:
        raise ValueError(
            f"未找到一分一段数据：province={province} year={year} category={category}"
        )

    seen: Dict[str, Dict] = {}
    for r in rows:
        b = r["batch"] or "未知"
        cs = r["control_score"]
        if b not in seen:
            seen[b] = {
                "batch": b,
                "canonical": canonical_batch(b),
                "control_score": cs,
            }
        elif cs is not None and seen[b]["control_score"] is None:
            seen[b]["control_score"] = cs

    lines = sorted(
        seen.values(),
        key=lambda x: (x["control_score"] is None, -(x["control_score"] or 0)),
    )

    def _min_of(prefix: str) -> Optional[int]:
        vals = [
            l["control_score"]
            for l in lines
            if l["canonical"].startswith(prefix) and l["control_score"] is not None
        ]
        return min(vals) if vals else None

    ben_min = _min_of("本科")
    zhuan_min = _min_of("专科")

    # 成绩类型（本科/专科）对应的可填写分数区间，与示例 App 保持一致：
    #   本科：1 ~ 满分；专科：1 ~ 本科线 - 1（即低于本科线的分数段）
    bounds = {}
    if ben_min is not None:
        bounds["ben"] = {"min": 1, "max": FULL_SCORE}
    if zhuan_min is not None:
        bounds["zhuan"] = {
            "min": 1,
            "max": (ben_min - 1) if ben_min is not None else FULL_SCORE,
        }

    return {
        "province": province,
        "year": year,
        "category": category,
        "full_score": FULL_SCORE,
        "lines": lines,
        "bounds": bounds,
        "min_line": min(
            [l["control_score"] for l in lines if l["control_score"] is not None],
            default=None,
        ),
    }


def score_check(province: str, year: int, category: str, score: float) -> Dict:
    """分数校验 + 自动推荐填报批次 + 自动换算位次。

    一次返回前端自动填充所需的全部信息：
    · 低于最低批次线 → below_all=True，rank/recommend_batch 为空
    · 否则给出 recommend_batch（本科批/专科批）与对应位次
    """
    lines_info = control_lines(province, year, category)
    lines = lines_info["lines"]
    target = float(score)

    recommend, recommend_level = None, None
    below_all = lines_info["min_line"] is not None and target < lines_info["min_line"]
    if not below_all:
        for l in lines:  # 已按省控线降序
            cs = l["control_score"]
            if cs is not None and target >= cs:
                recommend = l["canonical"]
                recommend_level = "ben" if l["canonical"].startswith("本科") else "zhuan"
                break
        if recommend is None:
            recommend = lines[-1]["canonical"]
            recommend_level = "ben" if recommend.startswith("本科") else "zhuan"

    info: Dict = {"rank": None, "rank_range": None, "segment_count": None}
    if not below_all:
        info = score_to_rank_detail(
            province, year, category, recommend or lines[-1]["canonical"], target
        )
    hit_line = next(
        (l["control_score"] for l in lines if l["canonical"] == recommend), None
    )

    return {
        "province": province,
        "year": year,
        "category": category,
        "score": target,
        "full_score": FULL_SCORE,
        "lines": lines,
        "bounds": lines_info["bounds"],
        "min_line": lines_info["min_line"],
        "below_all": below_all,
        "recommend_batch": None if below_all else recommend,
        "recommend_level": recommend_level,
        "rank": None if below_all else info["rank"],
        "rank_range": None if below_all else info["rank_range"],
        "segment_count": None if below_all else info["segment_count"],
        "control_score": hit_line,
        "score_diff": (
            int(target - hit_line) if (hit_line is not None and not below_all) else None
        ),
    }


_DEFAULT = settings.DEFAULT_PROVINCE
