"""志愿推荐规则引擎。

职责（全部由规则完成，AI 不参与）：
1. 分数 -> 位次（调用 rank_service）
2. 按 province + year + category + batch 物理隔离查询录取表
3. 按位次差划分冲 / 稳 / 保
4. 计算规则化的录取概率与推荐理由

0.11.0 全国多省自适应：新增 `calculate_tiers()`，直接查
`major_admission_{year}_all` 全国总表，省份/科类/年份全部参数化；
原有 `recommend()` 保留为「河南单省富信息版」（带学费、计划数、AI 理由）。
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Dict, List, Optional

from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal, table_exists
from app.utils.region_mapper import normalize_province

logger = logging.getLogger(__name__)

from sqlalchemy import and_, or_, select

from app.config import settings
from app.database import fetch_all, get_table
from app.models.dataset import (
    KIND_MAJOR,
    KIND_PLAN,
    normalize_code,
    normalize_duration,
    normalize_int,
    normalize_score,
    resolve_batch,
    resolve_category,
    subject_match,
    table_name,
)

TIER_LABEL = {"chong": "冲", "wen": "稳", "bao": "保"}


# ------------------------------------------------------------ 招生计划索引


@lru_cache(maxsize=32)
def _plan_index(province: str, year: int, category: str, batch: str) -> Dict[str, Dict]:
    """招生计划索引：key -> {tuition, plan_count, duration, subject_req}

    key 优先级：(院校代码, 专业代码) > (院校名, 专业名) > 院校名。
    2024 的 enrollment_plan 院校代码/专业代码整列为空，只能退回按名称匹配。

    0.11.1：查全国总表 `enrollment_plan_{year}_all`，并**必须**按省份隔离，
    否则会把外省的学费 / 计划数套到本省院校上。

    0.11.2：部分省份（安徽/广西/陕西等）的 tuition / duration 整列为 NULL，
    信息混在 `major_note` 文本里，这里用 `data_cleaner` 提纯后再入索引，
    使 `/api/recommend` 与 `/api/majors` 两个消费方同时受益。
    """
    from app.services.dataset_access import scope_conditions
    from app.utils.data_cleaner import clean_item

    tbl = get_table(table_name(KIND_PLAN, year, province))
    stmt = select(
        tbl.c.university_code,
        tbl.c.university_name,
        tbl.c.major_code,
        tbl.c.major_name,
        tbl.c.tuition,
        tbl.c.plan_count,
        tbl.c.duration,
        tbl.c.subject_req,
        tbl.c.major_note,
    )
    # 0.11.2：批次必须用**省份感知**的归一（广西写作「本科普通批」、
    # 四川写作「本科批B段」），否则索引直接为空、学费全都补不上
    conds = scope_conditions(KIND_PLAN, tbl, province, year, category, batch)
    if conds:
        stmt = stmt.where(*conds)

    by_code: Dict[str, Dict] = {}
    by_name: Dict[str, Dict] = {}
    by_school: Dict[str, Dict] = {}
    for r in fetch_all(stmt):
        info = {
            "tuition": normalize_score(r.get("tuition")),
            "plan_count": normalize_score(r.get("plan_count")),
            "duration": normalize_duration(r.get("duration")),
            "subject_req": r.get("subject_req"),
            "major_note": r.get("major_note"),
        }
        # 0.11.2：tuition / duration 缺失时从 major_note 里正则提纯
        clean_item(info)
        ucode = normalize_code(r.get("university_code"))
        mcode = normalize_code(r.get("major_code"))
        uname = (r.get("university_name") or "").strip()
        mname = (r.get("major_name") or "").strip()
        if ucode and mcode:
            by_code.setdefault(f"{ucode}|{mcode}", info)
        if uname and mname:
            by_name.setdefault(f"{uname}|{mname}", info)
        if uname:
            by_school.setdefault(uname, info)
    return {"code": by_code, "name": by_name, "school": by_school}


def _lookup_plan(idx: Dict, uni_code, uni_name, major_code, major_name) -> Dict:
    ucode = normalize_code(uni_code)
    mcode = normalize_code(major_code)
    uname = (uni_name or "").strip()
    mname = (major_name or "").strip()
    if ucode and mcode:
        hit = idx["code"].get(f"{ucode}|{mcode}")
        if hit:
            return hit
    if uname and mname:
        hit = idx["name"].get(f"{uname}|{mname}")
        if hit:
            return hit
    return idx["school"].get(uname, {})


# ------------------------------------------------------------ 候选数据查询


def _build_filters(tbl, filters: Optional[Dict]):
    conds = [tbl.c.min_rank.isnot(None)]
    if not filters:
        return conds

    def _like(col, kw: str):
        return col.like(f"%{kw}%")

    kw = (filters.get("major_keyword") or "").strip()
    if kw:
        conds.append(
            or_(
                _like(tbl.c.major_name, kw),
                _like(tbl.c.major_note, kw),
                _like(tbl.c.major_group, kw),
            )
        )
    ex = (filters.get("exclude_keyword") or "").strip()
    if ex:
        conds.append(
            and_(
                or_(tbl.c.major_name.is_(None), tbl.c.major_name.not_like(f"%{ex}%")),
                or_(tbl.c.major_note.is_(None), tbl.c.major_note.not_like(f"%{ex}%")),
            )
        )
    uk = (filters.get("university_keyword") or "").strip()
    if uk:
        conds.append(_like(tbl.c.university_name, uk))
    sp = (filters.get("school_province") or "").strip()
    if sp:
        conds.append(tbl.c.school_province == sp)
    nat = (filters.get("school_nature") or "").strip()
    if nat:
        conds.append(tbl.c.school_nature == nat)
    sub = (filters.get("subject_req") or "").strip()
    if sub:
        conds.append(_like(tbl.c.subject_req, sub))
    if filters.get("is_985"):
        conds.append(tbl.c.is_985 == 1)
    if filters.get("is_211"):
        conds.append(tbl.c.is_211 == 1)
    return conds


def _fetch_candidates(
    province: str,
    year: int,
    category: str,
    batch: str,
    filters: Optional[Dict],
    rank: Optional[int],
    buffer: int,
    span: int,
) -> List[Dict]:
    from app.services.dataset_access import scope_conditions

    tbl = get_table(table_name(KIND_MAJOR, year, province))
    conds = _build_filters(tbl, filters)

    # ★ 省份 + 科类 + 批次三重隔离（0.11.2 起批次也走省份感知归一）
    conds += scope_conditions(KIND_MAJOR, tbl, province, year, category, batch)

    # 位次窗口裁剪，避免全表扫描（2025 河南本科批约 1.7 万行）
    if rank:
        conds.append(tbl.c.min_rank >= max(1, rank - buffer * span - buffer))
        conds.append(tbl.c.min_rank <= rank + buffer * span + buffer)

    rows = fetch_all(select(tbl).where(and_(*conds)))
    return _dedupe(rows)


def _dedupe(rows: List[Dict]) -> List[Dict]:
    """同一院校+专业+专业组只保留最低位次的一条。"""
    best: Dict[str, Dict] = {}
    for r in rows:
        key = "|".join(
            [
                (r.get("university_name") or "").strip(),
                (r.get("major_name") or "").strip(),
                (r.get("major_group") or "").strip(),
                normalize_code(r.get("major_code")) or "",
            ]
        )
        cur = best.get(key)
        rk = normalize_score(r.get("min_rank"))
        if cur is None:
            best[key] = r
            continue
        cur_rk = normalize_score(cur.get("min_rank"))
        if rk is not None and (cur_rk is None or rk < cur_rk):
            best[key] = r
    return list(best.values())


# ------------------------------------------------------------ 规则计算


def _probability(tier: str, gap: int, buffer: int, span: int) -> int:
    """规则估算录取概率（%），仅用于排序与直观展示，不是官方数据。"""
    lo = max(1, buffer * span)
    if tier == "chong":
        x = min(abs(gap) / lo, 1.0)
        v = 40 - 30 * x
    elif tier == "wen":
        x = max(-1.0, min(1.0, gap / max(1, buffer)))
        v = 70 - 15 * x
    else:
        x = min(abs(gap) / lo, 1.0)
        v = 98 - 10 * x
    return int(max(5, min(99, round(v))))


def _to_item(row: Dict, rank: int, tier: str, buffer: int, span: int, plan: Dict) -> Dict:
    min_rank = normalize_int(row.get("min_rank"))
    gap = (min_rank - rank) if (min_rank is not None and rank is not None) else 0
    tuition = normalize_score(plan.get("tuition"))
    item = {
        "university_code": normalize_code(row.get("university_code")),
        "university_name": row.get("university_name"),
        "major_code": normalize_code(row.get("major_code")),
        "major_name": row.get("major_name"),
        "major_group": row.get("major_group"),
        "major_note": row.get("major_note"),
        "subject_req": row.get("subject_req") or plan.get("subject_req"),
        "min_score": normalize_score(row.get("min_score")),
        "min_rank": min_rank,
        "max_score": normalize_score(row.get("max_score")),
        "avg_score": normalize_score(row.get("avg_score")),
        "admit_count": normalize_score(row.get("admit_count")),
        "plan_count": normalize_score(plan.get("plan_count")),
        "tuition": tuition,
        "duration": plan.get("duration"),
        "school_province": row.get("school_province"),
        "school_nature": row.get("school_nature"),
        "is_985": int(row.get("is_985") or 0) == 1,
        "is_211": int(row.get("is_211") or 0) == 1,
        "is_double_first_class": int(row.get("is_985") or 0) == 1
        or int(row.get("is_211") or 0) == 1,
        "batch": row.get("batch"),
        "year": normalize_int(row.get("year")),
        "rank_diff": gap,
        "tier": tier,
        "tier_label": TIER_LABEL.get(tier, tier),
        "probability": _probability(tier, gap, buffer, span),
        "ai": False,
        "ai_reason": None,
    }
    item["reason"] = _reason_of(item, rank)
    return item


def _reason_of(item: Dict, rank: Optional[int]) -> str:
    from app.services.ai_service import _rule_reason  # 局部导入避免循环依赖

    return _rule_reason(
        {
            "university_name": item.get("university_name"),
            "major_name": item.get("major_name"),
            "school_province": item.get("school_province"),
            "school_nature": item.get("school_nature"),
            "min_score": item.get("min_score"),
            "min_rank": item.get("min_rank"),
            "student_rank": rank,
            "rank_diff": item.get("rank_diff"),
            "tier_label": item.get("tier_label"),
            "tuition": item.get("tuition"),
            "plan_count": item.get("plan_count"),
            "admit_count": item.get("admit_count"),
            "subject_req": item.get("subject_req"),
            "is_985": item.get("is_985"),
            "is_211": item.get("is_211"),
        }
    )


def split_tiers(rows: List[Dict], rank: int, buffer: int, span: int, limit: int):
    """按位次差切分冲/稳/保，并对每档做最有利于考生的排序。"""
    lo = buffer * span
    chong_pool = [
        r for r in rows
        if r["min_rank"] is not None and rank - lo <= r["min_rank"] < rank - buffer
    ]
    if not chong_pool:
        chong_pool = [
            r for r in rows if r["min_rank"] is not None and r["min_rank"] < rank - buffer
        ]
    wen_pool = [
        r for r in rows
        if r["min_rank"] is not None and rank - buffer <= r["min_rank"] <= rank + buffer
    ]
    bao_pool = [
        r for r in rows
        if r["min_rank"] is not None and rank + buffer < r["min_rank"] <= rank + lo
    ]
    if not bao_pool:
        bao_pool = [
            r for r in rows if r["min_rank"] is not None and r["min_rank"] > rank + buffer
        ]

    # 冲：位次越接近考生越有希望，按 min_rank 降序
    chong = sorted(chong_pool, key=lambda r: -r["min_rank"])[:limit]
    # 稳：按位次差绝对值升序
    wen = sorted(wen_pool, key=lambda r: abs(r["min_rank"] - rank))[:limit]
    # 保：位次越低越保险，按 min_rank 升序
    bao = sorted(bao_pool, key=lambda r: r["min_rank"])[:limit]
    return chong, wen, bao


# ------------------------------------------------------------ 主入口


def recommend(
    province: str,
    year: int,
    category: str,
    batch: str,
    rank: Optional[int] = None,
    score: Optional[int] = None,
    filters: Optional[Dict] = None,
    buffer: Optional[int] = None,
    span_factor: Optional[int] = None,
    limit: int = 60,
    with_ai: bool = False,
    ai_limit: int = 0,
) -> Dict:
    from app.services.ai_service import ai_enabled, batch_reasons
    # 0.11.0：河南单省富信息版改名为 score_to_rank_detail（全国版占用了 score_to_rank）
    from app.services.rank_service import score_to_rank_detail

    t0 = time.time()
    buffer = buffer or settings.RANK_BUFFER
    span = span_factor or settings.RANK_SPAN_FACTOR

    rank_info = None
    if rank is None:
        if score is None:
            raise ValueError("score 与 rank 至少提供一个")
        rank_info = score_to_rank_detail(province, year, category, batch, score)
        rank = rank_info["rank"]

    plan_idx = _plan_index(province, year, category, batch)
    raw_rows = _fetch_candidates(province, year, category, batch, filters, rank, buffer, span)

    # 规整成统一结构并补招生计划信息
    subject_selected = (filters or {}).get("subject_selected") or None
    prepared: List[Dict] = []
    for r in raw_rows:
        mr = normalize_int(r.get("min_rank"))
        if mr is None:
            continue
        plan = _lookup_plan(
            plan_idx, r.get("university_code"), r.get("university_name"),
            r.get("major_code"), r.get("major_name"),
        )
        if subject_selected:
            req = r.get("subject_req") or plan.get("subject_req")
            if not subject_match(req, subject_selected):
                continue
        if filters and filters.get("tuition_max"):
            tuition = normalize_score(plan.get("tuition"))
            # 学费缺失不直接淘汰，避免把大量数据漏掉
            if tuition is not None and tuition > float(filters["tuition_max"]):
                continue
        prepared.append({"_row": r, "_plan": plan, "min_rank": mr})

    chong_rows, wen_rows, bao_rows = split_tiers(prepared, rank, buffer, span, limit)

    def _pack(rows: List[Dict], tier: str) -> List[Dict]:
        return [
            _to_item(r["_row"], rank, tier, buffer, span, r["_plan"]) for r in rows
        ]

    chong, wen, bao = _pack(chong_rows, "chong"), _pack(wen_rows, "wen"), _pack(bao_rows, "bao")

    ai_generated = 0
    if with_ai and ai_enabled():
        student = {"rank": rank, "score": score}
        # 三档各取前若干条，保证每档都有 AI 解读
        per = max(1, ai_limit // 3) if ai_limit >= 3 else ai_limit
        left = ai_limit
        for items in (chong, wen, bao):
            take = min(per, left)
            ai_generated += batch_reasons(items, student, limit=take)
            left -= take
            if left <= 0:
                break

    student_out = {
        "province": province,
        "year": year,
        "category": category,
        "batch": batch,
        "score": score,
        "rank": rank,
    }
    if rank_info:
        student_out["control_score"] = rank_info.get("control_score")
        student_out["score_diff"] = rank_info.get("score_diff")
        student_out["rank_range"] = rank_info.get("rank_range")

    return {
        "student": student_out,
        "chong": chong,
        "wen": wen,
        "bao": bao,
        "meta": {
            "total_scanned": len(prepared),
            "buffer": buffer,
            "span_factor": span,
            "table": table_name(KIND_MAJOR, year, province),
            "ai_enabled": ai_enabled(),
            "ai_generated": ai_generated,
            "elapsed_ms": int((time.time() - t0) * 1000),
        },
    }


# ============================================================
# 0.11.0 全国多省自适应核心引擎
# ============================================================
#
# ## 与上面 recommend() 的区别
#   · 数据源：`major_admission_{year}_all` 全国总表（30+ 省，43 万行），
#             不再按省份拼表名，因此不会出现「某省没建表就查不到」的问题；
#   · 过滤  ：province + category + year 三个条件**必传**，
#             防止跨省数据串联污染（不同省份科类名不同，混查会张冠李戴）；
#   · 内存  ：每个档位 LIMIT 50 条，绝不 `SELECT *` 全量拉进 Python；
#   · 概率  ：位次差线性映射，见 _tier_probability()。
#
# ## 参数传递路径
#   前端 province/category/score
#     → routers/recommend.py 校验（region_mapper.is_supported）
#     → rank_service.score_to_rank(score, province, category) 得到 student_rank
#     → 本函数 calculate_tiers(student_rank, province, category)
#     → SQL 绑定 :prov/:cat/:min_r/:max_r → LIMIT 50
#     → 返回 {"chong": [...], "wen": [...], "bao": [...]}

# 全国总表名模板
_NATIONAL_MAJOR_TABLE = "major_admission_{year}_all"

# 单个档位最多返回条数（内存保护）
_TIER_LIMIT = 50

# 冲 / 稳 / 保 的位次窗口宽度（相对考生位次的 buffer 倍数）
_TIER_SPAN = {"chong": 3.0, "wen": 1.0, "bao": 3.0}

# 档位中文名
_TIER_LABEL = {"chong": "冲", "wen": "稳", "bao": "保"}


def _tier_buffer(province: str) -> int:
    """位次缓冲宽度（按省份动态读取，不再全局写死 5000）。

    考生基数大的省份（河南、山东、广东等）用更宽的缓冲，避免窗口过窄候选不足；
    其余省份用配置的默认值。
    """
    prov = normalize_province(province)
    wide = {"河南", "山东", "广东", "四川", "河北", "安徽"}
    base = int(getattr(settings, "RANK_BUFFER", 5000) or 5000)
    return base * (2 if prov in wide else 1)


def _tier_probability(tier: str, gap: int, buffer: int) -> float:
    """录取概率：位次差线性映射，保留 1 位小数。

    gap = 院校最低位次 - 考生位次（正数表示院校位次更靠后、录取更稳）。

    · 冲（gap 为负，院校比考生靠前）：10% ~ 40%
    · 稳（gap 接近 0）              ：55% ~ 85%
    · 保（gap 为正，院校比考生靠后） ：88% ~ 98%

    只用于排序与直观展示，不是官方数据。
    """
    b = max(1, int(buffer))
    if tier == "chong":
        x = min(abs(gap) / (b * _TIER_SPAN["chong"]), 1.0)   # 0=最接近，1=最冒险
        return round(40 - 30 * x, 1)
    if tier == "wen":
        x = max(-1.0, min(1.0, gap / b))                     # -1=略冒险，1=略稳妥
        return round(70 - 15 * x, 1)
    x = min(abs(gap) / (b * _TIER_SPAN["bao"]), 1.0)         # 0=刚刚保底，1=非常保险
    return round(98 - 10 * x, 1)


def _tier_window(tier: str, rank: int, buffer: int) -> tuple:
    """算出该档位的 [min_rank, max_rank] 查询区间（含端点）。

    位次数值越小排名越靠前：
      冲：院校位次明显好于考生（数值更小）
      稳：与考生位次接近
      保：院校位次明显差于考生（数值更大）
    """
    b = int(buffer)
    lo = int(b * _TIER_SPAN[tier])
    if tier == "chong":
        return max(1, rank - lo), rank - b
    if tier == "wen":
        return rank - b, rank + b
    return rank + b, rank + lo


def _national_reason(item: Dict, rank: Optional[int]) -> str:
    """规则版推荐理由（与 _reason_of 同风格，但不依赖招生计划表）。"""
    name = item.get("university_name") or "该校"
    major = item.get("major_name") or "该专业"
    gap = item.get("rank_diff")
    tier = item.get("tier_label") or ""
    parts = [f"{name}{major}属于{tier}档"]
    if gap is not None and rank:
        if gap > 0:
            parts.append(f"院校最低位次比你低 {abs(gap)} 名，录取较稳")
        elif gap < 0:
            parts.append(f"院校最低位次比你高 {abs(gap)} 名，需要冲一冲")
        else:
            parts.append("院校最低位次与你基本持平")
    if item.get("is_985"):
        parts.append("985 高校")
    elif item.get("is_211"):
        parts.append("211 高校")
    if item.get("min_score"):
        parts.append(f"最低分 {int(item['min_score'])}")
    return "，".join(parts) + "。"


def _to_national_item(row: Dict, rank: int, tier: str, buffer: int) -> Dict:
    """把总表的一行转成前端可直接渲染的推荐条目。

    0.11.2：投档表里没有 tuition / duration，先留空，等 `enrich_with_plan()`
    从招生计划表补齐；若计划表也缺，再由 `clean_item()` 从 `major_note` 提纯。
    """
    from app.utils.data_cleaner import clean_item

    min_rank = row.get("min_rank")
    gap = int(min_rank - rank) if min_rank is not None else None
    item = {
        "university_code": row.get("university_code"),
        "university_name": row.get("university_name"),
        "major_name": row.get("major_name"),
        "major_group": row.get("major_group"),
        "major_code": row.get("major_code"),
        "subject_req": row.get("subject_req"),
        "school_province": row.get("school_province"),
        "school_nature": row.get("school_nature"),
        "is_985": int(row.get("is_985") or 0) == 1,
        "is_211": int(row.get("is_211") or 0) == 1,
        "min_score": row.get("min_score"),
        "min_rank": min_rank,
        "batch": row.get("batch"),
        "year": row.get("year"),
        # 0.11.2：保留原始说明文本，供提纯与前端展示
        "major_note": row.get("major_note"),
        "tuition": None,
        "duration": None,
        "rank_diff": gap,
        "tier": tier,
        "tier_label": _TIER_LABEL.get(tier, tier),
        "probability": _tier_probability(tier, gap, buffer) if gap is not None else None,
    }
    # 先用投档表自身的 major_note 兜一层（多数情况下计划表会更准，后面会覆盖）
    clean_item(item)
    item["reason"] = _national_reason(item, rank)
    return item


def calculate_tiers(
    student_rank: int, province: str, category: str, year: int = 2025
) -> Dict[str, List[Dict]]:
    """按位次计算冲 / 稳 / 保三档志愿（全国总表版）。

    :param student_rank: 考生位次（由 rank_service.score_to_rank 得到）
    :param province:      省份，中文名或拼音均可
    :param category:      科类，如 "物理类" / "综合" / "理科"
    :param year:          数据年份，默认 2025
    :return: {"chong": [...], "wen": [...], "bao": [...]}，每个档位最多 50 条；
             任何异常都返回三档全空 + logger.warning，不抛异常。
    """
    empty = {"chong": [], "wen": [], "bao": []}
    prov = normalize_province(province)
    cat = (category or "").strip()
    rank = int(student_rank or 0)
    if not prov or not cat or rank <= 0:
        logger.warning("[TIER] 参数不完整 rank=%s province=%s category=%s",
                       student_rank, province, category)
        return empty

    tbl = _NATIONAL_MAJOR_TABLE.format(year=int(year))
    if not table_exists(tbl):
        logger.warning("[TIER] 全国总表不存在：%s", tbl)
        return empty

    buffer = _tier_buffer(prov)
    out: Dict[str, List[Dict]] = {"chong": [], "wen": [], "bao": []}

    for tier in ("chong", "wen", "bao"):
        min_r, max_r = _tier_window(tier, rank, buffer)
        if min_r > max_r:
            continue
        sql = (
            f"SELECT university_code, university_name, major_group, major_name, major_code, "
            f"subject_req, school_province, school_nature, is_985, is_211, "
            f"min_score, min_rank, batch, year, major_note "
            f"FROM `{tbl}` "
            f"WHERE `province` = :prov AND `category` = :cat AND `year` = :yr "
            f"AND `min_rank` IS NOT NULL AND `min_rank` BETWEEN :min_r AND :max_r "
            f"ORDER BY `min_rank` ASC LIMIT :lim"
        )
        try:
            with SessionLocal() as db:
                rows = db.execute(text(sql), {
                    "prov": prov, "cat": cat, "yr": int(year),
                    "min_r": min_r, "max_r": max_r, "lim": _TIER_LIMIT,
                }).mappings().all()
        except Exception as exc:  # noqa: BLE001 单档失败不影响其他档
            logger.warning("[TIER] %s 档查询失败 %s/%s/%s：%s %s",
                           tier, prov, cat, year, exc.__class__.__name__, str(exc)[:150])
            continue

        items = [_to_national_item(dict(r), rank, tier, buffer) for r in rows]
        # 档内排序：冲看谁更接近考生位次；稳看位次差绝对值；保看谁更保险
        if tier == "chong":
            items.sort(key=lambda x: -(x["min_rank"] or 0))
        elif tier == "wen":
            items.sort(key=lambda x: abs(x["rank_diff"] or 0))
        else:
            items.sort(key=lambda x: (x["min_rank"] or 0))
        out[tier] = items[:_TIER_LIMIT]

    logger.info(
        "[TIER] 全国引擎 rank=%s %s/%s buffer=%s → 冲%d 稳%d 保%d",
        rank, prov, cat, buffer, len(out["chong"]), len(out["wen"]), len(out["bao"]),
    )
    return out


# 富化时每个档位最多补多少条。
# 0.11.2 起富化改为走**内存索引**（`_plan_index` 已缓存，无逐条 DB 查询），
# 成本极低，因此上限放宽到覆盖三档全部条目（每档上限 `_TIER_LIMIT` = 50）。
_ENRICH_LIMIT = 200


def enrich_with_plan(
    tiers: Dict[str, List[Dict]],
    province: str,
    category: str,
    year: int = 2025,
    batch: str = "本科批",
) -> Dict[str, List[Dict]]:
    """用招生计划索引给三档结果补上学费 / 计划数 / 学制。

    ## 为什么需要
    `major_admission_{year}_all`（投档表）只有分数与位次，没有学费；
    学费在 `enrollment_plan_{year}_all`（招生计划表）里。

    ## 0.11.2 重写：复用 `_plan_index` / `_lookup_plan`
    原实现自己按 `(院校名, 专业名)` 精确匹配，但**各省计划表的专业名带括号后缀**
    （广西：`工科试验班(吴健雄班)` vs 投档表 `工科试验班`），精确匹配全部落空，
    结果就是「索引里有学费、页面上却没有」。

    改为复用 `_plan_index` + `_lookup_plan` 后得到三级匹配：
      ① (院校代码, 专业代码) → ② (院校名, 专业名) → ③ 院校名（兜底）
    同时不再重复写查询逻辑（合成复用，`/api/majors` 与本函数共用同一套索引）。
    """
    from app.utils.data_cleaner import clean_item

    prov = normalize_province(province)
    cat = (category or "").strip()
    if not prov or not cat:
        return tiers

    try:
        idx = _plan_index(prov, int(year), cat, batch)
    except Exception as exc:  # noqa: BLE001 富化失败不影响推荐结果
        logger.info("[TIER] 招生计划索引构建失败：%s", exc.__class__.__name__)
        return tiers
    if not idx.get("name") and not idx.get("school"):
        logger.info("[TIER] 招生计划索引为空，跳过富化 %s/%s/%s", prov, cat, batch)
        return tiers

    for tier, items in tiers.items():
        for item in items[:_ENRICH_LIMIT]:
            info = _lookup_plan(
                idx,
                item.get("university_code"),
                item.get("university_name"),
                item.get("major_code"),
                item.get("major_name"),
            )
            if info:
                # 计划表是学费 / 计划数 / 学制的权威来源：有值就覆盖
                for src, dst in (("tuition", "tuition"), ("plan_count", "plan_count"),
                                 ("duration", "duration")):
                    if info.get(src) not in (None, ""):
                        item[dst] = info[src]
                if not item.get("subject_req") and info.get("subject_req"):
                    item["subject_req"] = info["subject_req"]
                if not item.get("major_note") and info.get("major_note"):
                    item["major_note"] = info["major_note"]
            # 补缺 + 金额收敛成整数（计划表给的是 Decimal，前端会显示成 5500.0）
            clean_item(item)
    return tiers
