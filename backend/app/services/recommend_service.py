"""志愿推荐规则引擎。

职责（全部由规则完成，AI 不参与）：
1. 分数 -> 位次（调用 rank_service）
2. 按 province + year + category + batch 物理隔离查询录取表
3. 按位次差划分冲 / 稳 / 保
4. 计算规则化的录取概率与推荐理由
"""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Dict, List, Optional

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
    """
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
    )
    cats = resolve_category(category, year, KIND_PLAN)
    batches = resolve_batch(batch, year, KIND_PLAN)
    if cats:
        stmt = stmt.where(tbl.c.category.in_(cats))
    if batches:
        stmt = stmt.where(tbl.c.batch.in_(batches))

    by_code: Dict[str, Dict] = {}
    by_name: Dict[str, Dict] = {}
    by_school: Dict[str, Dict] = {}
    for r in fetch_all(stmt):
        info = {
            "tuition": normalize_score(r.get("tuition")),
            "plan_count": normalize_score(r.get("plan_count")),
            "duration": normalize_duration(r.get("duration")),
            "subject_req": r.get("subject_req"),
        }
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
    tbl = get_table(table_name(KIND_MAJOR, year, province))
    conds = _build_filters(tbl, filters)

    cats = resolve_category(category, year, KIND_MAJOR)
    if cats:
        conds.append(tbl.c.category.in_(cats))
    batches = resolve_batch(batch, year, KIND_MAJOR)
    if batches:
        conds.append(tbl.c.batch.in_(batches))

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
    from app.services.rank_service import score_to_rank

    t0 = time.time()
    buffer = buffer or settings.RANK_BUFFER
    span = span_factor or settings.RANK_SPAN_FACTOR

    rank_info = None
    if rank is None:
        if score is None:
            raise ValueError("score 与 rank 至少提供一个")
        rank_info = score_to_rank(province, year, category, batch, score)
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
