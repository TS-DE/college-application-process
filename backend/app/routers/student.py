"""考生信息与分数/位次换算接口。

考生档案只做内存保存（数据集没有考生表），重启即清空；
如需持久化，把 _STUDENTS 换成数据库表即可，接口契约不变。
"""
import itertools
from typing import Dict

from fastapi import APIRouter, HTTPException, Query

from app.schemas.student import (
    RankToScoreOut,
    ScoreToRankOut,
    StudentProfileIn,
    StudentProfileOut,
)

router = APIRouter(prefix="/api", tags=["student"])

_STUDENTS: Dict[int, Dict] = {}
_ID_SEQ = itertools.count(1)


def _ensure_rank(p: StudentProfileIn) -> Dict:
    from app.services.rank_service import score_to_rank

    info = None
    rank = p.rank
    if rank is None:
        if p.score is None:
            raise HTTPException(status_code=400, detail="score 与 rank 至少提供一个")
        info = score_to_rank(p.province, p.year, p.category, p.batch, p.score)
        rank = info["rank"]
    return {
        "rank": int(rank),
        "control_score": (info or {}).get("control_score"),
        "score_diff": (
            int(p.score - info["control_score"])
            if info and p.score is not None and info.get("control_score") is not None
            else None
        ),
    }


@router.post("/student/profile", response_model=StudentProfileOut)
def create_profile(p: StudentProfileIn) -> StudentProfileOut:
    """保存考生信息并返回换算后的位次。"""
    extra = _ensure_rank(p)
    sid = next(_ID_SEQ)
    _STUDENTS[sid] = {**p.model_dump(), **extra}
    return StudentProfileOut(
        student_id=sid,
        province=p.province,
        year=p.year,
        category=p.category,
        batch=p.batch,
        score=p.score,
        rank=extra["rank"],
        control_score=extra["control_score"],
        score_diff=extra["score_diff"],
    )


@router.get("/student/profile/{student_id}", response_model=StudentProfileOut)
def get_profile(student_id: int) -> StudentProfileOut:
    data = _STUDENTS.get(student_id)
    if not data:
        raise HTTPException(status_code=404, detail="考生不存在")
    return StudentProfileOut(student_id=student_id, **data)


@router.get("/score-to-rank", response_model=ScoreToRankOut)
def score_to_rank(
    province: str = Query(default="河南"),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
    batch: str = Query(default="本科批"),
    score: float = Query(..., ge=0, le=750),
) -> ScoreToRankOut:
    """分数 -> 位次，查一分一段表。"""
    from app.services.rank_service import score_to_rank as _conv

    try:
        info = _conv(province, year, category, batch, score)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ScoreToRankOut(**info)


@router.get("/rank-to-score", response_model=RankToScoreOut)
def rank_to_score(
    province: str = Query(default="河南"),
    year: int = Query(default=2025),
    category: str = Query(default="物理类"),
    batch: str = Query(default="本科批"),
    rank: int = Query(..., ge=1),
) -> RankToScoreOut:
    """位次 -> 分数（同分去向 / 位次反查）。"""
    from app.services.rank_service import rank_to_score as _conv

    try:
        info = _conv(province, year, category, batch, rank)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RankToScoreOut(**info)
