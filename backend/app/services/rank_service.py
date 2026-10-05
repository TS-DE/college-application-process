"""分数 <-> 位次 换算服务。

数据来源：score_range_{year}_{province}（一分一段表）。
cumulative_count = 该分数及以上的累计人数，即该分数对应的最低位次。

河南 2024 老高考一分一段按「本科一批 / 本科二批 / 专科批」分段存储，
分数区间互不重叠（一本 511-709、二本 396-510、专科 100-395），
因此选「本科批」时要在一本、二本两张区间里按分数定位。
"""
from typing import Dict, List, Optional

from sqlalchemy import select

from app.config import settings
from app.database import fetch_all, get_table
from app.models.dataset import (
    KIND_SCORE,
    canonical_batch,
    normalize_int,
    resolve_batch,
    resolve_category,
    table_name,
)

FULL_SCORE = 750


def _load_score_range(
    province: str, year: int, category: str, batch: Optional[str] = None
) -> List[Dict]:
    """batch 传 None 时加载该科类全部批次的分数段（用于批次线 / 跨批次定位）。"""
    tbl = get_table(table_name(KIND_SCORE, year, province))
    stmt = select(tbl)
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


def score_to_rank(province: str, year: int, category: str, batch: str, score: float) -> Dict:
    """分数 -> 位次。

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


def rank_to_score(province: str, year: int, category: str, batch: str, rank: int) -> Dict:
    """位次 -> 分数：按分数从高到低，找第一个累计人数 >= rank 的分数。"""
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
        info = score_to_rank(
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
